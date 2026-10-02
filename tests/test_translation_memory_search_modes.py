from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from tortoise import Tortoise

from translation_backend.app.application.translation_memory.schemas import TranslationMemorySearchRequest
from translation_backend.app.application.translation_memory.service import (
    TranslationMemoryIndexUnavailableError,
    TranslationMemoryService,
)
from translation_backend.app.models import Project, ProjectMember, TranslationMemoryEntry, TranslationMemoryLibrary, User
from translation_backend.app.infrastructure.translation_memory.search_index import source_hash
from translation_backend.app.application.translation_memory.index_service import TranslationMemoryIndexService
from translation_backend.app.infrastructure.translation_memory.artifact_store import LocalIndexArtifactStore
from translation_backend.app.infrastructure.translation_memory.search_index import TranslationMemorySearchIndex
from translation_backend.app.models import BackgroundJob


def test_search_schema_accepts_fuzzy_mode():
    request = TranslationMemorySearchRequest(
        source_text="hello",
        source_language="en",
        target_language="zh-CN",
        match_mode="fuzzy",
    )
    assert request.match_mode == "fuzzy"


def test_fuzzy_search_requires_a_compatible_active_artifact():
    async def scenario():
        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["translation_backend.app.models"]})
        await Tortoise.generate_schemas()
        try:
            user = await User.create(username="fuzzy", email="fuzzy@example.com", password_hash="x", display_name="Fuzzy")
            project = await Project.create(key="fuzzy-project", name="Fuzzy", created_by=user)
            await ProjectMember.create(project=project, user=user, role="owner")
            library = await TranslationMemoryLibrary.create(scope="user", owner_user=user, name="TM")
            await TranslationMemoryEntry.create(
                library=library,
                source_language="en",
                target_language="zh-CN",
                source_text="hello world",
                target_text="你好世界",
                source_hash=source_hash("hello world"),
                target_hash=source_hash("你好世界"),
                origin="manual",
            )
            request = TranslationMemorySearchRequest(
                source_text="hello",
                source_language="en",
                target_language="zh-CN",
                match_mode="fuzzy",
            )

            with pytest.raises(TranslationMemoryIndexUnavailableError) as raised:
                await TranslationMemoryService().search(user, project.id, request)
            assert raised.value.status_code == 503
            assert raised.value.code == "INDEX_NOT_AVAILABLE"
        finally:
            await Tortoise.close_connections()

    asyncio.run(scenario())


def test_fuzzy_search_does_not_use_cached_results_when_artifact_is_unavailable():
    class Cache:
        def __init__(self):
            self.get_calls = 0

        async def get(self, key):
            self.get_calls += 1
            return '{"items":[],"total":0,"source_hash":"cached","index_status":"artifact"}'

        async def set(self, key, value, ttl_seconds):
            raise AssertionError("fuzzy results must not be cached")

    async def scenario():
        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["translation_backend.app.models"]})
        await Tortoise.generate_schemas()
        try:
            user = await User.create(username="fuzzy-cache", email="fuzzy-cache@example.com", password_hash="x", display_name="Fuzzy")
            project = await Project.create(key="fuzzy-cache-project", name="Fuzzy", created_by=user)
            await ProjectMember.create(project=project, user=user, role="owner")
            await TranslationMemoryLibrary.create(scope="user", owner_user=user, name="TM")
            cache = Cache()
            with pytest.raises(TranslationMemoryIndexUnavailableError):
                await TranslationMemoryService(cache=cache).search(
                    user,
                    project.id,
                    TranslationMemorySearchRequest(
                        source_text="hello",
                        source_language="en",
                        target_language="zh-CN",
                        match_mode="fuzzy",
                    ),
                )
            assert cache.get_calls == 0
        finally:
            await Tortoise.close_connections()

    asyncio.run(scenario())


def test_exact_search_remains_available_without_an_index():
    async def scenario():
        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["translation_backend.app.models"]})
        await Tortoise.generate_schemas()
        try:
            user = await User.create(username="exact", email="exact@example.com", password_hash="x", display_name="Exact")
            project = await Project.create(key="exact-project", name="Exact", created_by=user)
            await ProjectMember.create(project=project, user=user, role="owner")
            library = await TranslationMemoryLibrary.create(scope="user", owner_user=user, name="TM")
            await TranslationMemoryEntry.create(
                library=library,
                source_language="en",
                target_language="zh-CN",
                source_text="hello world",
                target_text="你好世界",
                source_hash=source_hash("hello world"),
                target_hash=source_hash("你好世界"),
                origin="manual",
            )
            result = await TranslationMemoryService().search(
                user,
                project.id,
                TranslationMemorySearchRequest(
                    source_text="hello world",
                    source_language="en",
                    target_language="zh-CN",
                    match_mode="exact",
                ),
            )
            assert result.total == 1
            assert result.items[0].match_type == "exact"
        finally:
            await Tortoise.close_connections()

    asyncio.run(scenario())


def test_fuzzy_search_maps_active_sdk_hits_back_to_scoped_tm_rows(tmp_path):
    async def scenario():
        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["translation_backend.app.models"]})
        await Tortoise.generate_schemas()
        try:
            user = await User.create(username="fuzzy-hit", email="fuzzy-hit@example.com", password_hash="x", display_name="Fuzzy")
            project = await Project.create(key="fuzzy-hit-project", name="Fuzzy", created_by=user)
            await ProjectMember.create(project=project, user=user, role="owner")
            library = await TranslationMemoryLibrary.create(scope="user", owner_user=user, name="TM")
            await TranslationMemoryEntry.create(
                library=library,
                source_language="en",
                target_language="zh-CN",
                source_text="hello world",
                target_text="你好世界",
                source_hash=source_hash("hello world"),
                target_hash=source_hash("你好世界"),
                origin="manual",
            )
            job = await BackgroundJob.create(
                type="tm_index_rebuild",
                resource_type="translation_memory_library",
                resource_id=library.id,
                requested_version=library.content_version,
            )
            claimed = await BackgroundJob.claim("fuzzy-worker", job_id=job.id, job_type="tm_index_rebuild")
            index_service = TranslationMemoryIndexService(store=LocalIndexArtifactStore(tmp_path))
            await index_service.build_job(claimed.id, worker_id="fuzzy-worker")
            search_service = TranslationMemoryService(
                search_index=TranslationMemorySearchIndex(index_service=index_service),
            )

            result = await search_service.search(
                user,
                project.id,
                TranslationMemorySearchRequest(
                    source_text="hello",
                    source_language="en",
                    target_language="zh-CN",
                    match_mode="fuzzy",
                    min_score=0.1,
                ),
            )

            assert result.index_status == "artifact"
            assert result.total == 1
            assert result.items[0].match_type == "fuzzy"
            assert result.items[0].target_text == "你好世界"
        finally:
            await Tortoise.close_connections()

    asyncio.run(scenario())
