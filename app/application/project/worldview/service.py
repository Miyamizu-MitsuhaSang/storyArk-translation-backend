from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

from ....domain.project.policies import ProjectPolicy
from ....domain.shared.errors import DomainError
from ....models import Project, ProjectMember, User, Worldview, WorldviewEntry
from ....repositories import MembershipRepository, ProjectRepository, WorldviewRepository
from ..service import ProjectError, ProjectForbiddenError, ProjectNotFoundError
from .schemas import (
    WorldviewEntryCreateRequest,
    WorldviewEntryPage,
    WorldviewEntryResponse,
    WorldviewEntryRevisionSummary,
    WorldviewEntryUpdateRequest,
    WorldviewResponse,
    WorldviewUpdateRequest,
)


class WorldviewError(ProjectError):
    code = "WORLDVIEW_ERROR"


class WorldviewNotFoundError(WorldviewError):
    status_code = 404
    code = "WORLDVIEW_NOT_FOUND"


class WorldviewEntryNotFoundError(WorldviewError):
    status_code = 404
    code = "WORLDVIEW_ENTRY_NOT_FOUND"


class WorldviewForbiddenError(WorldviewError):
    status_code = 403
    code = "WORLDVIEW_FORBIDDEN"


class WorldviewConflictError(WorldviewError):
    status_code = 409
    code = "WORLDVIEW_CONFLICT"


