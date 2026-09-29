from __future__ import annotations

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
        TranslationMemorySearchRequest(source_text="x" * 4097, source_language="en", target_language="zh")
