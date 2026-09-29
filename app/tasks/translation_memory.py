from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

from tortoise import transactions

from ..application.translation_memory.schemas import JobReference
from ..application.translation_memory.service import TranslationMemoryService
from ..models import TranslationMemoryImport, User
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

    def enqueue_rebuild(self, library_id: UUID, content_version: int) -> JobReference:
        job_id = uuid4()
        rebuild_translation_memory_index_task.apply_async(
            args=[str(library_id), content_version], task_id=str(job_id)
        )
        return JobReference(job_id=job_id, status="queued")


@celery_app.task(name="translation_memory.rebuild_index")
def rebuild_translation_memory_index_task(library_id: str, content_version: int) -> str:
    """Worker contract; a future index backend can consume this immutable version."""
    return f"{library_id}:{content_version}"
