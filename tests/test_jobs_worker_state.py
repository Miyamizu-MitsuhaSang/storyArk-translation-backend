from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from tortoise import Tortoise

from translation_backend.app.models import BackgroundJob


def run_db_test(coro):
    async def scenario():
        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["translation_backend.app.models"]})
        await Tortoise.generate_schemas()
        try:
            return await coro()
        finally:
            await Tortoise.close_connections()

    return asyncio.run(scenario())


async def make_job(**overrides):
    values = {
        "type": "cat_bulk_action",
        "resource_type": "project",
        "resource_id": uuid4(),
        "requested_version": 1,
        "max_attempts": 2,
    }
    values.update(overrides)
    return await BackgroundJob.create(**values)


def test_cancelled_job_cannot_be_completed_by_old_worker() -> None:
    async def scenario():
        now = datetime.now(timezone.utc)
        job = await make_job(status="running", worker_id="worker-a", lease_expires_at=now + timedelta(minutes=1))
        await job.cancel(reason="用户取消", now=now)
        with pytest.raises(ValueError):
            await job.complete(worker_id="worker-a", result={"secret": "must-not-win"}, now=now)
        stored = await BackgroundJob.get(id=job.id)
        assert stored.status == "cancelled"
        assert stored.result is None

    run_db_test(scenario)


def test_expired_lease_can_be_reclaimed_and_old_owner_cannot_complete() -> None:
    async def scenario():
        now = datetime.now(timezone.utc)
        job = await make_job(status="running", worker_id="worker-a", lease_expires_at=now - timedelta(seconds=1))
        claimed = await BackgroundJob.claim("worker-b", now=now, lease_seconds=30, job_id=job.id)
        assert claimed is not None and claimed.worker_id == "worker-b"
        with pytest.raises(ValueError):
            await job.complete(worker_id="worker-a", now=now)
        await claimed.complete(worker_id="worker-b", result={"ok": True}, now=now)
        stored = await BackgroundJob.get(id=job.id)
        assert stored.status == "succeeded"

    run_db_test(scenario)


def test_claim_after_max_attempts_marks_job_failed_and_sanitizes_failure() -> None:
    async def scenario():
        now = datetime.now(timezone.utc)
        job = await make_job(
            status="queued",
            attempts=2,
            max_attempts=2,
            error_code="PROVIDER_FAILED",
            error_message="api_key=old-secret",
        )
        assert await BackgroundJob.claim("worker-a", now=now + timedelta(seconds=1), job_id=job.id) is None
        stored = await BackgroundJob.get(id=job.id)
        assert stored.status == "failed"
        assert "old-secret" not in (stored.error_message or "")
        assert "REDACTED" in (stored.error_message or "")

    run_db_test(scenario)
