from __future__ import annotations

import base64
import hashlib
import json
import logging
from time import perf_counter
from datetime import datetime, timezone
from typing import Iterable
from uuid import UUID, uuid4

from tortoise import transactions
from tortoise.exceptions import IntegrityError

from ...models import (
    TranslationMemoryEntry,
    TranslationMemoryEntryRevision,
    TranslationMemoryLibrary,
    TranslationMemoryEntrySource,
    TranslationMemoryImport,
    ProjectLanguagePair,
    User,
)
from ...domain.translation_memory.policies import can_write_library
from .schemas import (
    EffectiveTranslationMemoryScope,
    TranslationMemoryEntryCreateRequest,
    TranslationMemoryEntryPage,
    TranslationMemoryEntryResponse,
    TranslationMemoryEntryUpdateRequest,
    TranslationMemoryLibraryPage,
    TranslationMemoryLibraryResponse,
    TranslationMemoryLibraryUpdateRequest,
    TranslationMemorySearchRequest,
    TranslationMemorySearchResponse,
    TranslationMemoryImportRow,
    TranslationMemoryImportResult,
    JobReference,
)
from ...infrastructure.translation_memory.search_index import TranslationMemorySearchIndex, build_effective_scope, source_hash
from ...infrastructure.translation_memory.cache import NoopTranslationMemoryCache, RedisTranslationMemoryCache, TranslationMemoryCache, build_search_cache_key, cache_get, cache_set
from ...core import redis as redis_module
from ...core.config import app_settings
from ...application.project.service import ProjectForbiddenError, ProjectNotFoundError
from ...repositories import ProjectRepository
from ...models import ProjectMember


class TranslationMemoryError(Exception):
    status_code = 400
    code = "TRANSLATION_MEMORY_ERROR"


class TranslationMemoryNotFoundError(TranslationMemoryError):
    status_code = 404
    code = "TRANSLATION_MEMORY_NOT_FOUND"


class TranslationMemoryConflictError(TranslationMemoryError):
    status_code = 409
    code = "TRANSLATION_MEMORY_CONFLICT"


class TranslationMemoryIdempotencyError(TranslationMemoryError):
    status_code = 422
    code = "TRANSLATION_MEMORY_IDEMPOTENCY_MISMATCH"


class TranslationMemoryCursorError(TranslationMemoryError):
    status_code = 422
    code = "TRANSLATION_MEMORY_INVALID_CURSOR"


class TranslationMemoryIndexUnavailableError(TranslationMemoryError):
    status_code = 503
    code = "INDEX_NOT_AVAILABLE"


