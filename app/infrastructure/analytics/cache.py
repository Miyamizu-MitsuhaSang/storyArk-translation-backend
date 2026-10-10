from __future__ import annotations

import json
from typing import Any
from uuid import UUID


class NoopAnalyticsCache:
    async def get(self, key: str) -> str | None:
        return None

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        return None

    async def delete(self, key: str) -> None:
        return None


class RedisAnalyticsCache(NoopAnalyticsCache):
    def __init__(self, client: Any, *, namespace: str = "analytics") -> None:
        self.client = client
        self.namespace = namespace

    def _key(self, key: str) -> str:
        return key if key.startswith(f"{self.namespace}:") else f"{self.namespace}:{key}"

    async def get(self, key: str) -> str | None:
        return await self.client.get(self._key(key))

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        await self.client.set(self._key(key), value, ex=ttl_seconds)

    async def delete(self, key: str) -> None:
        await self.client.delete(self._key(key))


def build_usage_cache_key(scope: str, scope_id: UUID, query: Any) -> str:
    payload = query.model_dump(mode="json", by_alias=True)
    return "analytics:usage:" + json.dumps({"scope": scope, "id": str(scope_id), "query": payload}, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


__all__ = ["NoopAnalyticsCache", "RedisAnalyticsCache", "build_usage_cache_key"]
