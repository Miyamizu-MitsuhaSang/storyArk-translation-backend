from __future__ import annotations

import inspect
import json
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from ...application.translation_memory.schemas import TranslationMemorySearchRequest
from .search_index import normalize_text


class TranslationMemoryCache:
    async def get(self, key: str) -> str | None:
        return None

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        return None

    async def delete_by_library_version(self, library_id: UUID, content_version: int) -> None:
        return None


class NoopTranslationMemoryCache(TranslationMemoryCache):
    pass


class RedisTranslationMemoryCache:
    def __init__(self, client: Any, *, namespace: str = "tm") -> None:
        self.client = client
        self.namespace = namespace

    async def get(self, key: str) -> str | None:
        return await self.client.get(self._key(key))

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        await self.client.set(self._key(key), value, ex=ttl_seconds)

    async def delete_by_library_version(self, library_id: UUID, content_version: int) -> None:
        prefix = f"{self.namespace}:search:"
        keys: list[str] = []
        async for raw_key in self.client.scan_iter(match=f"{prefix}*"):
            key = raw_key.decode() if isinstance(raw_key, bytes) else raw_key
            try:
                payload = json.loads(key[len(prefix):])
                libraries = payload.get("libraries", [])
            except (ValueError, TypeError):
                continue
            if [str(library_id), int(content_version)] in libraries:
                keys.append(key)
        if keys:
            await self.client.delete(*keys)

    def _key(self, key: str) -> str:
        return key if key.startswith(f"{self.namespace}:") else f"{self.namespace}:{key}"


def build_search_cache_key(request: TranslationMemorySearchRequest, *, user_id: UUID, project_id: UUID, library_versions: Mapping[UUID, int] | None = None, namespace: str = "tm") -> str:
    versions = library_versions or {}
    libraries = sorted((str(library_id), int(version)) for library_id, version in versions.items())
    filters = {
        "include_library_ids": sorted(str(item) for item in (request.include_library_ids or [])),
        "min_score": request.min_score,
        "match_mode": request.match_mode,
        "source_language": request.source_language,
        "target_language": request.target_language,
        "top_k": request.top_k,
        "updated_after": request.updated_after.isoformat() if request.updated_after else None,
        "updated_before": request.updated_before.isoformat() if request.updated_before else None,
    }
    return f"{namespace}:search:" + json.dumps({"user": str(user_id), "project": str(project_id), "query": normalize_text(request.source_text), "filters": filters, "libraries": libraries}, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


async def cache_get(cache: Any, key: str) -> str | None:
    result = cache.get(key)
    return await result if inspect.isawaitable(result) else result


async def cache_set(cache: Any, key: str, value: str, ttl_seconds: int) -> None:
    result = cache.set(key, value, ttl_seconds)
    if inspect.isawaitable(result):
        await result
