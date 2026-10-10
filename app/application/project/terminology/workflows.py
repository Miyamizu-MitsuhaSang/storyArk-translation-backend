from __future__ import annotations

import base64
import csv
import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from tortoise import transactions

from ...idempotency import execute_idempotently
from ....domain.project.policies import ProjectPolicy
from ....domain.shared.errors import DomainError
from ....models import (
    BackgroundJob,
    Document,
    Project,
    ProjectMember,
    TerminologyBase,
    TerminologyTerm,
    TerminologyTermRevision,
    TranslationMemoryEntry,
    TranslationMemoryLibrary,
    User,
)
from ....repositories import MembershipRepository, ProjectRepository, TerminologyRepository
from ..audit import ProjectAuditService
from ..service import ProjectConflictError, ProjectForbiddenError, ProjectNotFoundError
from .schemas import (
    BulkActionRequest,
    BulkActionResponse,
    ClearResult,
    FileResponseData,
    ImportResult,
    JobAccepted,
    TerminologyBulkActionRequest,
    TerminologyClearRequest,
    TerminologyExportRequest,
    TerminologyExtractRequest,
    TerminologyImportRequest,
    TerminologyImportInvalidRow,
    TerminologyMineRequest,
    TerminologyTermResponse,
)


WORKFLOW_JOB_TYPES = {
    "import": "terminology_import",
    "export": "terminology_export",
    "extract": "terminology_extract",
    "mine": "terminology_mine",
}


class TerminologyWorkflowValidationError(ProjectConflictError):
    status_code = 422
    code = "TERMINOLOGY_WORKFLOW_INVALID"


class TerminologyWorkflowNotFoundError(ProjectNotFoundError):
    code = "TERMINOLOGY_RESOURCE_NOT_FOUND"


class TerminologyWorkflowConflictError(ProjectConflictError):
    code = "TERMINOLOGY_WORKFLOW_CONFLICT"


class TerminologyVersionConflictError(ProjectConflictError):
    code = "VERSION_CONFLICT"

    def __init__(self, current_revision: int) -> None:
        super().__init__("术语版本已变化，请重新读取后再试", details={"current_revision": current_revision})


class TerminologyCountMismatchError(ProjectConflictError):
    code = "COUNT_MISMATCH"


