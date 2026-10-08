"""Celery entry point for large CAT workflow batches."""

from __future__ import annotations

import asyncio
import socket
from uuid import UUID

from tortoise import Tortoise

from ..application.project.cat.schemas import BulkActionRequest
from ..application.project.cat.workflow.service import CatWorkflowService
from ..core.database import TORTOISE_ORM
from ..models import BackgroundJob, User
from .celery_app import celery_app


@celery_app.task(name="cat.bulk_action")
def process_cat_bulk_action_task(job_id: str) -> dict[str, object]:
    async def run() -> dict[str, object]:
        await Tortoise.init(config=TORTOISE_ORM)
        worker_id = f"cat:{socket.gethostname()}"
        try:
            job = await BackgroundJob.claim(worker_id, job_type="cat_bulk_action", job_id=UUID(job_id), lease_seconds=600)
            if job is None:
                return {"status": "not_claimed"}
            payload = job.result if isinstance(job.result, dict) else {}
            user = await User.get(id=payload["user_id"])
            request = BulkActionRequest.model_validate(payload["request"])
            service = CatWorkflowService()
            affected = 0
            for start in range(0, len(request.segment_ids), 100):
                chunk_ids = request.segment_ids[start : start + 100]
                chunk_versions = {segment_id: request.expected_versions[segment_id] for segment_id in chunk_ids}
                chunk = request.model_copy(update={"segment_ids": chunk_ids, "expected_versions": chunk_versions})
                result = await service.bulk_action(user, UUID(job.resource_id), chunk)
                affected += result.affected
            result = {"status": "succeeded", "affected": affected}
            await job.complete(worker_id=worker_id, result=result)
            return result
        except Exception as exc:
            job = await BackgroundJob.get_or_none(id=UUID(job_id))
            if job is not None and job.status == "running":
                await job.fail("CAT_BULK_ACTION_FAILED", str(exc), worker_id=worker_id, retry_delay_seconds=30)
            return {"status": "failed", "error": str(exc)}
        finally:
            await Tortoise.close_connections()

    return asyncio.run(run())


__all__ = ["process_cat_bulk_action_task"]
