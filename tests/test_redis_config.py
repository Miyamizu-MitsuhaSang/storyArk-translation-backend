from __future__ import annotations

import asyncio

from translation_backend.app.core import redis as redis_module
from translation_backend.app.core.config import app_settings


def test_init_redis_uses_app_settings_url(monkeypatch) -> None:
    class FakeRedis:
        async def ping(self) -> bool:
            return True

    calls: list[tuple[str, bool]] = []

    def fake_from_url(url: str, *, decode_responses: bool) -> FakeRedis:
        calls.append((url, decode_responses))
        return FakeRedis()

    async def scenario() -> None:
        monkeypatch.setattr(redis_module.redis, "from_url", fake_from_url)
        monkeypatch.setattr(app_settings, "redis_enabled", True)
        monkeypatch.setattr(app_settings, "redis_url", "redis://redis.internal:6379/7")
        monkeypatch.setattr(redis_module, "redis_client", None)

        client = await redis_module.init_redis()

        assert client is not None
        assert calls == [("redis://redis.internal:6379/7", True)]
        redis_module.redis_client = None

    asyncio.run(scenario())


def test_init_redis_does_not_connect_when_global_switch_is_disabled(monkeypatch) -> None:
    calls: list[str] = []

    def fake_from_url(url: str, *, decode_responses: bool):
        calls.append(url)
        raise AssertionError("Redis must not be initialized while disabled")

    async def scenario() -> None:
        monkeypatch.setattr(redis_module.redis, "from_url", fake_from_url)
        monkeypatch.setattr(app_settings, "redis_enabled", False)
        monkeypatch.setattr(redis_module, "redis_client", None)

        assert await redis_module.init_redis() is None
        assert calls == []

    asyncio.run(scenario())
