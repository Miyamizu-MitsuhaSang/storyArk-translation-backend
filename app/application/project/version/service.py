"""Project business version creation and version-file lookup."""

from __future__ import annotations

from uuid import UUID

from tortoise import transactions

from ....domain.project.policies import ProjectPolicy
from ....domain.shared.errors import DomainError
from ....models import Document, Project, ProjectMember, ProjectVersion, User
from ....application.project.service import ProjectError
from ..shared import decode_cursor, encode_cursor
from .schemas import (
    FilePage,
    VersionCreateRequest,
    VersionFileResponse,
    VersionListQuery,
    VersionPage,
    VersionResponse,
)


class VersionError(ProjectError):
    code = "VERSION_ERROR"


class VersionNotFoundError(VersionError):
    status_code = 404
    code = "VERSION_NOT_FOUND"


class VersionForbiddenError(VersionError):
    status_code = 403
    code = "VERSION_FORBIDDEN"


class VersionValidationError(VersionError):
    status_code = 422
    code = "VERSION_INVALID"


class VersionService:
    async def list(self, user: User, project_id: UUID, query: VersionListQuery) -> VersionPage:
        await self._require_member(user, project_id)
        offset = decode_cursor(query.cursor)
        versions = ProjectVersion.filter(project_id=project_id)
        if query.q and query.q.strip():
            versions = versions.filter(name__icontains=query.q.strip())
        versions = versions.order_by(*self._order_clause(query.sort))
        total = await versions.count()
        rows = await versions.offset(offset).limit(query.page_size)
        next_offset = offset + len(rows)
        return VersionPage(
            items=[self._response(row) for row in rows],
            next_cursor=encode_cursor(next_offset) if next_offset < total else None,
            total=total,
        )

    async def create(
        self,
        user: User,
        project_id: UUID,
        request: VersionCreateRequest,
    ) -> VersionResponse:
        await self._require_manager(user, project_id)
        values = request.model_dump()
        async with transactions.in_transaction() as connection:
            project = (
                await Project.filter(id=project_id)
                .using_db(connection)
                .select_for_update()
                .first()
            )
            if project is None:
                raise VersionNotFoundError("项目不存在或当前用户不可见")
            version_number = project.next_version_number
            project.next_version_number = version_number + 1
            await project.save(using_db=connection, update_fields=["next_version_number", "updated_at"])
            row = await ProjectVersion.create(
                project_id=project.id,
                version_number=version_number,
                created_by_id=user.id,
                using_db=connection,
                **values,
            )
        return self._response(row)

    async def list_files(
        self,
        user: User,
        project_id: UUID,
        version_id: UUID,
        *,
        page_size: int = 20,
        cursor: str | None = None,
    ) -> FilePage:
        await self._require_member(user, project_id)
        version = await ProjectVersion.filter(id=version_id, project_id=project_id).first()
        if version is None:
            raise VersionNotFoundError("版本不存在或当前项目不可见")
        offset = decode_cursor(cursor)
        documents = (
            Document.filter(project_id=project_id, project_version_id=version.id)
            .exclude(status__in=["deletion_pending", "purged"])
            .order_by("-updated_at", "-id")
        )
        total = await documents.count()
        rows = await documents.offset(offset).limit(page_size)
        next_offset = offset + len(rows)
        return FilePage(
            items=[self._file_response(row) for row in rows],
            next_cursor=encode_cursor(next_offset) if next_offset < total else None,
            total=total,
        )

    async def _require_member(self, user: User, project_id: UUID) -> ProjectMember:
        membership = await ProjectMember.filter(project_id=project_id, user_id=user.id).first()
        if membership is None:
            raise VersionNotFoundError("项目不存在或当前用户不可见")
        return membership

    async def _require_manager(self, user: User, project_id: UUID) -> ProjectMember:
        membership = await self._require_member(user, project_id)
        try:
            ProjectPolicy.ensure_manager(membership.role)
        except DomainError as exc:
            raise VersionForbiddenError(str(exc)) from exc
        return membership

    @staticmethod
    def _order_clause(sort: str) -> tuple[str, str]:
        if sort == "name":
            return "name", "-version_number"
        if sort == "created_at":
            return "-created_at", "-version_number"
        return "-version_number", "-id"

    @staticmethod
    def _response(row: ProjectVersion) -> VersionResponse:
        return VersionResponse(
            id=row.id,
            project_id=row.project_id,
            version_number=row.version_number,
            name=row.name,
            description=row.description,
            source_language=row.source_language,
            target_languages=list(row.target_languages or []),
            created_by=row.created_by_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _file_response(document: Document) -> VersionFileResponse:
        return VersionFileResponse(
            id=document.id,
            name=document.name,
            source_language=document.source_language,
            format=document.file_format,
            updated_at=document.updated_at,
            size_bytes=document.file_size,
        )


__all__ = [
    "VersionError",
    "VersionForbiddenError",
    "VersionNotFoundError",
    "VersionService",
    "VersionValidationError",
]
