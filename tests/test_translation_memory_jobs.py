from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from tortoise import Tortoise

from translation_backend.app import models as model_module


def test_job_lease_prevents_duplicate_claim_and_recovers_after_expiry():
    async def scenario():
        assert hasattr(model_module, "BackgroundJob"), "BackgroundJob model is not implemented"
        BackgroundJob = model_module.BackgroundJob
        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["translation_backend.app.models"]})
        await Tortoise.generate_schemas()
        try:
            now = datetime(2026, 10, 2, tzinfo=timezone.utc)
            job = await BackgroundJob.create(
                type="tm_index_rebuild",
                resource_type="translation_memory_library",
                resource_id=uuid4(),
                requested_version=2,
                available_at=now,
            )
            claimed = await BackgroundJob.claim("worker-a", now=now, lease_seconds=30)
            assert claimed is not None and claimed.id == job.id
            assert claimed.status == "running"
            assert claimed.attempts == 1
            assert await BackgroundJob.claim("worker-b", now=now, lease_seconds=30) is None

            reclaimed = await BackgroundJob.claim("worker-b", now=now + timedelta(seconds=31), lease_seconds=30)
            assert reclaimed is not None and reclaimed.id == job.id
            assert reclaimed.worker_id == "worker-b"
            assert reclaimed.attempts == 2
        finally:
            await Tortoise.close_connections()

    asyncio.run(scenario())


def test_job_failure_retries_then_stops_at_attempt_limit():
    async def scenario():
        assert hasattr(model_module, "BackgroundJob"), "BackgroundJob model is not implemented"
        BackgroundJob = model_module.BackgroundJob
        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["translation_backend.app.models"]})
        await Tortoise.generate_schemas()
        try:
            now = datetime(2026, 10, 2, tzinfo=timezone.utc)
            job = await BackgroundJob.create(
                type="tm_index_rebuild",
                resource_type="translation_memory_library",
                resource_id=uuid4(),
                requested_version=2,
                max_attempts=2,
                available_at=now,
            )
            claimed = await BackgroundJob.claim("worker-a", now=now)
            await claimed.fail("INDEX_BUILD_FAILED", "api_key=secret-value", worker_id="worker-a", now=now)
            await claimed.refresh_from_db()
            assert claimed.status == "queued"
            assert claimed.error_message == "api_key=[REDACTED]"

            claimed = await BackgroundJob.claim("worker-b", now=claimed.available_at)
            await claimed.fail("INDEX_BUILD_FAILED", "failed", worker_id="worker-b", now=claimed.available_at)
            await claimed.refresh_from_db()
            assert claimed.status == "failed"
            assert claimed.finished_at is not None
        finally:
            await Tortoise.close_connections()

    asyncio.run(scenario())


def test_job_completion_requires_lease_owner():
    async def scenario():
        assert hasattr(model_module, "BackgroundJob"), "BackgroundJob model is not implemented"
        BackgroundJob = model_module.BackgroundJob
        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["translation_backend.app.models"]})
        await Tortoise.generate_schemas()
        try:
            job = await BackgroundJob.create(
                type="tm_index_rebuild",
                resource_type="translation_memory_library",
                resource_id=uuid4(),
                requested_version=1,
            )
            claimed = await BackgroundJob.claim("worker-a")
            with pytest.raises(ValueError, match="lease"):
                await claimed.complete(worker_id="worker-b", result={})
            await claimed.complete(worker_id="worker-a", result={"row_count": 4})
            await claimed.refresh_from_db()
            assert claimed.status == "succeeded"
            assert claimed.result == {"row_count": 4}
        finally:
            await Tortoise.close_connections()

    asyncio.run(scenario())
