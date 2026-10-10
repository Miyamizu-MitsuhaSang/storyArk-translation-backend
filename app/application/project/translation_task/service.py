from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import UUID

from tortoise import transactions

from ....core.config import app_settings
from ....application.idempotency import execute_idempotently
from ....domain.project.policies import ProjectPolicy
from ....domain.shared.errors import DomainError
from ....models import AIProviderCredential, BackgroundJob, Document, ProjectMember, ProjectVersion, TranslationTask, TranslationTaskFile, User
from ....repositories import ApiKeyRepository
from ..shared import decode_cursor, encode_cursor
from .repository import TranslationTaskRepository
from .schemas import (
    TaskStatus,
    TranslationTaskApiKeyResponse,
    TranslationTaskCreateRequest,
    TranslationTaskPage,
    TranslationTaskOutputResponse,
    TranslationTaskResponse,
)


class TranslationTaskError(Exception):
    status_code = 400
    code = "TRANSLATION_TASK_ERROR"

    def __init__(self, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


class TranslationTaskNotFoundError(TranslationTaskError):
    status_code = 404
    code = "TRANSLATION_TASK_NOT_FOUND"


class TranslationTaskForbiddenError(TranslationTaskError):
    status_code = 403
    code = "TRANSLATION_TASK_FORBIDDEN"


class TranslationTaskValidationError(TranslationTaskError):
    status_code = 422
    code = "TRANSLATION_TASK_INVALID"


class TranslationTaskConflictError(TranslationTaskError):
    status_code = 409
    code = "TRANSLATION_TASK_CONFLICT"


class TranslationTaskService:
    def __init__(self, *, repository: TranslationTaskRepository | None = None) -> None:
        self._repository = repository or TranslationTaskRepository()
        self._api_keys = ApiKeyRepository()

    async def create(
        self,
        user: User,
        project_id: UUID,
        request: TranslationTaskCreateRequest,
        *,
        idempotency_key: str | None = None,
    ) -> TranslationTaskResponse:
        payload = request.model_dump(mode="json")

        async def callback() -> TranslationTaskResponse:
            return await self._create(user, project_id, request)

        return await execute_idempotently(
            user,
            operation="translation_task_create",
            scope=str(project_id),
            key=idempotency_key,
            payload=payload,
            response_type=TranslationTaskResponse,
            callback=callback,
        )

    async def _create(self, user: User, project_id: UUID, request: TranslationTaskCreateRequest) -> TranslationTaskResponse:
        membership = await self._membership(user, project_id)
        if membership.role not in {"owner", "manager", "translator"}:
            raise TranslationTaskForbiddenError("当前角色不能创建翻译任务")
        documents = await Document.filter(project_id=project_id, id__in=request.file_ids).all()
        if len(documents) != len(request.file_ids):
            raise TranslationTaskNotFoundError("文件不存在或当前项目不可见")
        if any(document.source_language != request.source_language for document in documents):
            raise TranslationTaskValidationError("所有文件必须与任务源语言一致")
        if request.model_type is not None:
            if len(documents) != 1:
                raise TranslationTaskValidationError("表格翻译任务当前只支持一个输入文件")
            if documents[0].file_format not in {"csv", "xlsx"}:
                raise TranslationTaskValidationError("表格翻译任务只支持 CSV 或 XLSX 文件")
        version = None
        if request.version_id is not None:
            version = await ProjectVersion.filter(id=request.version_id, project_id=project_id).first()
            if version is None:
                raise TranslationTaskNotFoundError("版本不存在或当前项目不可见")
        credential = await AIProviderCredential.filter(id=request.api_key_id, user_id=user.id, is_active=True).first()
        if credential is None:
            raise TranslationTaskNotFoundError("API key 不存在或不可用")
        async with transactions.in_transaction() as connection:
            task = await TranslationTask.create(
                project_id=project_id,
                created_by_id=user.id,
                name=request.name,
                source_language=request.source_language,
                target_languages=request.target_languages,
                version_id=version.id if version else None,
                api_key_id=credential.id,
                api_key_provider=credential.provider,
                api_key_label=credential.label,
                api_key_masked=f"{credential.key_prefix or ''}{'•' * 8}{credential.key_hint or ''}",
                model_type=request.model_type,
                model=request.model,
                source_column=request.source_column,
                target_columns=[item.model_dump(mode="json") for item in (request.target_columns or [])],
                sheet_names=request.sheet_names,
                overwrite=request.overwrite,
                status="queued",
                progress=0,
                using_db=connection,
            )
            await TranslationTaskFile.bulk_create(
                [TranslationTaskFile(task_id=task.id, document_id=document.id) for document in documents],
                using_db=connection,
            )
            if request.model_type is not None:
                job = await BackgroundJob.create(
                    type="translation_task",
                    status="queued",
                    resource_type="translation_task",
                    resource_id=task.id,
                    requested_version=1,
                    result={"task_id": str(task.id)},
                    using_db=connection,
                )
                task.job_id = job.id
                await task.save(using_db=connection, update_fields=["job_id", "updated_at"])
                if app_settings.translation_tasks_enabled:
                    from ....tasks.translation_tasks import run_translation_task_job

                    try:
                        await asyncio.to_thread(
                            run_translation_task_job.apply_async,
                            args=[str(task.id)],
                            task_id=str(job.id),
                        )
                    except Exception as exc:
                        job.status = "failed"
                        job.error_code = "TRANSLATION_TASK_DISPATCH_FAILED"
                        job.error_message = "翻译任务队列暂时不可用"
                        job.finished_at = datetime.now(timezone.utc)
                        await job.save(update_fields=["status", "error_code", "error_message", "finished_at", "updated_at"])
                        raise TranslationTaskError("翻译任务队列暂时不可用") from exc
        return await self.get(user, project_id, task.id)

    async def list(
        self,
        user: User,
        project_id: UUID,
        *,
        page_size: int = 20,
        cursor: str | None = None,
        source_language: str | None = None,
        target_language: str | None = None,
        status: TaskStatus | None = None,
        version_id: UUID | None = None,
        q: str | None = None,
    ) -> TranslationTaskPage:
        await self._membership(user, project_id)
        offset = decode_cursor(cursor)
        query = TranslationTask.filter(project_id=project_id)
        if source_language:
            query = query.filter(source_language=source_language)
        if status:
            query = query.filter(status=status)
        if version_id is not None:
            query = query.filter(version_id=version_id)
        if q:
            query = query.filter(name__icontains=q.strip())
        query = query.order_by("-created_at", "-id")
        if target_language:
            # Tortoise's JSON contains operator is not implemented by the
            # SQLite test executor; filter the small metadata set in Python.
            candidates = await query
            rows = [row for row in candidates if target_language in (row.target_languages or [])]
            total = len(rows)
            rows = rows[offset : offset + page_size]
        else:
            total = await query.count()
            rows = await query.offset(offset).limit(page_size)
        items = [await self._response(row) for row in rows]
        next_offset = offset + len(items)
        return TranslationTaskPage(items=items, next_cursor=encode_cursor(next_offset) if next_offset < total else None, total=total)

    async def get(self, user: User, project_id: UUID, task_id: UUID) -> TranslationTaskResponse:
        await self._membership(user, project_id)
        task = await TranslationTask.filter(id=task_id, project_id=project_id).first()
        if task is None:
            raise TranslationTaskNotFoundError("翻译任务不存在或当前项目不可见")
        return await self._response(task)

    async def cancel(self, user: User, project_id: UUID, task_id: UUID) -> TranslationTaskResponse:
        membership = await self._membership(user, project_id)
        if membership.role not in {"owner", "manager", "translator"}:
            raise TranslationTaskForbiddenError("当前角色不能取消翻译任务")
        task = await TranslationTask.filter(id=task_id, project_id=project_id).first()
        if task is None:
            raise TranslationTaskNotFoundError("翻译任务不存在或当前项目不可见")
        if task.status not in {"queued", "translating"}:
            raise TranslationTaskConflictError("当前任务状态不可取消")
        if task.job_id:
            job = await BackgroundJob.filter(id=task.job_id).first()
            if job is not None and job.status in {"queued", "running"}:
                await job.cancel(reason="用户请求取消翻译任务")
        task.status = "cancelled"
        task.error_code = "TRANSLATION_TASK_CANCELLED"
        task.error_message = "用户请求取消翻译任务"
        await task.save(update_fields=["status", "error_code", "error_message", "updated_at"])
        return await self._response(task)

    async def output_file(self, user: User, project_id: UUID, task_id: UUID) -> tuple[str, str, int]:
        await self._membership(user, project_id)
        task = await TranslationTask.filter(id=task_id, project_id=project_id).first()
        if task is None:
            raise TranslationTaskNotFoundError("翻译任务不存在或当前项目不可见")
        if task.status != "review" or not task.output_storage_key:
            raise TranslationTaskConflictError("翻译任务尚未生成可下载结果")
        return task.output_storage_key, task.output_file_name or "translated-output", task.output_size_bytes or 0

    async def _membership(self, user: User, project_id: UUID) -> ProjectMember:
        membership = await ProjectMember.filter(project_id=project_id, user_id=user.id).first()
        if membership is None:
            raise TranslationTaskNotFoundError("项目不存在或当前用户不可见")
        return membership

    async def _response(self, task: TranslationTask) -> TranslationTaskResponse:
        links = await TranslationTaskFile.filter(task_id=task.id).order_by("created_at")
        return TranslationTaskResponse(
            id=task.id,
            project_id=task.project_id,
            name=task.name,
            source_language=task.source_language,
            target_languages=list(task.target_languages or []),
            file_ids=[link.document_id for link in links],
            version_id=task.version_id,
            api_key=TranslationTaskApiKeyResponse(
                id=task.api_key_id,
                provider=task.api_key_provider or "",
                label=task.api_key_label,
                masked_secret=task.api_key_masked or "",
            ),
            model_type=task.model_type,
            model=task.model,
            source_column=task.source_column,
            target_columns=list(task.target_columns or []),
            sheet_names=list(task.sheet_names) if task.sheet_names is not None else None,
            overwrite=task.overwrite,
            job_id=task.job_id,
            output=TranslationTaskOutputResponse(
                file_name=task.output_file_name,
                size_bytes=task.output_size_bytes,
            ) if task.output_file_name or task.output_size_bytes is not None else None,
            status=task.status,
            progress=task.progress,
            error_code=task.error_code,
            error_message=task.error_message,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )


__all__ = [
    "TranslationTaskConflictError",
    "TranslationTaskError",
    "TranslationTaskForbiddenError",
    "TranslationTaskNotFoundError",
    "TranslationTaskService",
    "TranslationTaskValidationError",
]
