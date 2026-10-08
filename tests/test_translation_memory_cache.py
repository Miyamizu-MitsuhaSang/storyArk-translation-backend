from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from translation_backend.app.application.translation_memory.schemas import (
    TranslationMemoryMatch,
    TranslationMemorySearchRequest,
    TranslationMemorySearchResponse,
)
from translation_backend.app.infrastructure.translation_memory.cache import build_search_cache_key
from translation_backend.app.application.translation_memory.service import TranslationMemoryService
from translation_backend.app.application.translation_memory.service import (
    TranslationMemoryCursorError,
    TranslationMemoryIdempotencyError,
)
from translation_backend.app.application.translation_memory.schemas import TranslationMemoryImportRow
from translation_backend.app.core.config import app_settings
from translation_backend.app.core import redis as redis_module
from translation_backend.app.api.modules.project.project_content.tm.dependencies import get_translation_memory_service
from translation_backend.app.infrastructure.translation_memory.search_index import source_hash
from translation_backend.app.infrastructure.translation_memory.cache import RedisTranslationMemoryCache
from translation_backend.app.models import Project, ProjectMember, TranslationMemoryEntry, TranslationMemoryLibrary, User
from tortoise import Tortoise


class UnavailableCache:
    def get(self, key: str) -> str | None:
        raise ConnectionError("redis unavailable")

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        raise ConnectionError("redis unavailable")

    def delete_by_library_version(self, library_id: UUID, content_version: int) -> None:
        raise ConnectionError("redis unavailable")


@pytest.fixture
def tm_request() -> TranslationMemorySearchRequest:
    return TranslationMemorySearchRequest(
        source_text="  Hello   world ",
        source_language="en",
        target_language="zh-CN",
        top_k=10,
        include_library_ids=[UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")],
    )


def run_search_with_cache(cache: UnavailableCache, request: TranslationMemorySearchRequest) -> TranslationMemorySearchResponse:
    """Exercise cache failure handling while keeping the database result available."""
    match = TranslationMemoryMatch(
        entry_id=uuid4(),
        library_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        scope="user",
        source_language=request.source_language,
        target_language=request.target_language,
        source_text="Hello world",
        target_text="你好世界",
        updated_at=datetime.now(timezone.utc),
    )
    try:
        cached = cache.get("search")
        if cached:
            return TranslationMemorySearchResponse.model_validate_json(cached)
    except Exception:
        pass
    return TranslationMemorySearchResponse(items=[match], total=1, source_hash="test")


def test_search_falls_back_to_database_when_redis_is_unavailable(tm_request):
    result = run_search_with_cache(UnavailableCache(), tm_request)
    assert result.items


def test_cache_key_changes_when_library_content_version_changes(tm_request):
    request = tm_request
    first = build_search_cache_key(request, user_id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"), project_id=UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"), library_versions={(request.include_library_ids or [])[0]: 3})
    second = build_search_cache_key(request, user_id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"), project_id=UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"), library_versions={(request.include_library_ids or [])[0]: 4})
    assert first != second
    assert "hello world" in first


def test_search_request_rejects_large_top_k_and_query_text():
    with pytest.raises(ValidationError):
        TranslationMemorySearchRequest(source_text="x", source_language="en", target_language="zh", top_k=51)
    with pytest.raises(ValidationError):
        TranslationMemorySearchRequest(source_text="x" * 16385, source_language="en", target_language="zh")


def test_translation_memory_service_falls_back_to_sqlite_when_cache_is_unavailable(tm_request):
    async def scenario():
        await Tortoise.init(
            db_url="sqlite://:memory:",
            modules={"models": ["translation_backend.app.models"]},
        )
        await Tortoise.generate_schemas()
        try:
            user = await User.create(
                username="tm-test", email="tm-test@example.com", password_hash="hash", display_name="TM Test"
            )
            project = await Project.create(key="tm-test-project", name="TM Test", created_by=user)
            await ProjectMember.create(project=project, user=user, role="owner")
            library = await TranslationMemoryLibrary.create(scope="user", owner_user=user, name="TM Test")
            await TranslationMemoryEntry.create(
                library=library,
                source_language="en",
                target_language="zh-CN",
                source_text="Hello world",
                target_text="你好世界",
                source_hash=source_hash("Hello world"),
                target_hash=source_hash("你好世界"),
                origin="manual",
            )
            service = TranslationMemoryService(cache=UnavailableCache())
            request = tm_request.model_copy(update={"include_library_ids": [library.id]})
            result = await service.search(user, project.id, request)
            assert result.items
            assert result.items[0].target_text == "你好世界"
        finally:
            await Tortoise.close_connections()

    asyncio.run(scenario())


def test_service_uses_configured_query_length_limit(tm_request, monkeypatch):
    monkeypatch.setattr(app_settings, "tm_search_max_text_length", 4)

    async def scenario():
        with pytest.raises(TranslationMemoryCursorError):
            await TranslationMemoryService(cache=UnavailableCache()).search(
                User(id=uuid4()), uuid4(), tm_request
            )

    asyncio.run(scenario())


def test_redis_cache_invalidates_matching_library_version():
    class FakeRedis:
        def __init__(self):
            self.deleted = []

        async def get(self, key):
            return None

        async def set(self, key, value, ex):
            return None

        async def delete(self, *keys):
            self.deleted.extend(keys)

        async def scan_iter(self, match):
            for key in (
                'custom:search:{"libraries":[["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",3]]}',
                'custom:search:{"libraries":[["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",4]]}',
            ):
                yield key

    async def scenario():
        client = FakeRedis()
        await RedisTranslationMemoryCache(client, namespace="custom").delete_by_library_version(
            UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"), 3
        )
        assert client.deleted == ['custom:search:{"libraries":[["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",3]]}']

    asyncio.run(scenario())


def test_service_factory_binds_redis_after_lifespan_initialization(monkeypatch):
    class ReadyRedis:
        pass

    monkeypatch.setattr(app_settings, "tm_cache_enabled", True)
    monkeypatch.setattr(app_settings, "tm_cache_namespace", "delayed")
    monkeypatch.setattr(redis_module, "redis_client", ReadyRedis())
    first = get_translation_memory_service()
    second = get_translation_memory_service()
    assert first is not second
    assert first._cache.namespace == "delayed"


def test_import_rejects_same_idempotency_key_with_different_payload():
    async def scenario():
        await Tortoise.init(
            db_url="sqlite://:memory:",
            modules={"models": ["translation_backend.app.models"]},
        )
        await Tortoise.generate_schemas()
        try:
            user = await User.create(
                username="tm-idempotency", email="tm-idempotency@example.com", password_hash="hash", display_name="TM Idempotency"
            )
            library = await TranslationMemoryLibrary.create(scope="user", owner_user=user, name="TM Idempotency")
            service = TranslationMemoryService(cache=UnavailableCache())
            first = TranslationMemoryImportRow(
                source_language="en", target_language="zh-CN", source_text="Hello", target_text="你好"
            )
            second = first.model_copy(update={"target_text": "您好"})
            await service.import_entries(user, library.id, [first], "same-key")
            with pytest.raises(TranslationMemoryIdempotencyError):
                await service.import_entries(user, library.id, [second], "same-key")
        finally:
            await Tortoise.close_connections()

    asyncio.run(scenario())
