from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from tortoise import Tortoise

from translation_backend.app.core.config import app_settings
from translation_backend.app.infrastructure.translation_memory.artifact_store import LocalIndexArtifactStore
from translation_backend.app.models import BackgroundJob, TranslationMemoryIndexArtifact, TranslationMemoryLibrary, User
from translation_backend.app.tasks.translation_memory_maintenance import cleanup_superseded_artifacts, reset_metrics, snapshot_metrics


def test_cleanup_preserves_active_building_referenced_and_configured_history(tmp_path, monkeypatch):
    async def scenario():
        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["translation_backend.app.models"]})
        await Tortoise.generate_schemas()
        try:
            monkeypatch.setattr(app_settings, "tm_index_retention_count", 2)
            user = await User.create(username="maintenance", email="maintenance@example.com", password_hash="x", display_name="Maintenance")
            library = await TranslationMemoryLibrary.create(scope="user", owner_user=user, name="TM")
            store = LocalIndexArtifactStore(tmp_path)
            now = datetime.now(timezone.utc)

            async def create_artifact(status, age, *, job=None):
                payload = f"{status}-{age}".encode()
                uri, checksum = store.put_atomic(payload)
                return await TranslationMemoryIndexArtifact.create(
                    library=library,
                    content_version=age,
                    format_version=1,
                    status=status,
                    storage_uri=uri,
                    checksum=checksum,
                    vectorizer_version="tfidf-cosine-v1",
                    build_job=job,
                    built_at=now - timedelta(days=age),
                )

            active = await create_artifact("active", 1)
            building = await create_artifact("building", 2)
            latest_history = await create_artifact("superseded", 3)
            retained_history = await create_artifact("superseded", 4)
            old_history = await create_artifact("superseded", 10)
            running_job = await BackgroundJob.create(
                type="tm_index_rebuild",
                resource_type="translation_memory_library",
                resource_id=library.id,
                requested_version=99,
                status="running",
            )
            referenced = await create_artifact("failed", 20, job=running_job)

            deleted = await cleanup_superseded_artifacts(store=store)

            assert deleted == 1
            assert await TranslationMemoryIndexArtifact.exists(id=active.id)
            assert await TranslationMemoryIndexArtifact.exists(id=building.id)
            assert await TranslationMemoryIndexArtifact.exists(id=latest_history.id)
            assert await TranslationMemoryIndexArtifact.exists(id=retained_history.id)
            assert await TranslationMemoryIndexArtifact.exists(id=referenced.id)
            assert not await TranslationMemoryIndexArtifact.exists(id=old_history.id)
            assert not store.exists(old_history.storage_uri)
        finally:
            await Tortoise.close_connections()

    asyncio.run(scenario())


def test_metrics_are_bounded_named_counters():
    reset_metrics()
    from translation_backend.app.tasks.translation_memory_maintenance import increment_metric, observe_duration_ms

    increment_metric("tm_index_retries_total", 2)
    observe_duration_ms("tm_index_build_duration_ms", 12.5)

    assert snapshot_metrics() == {
        "tm_index_retries_total": 2,
        "tm_index_build_duration_ms_count": 1,
        "tm_index_build_duration_ms_total_ms": 12,
    }