class TranslationMemoryService:
    IMPORT_SYNC_LIMIT = 100
    def __init__(self, *, search_index: TranslationMemorySearchIndex | None = None, cache: TranslationMemoryCache | None = None) -> None:
        if search_index is not None:
            self._search_index = search_index
        elif app_settings.tm_index_tasks_enabled:
            from ...tasks.translation_memory import TranslationMemoryTaskDispatcher
            self._search_index = TranslationMemorySearchIndex(TranslationMemoryTaskDispatcher())
        else:
            self._search_index = TranslationMemorySearchIndex()
        if cache is not None:
            self._cache = cache
        elif app_settings.tm_cache_enabled and redis_module.redis_client is not None:
            self._cache = RedisTranslationMemoryCache(
                redis_module.redis_client, namespace=app_settings.tm_cache_namespace
            )
        else:
            self._cache = NoopTranslationMemoryCache()
        self._projects = ProjectRepository()

    async def _ensure_project_member(self, user: User, project_id: UUID) -> ProjectMember:
        membership = await self._projects.find_membership(project_id, user.id)
        if membership is None:
            raise ProjectNotFoundError("项目不存在或当前用户不可见")
        return membership

    async def list_effective_libraries(self, user: User, project_id: UUID):
        await self._ensure_project_member(user, project_id)
        scope = await build_effective_scope(user.id)
        items = []
        for item in scope:
            library = await TranslationMemoryLibrary.get(id=item.library_id)
            response = self._library_response(library)
            response.priority = item.priority
            response.entry_count = item.entry_count
            response.language_pairs = item.language_pairs
            items.append(response)
        return TranslationMemoryLibraryPage(
            items=items,
            next_cursor=None,
            total=len(scope),
        )

    async def search(self, user: User, project_id: UUID, request: TranslationMemorySearchRequest) -> TranslationMemorySearchResponse:
        if len(request.source_text) > app_settings.tm_search_max_text_length:
            raise TranslationMemoryCursorError("查询文本超过长度限制")
        started_at = perf_counter()
        await self._ensure_project_member(user, project_id)
        scope = await build_effective_scope(user.id)
        key = build_search_cache_key(
            request,
            user_id=user.id,
            project_id=project_id,
            library_versions={item.library_id: item.content_version for item in scope},
            namespace=app_settings.tm_cache_namespace,
        )
        logger = logging.getLogger("translation_backend.translation_memory.search")
        try:
            cached = await cache_get(self._cache, key)
            if cached:
                logger.info("translation_memory_search cache_hit=true duration_ms=%.2f matches=cached", (perf_counter() - started_at) * 1000)
                return TranslationMemorySearchResponse.model_validate_json(cached)
        except Exception:
            logger.info("translation_memory_search cache_hit=false cache_available=false")
        matches = await self._search_index.search(scope, request)
        response = TranslationMemorySearchResponse(items=matches, total=len(matches), source_hash=source_hash(request.source_text))
        try:
            await cache_set(self._cache, key, response.model_dump_json(), app_settings.tm_cache_ttl_seconds)
        except Exception:
            logger.info("translation_memory_search cache_hit=false cache_write=false")
        logger.info("translation_memory_search cache_hit=false duration_ms=%.2f matches=%d", (perf_counter() - started_at) * 1000, len(matches))
        return response

    async def _invalidate_library_version(self, library_id: UUID, content_version: int) -> None:
        try:
            await self._cache.delete_by_library_version(library_id, content_version)
        except Exception:
            logging.getLogger("translation_backend.translation_memory.search").info(
                "translation_memory_cache_invalidation available=false"
            )

    async def reindex(self, user: User, project_id: UUID):
        await self._ensure_project_member(user, project_id)
        scope = await build_effective_scope(user.id)
        if not scope:
            raise TranslationMemoryIndexUnavailableError("没有可重建的翻译记忆库")
        try:
            return [self._search_index.enqueue_rebuild(item.library_id, item.content_version) for item in scope]
        except (RuntimeError, NotImplementedError) as exc:
            raise TranslationMemoryIndexUnavailableError(str(exc)) from exc
    async def get_or_create_user_library(self, user: User) -> TranslationMemoryLibrary:
        library = await TranslationMemoryLibrary.filter(scope="user", owner_user_id=user.id, status="active").first()
        if library:
            return library
        try:
            return await TranslationMemoryLibrary.create(
                scope="user", owner_user=user, name=f"{user.display_name} TM", status="active"
            )
        except IntegrityError:
            library = await TranslationMemoryLibrary.filter(scope="user", owner_user_id=user.id, status="active").first()
            if library is None:
                raise TranslationMemoryConflictError("用户翻译记忆库创建冲突")
            return library

    async def list_user_libraries(self, user: User, page_size: int, cursor: str | None) -> TranslationMemoryLibraryPage:
        page_size = max(1, min(page_size, app_settings.tm_search_max_page_size))
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
        page_size = max(1, min(page_size, app_settings.tm_search_max_page_size))
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
            library = await TranslationMemoryLibrary.filter(id=library.id).select_for_update().get()
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
                previous_version = library.content_version
                library.content_version += 1
                await library.save(update_fields=["content_version"])
                await self._invalidate_library_version(library.id, previous_version)
        return self._entry_response(entry)

    async def upsert_confirmed_segment(
        self,
        user: User,
        project_id: UUID,
        document_id: UUID | None,
        segment_id: UUID,
        source_language: str | None,
        target_language: str | None,
        source_text: str,
        target_text: str,
    ) -> TranslationMemoryEntry:
        """Write a confirmed segment to the user's TM and retain source provenance."""
        await self._ensure_project_member(user, project_id)
        if not source_language or not target_language:
            pair = await ProjectLanguagePair.filter(project_id=project_id, is_active=True).order_by("id").first()
            source_language = source_language or (pair.source_language if pair else "und")
            target_language = target_language or (pair.target_language if pair else "und")
        library = await self.get_or_create_user_library(user)
        source_digest = self._hash(source_text)
        target_digest = self._hash(target_text)
        async with transactions.in_transaction():
            library = await TranslationMemoryLibrary.filter(id=library.id).select_for_update().get()
            entry = await TranslationMemoryEntry.filter(
                library_id=library.id,
                source_language=source_language,
                target_language=target_language,
                source_hash=source_digest,
                target_hash=target_digest,
            ).first()
            if entry is None:
                entry = await TranslationMemoryEntry.create(
                    library=library,
                    source_language=source_language,
                    target_language=target_language,
                    source_text=source_text,
                    target_text=target_text,
                    source_hash=source_digest,
                    target_hash=target_digest,
                    origin="confirmed_segment",
                    metadata={},
                )
                await self._record_revision(entry, user, "确认 segment 写入翻译记忆")
                previous_version = library.content_version
                library.content_version += 1
                await library.save(update_fields=["content_version"])
                await self._invalidate_library_version(library.id, previous_version)
            source = await TranslationMemoryEntrySource.filter(
                entry_id=entry.id,
                user_id=user.id,
                project_id=project_id,
                document_id=document_id,
                segment_id=segment_id,
            ).first()
            if source is None:
                await TranslationMemoryEntrySource.create(
                    entry=entry,
                    user_id=user.id,
                    project_id=project_id,
                    document_id=document_id,
                    segment_id=segment_id,
                )
            else:
                # save() refreshes updated_at, providing last_seen_at semantics.
                await source.save()
        return entry

    async def import_entries(
        self,
        user: User,
        memory_id: UUID,
        rows: Iterable[TranslationMemoryImportRow],
        idempotency_key: str,
        *,
        _ignore_existing: bool = False,
    ) -> TranslationMemoryImportResult:
        """Import a bounded user batch, retaining every validation error's row number."""
        library = await self.get_user_library(user, memory_id)
        if not can_write_library(user, library):
            raise TranslationMemoryConflictError("翻译记忆库不可写入")
        if not idempotency_key.strip():
            raise TranslationMemoryConflictError("幂等键不能为空")
        materialized = list(rows)
        payload_hash = self._import_payload_hash(materialized)
        if len(materialized) > self.IMPORT_SYNC_LIMIT:
            from ...tasks.translation_memory import TranslationMemoryTaskDispatcher
            import_id = uuid4()
            async with transactions.in_transaction():
                locked = await TranslationMemoryLibrary.filter(id=library.id).select_for_update().get()
                existing = await TranslationMemoryImport.filter(
                    library_id=locked.id, user_id=user.id, idempotency_key=idempotency_key,
                ).first()
                if existing is not None:
                    if existing.payload_hash and existing.payload_hash != payload_hash:
                        raise TranslationMemoryIdempotencyError("相同幂等键不能复用不同的导入内容")
                    return TranslationMemoryImportResult(
                        imported=existing.imported, skipped=existing.skipped,
                        invalid_rows=existing.invalid_rows,
                        job=JobReference(job_id=existing.id, status="queued") if existing.status in {"queued", "running"} else None,
                    )
                await TranslationMemoryImport.create(
                    id=import_id, library=locked, user=user, idempotency_key=idempotency_key,
                    rows=[row.model_dump() if isinstance(row, TranslationMemoryImportRow) else row for row in materialized],
                    payload_hash=payload_hash,
                    status="queued",
                )
            job = TranslationMemoryTaskDispatcher().enqueue_import(user.id, memory_id, import_id)
            return TranslationMemoryImportResult(job=job)
        from pydantic import ValidationError
        valid: list[TranslationMemoryEntryCreateRequest] = []
        invalid: list[dict[str, object]] = []
        for row_number, row in enumerate(materialized, start=1):
            try:
                parsed = row if isinstance(row, TranslationMemoryImportRow) else TranslationMemoryImportRow.model_validate(row)
                valid.append(TranslationMemoryEntryCreateRequest(**parsed.model_dump()))
            except ValidationError as exc:
                field = str(exc.errors()[0].get("loc", ["row"])[0])
                code = (
                    "SOURCE_REQUIRED" if field in {"source_language", "source_text"}
                    else "TARGET_REQUIRED" if field in {"target_language", "target_text"}
                    else "ROW_INVALID"
                )
                invalid.append({"row": row_number, "code": code, "message": str(exc.errors()[0].get("msg", "行无效"))})
        imported = skipped = 0
        async with transactions.in_transaction():
            library = await TranslationMemoryLibrary.filter(id=library.id).select_for_update().get()
            existing = await TranslationMemoryImport.filter(library_id=library.id, user_id=user.id, idempotency_key=idempotency_key).first()
            if existing is not None and not _ignore_existing:
                if existing.payload_hash and existing.payload_hash != payload_hash:
                    raise TranslationMemoryIdempotencyError("相同幂等键不能复用不同的导入内容")
                return TranslationMemoryImportResult(imported=existing.imported, skipped=existing.skipped, invalid_rows=existing.invalid_rows)
            for request in valid:
                source_digest = self._hash(request.source_text)
                target_digest = self._hash(request.target_text)
                entry = await TranslationMemoryEntry.filter(
                    library_id=library.id, source_language=request.source_language, target_language=request.target_language,
                    source_hash=source_digest, target_hash=target_digest,
                ).first()
                if entry is None:
                    entry = await TranslationMemoryEntry.create(
                        library=library, source_language=request.source_language, target_language=request.target_language,
                        source_text=request.source_text, target_text=request.target_text, source_hash=source_digest,
                        target_hash=target_digest, origin=request.origin, metadata=request.metadata,
                    )
                    await self._record_revision(entry, user, "批量导入翻译记忆")
                    imported += 1
                else:
                    skipped += 1
            if imported:
                previous_version = library.content_version
                library.content_version += imported
                await library.save(update_fields=["content_version"])
                await self._invalidate_library_version(library.id, previous_version)
            if existing is None:
                await TranslationMemoryImport.create(
                    library=library, user=user, idempotency_key=idempotency_key,
                    imported=imported, skipped=skipped, invalid_rows=invalid, payload_hash=payload_hash, status="completed",
                )
            else:
                existing.imported = imported
                existing.skipped = skipped
                existing.invalid_rows = invalid
                existing.payload_hash = payload_hash
                existing.status = "completed"
                await existing.save(update_fields=["imported", "skipped", "invalid_rows", "payload_hash", "status"])
        return TranslationMemoryImportResult(imported=imported, skipped=skipped, invalid_rows=invalid)

    async def update_entry(self, user: User, memory_id: UUID, entry_id: UUID, request: TranslationMemoryEntryUpdateRequest) -> TranslationMemoryEntryResponse:
        async with transactions.in_transaction():
            library = await self.get_user_library(user, memory_id)
            if not can_write_library(user, library):
                raise TranslationMemoryConflictError("翻译记忆库不可写入")
            entry = await self._owned_entry(user, memory_id, entry_id)
            entry = await TranslationMemoryEntry.filter(id=entry.id).select_for_update().get()
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
            library = await TranslationMemoryLibrary.filter(id=memory_id).select_for_update().get()
            previous_version = library.content_version
            library.content_version += 1
            await library.save(update_fields=["content_version"])
            await self._invalidate_library_version(library.id, previous_version)
        return self._entry_response(entry)

    async def archive_entry(self, user: User, memory_id: UUID, entry_id: UUID, expected_revision: int) -> None:
        async with transactions.in_transaction():
            library = await self.get_user_library(user, memory_id)
            if not can_write_library(user, library):
                raise TranslationMemoryConflictError("翻译记忆库不可写入")
            entry = await self._owned_entry(user, memory_id, entry_id)
            entry = await TranslationMemoryEntry.filter(id=entry.id).select_for_update().get()
            if entry.revision != expected_revision:
                raise TranslationMemoryConflictError("条目版本已变化，请重新读取后归档")
            entry.status = "archived"
            entry.deleted_at = datetime.now(timezone.utc)
            entry.revision += 1
            await entry.save(update_fields=["status", "deleted_at", "revision"])
            await self._record_revision(entry, user, "归档翻译记忆条目")
            library = await TranslationMemoryLibrary.filter(id=memory_id).select_for_update().get()
            previous_version = library.content_version
            library.content_version += 1
            await library.save(update_fields=["content_version"])
            await self._invalidate_library_version(library.id, previous_version)

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

    @classmethod
    def _import_payload_hash(cls, rows: Iterable[TranslationMemoryImportRow]) -> str:
        payload = [
            row.model_dump(mode="json") if isinstance(row, TranslationMemoryImportRow) else row
            for row in rows
        ]
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

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
            raise TranslationMemoryCursorError("分页游标无效") from exc
        if offset < 0:
            raise TranslationMemoryCursorError("分页游标无效")
        return offset
