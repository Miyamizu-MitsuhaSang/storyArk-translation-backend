from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from tortoise.exceptions import IntegrityError

from ....domain.project.policies import ProjectPolicy
from ....domain.shared.errors import DomainError
from ....models import (
    Project,
    ProjectMember,
    TerminologyBase,
    TerminologyTerm,
    TerminologyTermRevision,
    User,
    WorldviewEntry,
)
from ....repositories import MembershipRepository, ProjectRepository, TerminologyRepository
from ..service import ProjectError, ProjectForbiddenError, ProjectNotFoundError
from ..audit import ProjectAuditService
from .schemas import (
    TerminologyBaseCreateRequest,
    TerminologyBasePage,
    TerminologyBaseResponse,
    TerminologySearchRequest,
    TerminologySearchResponse,
    TerminologyTermCreateRequest,
    TerminologyTermPage,
    TerminologyTermQuery,
    TerminologyTermResponse,
    TerminologyTermRevisionSummary,
    TerminologyTermUpdateRequest,
    TerminologyMatchResponse,
)


class TerminologyError(ProjectError):
    code = "TERMINOLOGY_ERROR"


class TerminologyBaseNotFoundError(TerminologyError):
    status_code = 404
    code = "TERMINOLOGY_BASE_NOT_FOUND"


class TerminologyTermNotFoundError(TerminologyError):
    status_code = 404
    code = "TERMINOLOGY_TERM_NOT_FOUND"


class TerminologyForbiddenError(TerminologyError):
    status_code = 403
    code = "TERMINOLOGY_FORBIDDEN"


class TerminologyConflictError(TerminologyError):
    status_code = 409
    code = "TERMINOLOGY_CONFLICT"


