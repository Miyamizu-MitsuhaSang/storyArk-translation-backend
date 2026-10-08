from __future__ import annotations

import hashlib
import json
import logging
import secrets
from collections.abc import Awaitable, Callable
from typing import TypeVar

from tortoise.exceptions import IntegrityError

from ..models import IdempotencyRecord, User
from ..core import redis as redis_module
from ..core.config import app_settings

T = TypeVar("T")
_logger = logging.getLogger(__name__)
_RELEASE_LOCK_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


class IdempotencyConflictError(Exception):
    """The same idempotency key was used for a different or unfinished operation."""


def request_fingerprint(payload: object) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


async def execute_idempotently(
    user: User,
    *,
    operation: str,
    scope: str,
    key: str | None,
    payload: object,
    response_type: type[T],
    callback: Callable[[], Awaitable[T]],
) -> T:
    if key is None:
        return await callback()
    if not key.strip() or len(key) > 160:
        raise ValueError("Idempotency-Key 必须为 1 到 160 个字符")

    fingerprint = request_fingerprint(payload)
    existing = await IdempotencyRecord.filter(user_id=user.id, idempotency_key=key).first()
    if existing is not None:
        return _replay(existing, operation, scope, fingerprint, response_type)

    lock_key = _redis_lock_key(user.id, operation, scope, key)
    lock_token = await _try_acquire_redis_lock(lock_key)
    if lock_token is False:
        existing = await IdempotencyRecord.filter(user_id=user.id, idempotency_key=key).first()
        if existing is not None:
            return _replay(existing, operation, scope, fingerprint, response_type)
        raise IdempotencyConflictError("相同幂等请求仍在处理中")

    try:
        try:
            record = await IdempotencyRecord.create(
                user_id=user.id,
                operation=operation,
                scope=scope,
                idempotency_key=key,
                request_hash=fingerprint,
            )
        except IntegrityError:
            existing = await IdempotencyRecord.filter(user_id=user.id, idempotency_key=key).first()
            if existing is None:
                raise
            return _replay(existing, operation, scope, fingerprint, response_type)

        result = await callback()
        record.response_json = result.model_dump(mode="json")
        await record.save(update_fields=["response_json", "updated_at"])
        return result
    except Exception:
        if "record" in locals():
            await record.delete()
        raise
    finally:
        if lock_token:
            await _release_redis_lock(lock_key, lock_token)


def _redis_lock_key(user_id, operation: str, scope: str, key: str) -> str:
    material = f"{user_id}:{operation}:{scope}:{key}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return f"{app_settings.idempotency_redis_namespace}:lock:{digest}"


async def _try_acquire_redis_lock(lock_key: str) -> str | bool | None:
    """Return token when acquired, False when busy, None when Redis is unavailable."""
    if not app_settings.idempotency_redis_enabled or redis_module.redis_client is None:
        return None
    token = secrets.token_urlsafe(32)
    try:
        acquired = await redis_module.redis_client.set(
            lock_key,
            token,
            nx=True,
            ex=app_settings.idempotency_lock_ttl_seconds,
        )
    except Exception as exc:
        _logger.warning("idempotency redis lock unavailable: %s", type(exc).__name__)
        return None
    return token if acquired else False


async def _release_redis_lock(lock_key: str, token: str) -> None:
    if redis_module.redis_client is None:
        return
    try:
        await redis_module.redis_client.eval(_RELEASE_LOCK_SCRIPT, 1, lock_key, token)
    except Exception as exc:
        _logger.warning("idempotency redis lock release failed: %s", type(exc).__name__)


def _replay(record, operation: str, scope: str, fingerprint: str, response_type: type[T]) -> T:
    if record.operation != operation or record.scope != scope or record.request_hash != fingerprint:
        raise IdempotencyConflictError("Idempotency-Key 已用于不同的请求")
    if record.response_json is None:
        raise IdempotencyConflictError("相同幂等请求仍在处理中")
    return response_type.model_validate(record.response_json)


__all__ = ["IdempotencyConflictError", "execute_idempotently", "request_fingerprint"]
