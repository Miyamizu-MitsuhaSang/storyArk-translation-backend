from __future__ import annotations

import hashlib
import hmac
import base64
import binascii
import json
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from ...core.config import app_settings, security_settings
from ...infrastructure.document.storage import DocumentStorageError, LocalDocumentStorage
from ...models import BackgroundJob, Document, ProjectMember, TerminologyBase, TranslationMemoryLibrary, TranslationTask, User
from .schemas import JobErrorResponse, JobListQuery, JobPage, JobStatusResponse


class JobError(Exception):
    """Base error for jobs application use cases."""

    code = "JOB_ERROR"
    status_code = 400

    def __init__(self, message: str, *, code: str | None = None, details: dict[str, Any] | None = None):
        super().__init__(message)
        if code:
            self.code = code
        self.details = details or {}


class JobNotFoundError(JobError):
    """The job is missing or not visible to the current user."""
    code = "JOB_NOT_FOUND"
    status_code = 404


class JobConflictError(JobError):
    """The requested job lifecycle transition is not allowed."""
    code = "JOB_CONFLICT"
    status_code = 409


class JobsService:
    """Authorize, present and mutate the shared background-job lifecycle."""

    async def get_status(self, user: User, job_id: UUID) -> JobStatusResponse:
        job = await self._visible_job(user, job_id)
        return await self._response(job)

    async def list(self, user: User, query: JobListQuery) -> JobPage:
        filters: dict[str, Any] = {}
        if query.status:
            filters["status"] = query.status
        if query.type:
            filters["type"] = query.type
        if query.resource_type:
            filters["resource_type"] = query.resource_type
        if query.created_after:
            filters["created_at__gte"] = query.created_after
        if query.created_before:
            filters["created_at__lte"] = query.created_before
        if query.active_only:
            filters["status__in"] = ["queued", "running"]
        jobs = await BackgroundJob.filter(**filters).order_by("-created_at", "-id")
        visible: list[tuple[BackgroundJob, UUID | None]] = []
        for job in jobs:
            project_id = await self._project_id(job)
            if project_id is None and job.resource_type not in {"translation_memory_library", "translation_memory"}:
                continue
            if query.project_id is not None and project_id != query.project_id:
                continue
            if not await self._can_access(user, job):
                continue
            visible.append((job, project_id))

        # The database query already orders equal timestamps by descending ID;
        # this stable sort adds active-job priority while preserving that tie-breaker.
        visible.sort(key=lambda item: 0 if item[0].status in {"queued", "running"} else 1)
        if query.cursor:
            cursor = self._decode_cursor(query.cursor)
            visible = [item for item in visible if self._is_after(item[0], cursor)]
        selected = visible[: query.page_size]
        next_cursor = None
        if len(visible) > query.page_size and selected:
            next_cursor = self._encode_cursor(selected[-1][0])
        return JobPage(
            items=[await self._response(job, project_id=project_id) for job, project_id in selected],
            next_cursor=next_cursor,
        )

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
            raise JobConflictError("导出任务尚未完成或不可下载", code="JOB_DOWNLOAD_NOT_READY")
        if expires < int(time.time()) or expires > int(time.time()) + 900:
            raise JobNotFoundError("下载链接无效或已过期", code="JOB_DOWNLOAD_EXPIRED")
        expected = self._download_signature(job.id, expires)
        if not hmac.compare_digest(signature, expected):
            raise JobNotFoundError("下载链接无效或已过期", code="JOB_DOWNLOAD_INVALID_SIGNATURE")
        result = job.result if isinstance(job.result, dict) else {}
        storage_key = result.get("storage_key")
        if not isinstance(storage_key, str):
            raise JobNotFoundError("导出文件不存在", code="JOB_RESULT_INVALID")
        try:
            with LocalDocumentStorage(app_settings.document_storage_dir).open(storage_key=storage_key) as stream:
                content = stream.read()
        except DocumentStorageError as exc:
            raise JobNotFoundError("导出文件不存在", code="JOB_RESULT_INVALID") from exc
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
            raise JobConflictError("只有 queued 或 running 状态的任务可以取消", code="JOB_NOT_CANCELLABLE")
        try:
            await job.cancel(reason=reason)
        except ValueError as exc:
            raise JobConflictError("任务状态已变化，无法取消", code="JOB_NOT_CANCELLABLE") from exc
        return await self._response(await BackgroundJob.get(id=job.id))

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

    async def _project_id(self, job: BackgroundJob) -> UUID | None:
        if job.resource_type == "project":
            return job.resource_id
        if job.resource_type == "document":
            resource = await Document.filter(id=job.resource_id).first()
            return resource.project_id if resource else None
        if job.resource_type == "terminology_base":
            resource = await TerminologyBase.filter(id=job.resource_id).first()
            return resource.project_id if resource else None
        if job.resource_type == "translation_task":
            resource = await TranslationTask.filter(id=job.resource_id).first()
            return resource.project_id if resource else None
        return None

    async def _response(self, job: BackgroundJob, *, project_id: UUID | None = None) -> JobStatusResponse:
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
            resource_type=job.resource_type,
            resource_id=job.resource_id,
            project_id=project_id if project_id is not None else await self._project_id(job),
            requested_version=job.requested_version,
            attempts=job.attempts,
            max_attempts=job.max_attempts,
            progress=JobsService._progress(job.status, raw_result),
            message=message,
            result=result,
            error=error,
            created_at=job.created_at,
            started_at=job.started_at,
            updated_at=job.updated_at,
            finished_at=job.finished_at,
        )

    @staticmethod
    def _sort_key(job: BackgroundJob) -> tuple[int, float, str]:
        priority = 0 if job.status in {"queued", "running"} else 1
        created = job.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return priority, -created.timestamp(), str(job.id)

    @staticmethod
    def _encode_cursor(job: BackgroundJob) -> str:
        created = job.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        payload = {"priority": 0 if job.status in {"queued", "running"} else 1, "created_at": created.isoformat(), "id": str(job.id)}
        raw = json.dumps(payload, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    @staticmethod
    def _decode_cursor(cursor: str) -> dict[str, Any]:
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
            if not isinstance(payload, dict) or set(payload) != {"priority", "created_at", "id"}:
                raise ValueError
            if payload["priority"] not in {0, 1} or not isinstance(payload["created_at"], str) or not isinstance(payload["id"], str):
                raise ValueError
            datetime.fromisoformat(payload["created_at"])
            UUID(payload["id"])
            return payload
        except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError, UnicodeEncodeError, binascii.Error) as exc:
            raise JobConflictError("分页游标无效", code="JOB_CURSOR_INVALID") from exc

    @staticmethod
    def _is_after(job: BackgroundJob, cursor: dict[str, Any]) -> bool:
        priority, _, job_id = JobsService._sort_key(job)
        cursor_priority = int(cursor["priority"])
        cursor_created = datetime.fromisoformat(str(cursor["created_at"]))
        if cursor_created.tzinfo is None:
            cursor_created = cursor_created.replace(tzinfo=timezone.utc)
        job_created = job.created_at
        if job_created.tzinfo is None:
            job_created = job_created.replace(tzinfo=timezone.utc)
        if priority != cursor_priority:
            return priority > cursor_priority
        if job_created != cursor_created:
            return job_created < cursor_created
        return job_id < str(cursor["id"])

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
