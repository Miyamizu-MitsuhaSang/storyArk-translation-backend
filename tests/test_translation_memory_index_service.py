from __future__ import annotations

import asyncio
import hashlib

import pytest
from tortoise import Tortoise

from translation_backend.app import models as model_module
from translation_backend.app.application.translation_memory.index_service import (
    TranslationMemoryIndexBackend,
    TranslationMemoryIndexService,
)
from translation_backend.app.infrastructure.translation_memory.artifact_store import LocalIndexArtifactStore
from translation_backend.app.models import BackgroundJob, TranslationMemoryEntry, TranslationMemoryLibrary, User


def test_index_backend_partitions_by_language_pair_and_round_trips():
    async def scenario():
        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["translation_backend.app.models"]})
        await Tortoise.generate_schemas()
        try:
            user = await User.create(username="tm-index", email="tm-index@example.com", password_hash="x", display_name="TM")
            library = await TranslationMemoryLibrary.create(scope="user", owner_user=user, name="TM")
            rows = []
            for source_language, target_language, source, target in (
                ("en", "zh-CN", "hello world", "你好世界"),
                ("en", "zh-TW", "hello world", "你好世界"),
            ):
                rows.append(await TranslationMemoryEntry.create(
                    library=library,
                    source_language=source_language,
                    target_language=target_language,
                    source_text=source,
                    target_text=target,
                    source_hash=hashlib.sha256(source.encode()).hexdigest(),
                    target_hash=hashlib.sha256(target.encode()).hexdigest(),
                    origin="manual",
                ))
            backend = TranslationMemoryIndexBackend()
            index = backend.build(rows)
            payload = backend.serialize(index)
            restored = backend.deserialize(payload)

            assert restored.row_count == 2
            assert len(restored.partitions) == 2
            assert backend.search(restored, "hello", "en", "zh-CN", 1)[0]["entry_id"] == str(rows[0].id)
            assert backend.search(restored, "hello", "en", "zh-TW", 1)[0]["entry_id"] == str(rows[1].id)
            assert backend.search(restored, "hello", "en", "zh", 1) == []
        finally:
            await Tortoise.close_connections()

    import pytest

    pytest.importorskip("translate_manager_rag")
    asyncio.run(scenario())


def test_index_service_publishes_only_when_library_version_is_current(tmp_path):
    async def scenario():
        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["translation_backend.app.models"]})
        await Tortoise.generate_schemas()
        try:
            user = await User.create(username="tm-build", email="tm-build@example.com", password_hash="x", display_name="TM")
            library = await TranslationMemoryLibrary.create(scope="user", owner_user=user, name="TM")
            entry = await TranslationMemoryEntry.create(
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
            claimed = await BackgroundJob.claim("worker-test", job_type="tm_index_rebuild")
            service = TranslationMemoryIndexService(store=LocalIndexArtifactStore(tmp_path))

            result = await service.build_job(claimed.id, worker_id="worker-test")

            assert result["status"] == "active"
            artifact = await model_module.TranslationMemoryIndexArtifact.get(id=result["artifact_id"])
            assert artifact.status == "active"
            assert artifact.row_count == 1
            assert artifact.checksum is not None
            assert (await service.load_active(library.id)).row_count == 1
            artifact_path = tmp_path / artifact.storage_uri
            artifact_path.write_bytes(artifact_path.read_bytes() + b"corrupt")
            with pytest.raises(ValueError, match="checksum"):
                await service.load_active(library.id)
        finally:
            await Tortoise.close_connections()

    asyncio.run(scenario())


def test_index_service_refuses_to_publish_artifact_for_stale_version(tmp_path):
    async def scenario():
        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["translation_backend.app.models"]})
        await Tortoise.generate_schemas()
        try:
            user = await User.create(username="tm-stale", email="tm-stale@example.com", password_hash="x", display_name="TM")
            library = await TranslationMemoryLibrary.create(scope="user", owner_user=user, name="TM")
            artifact = await model_module.TranslationMemoryIndexArtifact.create(
                library=library,
                content_version=library.content_version,
                format_version=1,
                status="ready",
                storage_uri="sha256/" + "a" * 64,
                checksum="a" * 64,
                vectorizer_version="tfidf-cosine-v1",
            )
            await TranslationMemoryLibrary.filter(id=library.id).update(content_version=library.content_version + 1)
            service = TranslationMemoryIndexService(store=LocalIndexArtifactStore(tmp_path))

            published = await service.publish_if_current(artifact)

            await artifact.refresh_from_db()
            assert published is False
            assert artifact.status == "superseded"
        finally:
            await Tortoise.close_connections()

    asyncio.run(scenario())