class TerminologyWorkflowService:
    IMPORT_SYNC_LIMIT = 1000
    EXPORT_SYNC_LIMIT = 1000
    CLEAR_SYNC_LIMIT = 1000

    def __init__(
        self,
        *,
        projects: ProjectRepository | None = None,
        memberships: MembershipRepository | None = None,
        repository: TerminologyRepository | None = None,
    ) -> None:
        self._projects = projects or ProjectRepository()
        self._memberships = memberships or MembershipRepository()
        self._repository = repository or TerminologyRepository()

    async def import_terms(
        self,
        user: User,
        project_id: UUID,
        base_id: UUID,
        request: TerminologyImportRequest,
        *,
        idempotency_key: str | None = None,
    ) -> ImportResult:
        project, base = await self._authorized_base(user, project_id, base_id, manage=True)
        self._require_idempotency(idempotency_key)
        rows = self._parse_import(request, base)
        if len(rows) > self.IMPORT_SYNC_LIMIT:
            async def create_job() -> ImportResult:
                job = await self._create_job(
                    project_id,
                    base.version,
                    WORKFLOW_JOB_TYPES["import"],
                    {
                        "user_id": str(user.id),
                        "base_id": str(base_id),
                        "rows": rows,
                        "on_conflict": request.on_conflict,
                    },
                )
                return ImportResult(job=self._job_response(job))

            return await execute_idempotently(
                user,
                operation="terminology.import",
                scope=f"project:{project_id}:base:{base_id}",
                key=idempotency_key,
                payload=request.model_dump(mode="json"),
                response_type=ImportResult,
                callback=create_job,
            )

        async def callback() -> ImportResult:
            result = await self._import_rows(user, project, base, rows, request.on_conflict)
            await ProjectAuditService.record(
                project_id,
                actor_user_id=user.id,
                resource_type="terminology_base",
                resource_id=base.id,
                action="terminology_terms.imported",
                details={"created": result.created, "updated": result.updated, "skipped": result.skipped},
            )
            return result

        return await execute_idempotently(
            user,
            operation="terminology.import",
            scope=f"project:{project_id}:base:{base_id}",
            key=idempotency_key,
            payload=request.model_dump(mode="json"),
            response_type=ImportResult,
            callback=callback,
        )

    async def export_terms(
        self,
        user: User,
        project_id: UUID,
        base_id: UUID,
        request: TerminologyExportRequest,
        *,
        idempotency_key: str | None = None,
    ) -> FileResponseData | JobAccepted:
        project, base = await self._authorized_base(user, project_id, base_id)
        self._require_idempotency(idempotency_key)
        terms = await self._filtered_terms(base, request)
        if len(terms) > self.EXPORT_SYNC_LIMIT:
            job = await self._create_job(
                project_id,
                base.version,
                WORKFLOW_JOB_TYPES["export"],
                {"user_id": str(user.id), "base_id": str(base_id), "request": request.model_dump(mode="json")},
            )
            return self._job_response(job)
        return self._serialize_export(base, terms, request)

    async def bulk_action(
        self,
        user: User,
        project_id: UUID,
        base_id: UUID,
        request: TerminologyBulkActionRequest,
        *,
        idempotency_key: str | None = None,
    ) -> BulkActionResponse:
        project, base = await self._authorized_base(user, project_id, base_id, manage=True)
        self._require_idempotency(idempotency_key)
        async def callback() -> BulkActionResponse:
            if request.action == "delete" and not request.confirm:
                raise TerminologyWorkflowValidationError("批量删除必须 confirm=true")
            if request.action == "add_disabled_translation" and not request.value:
                raise TerminologyWorkflowValidationError("add_disabled_translation 必须提供 value")
            terms = await self._repository.list_terms_by_ids(base.id, request.term_ids)
            if len(terms) != len(request.term_ids):
                raise TerminologyWorkflowNotFoundError("术语不存在或不属于当前术语库")
            for term in terms:
                expected = request.expected_revisions.get(str(term.id))
                if expected is None:
                    raise TerminologyWorkflowValidationError("expected_revisions 必须覆盖全部 term_ids")
                if expected != term.version:
                    raise TerminologyVersionConflictError(term.version)
            async with transactions.in_transaction():
                for term in terms:
                    if request.action == "delete":
                        term.status = "archived"
                        term.deleted_at = datetime.now(timezone.utc)
                    elif request.action == "add_disabled_translation":
                        disabled = list(term.forbidden_translations or [])
                        if request.value not in disabled:
                            disabled.append(request.value)
                        term.forbidden_translations = disabled
                    else:
                        marker = "[required]"
                        if marker not in (term.notes or ""):
                            term.notes = f"{term.notes}\n{marker}".strip()
                    term.version += 1
                    await term.save(update_fields=[
                        "status", "deleted_at", "forbidden_translations", "notes", "version", "updated_at",
                    ])
                    await self._record_revision(term, user, f"批量操作: {request.action}")
                base.version += 1
                await base.save(update_fields=["version", "updated_at"])
            items = [await self._term_response(term) for term in terms]
            await ProjectAuditService.record(
                project_id,
                actor_user_id=user.id,
                resource_type="terminology_base",
                resource_id=base.id,
                action="terminology_terms.bulk_action",
                details={"action": request.action, "affected": len(terms)},
            )
            return BulkActionResponse(affected=len(terms), items=items)

        return await execute_idempotently(
            user,
            operation="terminology.bulk_action",
            scope=f"project:{project_id}:base:{base_id}",
            key=idempotency_key,
            payload=request.model_dump(mode="json"),
            response_type=BulkActionResponse,
            callback=callback,
        )

    async def clear(
        self,
        user: User,
        project_id: UUID,
        base_id: UUID,
        request: TerminologyClearRequest,
        *,
        idempotency_key: str | None = None,
    ) -> ClearResult:
        project, base = await self._authorized_base(user, project_id, base_id, manage=True)
        self._require_idempotency(idempotency_key)
        membership = await self._projects.find_membership(project_id, user.id)
        if membership is None or membership.role != "owner":
            raise ProjectForbiddenError("只有 owner 可以清空术语库")
        if not request.confirm:
            raise TerminologyWorkflowValidationError("清空术语库必须 confirm=true")
        count = await self._repository.count_terms(base)
        if count != request.expected_count:
            raise TerminologyCountMismatchError(
                f"术语数量已变化，当前数量为 {count}", details={"current_count": count}
            )
        if count > self.CLEAR_SYNC_LIMIT:
            async def create_job() -> ClearResult:
                job = await self._create_job(
                    project_id,
                    base.version,
                    "terminology_clear",
                    {"user_id": str(user.id), "base_id": str(base_id), "expected_count": count},
                )
                return ClearResult(deleted=0, job=self._job_response(job))

            return await execute_idempotently(
                user,
                operation="terminology.clear",
                scope=f"project:{project_id}:base:{base_id}",
                key=idempotency_key,
                payload=request.model_dump(mode="json"),
                response_type=ClearResult,
                callback=create_job,
            )

        async def callback() -> ClearResult:
            deleted = 0
            async with transactions.in_transaction():
                terms = await self._repository.list_terms(base)
                for term in terms:
                    term.status = "archived"
                    term.deleted_at = datetime.now(timezone.utc)
                    term.version += 1
                    await term.save(update_fields=["status", "deleted_at", "version", "updated_at"])
                    await self._record_revision(term, user, "清空术语库")
                    deleted += 1
                if deleted:
                    base.version += 1
                    await base.save(update_fields=["version", "updated_at"])
            await ProjectAuditService.record(
                project_id,
                actor_user_id=user.id,
                resource_type="terminology_base",
                resource_id=base.id,
                action="terminology_base.cleared",
                details={"deleted": deleted},
            )
            return ClearResult(deleted=deleted)

        return await execute_idempotently(
            user,
            operation="terminology.clear",
            scope=f"project:{project_id}:base:{base_id}",
            key=idempotency_key,
            payload=request.model_dump(mode="json"),
            response_type=ClearResult,
            callback=callback,
        )

    async def extract(
        self,
        user: User,
        project_id: UUID,
        request: TerminologyExtractRequest,
        *,
        idempotency_key: str | None = None,
    ) -> JobAccepted:
        self._require_idempotency(idempotency_key)
        project, base = await self._authorized_base(user, project_id, request.terminology_base_id, manage=True)
        documents = await Document.filter(id__in=request.file_ids, project_id=project_id)
        if len(documents) != len(request.file_ids):
            raise TerminologyWorkflowNotFoundError("文件不存在或不属于当前项目")
        if any(
            document.source_language != request.source_language
            or document.target_language not in request.target_languages
            for document in documents
        ):
            raise TerminologyWorkflowValidationError("文件语言与术语提取请求不匹配")
        self._validate_base_languages(base, request.target_languages)

        async def callback() -> JobAccepted:
            job = await self._create_job(
                project_id,
                base.version,
                WORKFLOW_JOB_TYPES["extract"],
                {"file_ids": [str(item) for item in request.file_ids], "min_occurrences": 1},
            )
            return self._job_response(job)

        return await execute_idempotently(
            user,
            operation="terminology.extract",
            scope=f"project:{project_id}",
            key=idempotency_key,
            payload=request.model_dump(mode="json"),
            response_type=JobAccepted,
            callback=callback,
        )

    async def mine(
        self,
        user: User,
        project_id: UUID,
        request: TerminologyMineRequest,
        *,
        idempotency_key: str | None = None,
    ) -> JobAccepted:
        self._require_idempotency(idempotency_key)
        project, base = await self._authorized_base(user, project_id, request.terminology_base_id, manage=True)
        self._validate_base_languages(base, request.target_languages)
        libraries = await TranslationMemoryLibrary.filter(id__in=request.tm_base_ids)
        if len(libraries) != len(request.tm_base_ids) or any(
            library.scope != "platform" and library.owner_user_id != user.id for library in libraries
        ):
            raise TerminologyWorkflowNotFoundError("翻译记忆库不存在或当前用户不可访问")

        async def callback() -> JobAccepted:
            job = await self._create_job(
                project_id,
                base.version,
                WORKFLOW_JOB_TYPES["mine"],
                {
                    "tm_base_ids": [str(item) for item in request.tm_base_ids],
                    "source_language": request.source_language,
                    "target_languages": request.target_languages,
                    "min_occurrences": request.min_occurrences,
                },
            )
            return self._job_response(job)

        return await execute_idempotently(
            user,
            operation="terminology.mine",
            scope=f"project:{project_id}",
            key=idempotency_key,
            payload=request.model_dump(mode="json"),
            response_type=JobAccepted,
            callback=callback,
        )

    async def _authorized_base(
        self,
        user: User,
        project_id: UUID,
        base_id: UUID,
        *,
        manage: bool = False,
    ) -> tuple[Project, TerminologyBase]:
        membership = await self._projects.find_membership(project_id, user.id, with_project=True)
        if membership is None:
            raise ProjectNotFoundError("项目不存在或当前用户不可见")
        if manage:
            self._require_manager(membership)
        base = await self._repository.find_base(project_id, base_id)
        if base is None:
            raise TerminologyWorkflowNotFoundError("术语库不存在")
        return membership.project, base

    @staticmethod
    def _require_manager(membership: ProjectMember) -> None:
        try:
            ProjectPolicy.ensure_manager(membership.role)
        except DomainError as exc:
            raise ProjectForbiddenError(str(exc)) from exc

    @staticmethod
    def _require_idempotency(key: str | None) -> None:
        if key is None or not key.strip():
            raise TerminologyWorkflowValidationError("该术语工作流必须提供 Idempotency-Key")

    @staticmethod
    def _validate_base_languages(base: TerminologyBase, languages: list[str]) -> None:
        unsupported = sorted(set(languages) - set(base.target_languages))
        if unsupported:
            raise TerminologyWorkflowValidationError(f"术语库未配置目标语言: {', '.join(unsupported)}")

    @staticmethod
    def _parse_import(request: TerminologyImportRequest, base: TerminologyBase) -> list[dict[str, object]]:
        if request.format == "csv":
            return TerminologyWorkflowService._parse_csv(request.content, base.target_languages)
        return TerminologyWorkflowService._parse_json(request.content, base.target_languages)

    @staticmethod
    def _parse_csv(content: str, languages: list[str]) -> list[dict[str, object]]:
        rows = list(csv.reader(io.StringIO(content)))
        if not rows:
            return []
        header = [cell.strip() for cell in rows[0]]
        normalized = [cell.casefold() for cell in header]
        has_header = any(item in {"source", "source_term", "原文"} for item in normalized)
        data = rows[1:] if has_header else rows
        source_index = next((index for index, item in enumerate(normalized) if item in {"source", "source_term", "原文"}), 0)
        language_indexes = {
            language: normalized.index(language.casefold())
            for language in languages
            if language.casefold() in normalized
        }
        result = []
        for line_number, row in enumerate(data, start=2 if has_header else 1):
            source = row[source_index].strip() if len(row) > source_index else ""
            target_values: dict[str, str] = {}
            for language_index, language in enumerate(languages):
                index = language_indexes.get(language, language_index + 1)
                if len(row) > index and row[index].strip():
                    target_values[language] = row[index].strip()
            result.append({"row": line_number, "source_term": source, "target_terms": target_values, "term_type": "general"})
        return result

    @staticmethod
    def _parse_json(content: str, languages: list[str]) -> list[dict[str, object]]:
        try:
            value = json.loads(content)
        except json.JSONDecodeError as exc:
            raise TerminologyWorkflowValidationError("JSON 术语内容无效") from exc
        rows = value.get("terms", []) if isinstance(value, dict) else value
        if not isinstance(rows, list):
            raise TerminologyWorkflowValidationError("JSON 术语内容必须是数组或 terms 数组")
        parsed = []
        for line_number, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                parsed.append({"row": line_number, "source_term": "", "target_terms": {}, "term_type": "general"})
                continue
            source = row.get("source_term", row.get("source", ""))
            translations = row.get("target_terms", row.get("translations", {}))
            if isinstance(translations, str):
                translations = {languages[0]: translations} if languages else {}
            parsed.append({
                "row": line_number,
                "source_term": source if isinstance(source, str) else "",
                "target_terms": translations if isinstance(translations, dict) else {},
                "term_type": row.get("term_type", "general"),
                "notes": row.get("notes"),
            })
        return parsed

    async def _import_rows(
        self,
        user: User,
        project: Project,
        base: TerminologyBase,
        rows: list[dict[str, object]],
        on_conflict: str,
    ) -> ImportResult:
        created = updated = skipped = 0
        invalid: list[TerminologyImportInvalidRow] = []
        async with transactions.in_transaction():
            for row in rows:
                row_number = int(row.get("row", 1))
                source = str(row.get("source_term", "")).strip()
                target_terms = row.get("target_terms", {})
                if not source:
                    invalid.append(TerminologyImportInvalidRow(row=row_number, code="SOURCE_REQUIRED", message="源术语不能为空"))
                    continue
                if not isinstance(target_terms, dict) or not target_terms or any(
                    not isinstance(language, str) or language not in base.target_languages or not isinstance(value, str) or not value.strip()
                    for language, value in target_terms.items()
                ):
                    invalid.append(TerminologyImportInvalidRow(row=row_number, code="TARGET_INVALID", message="译文语言或内容无效"))
                    continue
                term_type = str(row.get("term_type", "general"))
                if term_type not in {"character", "faction", "location", "item", "skill", "ui", "general"}:
                    invalid.append(TerminologyImportInvalidRow(row=row_number, code="TERM_TYPE_INVALID", message="术语类型无效"))
                    continue
                existing = await self._repository.find_term_by_source(base.id, source)
                if existing is not None:
                    if on_conflict == "skip":
                        skipped += 1
                        continue
                    if on_conflict == "error":
                        invalid.append(TerminologyImportInvalidRow(row=row_number, code="TERM_EXISTS", message="术语已存在"))
                        continue
                    existing.target_terms = target_terms
                    existing.term_type = term_type
                    existing.notes = row.get("notes") if isinstance(row.get("notes"), str) else existing.notes
                    existing.version += 1
                    await existing.save(update_fields=["target_terms", "term_type", "notes", "version", "updated_at"])
                    await self._record_revision(existing, user, "导入更新术语")
                    updated += 1
                    continue
                term = await TerminologyTerm.create(
                    base=base,
                    source_term=source,
                    target_terms=target_terms,
                    term_type=term_type,
                    status="suggested",
                    source="imported",
                    notes=row.get("notes") if isinstance(row.get("notes"), str) else None,
                    created_by_id=user.id,
                )
                await self._record_revision(term, user, "导入术语")
                created += 1
            if created or updated:
                base.version += 1
                await base.save(update_fields=["version", "updated_at"])
        return ImportResult(created=created, updated=updated, skipped=skipped, invalid_rows=invalid)

    async def _filtered_terms(self, base: TerminologyBase, request: TerminologyExportRequest) -> list[TerminologyTerm]:
        terms = await self._repository.list_terms(base, include_deleted=request.include_disabled)
        filters = request.filters
        if not request.include_disabled:
            terms = [term for term in terms if term.status not in {"archived", "deprecated"}]
        if request.language_codes:
            terms = [term for term in terms if any(language in term.target_terms for language in request.language_codes)]
        if filters:
            if filters.q:
                query = filters.q.casefold()
                terms = [term for term in terms if query in f"{term.source_term} {term.notes or ''} {' '.join(term.target_terms.values())}".casefold()]
            if filters.category:
                terms = [term for term in terms if term.term_type == filters.category]
            if filters.required is True:
                terms = [term for term in terms if "[required]" in (term.notes or "")]
            if filters.required is False:
                terms = [term for term in terms if "[required]" not in (term.notes or "")]
        return terms

    @staticmethod
    def _serialize_export(base: TerminologyBase, terms: list[TerminologyTerm], request: TerminologyExportRequest) -> FileResponseData:
        languages = request.language_codes or list(base.target_languages)
        if request.format == "json":
            content = json.dumps(
                [
                    {"source_term": term.source_term, "target_terms": {language: term.target_terms.get(language, "") for language in languages}, "term_type": term.term_type, "status": term.status}
                    for term in terms
                ],
                ensure_ascii=False,
            ).encode("utf-8")
        else:
            stream = io.StringIO()
            writer = csv.writer(stream)
            writer.writerow(["source_term", *languages, "term_type", "status"])
            for term in terms:
                writer.writerow([term.source_term, *[term.target_terms.get(language, "") for language in languages], term.term_type, term.status])
            content = stream.getvalue().encode("utf-8")
        safe_name = re.sub(r"[^A-Za-z0-9_.\-\u4e00-\u9fff]+", "-", base.name).strip("-.") or "terminology"
        return FileResponseData(content=content, filename=f"{safe_name}-terms.{request.format}", media_type="text/csv; charset=utf-8" if request.format == "csv" else "application/json")

    async def _create_job(self, project_id: UUID, requested_version: int, job_type: str, payload: dict[str, object]) -> BackgroundJob:
        return await BackgroundJob.create(
            type=job_type,
            status="queued",
            resource_type="project",
            resource_id=project_id,
            requested_version=requested_version,
            result={"workflow_payload": payload},
        )

    @staticmethod
    def _job_response(job: BackgroundJob) -> JobAccepted:
        return JobAccepted(job_id=job.id, status=job.status, type=job.type)

    async def _term_response(self, term: TerminologyTerm) -> TerminologyTermResponse:
        revisions = await self._repository.list_revisions(term)
        from .schemas import TerminologyTermRevisionSummary

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

    async def _record_revision(self, term: TerminologyTerm, user: User, note: str) -> None:
        await TerminologyTermRevision.create(
            term=term,
            version=term.version,
            snapshot={
                "source_term": term.source_term,
                "target_terms": term.target_terms,
                "term_type": term.term_type,
                "status": term.status,
                "forbidden_translations": term.forbidden_translations,
                "notes": term.notes,
                "source": term.source,
            },
            changed_by_id=user.id,
            change_note=note,
        )


__all__ = [
    "TerminologyCountMismatchError",
    "TerminologyVersionConflictError",
    "TerminologyWorkflowConflictError",
    "TerminologyWorkflowNotFoundError",
    "TerminologyWorkflowService",
    "TerminologyWorkflowValidationError",
    "WORKFLOW_JOB_TYPES",
]
