from __future__ import annotations

import base64
import hashlib
import json
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from ....core.config import app_settings
from ....domain.project.policies import ProjectPolicy
from ....domain.shared.errors import DomainError
from ...idempotency import IdempotencyConflictError, execute_idempotently
from ..audit import ProjectAuditService
from ....infrastructure.document.storage import DocumentStorageError, LocalDocumentStorage
from ....models import BackgroundJob, Document, DocumentSegment, ProjectMember, ProjectVersion, User
from ....repositories.document import DocumentRepository
from .schemas import (
    DocumentExportRequest,
    DocumentEnvelopeResponse,
    DocumentListQuery,
    DocumentPage,
    DocumentParseRequest,
    DocumentResponse,
    DocumentSegmentPage,
    DocumentSegmentResponse,
    DocumentTaskResponse,
    DocumentTaskStatusResponse,
)


DOCUMENT_JOB_TYPES = {
    "import": "document_import",
    "parse": "document_parse",
    "export": "document_export",
    "purge": "document_purge",
}
SUPPORTED_FORMATS = {"xliff", "csv", "xlsx", "json", "po", "txt"}


class DocumentError(Exception):
    status_code = 400
    code = "DOCUMENT_ERROR"


class DocumentNotFoundError(DocumentError):
    status_code = 404
    code = "DOCUMENT_NOT_FOUND"


class DocumentForbiddenError(DocumentError):
    status_code = 403
    code = "DOCUMENT_FORBIDDEN"


class DocumentConflictError(DocumentError):
    status_code = 409
    code = "DOCUMENT_BUSY"


class DocumentIdempotencyConflictError(DocumentConflictError):
    code = "IDEMPOTENCY_CONFLICT"


class DocumentValidationError(DocumentError):
    status_code = 422
    code = "DOCUMENT_INVALID"


