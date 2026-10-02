from __future__ import annotations

import asyncio

from tortoise import Tortoise

from translation_backend.app.application.translation_memory.index_service import TranslationMemoryIndexService
from translation_backend.app.infrastructure.translation_memory.artifact_store import LocalIndexArtifactStore
from translation_backend.app.models import BackgroundJob, TranslationMemoryEntry, TranslationMemoryLibrary, User


def test_active_index_loads_after_database_and_service_restart(tmp_path):
    async def scenario():
        db_path = tmp_path / "restart.sqlite3"
        config = {
            "connections": {"default": f"sqlite://{db_path}"},
            "apps": {"models": {"models": ["translation_backend.app.models"], "default_connection": "default"}},
            "use_tz": True,
            "timezone": "UTC",
        }
        await Tortoise.init(config=config)
        await Tortoise.generate_schemas()
        user = await User.create(username="restart", email="restart@example.com", password_hash="x", display_name="Restart")
        library = await TranslationMemoryLibrary.create(scope="user", owner_user=user, name="TM")
        await TranslationMemoryEntry.create(
            library=library,
            source_language="en",
            target_language="zh-CN",
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
        claimed = await BackgroundJob.claim("restart-worker", job_id=job.id, job_type="tm_index_rebuild")
        store = LocalIndexArtifactStore(tmp_path / "artifacts")
        first_service = TranslationMemoryIndexService(store=store)
        await first_service.build_job(claimed.id, worker_id="restart-worker")
        await Tortoise.close_connections()

        await Tortoise.init(config=config)
        restarted_service = TranslationMemoryIndexService(store=store)
        loaded = await restarted_service.load_active(library.id)

        assert loaded.row_count == 1
        assert loaded.partitions
        await Tortoise.close_connections()

    asyncio.run(scenario())

