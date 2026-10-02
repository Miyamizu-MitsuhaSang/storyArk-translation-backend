from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from tortoise import Tortoise

from translation_backend.app.core.config import app_settings
from translation_backend.app.models import BackgroundJob, TranslationMemoryEntry, User, TranslationMemoryLibrary
from translation_backend.app.tasks.translation_memory import (
    TranslationMemoryTaskDispatcher,
    process_rebuild_index,
    reclaim_expired_index_jobs,
    rebuild_translation_memory_index_task,
)
from translation_backend.app.tasks import translation_memory as worker_module


class FailingIndexService:
    def __init__(self):
        self.calls = 0

    async def build_job(self, job_id, *, worker_id):
        self.calls += 1
        raise OSError("temporary artifact store failure")


def test_worker_retries_storage_failure_and_duplicate_delivery_does_not_claim_early():
    async def scenario():
        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["translation_backend.app.models"]})
        await Tortoise.generate_schemas()
        try:
            user = await User.create(username="tm-worker", email="tm-worker@example.com", password_hash="x", display_name="TM")
            library = await TranslationMemoryLibrary.create(scope="user", owner_user=user, name="TM")
            job = await BackgroundJob.create(
                type="tm_index_rebuild",
                resource_type="translation_memory_library",
                resource_id=library.id,
                requested_version=library.content_version,
                available_at=datetime.now(timezone.utc) - timedelta(seconds=1),
            )
            service = FailingIndexService()

            first = await process_rebuild_index(job.id, worker_id="worker-test", service=service)
            duplicate = await process_rebuild_index(job.id, worker_id="worker-test-2", service=service)

            await job.refresh_from_db()
            assert first["status"] == "retry"
            assert duplicate["status"] == "not_claimed"
            assert service.calls == 1
            assert job.status == "queued"
            assert job.attempts == 1
            assert job.error_code == "INDEX_BUILD_FAILED"
            assert job.available_at > datetime.now(timezone.utc)
        finally:
            await Tortoise.close_connections()

    asyncio.run(scenario())


def test_worker_claims_only_the_requested_job_and_finishes_it():
    class SuccessfulIndexService:
        async def build_job(self, job_id, *, worker_id):
            job = await BackgroundJob.get(id=job_id)
            await job.complete(worker_id=worker_id, result={"status": "active"})
            return {"status": "active"}

    async def scenario():
        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["translation_backend.app.models"]})
        await Tortoise.generate_schemas()
        try:
            user = await User.create(username="tm-worker-target", email="tm-worker-target@example.com", password_hash="x", display_name="TM")
            library = await TranslationMemoryLibrary.create(scope="user", owner_user=user, name="TM")
            unrelated = await BackgroundJob.create(
                type="tm_index_rebuild", resource_type="translation_memory_library",
                resource_id=uuid4(), requested_version=1,
            )
            target = await BackgroundJob.create(
                type="tm_index_rebuild", resource_type="translation_memory_library",
                resource_id=library.id, requested_version=library.content_version,
            )

            result = await process_rebuild_index(target.id, worker_id="worker-target", service=SuccessfulIndexService())

            await target.refresh_from_db()
            await unrelated.refresh_from_db()
            assert result["status"] == "active"
            assert target.status == "succeeded"
            assert unrelated.status == "queued"
        finally:
            await Tortoise.close_connections()

    asyncio.run(scenario())


def test_rebuild_dispatcher_is_async_idempotent_and_uses_job_id_as_task_id(monkeypatch):
    async def scenario():
        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["translation_backend.app.models"]})
        await Tortoise.generate_schemas()
        try:
            user = await User.create(username="tm-enqueue", email="tm-enqueue@example.com", password_hash="x", display_name="TM")
            library = await TranslationMemoryLibrary.create(scope="user", owner_user=user, name="TM")
            dispatched = []
            monkeypatch.setattr(
                rebuild_translation_memory_index_task,
                "apply_async",
                lambda *, args, task_id: dispatched.append((args, task_id)),
            )
            dispatcher = TranslationMemoryTaskDispatcher()

            first = await dispatcher.enqueue_rebuild(library.id, library.content_version)
            second = await dispatcher.enqueue_rebuild(library.id, library.content_version)

            assert first.job_id == second.job_id
            assert first.status == second.status == "queued"
            assert dispatched == [([str(first.job_id)], str(first.job_id))]
            assert await BackgroundJob.filter(type="tm_index_rebuild").count() == 1
        finally:
            await Tortoise.close_connections()

    asyncio.run(scenario())


def test_celery_eager_worker_builds_and_publishes_index(tmp_path, monkeypatch):
    database_path = tmp_path / "worker.sqlite3"
    tortoise_config = {
        "connections": {"default": f"sqlite://{database_path}"},
        "apps": {
            "models": {
                "models": ["translation_backend.app.models"],
                "default_connection": "default",
            },
        },
        "use_tz": True,
        "timezone": "UTC",
    }
    monkeypatch.setattr(worker_module, "TORTOISE_ORM", tortoise_config)
    monkeypatch.setattr(app_settings, "tm_index_storage_dir", tmp_path / "indexes")

    async def seed_database():
        await Tortoise.init(config=tortoise_config)
        await Tortoise.generate_schemas()
        user = await User.create(username="tm-eager", email="tm-eager@example.com", password_hash="x", display_name="TM")
        library = await TranslationMemoryLibrary.create(scope="user", owner_user=user, name="TM")
        await TranslationMemoryEntry.create(
            library=library,
            source_language="en",
            target_language="zh",
            source_text="hello world",
            target_text="你好世界",
            source_hash="source",
            target_hash="target",
            origin="manual",
        )
        job = await BackgroundJob.create(
            type="tm_index_rebuild",
            resource_type="translation_memory_library",
            resource_id=library.id,
            requested_version=library.content_version,
        )
        duplicate_job = await BackgroundJob.create(
            type="tm_index_rebuild",
            resource_type="translation_memory_library",
            resource_id=library.id,
            requested_version=library.content_version,
        )
        await Tortoise.close_connections()
        return job.id, duplicate_job.id

    job_id, duplicate_job_id = asyncio.run(seed_database())
    result = rebuild_translation_memory_index_task.apply(args=[str(job_id)], throw=True)
    duplicate_result = rebuild_translation_memory_index_task.apply(args=[str(duplicate_job_id)], throw=True)

    assert result.successful(), result.result
    assert duplicate_result.successful(), duplicate_result.result
    artifacts = list((tmp_path / "indexes").glob("sha256/*"))
    assert len(artifacts) == 1
    assert artifacts[0].is_file()


def test_expired_index_jobs_are_redispatched_with_deterministic_task_id(monkeypatch):
    async def scenario():
        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["translation_backend.app.models"]})
        await Tortoise.generate_schemas()
        try:
            now = datetime.now(timezone.utc)
            job = await BackgroundJob.create(
                type="tm_index_rebuild",
                resource_type="translation_memory_library",
                resource_id=uuid4(),
                requested_version=1,
                status="running",
                attempts=1,
                worker_id="lost-worker",
                lease_expires_at=now - timedelta(seconds=1),
            )
            dispatched = []
            monkeypatch.setattr(
                rebuild_translation_memory_index_task,
                "apply_async",
                lambda *, args, task_id: dispatched.append((args, task_id)),
            )

            count = await reclaim_expired_index_jobs(now=now)

            assert count == 1
            assert dispatched == [([str(job.id)], str(job.id))]
        finally:
            await Tortoise.close_connections()

    asyncio.run(scenario())