class DocumentService:
    def __init__(
        self,
        *,
        documents: DocumentRepository | None = None,
        storage: LocalDocumentStorage | None = None,
    ) -> None:
        self._documents = documents or DocumentRepository()
        self._storage = storage or LocalDocumentStorage(app_settings.document_storage_dir)

    async def list(self, user: User, project_id: UUID, query: DocumentListQuery) -> DocumentPage:
        await self._membership(user, project_id)
        offset = self._decode_cursor(query.cursor)
        rows, total = await self._documents.list(
            project_id,
            status=query.status,
            file_name=query.file_name,
            created_by=query.created_by,
            source_language=query.source_language,
            target_language=query.target_language,
            order_by=self._order_clause(query.sort),
            offset=offset,
            limit=query.page_size,
        )
        items = [self._response(row) for row in rows]
        next_offset = offset + len(items)
        return DocumentPage(
            items=items,
            next_cursor=self._encode_cursor(next_offset) if next_offset < total else None,
            total=total,
        )

    async def upload(
        self,
        user: User,
        project_id: UUID,
        *,
        filename: str,
        content_type: str | None,
        content: bytes,
        name: str | None,
        source_language: str,
        target_language: str,
        translation_memory_ids: list[UUID] | None = None,
        version_id: UUID | None = None,
        idempotency_key: str | None = None,
    ) -> DocumentTaskResponse:
        return await self._idempotent(
            user,
            project_id,
            "document.upload",
            str(project_id),
            idempotency_key,
            {
                "filename": filename,
                "content_type": content_type,
                "content_sha256": hashlib.sha256(content).hexdigest(),
                "name": name,
                "source_language": source_language,
                "target_language": target_language,
                "translation_memory_ids": [str(item) for item in (translation_memory_ids or [])],
                "version_id": str(version_id) if version_id else None,
            },
            DocumentTaskResponse,
            lambda: self._upload_impl(
                user, project_id, filename=filename, content_type=content_type, content=content,
                name=name, source_language=source_language, target_language=target_language,
                translation_memory_ids=translation_memory_ids,
                version_id=version_id,
            ),
        )

    async def _upload_impl(
        self,
        user: User,
        project_id: UUID,
        *,
        filename: str,
        content_type: str | None,
        content: bytes,
        name: str | None,
        source_language: str,
        target_language: str,
        translation_memory_ids: list[UUID] | None = None,
        version_id: UUID | None = None,
    ) -> DocumentTaskResponse:
        await self._membership(user, project_id)
        if version_id is not None and not await ProjectVersion.filter(id=version_id, project_id=project_id).exists():
            raise DocumentNotFoundError("项目业务版本不存在")
        file_format = self._format_for(filename)
        if file_format not in SUPPORTED_FORMATS:
            raise DocumentValidationError("不支持的文档格式")
        if not content:
            raise DocumentValidationError("上传文件不能为空")
        if len(content) > app_settings.document_max_file_bytes:
            raise DocumentValidationError("上传文件超过大小限制")
        document = await Document.create(
            project_id=project_id,
            created_by=user,
            name=(name or Path(filename).stem or filename).strip()[:160],
            file_name=filename[:255],
            file_format=file_format,
            mime_type=content_type,
            checksum_sha256=hashlib.sha256(content).hexdigest(),
            file_size=len(content),
            source_language=source_language,
            target_language=target_language,
            translation_memory_ids=[str(item) for item in (translation_memory_ids or [])],
            project_version_id=version_id,
            status="uploaded",
        )
        storage_key = f"projects/{project_id}/documents/{document.id}/source.{file_format}"
        try:
            self._storage.put(storage_key=storage_key, content=content)
        except DocumentStorageError as exc:
            await document.delete()
            raise DocumentError("文档文件保存失败") from exc
        document.storage_uri = storage_key
        await document.save(update_fields=["storage_uri", "updated_at"])
        job = await self._create_job(document, DOCUMENT_JOB_TYPES["import"])
        await ProjectAuditService.record(
            project_id,
            actor_user_id=user.id,
            resource_type="document",
            resource_id=document.id,
            action="document.uploaded",
            details={"format": file_format, "size_bytes": len(content)},
        )
        return DocumentTaskResponse(document=self._response(document), job_id=job.id)

    async def get(self, user: User, project_id: UUID, document_id: UUID) -> DocumentResponse:
        await self._membership(user, project_id)
        document = await self._get(project_id, document_id)
        return self._response(document)

    async def archive(
        self, user: User, project_id: UUID, document_id: UUID, *, idempotency_key: str | None = None
    ) -> DocumentEnvelopeResponse:
        return await self._idempotent(
            user, project_id, "document.archive", str(document_id), idempotency_key, {},
            DocumentEnvelopeResponse, lambda: self._archive_impl(user, project_id, document_id),
        )

    async def _archive_impl(self, user: User, project_id: UUID, document_id: UUID) -> DocumentEnvelopeResponse:
        membership = await self._membership(user, project_id)
        self._require_manager(membership)
        document = await self._get(project_id, document_id)
        if document.status in {"parsing", "deletion_pending"} or await self._has_active_job(document):
            raise DocumentConflictError("文档当前正在处理，不能归档")
        if document.status == "purged":
            raise DocumentConflictError("文件已清理，不能归档")
        if document.status != "archived":
            document.status = "archived"
            document.archived_at = datetime.now(timezone.utc)
            await document.save(update_fields=["status", "archived_at", "updated_at"])
            await ProjectAuditService.record(
                project_id,
                actor_user_id=user.id,
                resource_type="document",
                resource_id=document.id,
                action="document.archived",
            )
        return DocumentEnvelopeResponse(document=self._response(document))

    async def delete(
        self, user: User, project_id: UUID, document_id: UUID, *, idempotency_key: str | None = None
    ) -> DocumentTaskResponse:
        return await self._idempotent(
            user, project_id, "document.delete", str(document_id), idempotency_key, {},
            DocumentTaskResponse, lambda: self._delete_impl(user, project_id, document_id),
        )

    async def _delete_impl(self, user: User, project_id: UUID, document_id: UUID) -> DocumentTaskResponse:
        membership = await self._membership(user, project_id)
        self._require_manager(membership)
        document = await self._get(project_id, document_id)
        if document.status == "purged":
            job = await self._latest_job(document, DOCUMENT_JOB_TYPES["purge"])
            if job is None:
                job = await self._create_job(document, DOCUMENT_JOB_TYPES["purge"])
            return DocumentTaskResponse(document=self._response(document), job_id=job.id)
        if document.status == "deletion_pending":
            job = await self._latest_job(document, DOCUMENT_JOB_TYPES["purge"])
            if job is None:
                job = await self._create_job(document, DOCUMENT_JOB_TYPES["purge"])
            return DocumentTaskResponse(document=self._response(document), job_id=job.id)
        if document.status in {"parsing"} or await self._has_active_job(document):
            raise DocumentConflictError("文档当前被后台任务使用，不能删除")
        now = datetime.now(timezone.utc)
        if document.status != "deletion_pending":
            document.status = "deletion_pending"
            document.deleted_at = now
            document.purge_after = now + timedelta(seconds=app_settings.document_purge_grace_seconds)
            await document.save(update_fields=["status", "deleted_at", "purge_after", "updated_at"])
            await ProjectAuditService.record(
                project_id,
                actor_user_id=user.id,
                resource_type="document",
                resource_id=document.id,
                action="document.delete_requested",
            )
        job = await self._latest_job(document, DOCUMENT_JOB_TYPES["purge"])
        if job is None:
            job = await self._create_job(document, DOCUMENT_JOB_TYPES["purge"])
        return DocumentTaskResponse(document=self._response(document), job_id=job.id)

    async def parse(
        self,
        user: User,
        project_id: UUID,
        document_id: UUID,
        request: DocumentParseRequest,
        *,
        idempotency_key: str | None = None,
    ) -> DocumentTaskResponse:
        return await self._idempotent(
            user, project_id, "document.parse", str(document_id), idempotency_key,
            request.model_dump(mode="json"), DocumentTaskResponse,
            lambda: self._parse_impl(user, project_id, document_id, request),
        )

    async def _parse_impl(
        self, user: User, project_id: UUID, document_id: UUID, request: DocumentParseRequest
    ) -> DocumentTaskResponse:
        membership = await self._membership(user, project_id)
        self._require_manager(membership)
        document = await self._get(project_id, document_id)
        if document.status in {"archived", "deletion_pending", "purged"}:
            raise DocumentConflictError("当前文档状态不允许解析")
        if document.translated_segment_count and not request.preserve_translations:
            raise DocumentValidationError("文档已有译文，必须显式设置 preserve_translations=true")
        active = await self._latest_job(document, DOCUMENT_JOB_TYPES["parse"], active_only=True)
        if active is not None:
            return DocumentTaskResponse(document=self._response(document), job_id=active.id)
        document.status = "parsing"
        document.version += 1
        await document.save(update_fields=["status", "version", "updated_at"])
        job = await self._create_job(
            document,
            DOCUMENT_JOB_TYPES["parse"],
            result={"preserve_translations": request.preserve_translations},
        )
        document.last_parse_job_id = job.id
        await document.save(update_fields=["last_parse_job_id", "updated_at"])
        return DocumentTaskResponse(document=self._response(document), job_id=job.id)

    async def segments(
        self,
        user: User,
        project_id: UUID,
        document_id: UUID,
        *,
        status: str | None = None,
        workflow_state: str | None = None,
        assigned_to: UUID | None = None,
        q: str | None = None,
        segment_no_from: int | None = None,
        segment_no_to: int | None = None,
        page_size: int = 20,
        cursor: str | None = None,
        sort: str = "segment_no",
    ) -> DocumentSegmentPage:
        await self._membership(user, project_id)
        await self._get(project_id, document_id)
        offset = self._decode_cursor(cursor)
        rows, total = await self._documents.list_segments(
            document_id,
            status=status,
            workflow_state=workflow_state,
            assigned_to=assigned_to,
            q=q,
            segment_no_from=segment_no_from,
            segment_no_to=segment_no_to,
            order_by=self._segment_order_clause(sort),
            offset=offset,
            limit=page_size,
        )
        items = [self._segment_response(row) for row in rows]
        next_offset = offset + len(items)
        return DocumentSegmentPage(
            items=items,
            next_cursor=self._encode_cursor(next_offset) if next_offset < total else None,
            total=total,
        )

    async def export(
        self,
        user: User,
        project_id: UUID,
        document_id: UUID,
        request: DocumentExportRequest,
        *,
        idempotency_key: str | None = None,
    ) -> DocumentTaskResponse:
        return await self._idempotent(
            user, project_id, "document.export", str(document_id), idempotency_key,
            request.model_dump(mode="json"), DocumentTaskResponse,
            lambda: self._export_impl(user, project_id, document_id, request),
        )

    async def _export_impl(
        self, user: User, project_id: UUID, document_id: UUID, request: DocumentExportRequest
    ) -> DocumentTaskResponse:
        membership = await self._membership(user, project_id)
        self._require_manager(membership)
        document = await self._get(project_id, document_id)
        if document.status in {"deletion_pending", "purged", "archived"}:
            raise DocumentConflictError("当前文档状态不允许导出")
        job = await self._create_job(
            document,
            DOCUMENT_JOB_TYPES["export"],
            result={
                "format": request.format,
                "include_untranslated": request.include_untranslated,
                "include_review_notes": request.include_review_notes,
            },
        )
        return DocumentTaskResponse(document=self._response(document), job_id=job.id)

    async def _idempotent(
        self,
        user: User,
        project_id: UUID,
        operation: str,
        scope: str,
        key: str | None,
        payload: object,
        response_type,
        callback,
    ):
        try:
            return await execute_idempotently(
                user,
                operation=operation,
                scope=f"project:{project_id}:{scope}",
                key=key,
                payload=payload,
                response_type=response_type,
                callback=callback,
            )
        except IdempotencyConflictError as exc:
            raise DocumentIdempotencyConflictError(str(exc)) from exc

    async def get_job_status(self, user: User, job_id: UUID) -> DocumentTaskStatusResponse:
        job = await BackgroundJob.filter(id=job_id, resource_type="document").first()
        if job is None:
            raise DocumentNotFoundError("后台任务不存在")
        document = await Document.get_or_none(id=job.resource_id)
        if document is None or not await ProjectMember.filter(project_id=document.project_id, user_id=user.id).exists():
            raise DocumentNotFoundError("后台任务不存在")
        result = job.result if isinstance(job.result, dict) else None
        safe_result = None
        if result is not None:
            safe_result = {
                key: result[key]
                for key in ("status", "format", "segment_count", "size_bytes")
                if key in result
            }
        return DocumentTaskStatusResponse(
            job_id=job.id,
            type=job.type,
            status=job.status,
            requested_version=job.requested_version,
            attempts=job.attempts,
            max_attempts=job.max_attempts,
            result=safe_result,
            error_code=job.error_code,
            error_message="文档任务执行失败" if job.status == "failed" else None,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )

    async def _membership(self, user: User, project_id: UUID) -> ProjectMember:
        membership = await ProjectMember.filter(project_id=project_id, user_id=user.id).first()
        if membership is None:
            raise DocumentNotFoundError("项目或文档不存在")
        return membership

    async def _get(self, project_id: UUID, document_id: UUID) -> Document:
        document = await self._documents.get(project_id, document_id)
        if document is None:
            raise DocumentNotFoundError("文档不存在")
        return document

    @staticmethod
    def _require_manager(membership: ProjectMember) -> None:
        try:
            ProjectPolicy.ensure_manager(membership.role)
        except DomainError as exc:
            raise DocumentForbiddenError(str(exc)) from exc

    async def _create_job(
        self,
        document: Document,
        job_type: str,
        *,
        result: dict[str, object] | None = None,
    ) -> BackgroundJob:
        job = await BackgroundJob.create(
            type=job_type,
            status="queued",
            resource_type="document",
            resource_id=document.id,
            requested_version=document.version,
            result=result,
        )
        if app_settings.document_tasks_enabled:
            from ....tasks.documents import process_document_job_task

            try:
                await asyncio.to_thread(
                    process_document_job_task.apply_async,
                    args=[str(job.id)],
                    task_id=str(job.id),
                )
            except Exception as exc:
                job.status = "failed"
                job.error_code = "DOCUMENT_TASK_DISPATCH_FAILED"
                job.error_message = "文档任务队列暂时不可用"
                job.finished_at = datetime.now(timezone.utc)
                await job.save(update_fields=["status", "error_code", "error_message", "finished_at", "updated_at"])
                raise DocumentError("文档任务队列暂时不可用") from exc
        return job

    async def _latest_job(
        self,
        document: Document,
        job_type: str,
        *,
        active_only: bool = False,
    ) -> BackgroundJob | None:
        query = BackgroundJob.filter(resource_type="document", resource_id=document.id, type=job_type)
        if active_only:
            query = query.filter(status__in=["queued", "running"])
        return await query.order_by("-created_at").first()

    async def _has_active_job(self, document: Document) -> bool:
        return await BackgroundJob.filter(
            resource_type="document",
            resource_id=document.id,
            status__in=["queued", "running"],
            type__in=list(DOCUMENT_JOB_TYPES.values()),
        ).exists()

    @staticmethod
    def _response(document: Document) -> DocumentResponse:
        return DocumentResponse(
            id=document.id,
            project_id=document.project_id,
            version_id=document.project_version_id,
            name=document.name,
            original_filename=document.file_name,
            format=document.file_format,
            mime_type=document.mime_type,
            source_language=document.source_language,
            target_language=document.target_language,
            status=document.status,
            version=document.version,
            size_bytes=document.file_size,
            checksum=document.checksum_sha256,
            created_by=document.created_by_id,
            segment_count=document.segment_count,
            translated_segment_count=document.translated_segment_count,
            error_count=document.error_count,
            import_errors=document.import_errors,
            archived_at=document.archived_at,
            deleted_at=document.deleted_at,
            purge_after=document.purge_after,
            purged_at=document.purged_at,
            created_at=document.created_at,
            updated_at=document.updated_at,
        )

    @staticmethod
    def _segment_response(segment: DocumentSegment) -> DocumentSegmentResponse:
        return DocumentSegmentResponse(
            id=segment.id,
            document_id=segment.document_id,
            segment_no=segment.segment_no,
            source=segment.source_text,
            target=segment.target_text,
            source_language=segment.source_language,
            target_language=segment.target_language,
            status=segment.status,
            workflow_state=segment.workflow_state,
            assigned_to=segment.assigned_to_id,
            version=segment.version,
            updated_at=segment.updated_at,
        )

    @staticmethod
    def _format_for(filename: str) -> str:
        suffix = Path(filename or "").suffix.lower().lstrip(".")
        return suffix or "unknown"

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
            raise DocumentValidationError("分页游标无效") from exc
        if offset < 0:
            raise DocumentValidationError("分页游标无效")
        return offset

    @staticmethod
    def _order_clause(sort: str) -> str:
        return "name" if sort == "name" else f"-{sort}"

    @staticmethod
    def _segment_order_clause(sort: str) -> str:
        return "-updated_at" if sort == "updated_at" else "segment_no"


__all__ = [
    "DocumentConflictError",
    "DocumentError",
    "DocumentForbiddenError",
    "DocumentNotFoundError",
    "DocumentService",
    "DocumentValidationError",
]
