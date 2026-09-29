from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID

from tortoise import transactions
from tortoise.exceptions import IntegrityError

from ...models import (
    TranslationMemoryEntry,
    TranslationMemoryEntryRevision,
    TranslationMemoryLibrary,
    User,
)
from ...domain.translation_memory.policies import can_write_library
from .schemas import (
    TranslationMemoryEntryCreateRequest,
    TranslationMemoryEntryPage,
    TranslationMemoryEntryResponse,
    TranslationMemoryEntryUpdateRequest,
    TranslationMemoryLibraryPage,
    TranslationMemoryLibraryResponse,
    TranslationMemoryLibraryUpdateRequest,
)


class TranslationMemoryError(Exception):
    status_code = 400
    code = "TRANSLATION_MEMORY_ERROR"


class TranslationMemoryNotFoundError(TranslationMemoryError):
    status_code = 404
    code = "TRANSLATION_MEMORY_NOT_FOUND"


class TranslationMemoryConflictError(TranslationMemoryError):
    status_code = 409
    code = "TRANSLATION_MEMORY_CONFLICT"


class TranslationMemoryService:
    async def get_or_create_user_library(self, user: User) -> TranslationMemoryLibrary:
        library = await TranslationMemoryLibrary.filter(scope="user", owner_user_id=user.id, status="active").first()
        if library:
            return library
        try:
            return await TranslationMemoryLibrary.create(
                scope="user", owner_user=user, name=f"{user.display_name} TM", status="active"
            )
        except IntegrityError:
            return await TranslationMemoryLibrary.filter(scope="user", owner_user_id=user.id, status="active").first()

    async def list_user_libraries(self, user: User, page_size: int, cursor: str | None) -> TranslationMemoryLibraryPage:
        offset = self._decode_cursor(cursor)
        query = TranslationMemoryLibrary.filter(scope="user", owner_user_id=user.id).order_by("created_at", "id")
        total = await query.count()
        rows = await query.offset(offset).limit(page_size)
        return TranslationMemoryLibraryPage(
            items=[self._library_response(row) for row in rows],
            next_cursor=self._encode_cursor(offset + len(rows)) if offset + len(rows) < total else None,
            total=total,
        )

    async def get_user_library(self, user: User, memory_id: UUID) -> TranslationMemoryLibrary:
        library = await TranslationMemoryLibrary.filter(id=memory_id, scope="user", owner_user_id=user.id).first()
        if library is None:
            raise TranslationMemoryNotFoundError("翻译记忆库不存在")
        return library

    async def update_library(self, user: User, memory_id: UUID, request: TranslationMemoryLibraryUpdateRequest) -> TranslationMemoryLibrary:
        library = await self.get_user_library(user, memory_id)
        changes = request.model_dump(exclude_unset=True)
        if changes.get("name"):
            changes["name"] = changes["name"].strip()
        for key, value in changes.items():
            setattr(library, key, value)
        if changes:
            await library.save(update_fields=list(changes))
        return library

    async def list_entries(self, user: User, memory_id: UUID, *, page_size: int = 20, cursor: str | None = None) -> TranslationMemoryEntryPage:
        library = await self.get_user_library(user, memory_id)
        offset = self._decode_cursor(cursor)
        query = TranslationMemoryEntry.filter(library_id=library.id, status="active", deleted_at=None).order_by("created_at", "id")
        total = await query.count()
        rows = await query.offset(offset).limit(page_size)
        return TranslationMemoryEntryPage(
            items=[self._entry_response(row) for row in rows],
            next_cursor=self._encode_cursor(offset + len(rows)) if offset + len(rows) < total else None,
            total=total,
        )

    async def get_entry_history(self, user: User, memory_id: UUID, entry_id: UUID) -> list[TranslationMemoryEntryRevision]:
        entry = await self._owned_entry(user, memory_id, entry_id, include_archived=True)
        return await TranslationMemoryEntryRevision.filter(entry_id=entry.id).order_by("version")

    async def create_entry(self, user: User, memory_id: UUID, request: TranslationMemoryEntryCreateRequest) -> TranslationMemoryEntryResponse:
        library = await self.get_user_library(user, memory_id)
        if not can_write_library(user, library):
            raise TranslationMemoryConflictError("翻译记忆库不可写入")
        source_hash = self._hash(request.source_text)
        target_hash = self._hash(request.target_text)
        async with transactions.in_transaction():
            entry = await TranslationMemoryEntry.filter(
                library_id=library.id, source_language=request.source_language, target_language=request.target_language,
                source_hash=source_hash, target_hash=target_hash,
            ).first()
            if entry is None:
                entry = await TranslationMemoryEntry.create(
                    library=library, source_language=request.source_language, target_language=request.target_language,
                    source_text=request.source_text, target_text=request.target_text, source_hash=source_hash,
                    target_hash=target_hash, origin=request.origin, metadata=request.metadata,
                )
                await self._record_revision(entry, user, None)
        return self._entry_response(entry)

    async def update_entry(self, user: User, memory_id: UUID, entry_id: UUID, request: TranslationMemoryEntryUpdateRequest) -> TranslationMemoryEntryResponse:
        async with transactions.in_transaction():
            entry = await self._owned_entry(user, memory_id, entry_id)
            if entry.revision != request.expected_revision:
                raise TranslationMemoryConflictError("条目版本已变化，请重新读取后更新")
            changes = request.model_dump(exclude_unset=True, exclude={"expected_revision", "change_note"})
            for key, value in changes.items():
                setattr(entry, key, value)
            if "source_text" in changes:
                entry.source_hash = self._hash(entry.source_text)
            if "target_text" in changes:
                entry.target_hash = self._hash(entry.target_text)
            entry.revision += 1
            await entry.save()
            await self._record_revision(entry, user, request.change_note)
        return self._entry_response(entry)

    async def archive_entry(self, user: User, memory_id: UUID, entry_id: UUID, expected_revision: int) -> None:
        async with transactions.in_transaction():
            entry = await self._owned_entry(user, memory_id, entry_id)
            if entry.revision != expected_revision:
                raise TranslationMemoryConflictError("条目版本已变化，请重新读取后归档")
            entry.status = "archived"
            entry.deleted_at = datetime.now(timezone.utc)
            await entry.save(update_fields=["status", "deleted_at"])

    async def _owned_entry(self, user: User, memory_id: UUID, entry_id: UUID, *, include_archived: bool = False) -> TranslationMemoryEntry:
        await self.get_user_library(user, memory_id)
        query = TranslationMemoryEntry.filter(id=entry_id, library_id=memory_id)
        if not include_archived:
            query = query.filter(status="active", deleted_at=None)
        entry = await query.first()
        if entry is None:
            raise TranslationMemoryNotFoundError("翻译记忆条目不存在")
        return entry

    async def _record_revision(self, entry: TranslationMemoryEntry, user: User, change_note: str | None) -> None:
        await TranslationMemoryEntryRevision.create(
            entry=entry, version=entry.revision,
            snapshot={"source_language": entry.source_language, "target_language": entry.target_language,
                      "source_text": entry.source_text, "target_text": entry.target_text, "status": entry.status,
                      "origin": entry.origin, "metadata": entry.metadata},
            changed_by_id=user.id, change_note=change_note,
        )

    @staticmethod
    def _library_response(library: TranslationMemoryLibrary) -> TranslationMemoryLibraryResponse:
        return TranslationMemoryLibraryResponse.model_validate(library)

    @staticmethod
    def _entry_response(entry: TranslationMemoryEntry) -> TranslationMemoryEntryResponse:
        return TranslationMemoryEntryResponse.model_validate(entry)

    @staticmethod
    def _hash(value: str) -> str:
        return hashlib.sha256(" ".join(value.split()).casefold().encode()).hexdigest()

    @staticmethod
    def _encode_cursor(offset: int) -> str:
        return base64.urlsafe_b64encode(json.dumps({"offset": offset}).encode()).decode().rstrip("=")

    @staticmethod
    def _decode_cursor(cursor: str | None) -> int:
        if not cursor:
            return 0
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            offset = int(json.loads(base64.urlsafe_b64decode(padded).decode())["offset"])
        except (ValueError, KeyError, TypeError, json.JSONDecodeError, base64.binascii.Error) as exc:
            raise TranslationMemoryConflictError("分页游标无效") from exc
        if offset < 0:
            raise TranslationMemoryConflictError("分页游标无效")
        return offset