class WorldviewService:
    def __init__(self, *, projects: ProjectRepository | None = None, memberships: MembershipRepository | None = None, repository: WorldviewRepository | None = None) -> None:
        self._projects = projects or ProjectRepository()
        self._memberships = memberships or MembershipRepository()
        self._repository = repository or WorldviewRepository()

    async def get(self, user: User, project_id: UUID) -> WorldviewResponse:
        project, _ = await self._authorized_project(user, project_id)
        worldview = await self._repository.find(project.id)
        if worldview is None:
            raise WorldviewNotFoundError("项目尚未创建世界观")
        return self._worldview_response(worldview)

    async def update(
        self,
        user: User,
        project_id: UUID,
        request: WorldviewUpdateRequest,
    ) -> WorldviewResponse:
        project, membership = await self._authorized_project(user, project_id)
        self._require_manager(membership)
        worldview = await self._repository.find(project.id)
        changes = request.model_dump(exclude_unset=True)
        if worldview is None:
            worldview = await self._repository.get_or_create(
                project,
                name=request.name or f"{project.name} Worldview",
            )
            for field, value in changes.items():
                if hasattr(worldview, field) and value is not None:
                    setattr(worldview, field, value)
            await self._repository.save(worldview, update_fields=[key for key in changes if hasattr(worldview, key)])
            return self._worldview_response(worldview)
        if changes:
            for field, value in changes.items():
                if value is not None or field in {"style_guide", "default_tone", "version_note"}:
                    setattr(worldview, field, value)
            worldview.version += 1
            await self._repository.save(worldview, update_fields=[*changes.keys(), "version"])
        return self._worldview_response(worldview)

    async def list_entries(
        self,
        user: User,
        project_id: UUID,
        *,
        entry_type: str | None,
        query: str | None,
        status: str | None,
        page_size: int,
        cursor: str | None,
    ) -> WorldviewEntryPage:
        _, _ = await self._authorized_project(user, project_id)
        worldview = await self._repository.find(project_id)
        if worldview is None:
            return WorldviewEntryPage(items=[], next_cursor=None, total=0)
        rows, _ = await self._repository.list_entries(worldview)
        normalized_query = query.strip().casefold() if query else None
        filtered = [
            entry
            for entry in rows
            if (entry_type is None or entry.entry_type == entry_type)
            and (status is None or entry.status == status)
            and (normalized_query is None or self._matches(entry, normalized_query))
        ]
        offset = self._decode_cursor(cursor)
        page = filtered[offset : offset + page_size]
        next_offset = offset + len(page)
        return WorldviewEntryPage(
            items=[await self._entry_response(entry) for entry in page],
            next_cursor=self._encode_cursor(next_offset) if next_offset < len(filtered) else None,
            total=len(filtered),
        )

    async def create_entry(
        self,
        user: User,
        project_id: UUID,
        request: WorldviewEntryCreateRequest,
    ) -> WorldviewEntryResponse:
        project, membership = await self._authorized_project(user, project_id)
        self._require_manager(membership)
        worldview = await self._repository.get_or_create(project, name=f"{project.name} Worldview")
        entry = await self._repository.create_entry(
            worldview,
            entry_key=f"{request.type}-{uuid4().hex}",
            entry_type=request.type,
            name=request.name.strip(),
            aliases=request.aliases,
            description=request.description,
            attributes=request.attributes,
            language_variants=request.language_variants,
            tags=request.tags,
            status=request.status,
        )
        await self._record_revision(entry, user, None)
        return await self._entry_response(entry)

    async def get_entry(self, user: User, project_id: UUID, entry_id: UUID) -> WorldviewEntryResponse:
        entry = await self._authorized_entry(user, project_id, entry_id)
        return await self._entry_response(entry)

    async def update_entry(
        self,
        user: User,
        project_id: UUID,
        entry_id: UUID,
        request: WorldviewEntryUpdateRequest,
    ) -> WorldviewEntryResponse:
        entry = await self._authorized_entry(user, project_id, entry_id)
        membership = await self._memberships.find(project_id, user.id)
        self._require_manager(membership)
        changes = request.model_dump(exclude_unset=True, exclude={"change_note"})
        if not changes:
            return await self._entry_response(entry)
        for field, value in changes.items():
            setattr(entry, "entry_type" if field == "type" else field, value)
        entry.version += 1
        await self._repository.save_entry(entry, update_fields=["entry_type" if field == "type" else field for field in changes] + ["version"])
        await self._record_revision(entry, user, request.change_note)
        return await self._entry_response(entry)

    async def delete_entry(self, user: User, project_id: UUID, entry_id: UUID) -> None:
        entry = await self._authorized_entry(user, project_id, entry_id)
        membership = await self._memberships.find(project_id, user.id)
        self._require_manager(membership)
        if entry.deleted_at is None:
            entry.deleted_at = datetime.now(timezone.utc)
            entry.status = "archived"
            entry.version += 1
            await self._repository.save_entry(entry, update_fields=["deleted_at", "status", "version"])
            await self._record_revision(entry, user, "软删除世界观条目")

    async def _authorized_project(self, user: User, project_id: UUID) -> tuple[Project, ProjectMember]:
        membership = await self._projects.find_membership(project_id, user.id, with_project=True)
        if membership is None:
            raise ProjectNotFoundError("项目不存在或当前用户不可见")
        return membership.project, membership

    async def _authorized_entry(self, user: User, project_id: UUID, entry_id: UUID) -> WorldviewEntry:
        _, _ = await self._authorized_project(user, project_id)
        entry = await self._repository.find_entry(project_id, entry_id)
        if entry is None:
            raise WorldviewEntryNotFoundError("世界观条目不存在")
        return entry

    @staticmethod
    def _require_manager(membership: ProjectMember | None) -> None:
        if membership is None:
            raise ProjectForbiddenError("当前角色没有世界观管理权限")
        try:
            ProjectPolicy.ensure_manager(membership.role)
        except DomainError as exc:
            raise ProjectForbiddenError(str(exc)) from exc

    @staticmethod
    def _matches(entry: WorldviewEntry, query: str) -> bool:
        values = [entry.entry_key, entry.name, entry.description or "", *entry.aliases, *entry.tags]
        values.extend(entry.language_variants.values())
        return any(query in str(value).casefold() for value in values)

    async def _entry_response(self, entry: WorldviewEntry) -> WorldviewEntryResponse:
        revisions = await self._repository.list_revisions(entry)
        return WorldviewEntryResponse(
            id=entry.id,
            entry_key=entry.entry_key,
            type=entry.entry_type,
            name=entry.name,
            aliases=entry.aliases,
            description=entry.description,
            attributes=entry.attributes,
            language_variants=entry.language_variants,
            tags=entry.tags,
            status=entry.status,
            version=entry.version,
            deleted_at=entry.deleted_at,
            created_at=entry.created_at,
            updated_at=entry.updated_at,
            history=[
                WorldviewEntryRevisionSummary(
                    id=revision.id,
                    version=revision.version,
                    changed_by_id=revision.changed_by_id,
                    change_note=revision.change_note,
                    changed_at=revision.created_at,
                )
                for revision in revisions
            ],
        )

    @staticmethod
    def _worldview_response(worldview: Worldview) -> WorldviewResponse:
        return WorldviewResponse(
            id=worldview.id,
            project_id=worldview.project_id,
            name=worldview.name,
            style_guide=worldview.style_guide,
            default_tone=worldview.default_tone,
            version_note=worldview.version_note,
            status=worldview.status,
            version=worldview.version,
            created_at=worldview.created_at,
            updated_at=worldview.updated_at,
        )

    async def _record_revision(self, entry: WorldviewEntry, user: User, change_note: str | None) -> None:
        await self._repository.create_revision(
            entry=entry,
            version=entry.version,
            snapshot={
                "entry_key": entry.entry_key,
                "type": entry.entry_type,
                "name": entry.name,
                "aliases": entry.aliases,
                "description": entry.description,
                "attributes": entry.attributes,
                "language_variants": entry.language_variants,
                "tags": entry.tags,
                "status": entry.status,
            },
            changed_by_id=user.id,
            change_note=change_note,
        )

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
            raise WorldviewConflictError("分页游标无效") from exc
        if offset < 0:
            raise WorldviewConflictError("分页游标无效")
        return offset