class TerminologyService:
    def __init__(self, *, projects: ProjectRepository | None = None, memberships: MembershipRepository | None = None, repository: TerminologyRepository | None = None) -> None:
        self._projects = projects or ProjectRepository()
        self._memberships = memberships or MembershipRepository()
        self._repository = repository or TerminologyRepository()

    async def list_bases(self, user: User, project_id: UUID, *, page_size: int, cursor: str | None) -> TerminologyBasePage:
        await self._authorized_project(user, project_id)
        rows = await self._repository.list_bases(project_id)
        offset = self._decode_cursor(cursor)
        page = rows[offset : offset + page_size]
        return TerminologyBasePage(
            items=[await self._base_response(base) for base in page],
            next_cursor=self._encode_cursor(offset + len(page)) if offset + len(page) < len(rows) else None,
            total=len(rows),
        )

    async def create_base(
        self,
        user: User,
        project_id: UUID,
        request: TerminologyBaseCreateRequest,
    ) -> TerminologyBaseResponse:
        project, membership = await self._authorized_project(user, project_id)
        self._require_manager(membership)
        try:
            base = await self._repository.create_base(project, **request.model_dump())
        except IntegrityError as exc:
            raise TerminologyConflictError("同一项目中术语库名称不能重复") from exc
        await ProjectAuditService.record(
            project_id, actor_user_id=user.id, resource_type="terminology_base", resource_id=base.id,
            action="terminology_base.created",
        )
        return await self._base_response(base)

    async def list_terms(
        self,
        user: User,
        project_id: UUID,
        base_id: UUID,
        query: TerminologyTermQuery,
    ) -> TerminologyTermPage:
        base = await self._authorized_base(user, project_id, base_id)
        rows = await self._repository.list_terms(base)
        normalized = query.q.strip().casefold() if query.q else None
        filtered = [
            term
            for term in rows
            if (query.term_type is None or term.term_type == query.term_type)
            and (query.status is None or term.status == query.status)
            and (query.language is None or query.language in term.target_terms)
            and (normalized is None or self._matches_term(term, normalized))
        ]
        offset = self._decode_cursor(query.cursor)
        page = filtered[offset : offset + query.page_size]
        next_offset = offset + len(page)
        return TerminologyTermPage(
            items=[await self._term_response(term) for term in page],
            next_cursor=self._encode_cursor(next_offset) if next_offset < len(filtered) else None,
            total=len(filtered),
        )

    async def create_term(
        self,
        user: User,
        project_id: UUID,
        base_id: UUID,
        request: TerminologyTermCreateRequest,
    ) -> TerminologyTermResponse:
        base = await self._authorized_base(user, project_id, base_id, manage=True)
        self._validate_target_languages(base, request.target_terms)
        worldview_entry_id = await self._validate_worldview_entry(project_id, request.worldview_entry_id)
        term = await self._repository.create_term(
            base,
            source_term=request.source_term.strip(),
            target_terms=request.target_terms,
            term_type=request.term_type,
            status=request.status,
            forbidden_translations=request.forbidden_translations,
            case_sensitive=request.case_sensitive,
            notes=request.notes,
            worldview_entry_id=worldview_entry_id,
            created_by_id=user.id,
        )
        await self._record_revision(term, user, None)
        await ProjectAuditService.record(
            project_id, actor_user_id=user.id, resource_type="terminology_term", resource_id=term.id,
            action="terminology_term.created",
        )
        return await self._term_response(term)

    async def get_term(self, user: User, project_id: UUID, base_id: UUID, term_id: UUID) -> TerminologyTermResponse:
        term = await self._authorized_term(user, project_id, base_id, term_id)
        return await self._term_response(term)

    async def update_term(
        self,
        user: User,
        project_id: UUID,
        base_id: UUID,
        term_id: UUID,
        request: TerminologyTermUpdateRequest,
    ) -> TerminologyTermResponse:
        term = await self._authorized_term(user, project_id, base_id, term_id, manage=True)
        base = await self._repository.find_base(project_id, base_id)
        changes = request.model_dump(exclude_unset=True, exclude={"change_note"})
        if not changes:
            return await self._term_response(term)
        if "target_terms" in changes:
            self._validate_target_languages(base, changes["target_terms"])
        if "worldview_entry_id" in changes:
            changes["worldview_entry_id"] = await self._validate_worldview_entry(project_id, changes["worldview_entry_id"])
        for field, value in changes.items():
            setattr(term, field, value)
        term.version += 1
        await self._repository.save_term(term, update_fields=[*changes.keys(), "version"])
        await self._record_revision(term, user, request.change_note)
        await ProjectAuditService.record(
            project_id, actor_user_id=user.id, resource_type="terminology_term", resource_id=term.id,
            action="terminology_term.updated",
        )
        return await self._term_response(term)

    async def delete_term(self, user: User, project_id: UUID, base_id: UUID, term_id: UUID) -> None:
        term = await self._authorized_term(user, project_id, base_id, term_id, manage=True)
        if term.deleted_at is None:
            term.deleted_at = datetime.now(timezone.utc)
            term.status = "archived"
            term.version += 1
            await self._repository.save_term(term, update_fields=["deleted_at", "status", "version"])
            await self._record_revision(term, user, "软删除术语")
            await ProjectAuditService.record(
                project_id, actor_user_id=user.id, resource_type="terminology_term", resource_id=term.id,
                action="terminology_term.deleted",
            )

    async def search(
        self,
        user: User,
        project_id: UUID,
        request: TerminologySearchRequest,
    ) -> TerminologySearchResponse:
        await self._authorized_project(user, project_id)
        bases = await self._repository.list_bases(project_id)
        bases = [base for base in bases if base.source_language == request.source_language and base.status == "active"]
        matches: list[TerminologyMatchResponse] = []
        for base in bases:
            terms = await self._repository.list_terms(base)
            for term in terms:
                if term.status not in {"approved", "suggested"} or request.target_language not in term.target_terms:
                    continue
                for start, end in self._find_occurrences(request.text, term.source_term, term.case_sensitive):
                    matches.append(
                        TerminologyMatchResponse(
                            term_id=term.id,
                            base_id=base.id,
                            source_term=term.source_term,
                            matched_text=request.text[start:end],
                            target_language=request.target_language,
                            target_term=term.target_terms[request.target_language],
                            status=term.status,
                            start=start,
                            end=end,
                            case_sensitive=term.case_sensitive,
                        )
                    )
                    if request.include_forbidden:
                        for forbidden in term.forbidden_translations:
                            matches.append(
                                TerminologyMatchResponse(
                                    term_id=term.id,
                                    base_id=base.id,
                                    source_term=term.source_term,
                                    matched_text=request.text[start:end],
                                    target_language=request.target_language,
                                    target_term=forbidden,
                                    status="forbidden",
                                    start=start,
                                    end=end,
                                    case_sensitive=term.case_sensitive,
                                )
                            )
        matches.sort(key=lambda item: (item.start, -(item.end - item.start), str(item.term_id), item.status))
        return TerminologySearchResponse(items=matches, total=len(matches))

    async def _authorized_project(self, user: User, project_id: UUID) -> tuple[Project, ProjectMember]:
        membership = await self._projects.find_membership(project_id, user.id, with_project=True)
        if membership is None:
            raise ProjectNotFoundError("项目不存在或当前用户不可见")
        return membership.project, membership

    async def _authorized_base(
        self,
        user: User,
        project_id: UUID,
        base_id: UUID,
        *,
        manage: bool = False,
    ) -> TerminologyBase:
        _, membership = await self._authorized_project(user, project_id)
        if manage:
            self._require_manager(membership)
        base = await self._repository.find_base(project_id, base_id)
        if base is None:
            raise TerminologyBaseNotFoundError("术语库不存在")
        return base

    async def _authorized_term(
        self,
        user: User,
        project_id: UUID,
        base_id: UUID,
        term_id: UUID,
        *,
        manage: bool = False,
    ) -> TerminologyTerm:
        await self._authorized_base(user, project_id, base_id, manage=manage)
        term = await self._repository.find_term(base_id, term_id)
        if term is None:
            raise TerminologyTermNotFoundError("术语不存在")
        return term

    @staticmethod
    def _require_manager(membership: ProjectMember) -> None:
        try:
            ProjectPolicy.ensure_manager(membership.role)
        except DomainError as exc:
            raise ProjectForbiddenError(str(exc)) from exc

    @staticmethod
    def _validate_target_languages(base: TerminologyBase, target_terms: dict[str, str]) -> None:
        unsupported = sorted(set(target_terms) - set(base.target_languages))
        if unsupported:
            raise TerminologyConflictError(f"译文包含术语库未配置的目标语言: {', '.join(unsupported)}")

    @staticmethod
    async def _validate_worldview_entry(project_id: UUID, entry_id: UUID | None) -> UUID | None:
        if entry_id is None:
            return None
        exists = await TerminologyRepository().worldview_entry_exists(project_id, entry_id)
        if not exists:
            raise TerminologyConflictError("关联的世界观条目不存在或不属于当前项目")
        return entry_id

    @staticmethod
    def _matches_term(term: TerminologyTerm, query: str) -> bool:
        values = [term.source_term, term.notes or "", *term.target_terms.values(), *term.forbidden_translations]
        return any(query in str(value).casefold() for value in values)

    async def _base_response(self, base: TerminologyBase) -> TerminologyBaseResponse:
        return TerminologyBaseResponse(
            id=base.id,
            project_id=base.project_id,
            name=base.name,
            description=base.description,
            source_language=base.source_language,
            target_languages=base.target_languages,
            priority=base.priority,
            status=base.status,
            version=base.version,
            term_count=await self._repository.count_terms(base),
            created_at=base.created_at,
            updated_at=base.updated_at,
        )

    async def _term_response(self, term: TerminologyTerm) -> TerminologyTermResponse:
        revisions = await self._repository.list_revisions(term)
        return TerminologyTermResponse(
            id=term.id,
            base_id=term.base_id,
            source_term=term.source_term,
            target_terms=term.target_terms,
            term_type=term.term_type,
            status=term.status,
            forbidden_translations=term.forbidden_translations,
            case_sensitive=term.case_sensitive,
            notes=term.notes,
            worldview_entry_id=term.worldview_entry_id,
            source=term.source,
            version=term.version,
            deleted_at=term.deleted_at,
            created_by_id=term.created_by_id,
            created_at=term.created_at,
            updated_at=term.updated_at,
            history=[
                TerminologyTermRevisionSummary(
                    id=revision.id,
                    version=revision.version,
                    changed_by_id=revision.changed_by_id,
                    change_note=revision.change_note,
                    changed_at=revision.created_at,
                )
                for revision in revisions
            ],
        )

    async def _record_revision(self, term: TerminologyTerm, user: User, change_note: str | None) -> None:
        await self._repository.create_revision(
            term=term,
            version=term.version,
            snapshot={
                "source_term": term.source_term,
                "target_terms": term.target_terms,
                "term_type": term.term_type,
                "status": term.status,
                "forbidden_translations": term.forbidden_translations,
                "case_sensitive": term.case_sensitive,
                "notes": term.notes,
                "worldview_entry_id": str(term.worldview_entry_id) if term.worldview_entry_id else None,
                "source": term.source,
            },
            changed_by_id=user.id,
            change_note=change_note,
        )

    @staticmethod
    def _find_occurrences(text: str, needle: str, case_sensitive: bool) -> list[tuple[int, int]]:
        if not needle:
            return []
        haystack = text if case_sensitive else text.casefold()
        target = needle if case_sensitive else needle.casefold()
        result: list[tuple[int, int]] = []
        start = 0
        while True:
            index = haystack.find(target, start)
            if index < 0:
                return result
            result.append((index, index + len(needle)))
            start = index + max(len(needle), 1)

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
            raise TerminologyConflictError("分页游标无效") from exc
        if offset < 0:
            raise TerminologyConflictError("分页游标无效")
        return offset
