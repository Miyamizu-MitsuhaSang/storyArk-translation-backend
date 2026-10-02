from __future__ import annotations

import asyncio
import os
import socket
from datetime import datetime, timezone
from uuid import UUID, uuid4

from tortoise import Tortoise, transactions
from tortoise.expressions import Q

from ..application.translation_memory.index_service import TranslationMemoryIndexService
from ..application.translation_memory.schemas import JobReference
from ..application.translation_memory.service import TranslationMemoryService
from ..core.database import TORTOISE_ORM
from ..models import BackgroundJob, TranslationMemoryImport, TranslationMemoryLibrary, User
from .celery_app import celery_app


@celery_app.task(name="translation_memory.import_entries")
def import_entries_task(user_id: str, memory_id: str, import_id: str) -> str:
    """Worker hook; the application layer owns validation and bounded writes."""
    async def run() -> None:
        async with transactions.in_transaction():
            record = await TranslationMemoryImport.filter(id=import_id).select_for_update().get()
            if record.status in {"completed", "running"}:
                return
            record.status = "running"
            await record.save(update_fields=["status"])
        user = await User.get(id=user_id)
        service = TranslationMemoryService()
        service.IMPORT_SYNC_LIMIT = max(service.IMPORT_SYNC_LIMIT, len(record.rows))
        try:
            result = await service.import_entries(user, UUID(memory_id), record.rows, record.idempotency_key, _ignore_existing=True)
            record.imported = result.imported
            record.skipped = result.skipped
            record.invalid_rows = result.invalid_rows
            record.status = "completed"
            await record.save(update_fields=["imported", "skipped", "invalid_rows", "status"])
        except Exception as exc:
            record.status = "failed"
            record.invalid_rows = [{"row": 0, "code": "IMPORT_FAILED", "message": str(exc)}]
            await record.save(update_fields=["status", "invalid_rows"])
    asyncio.run(run())
    return import_id


class TranslationMemoryTaskDispatcher:
    def enqueue_import(self, user_id: UUID, memory_id: UUID, import_id: UUID | None = None) -> JobReference:
        job_id = import_id or uuid4()
        import_entries_task.apply_async(args=[str(user_id), str(memory_id), str(job_id)], task_id=str(job_id))
        return JobReference(job_id=job_id, status="queued")

    async def enqueue_rebuild(
        self,
        library_id: UUID,
        content_version: int,
        *,
        retain_job_on_dispatch_failure: bool = False,
    ) -> JobReference:
        async def create_or_reuse() -> tuple[UUID, str, bool]:
            async with transactions.in_transaction() as connection:
                library = await TranslationMemoryLibrary.filter(id=library_id).using_db(connection).select_for_update().first()
                if library is None or library.content_version != content_version:
                    raise RuntimeError("translation memory library version changed before enqueue")
                pending = await BackgroundJob.filter(
                    type="tm_index_rebuild",
                    resource_type="translation_memory_library",
                    resource_id=library_id,
                    requested_version=content_version,
                    status__in=["queued", "running"],
                ).using_db(connection).order_by("created_at").first()
                if pending is not None:
                    return pending.id, pending.status, False
                job = await BackgroundJob.create(
                    type="tm_index_rebuild",
                    resource_type="translation_memory_library",
                    resource_id=library_id,
                    requested_version=content_version,
                using_db=connection,
                )
                return job.id, job.status, True

        job_id, status, created = await create_or_reuse()
        if not created:
            return JobReference(job_id=job_id, status=status)
        try:
            await asyncio.to_thread(
                rebuild_translation_memory_index_task.apply_async,
                args=[str(job_id)],
                task_id=str(job_id),
            )
        except Exception as exc:
            if created and not retain_job_on_dispatch_failure:
                try:
                    await BackgroundJob.filter(id=job_id, status="queued").delete()
                except Exception:
                    pass
            raise RuntimeError("translation memory index task dispatch failed") from exc
        return JobReference(job_id=job_id, status=status)


async def process_rebuild_index(job_id: UUID, *, worker_id: str, service=None) -> dict:
    job = await BackgroundJob.claim(
        worker_id,
        job_type="tm_index_rebuild",
        job_id=job_id,
        lease_seconds=300,
    )
    if job is None:
        return {"status": "not_claimed"}
    index_service = service or TranslationMemoryIndexService()
    try:
        result = await index_service.build_job(job.id, worker_id=worker_id)
    except Exception as exc:
        retry_delay = min(300, 2 ** max(0, job.attempts - 1))
        await job.fail(
            "INDEX_BUILD_FAILED",
            str(exc),
            worker_id=worker_id,
            retry_delay_seconds=retry_delay,
        )
        await job.refresh_from_db()
        return {
            "status": "retry" if job.status == "queued" else "failed",
            "retry_after": retry_delay,
        }
    if result.get("status") == "superseded":
        library = await TranslationMemoryLibrary.filter(id=job.resource_id).first()
        if library is not None:
            await TranslationMemoryTaskDispatcher().enqueue_rebuild(
                library.id,
                library.content_version,
                retain_job_on_dispatch_failure=True,
            )
    return result


@celery_app.task(bind=True, name="translation_memory.rebuild_index", max_retries=None)
def rebuild_translation_memory_index_task(task, job_id: str) -> dict:
    async def run() -> dict:
        await Tortoise.init(config=TORTOISE_ORM)
        try:
            worker_id = f"{socket.gethostname()}:{os.getpid()}"
            return await process_rebuild_index(UUID(job_id), worker_id=worker_id)
        finally:
            await Tortoise.close_connections()

    result = asyncio.run(run())
    if result.get("status") == "retry":
        raise task.retry(countdown=result["retry_after"])
        return result


async def reclaim_expired_index_jobs(*, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    eligible = Q(status="queued", available_at__lte=now) | Q(status="running", lease_expires_at__lte=now)
    jobs = await BackgroundJob.filter(eligible, type="tm_index_rebuild").order_by("available_at")
    dispatched = 0
    for job in jobs:
        rebuild_translation_memory_index_task.apply_async(args=[str(job.id)], task_id=str(job.id))
        dispatched += 1
    return dispatched


@celery_app.task(name="translation_memory.reclaim_expired_index_jobs")
def reclaim_expired_index_jobs_task() -> int:
    async def run() -> int:
        await Tortoise.init(config=TORTOISE_ORM)
        try:
            return await reclaim_expired_index_jobs()
        finally:
            await Tortoise.close_connections()

    return asyncio.run(run())
