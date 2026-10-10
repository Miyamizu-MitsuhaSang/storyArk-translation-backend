from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any
from uuid import UUID

from ...core.config import app_settings, security_settings
from ...infrastructure.document.storage import LocalDocumentStorage
from ...models import BackgroundJob, Document, ProjectMember, TerminologyBase, TranslationMemoryLibrary, TranslationTask, User
from .schemas import JobErrorResponse, JobStatusResponse


class JobError(Exception):
    """Base error for jobs application use cases."""


class JobNotFoundError(JobError):
    """The job is missing or not visible to the current user."""


class JobConflictError(JobError):
    """The requested job lifecycle transition is not allowed."""


class JobsService:
    """Authorize, present and mutate the shared background-job lifecycle."""

    async def get_status(self, user: User, job_id: UUID) -> JobStatusResponse:
        job = await self._visible_job(user, job_id)
        return self._response(job)

    async def download_export(
        self,
        user: User,
        job_id: UUID,
        *,
        expires: int,
        signature: str,
    ) -> tuple[bytes, str]:
        job = await self._visible_job(user, job_id)
        if job.type != "document_export" or job.status != "succeeded":
            raise JobConflictError("導出任务尚未完成或不可下载")
        if expires < int(time.time()) or expires > int(time.time()) + 900:
            raise JobNotFoundError("下载链接无效或已过期")
        expected = self._download_signature(job.id, expires)
        if not hmac.compare_digest(signature, expected):
            raise JobNotFoundError("下载链接无效或已过期")
        result = job.result if isinstance(job.result, dict) else {}
        storage_key = result.get("storage_key")
        if not isinstance(storage_key, str):
            raise JobNotFoundError("导出文件不存在")
        with LocalDocumentStorage(app_settings.document_storage_dir).open(storage_key=storage_key) as stream:
            content = stream.read()
        suffix = storage_key.rsplit("/", 1)[-1]
        return content, suffix

    async def cancel(
        self,
        user: User,
        job_id: UUID,
        *,
        reason: str = "用户请求取消任务",
    ) -> JobStatusResponse:
        job = await self._visible_job(user, job_id)
        if job.status not in {"queued", "running"}:
            raise JobConflictError("只有 queued 或 running 状态的任务可以取消")
        try:
            await job.cancel(reason=reason)
        except ValueError as exc:
            raise JobConflictError("任务状态已变化，无法取消") from exc
        return self._response(await BackgroundJob.get(id=job.id))

    async def _visible_job(self, user: User, job_id: UUID) -> BackgroundJob:
        job = await BackgroundJob.filter(id=job_id).first()
        if job is None or not await self._can_access(user, job):
            raise JobNotFoundError("后台任务不存在")
        return job

    async def _can_access(self, user: User, job: BackgroundJob) -> bool:
        if job.resource_type == "document":
            document = await Document.filter(id=job.resource_id).first()
            return bool(
                document
                and await ProjectMember.filter(project_id=document.project_id, user_id=user.id).exists()
            )
        if job.resource_type == "project":
            return await ProjectMember.filter(project_id=job.resource_id, user_id=user.id).exists()
        if job.resource_type in {"translation_memory_library", "translation_memory"}:
            library = await TranslationMemoryLibrary.filter(id=job.resource_id).first()
            return bool(library and (library.scope == "platform" or library.owner_user_id == user.id))
        if job.resource_type == "terminology_base":
            base = await TerminologyBase.filter(id=job.resource_id).first()
            return bool(base and await ProjectMember.filter(project_id=base.project_id, user_id=user.id).exists())
        if job.resource_type == "translation_task":
            task = await TranslationTask.filter(id=job.resource_id).first()
            return bool(task and await ProjectMember.filter(project_id=task.project_id, user_id=user.id).exists())
        return False

    @staticmethod
    def _response(job: BackgroundJob) -> JobStatusResponse:
        raw_result = job.result if isinstance(job.result, dict) else None
        result = JobsService._safe_result(raw_result)
        if result is not None and job.type == "document_export" and job.status == "succeeded":
            expires = int(time.time()) + 900
            signature = JobsService._download_signature(job.id, expires)
            result["download_url"] = (
                f"{app_settings.api_prefix}/jobs/{job.id}/download?expires={expires}&signature={signature}"
            )
        message = raw_result.get("message") if raw_result else None
        if not isinstance(message, str):
            message = {
                "queued": "任务等待 worker 领取",
                "running": "任务正在执行",
                "succeeded": "任务执行完成",
                "failed": "任务执行失败",
                "cancelled": "任务已取消",
            }.get(job.status)
        error = None
        if job.error_code:
            error = JobErrorResponse(code=job.error_code, message=job.error_message or "任务执行失败")
        return JobStatusResponse(
            id=job.id,
            type=job.type,
            status=job.status,
            progress=JobsService._progress(job.status, raw_result),
            message=message,
            result=result,
            error=error,
            created_at=job.created_at,
            finished_at=job.finished_at,
        )

    @staticmethod
    def _download_signature(job_id: UUID, expires: int) -> str:
        message = f"document-export:{job_id}:{expires}".encode()
        return hmac.new(security_settings.auth_jwt_secret.encode(), message, hashlib.sha256).hexdigest()

    @staticmethod
    def _safe_result(result: dict[str, Any] | None) -> dict[str, Any] | None:
        if result is None:
            return None
        blocked = {"user_id", "request", "storage_uri", "storage_key", "api_key", "token", "secret"}
        return {key: value for key, value in result.items() if key.casefold() not in blocked}

    @staticmethod
    def _progress(status: str, result: dict[str, Any] | None) -> float:
        value = result.get("progress") if result else None
        if isinstance(value, (int, float)):
            return max(0.0, min(1.0, float(value)))
        return 1.0 if status == "succeeded" else 0.0


__all__ = ["JobConflictError", "JobNotFoundError", "JobsService"]
