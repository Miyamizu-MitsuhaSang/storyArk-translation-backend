from __future__ import annotations

import asyncio
from uuid import uuid4

from pydantic import BaseModel
from tortoise import Tortoise

from translation_backend.app.application import idempotency
from translation_backend.app.application.idempotency import execute_idempotently
from translation_backend.app.core.config import app_settings
from translation_backend.app.models import User


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.set_calls: list[tuple[str, str, int]] = []
        self.eval_calls: list[tuple[str, str]] = []

    async def set(self, key: str, value: str, *, nx: bool, ex: int) -> bool:
        self.set_calls.append((key, value, ex))
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def eval(self, script: str, numkeys: int, key: str, value: str) -> int:
        self.eval_calls.append((key, value))
        if self.values.get(key) == value:
            del self.values[key]
            return 1
        return 0


class Result(BaseModel):
    value: str


def test_idempotency_uses_redis_as_distributed_inflight_lock(monkeypatch) -> None:
    async def scenario() -> None:
        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["translation_backend.app.models"]})
        await Tortoise.generate_schemas()
        try:
            user = await User.create(
                username="redis-idempotency",
                email="redis-idempotency@example.com",
                password_hash="hash",
                display_name="Redis",
            )
            fake = FakeRedis()
            monkeypatch.setattr(idempotency.redis_module, "redis_client", fake)
            monkeypatch.setattr(app_settings, "idempotency_redis_enabled", True)
            calls = 0

            async def callback() -> Result:
                nonlocal calls
                calls += 1
                return Result(value="created")

            first = await execute_idempotently(
                user,
                operation="test.create",
                scope="project:test",
                key="redis-key",
                payload={"name": "test"},
                response_type=Result,
                callback=callback,
            )
            second = await execute_idempotently(
                user,
                operation="test.create",
                scope="project:test",
                key="redis-key",
                payload={"name": "test"},
                response_type=Result,
                callback=callback,
            )

            assert first == second == Result(value="created")
            assert calls == 1
            assert len(fake.set_calls) == 1
            assert len(fake.eval_calls) == 1
            assert fake.values == {}
        finally:
            await Tortoise.close_connections()

    asyncio.run(scenario())


def test_idempotency_falls_back_to_database_when_redis_errors(monkeypatch) -> None:
    class BrokenRedis:
        async def set(self, *args, **kwargs):
            raise OSError("redis unavailable")

    async def scenario() -> None:
        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["translation_backend.app.models"]})
        await Tortoise.generate_schemas()
        try:
            user = await User.create(
                username="redis-fallback",
                email="redis-fallback@example.com",
                password_hash="hash",
                display_name="Fallback",
            )
            monkeypatch.setattr(idempotency.redis_module, "redis_client", BrokenRedis())
            monkeypatch.setattr(app_settings, "idempotency_redis_enabled", True)
            result = await execute_idempotently(
                user,
                operation="test.create",
                scope="project:fallback",
                key="fallback-key",
                payload={"value": 1},
                response_type=Result,
                callback=lambda: _result("fallback"),
            )
            assert result == Result(value="fallback")
        finally:
            await Tortoise.close_connections()

    asyncio.run(scenario())


async def _result(value: str) -> Result:
    return Result(value=value)
