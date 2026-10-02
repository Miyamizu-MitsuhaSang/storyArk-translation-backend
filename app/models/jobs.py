from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from tortoise import fields, transactions
from tortoise.expressions import Q

from .base import TimestampedModel

JOB_STATUSES = ("queued", "running", "succeeded", "failed", "cancelled")
_SENSITIVE_VALUE = re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*[^,\s;]+")


def _safe_error_message(value: str) -> str:
    return _SENSITIVE_VALUE.sub(r"\1=[REDACTED]", value).replace("\n", " ").replace("\r", " ")[:512]


class BackgroundJob(TimestampedModel):
    type = fields.CharField(max_length=64, description="稳定的后台任务类型标识。")
    status = fields.CharField(max_length=16, default="queued", choices=JOB_STATUSES, description="后台任务生命周期状态。")
    resource_type = fields.CharField(max_length=64, description="任务所作用资源的类型。")
    resource_id: UUID = fields.UUIDField(description="任务所作用资源的 UUID。")
    requested_version = fields.IntField(description="提交任务时捕获的资源版本。")
    attempts = fields.IntField(default=0, description="任务已领取次数。")
    max_attempts = fields.IntField(default=3, description="任务最大领取次数。")
    available_at = fields.DatetimeField(default=lambda: datetime.now(timezone.utc), description="任务可领取时间。")
    started_at: datetime | None = fields.DatetimeField(null=True, description="最近一次领取时间。")
    finished_at: datetime | None = fields.DatetimeField(null=True, description="任务结束时间。")
    worker_id: str | None = fields.CharField(max_length=128, null=True, description="当前租约所属 worker。")
    lease_expires_at: datetime | None = fields.DatetimeField(null=True, description="当前 worker 租约到期时间。")
    result: dict[str, Any] | None = fields.JSONField(null=True, description="不含秘密信息的任务结果元数据。")
    error_code: str | None = fields.CharField(max_length=64, null=True, description="稳定且受限的失败代码。")
    error_message: str | None = fields.CharField(max_length=512, null=True, description="已脱敏且受限长度的失败信息。")

    class Meta:
        table = "background_jobs"
        indexes = [
            ("status", "available_at"),
            ("resource_type", "resource_id", "requested_version"),
        ]

    @classmethod
    async def claim(
        cls,
        worker_id: str,
        *,
        lease_seconds: int = 60,
        now: datetime | None = None,
        job_type: str | None = None,
        job_id: UUID | None = None,
    ) -> BackgroundJob | None:
        if not worker_id or len(worker_id) > 128:
            raise ValueError("worker_id must contain 1 to 128 characters")
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")
        now = now or datetime.now(timezone.utc)
        async with transactions.in_transaction() as connection:
            eligible = Q(status="queued", available_at__lte=now) | Q(
                status="running", lease_expires_at__lte=now
            )
            query = cls.filter(eligible)
            if job_type is not None:
                query = query.filter(type=job_type)
            if job_id is not None:
                query = query.filter(id=job_id)
            job = await query.using_db(connection).select_for_update().order_by("available_at", "created_at").first()
            while job is not None:
                if job.attempts >= job.max_attempts:
                    job.status = "failed"
                    job.finished_at = now
                    job.worker_id = None
                    job.lease_expires_at = None
                    job.error_code = job.error_code or "RETRY_LIMIT_EXCEEDED"
                    job.error_message = job.error_message or "任务已达到最大重试次数"
                    await job.save(
                        using_db=connection,
                        update_fields=["status", "finished_at", "worker_id", "lease_expires_at", "error_code", "error_message"],
                    )
                    job = await query.using_db(connection).select_for_update().order_by("available_at", "created_at").first()
                    continue
                job.status = "running"
                job.attempts += 1
                job.started_at = now
                job.worker_id = worker_id
                job.lease_expires_at = now + timedelta(seconds=lease_seconds)
                await job.save(
                    using_db=connection,
                    update_fields=["status", "attempts", "started_at", "worker_id", "lease_expires_at"],
                )
                return job
            return None

    def _assert_lease_owner(self, worker_id: str, now: datetime) -> None:
        if self.status != "running" or self.worker_id != worker_id:
            raise ValueError("job lease is not owned by this worker")
        if self.lease_expires_at is None or self.lease_expires_at <= now:
            raise ValueError("job lease has expired")

    async def complete(
        self,
        *,
        worker_id: str,
        result: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> None:
        now = now or datetime.now(timezone.utc)
        async with transactions.in_transaction() as connection:
            current = await type(self).filter(id=self.id).using_db(connection).select_for_update().first()
            if current is None:
                raise ValueError("job lease no longer exists")
            current._assert_lease_owner(worker_id, now)
            current.status = "succeeded"
            current.result = result or {}
            current.finished_at = now
            current.worker_id = None
            current.lease_expires_at = None
            current.error_code = None
            current.error_message = None
            await current.save(
                using_db=connection,
                update_fields=["status", "result", "finished_at", "worker_id", "lease_expires_at", "error_code", "error_message"],
            )

    async def fail(
        self,
        error_code: str,
        error_message: str,
        *,
        worker_id: str,
        now: datetime | None = None,
        retry_delay_seconds: int | None = None,
    ) -> None:
        now = now or datetime.now(timezone.utc)
        async with transactions.in_transaction() as connection:
            current = await type(self).filter(id=self.id).using_db(connection).select_for_update().first()
            if current is None:
                raise ValueError("job lease no longer exists")
            current._assert_lease_owner(worker_id, now)
            current.error_code = error_code[:64] if re.fullmatch(r"[A-Za-z0-9_-]+", error_code) else "JOB_FAILED"
            current.error_message = _safe_error_message(error_message)
            current.worker_id = None
            current.lease_expires_at = None
            if current.attempts >= current.max_attempts:
                current.status = "failed"
                current.finished_at = now
            else:
                current.status = "queued"
                delay = retry_delay_seconds if retry_delay_seconds is not None else min(300, 2 ** (current.attempts - 1))
                current.available_at = now + timedelta(seconds=max(0, min(delay, 300)))
            await current.save(
                using_db=connection,
                update_fields=[
                    "status", "error_code", "error_message", "worker_id", "lease_expires_at",
                    "finished_at", "available_at",
                ],
            )
