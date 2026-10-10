from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from tortoise.exceptions import IntegrityError

from ...core.config import app_settings
from ...models import AIProviderCredential, AIUsageRecord, ProjectMember, User
from ...repositories.usage import AIUsageRepository
from ...infrastructure.analytics.cache import NoopAnalyticsCache, RedisAnalyticsCache, build_usage_cache_key
from .schemas import (
    TranslationReportResponse,
    UsageAnalyticsQuery,
    UsageAnalyticsResponse,
    UsageByApiKey,
    UsageByModel,
    UsageTotals,
    UsageTrendBucket,
)


class UsageAnalyticsError(Exception):
    status_code = 400
    code = "USAGE_ANALYTICS_ERROR"

    def __init__(self, message: str, *, code: str | None = None, status_code: int | None = None):
        super().__init__(message)
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code


@dataclass(frozen=True, slots=True)
class UsageEvent:
    user_id: UUID | None
    project_id: UUID | None
    api_key_id: UUID | None
    provider: str
    model: str
    provider_request_id: str | None
    status: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    cost: Decimal = Decimal("0")
    currency: str = "USD"
    completed_at: datetime | None = None
    started_at: datetime | None = None
    latency_ms: int | None = None
    error_code: str | None = None

    def __post_init__(self):
        if self.status not in {"succeeded", "failed", "timeout"}:
            raise ValueError("status 无效")
        if any(value < 0 for value in (self.input_tokens, self.output_tokens, self.cached_input_tokens, self.reasoning_tokens, self.total_tokens)):
            raise ValueError("token 数不能为负数")
        if self.cost < 0:
            raise ValueError("cost 不能为负数")
        if self.completed_at is not None and self.completed_at.tzinfo is None:
            raise ValueError("completed_at 必须包含时区")


class UsageAnalyticsService:
    def __init__(self, *, repository: AIUsageRepository | None = None, cache: Any | None = None):
        self._repository = repository or AIUsageRepository()
        if cache is not None:
            self._cache = cache
        elif app_settings.analytics_cache_enabled:
            from ...core import redis as redis_module

            self._cache = RedisAnalyticsCache(redis_module.redis_client, namespace=app_settings.analytics_cache_namespace) if redis_module.redis_client else NoopAnalyticsCache()
        else:
            self._cache = NoopAnalyticsCache()

    async def record(self, event: UsageEvent) -> AIUsageRecord:
        completed = event.completed_at or datetime.now(timezone.utc)
        values = {
            "user_id": event.user_id,
            "project_id": event.project_id,
            "api_key_id": event.api_key_id,
            "provider": event.provider,
            "model": event.model,
            "provider_request_id": event.provider_request_id,
            "status": event.status,
            "input_tokens": event.input_tokens,
            "output_tokens": event.output_tokens,
            "cached_input_tokens": event.cached_input_tokens,
            "reasoning_tokens": event.reasoning_tokens,
            "total_tokens": event.total_tokens,
            "cost": event.cost,
            "currency": event.currency,
            "started_at": event.started_at,
            "completed_at": completed,
            "latency_ms": event.latency_ms,
            "error_code": event.error_code,
        }
        return await self._repository.create(**values)

    async def for_user(self, user: User, query: UsageAnalyticsQuery) -> UsageAnalyticsResponse:
        if query.api_key_id is not None and not await AIProviderCredential.filter(id=query.api_key_id, user_id=user.id).exists():
            raise UsageAnalyticsError("API key 不存在或不可见", code="ANALYTICS_KEY_NOT_FOUND", status_code=404)
        return await self._aggregate("user", user.id, query, user_id=user.id, project_id=query.project_id)

    async def for_project(self, user: User, project_id: UUID, query: UsageAnalyticsQuery) -> UsageAnalyticsResponse:
        membership = await ProjectMember.filter(project_id=project_id, user_id=user.id).first()
        if membership is None or membership.role not in {"owner", "manager", "reviewer"}:
            raise UsageAnalyticsError("项目不存在或当前用户无报表权限", code="ANALYTICS_PROJECT_NOT_FOUND", status_code=404)
        if query.api_key_id is not None and not await AIProviderCredential.filter(id=query.api_key_id, user_id=user.id).exists():
            raise UsageAnalyticsError("API key 不存在或不可见", code="ANALYTICS_KEY_NOT_FOUND", status_code=404)
        return await self._aggregate("project", project_id, query, project_id=project_id)

    async def translation_report(self, user: User, project_id: UUID, query: dict[str, Any] | None = None) -> TranslationReportResponse:
        membership = await ProjectMember.filter(project_id=project_id, user_id=user.id).first()
        if membership is None or membership.role not in {"owner", "manager", "reviewer"}:
            raise UsageAnalyticsError("项目不存在或当前用户无报表权限", code="ANALYTICS_PROJECT_NOT_FOUND", status_code=404)
        filters = query or {}
        return TranslationReportResponse(filters=filters, summary={"task_count": 0, "translated_words": 0}, daily=[])

    async def _aggregate(self, scope: str, scope_id: UUID, query: UsageAnalyticsQuery, *, user_id: UUID | None = None, project_id: UUID | None = None) -> UsageAnalyticsResponse:
        start, end = query.window()
        self._validate_window(start, end, query.granularity)
        key = build_usage_cache_key(scope, scope_id, query)
        try:
            cached = await self._cache.get(key)
            if cached:
                return UsageAnalyticsResponse.model_validate_json(cached)
        except Exception:
            pass
        db_query = AIUsageRecord.filter(completed_at__gte=start, completed_at__lte=end)
        if user_id is not None:
            db_query = db_query.filter(user_id=user_id)
        if project_id is not None:
            db_query = db_query.filter(project_id=project_id)
        if query.api_key_id is not None:
            db_query = db_query.filter(api_key_id=query.api_key_id)
        if query.provider:
            db_query = db_query.filter(provider=query.provider)
        if query.model:
            db_query = db_query.filter(model=query.model)
        records = await db_query.order_by("completed_at")
        response = await self._build_response(records, query, start, end)
        try:
            await self._cache.set(key, response.model_dump_json(), app_settings.analytics_cache_ttl_seconds)
        except Exception:
            pass
        return response

    @staticmethod
    def _validate_window(start: datetime, end: datetime, granularity: str) -> None:
        limit = timedelta(days=7 if granularity == "hour" else 31)
        if end - start > limit:
            raise UsageAnalyticsError("查询时间范围过大", code="ANALYTICS_RANGE_TOO_LARGE", status_code=422)

    async def _build_response(self, records: list[AIUsageRecord], query: UsageAnalyticsQuery, start: datetime, end: datetime) -> UsageAnalyticsResponse:
        try:
            tz = ZoneInfo(query.timezone)
        except ZoneInfoNotFoundError as exc:
            raise UsageAnalyticsError("timezone 无效", code="ANALYTICS_TIMEZONE_INVALID", status_code=422) from exc
        totals = self._totals(records)
        trend: dict[datetime, list[AIUsageRecord]] = {}
        local_start, local_end = start.astimezone(tz), end.astimezone(tz)
        cursor = self._bucket(local_start, query.granularity)
        last = self._bucket(local_end, query.granularity)
        while cursor <= last:
            trend[cursor] = []
            cursor = cursor + (timedelta(hours=1) if query.granularity == "hour" else timedelta(days=1))
        for record in records:
            trend.setdefault(self._bucket(record.completed_at.astimezone(tz), query.granularity), []).append(record)
        trend_items = [self._trend_bucket(bucket, rows) for bucket, rows in sorted(trend.items())]
        key_ids = {record.api_key_id for record in records if record.api_key_id is not None}
        keys = {row.id: row for row in await AIProviderCredential.filter(id__in=list(key_ids))} if key_ids else {}
        by_key: dict[UUID | None, list[AIUsageRecord]] = {}
        for record in records:
            by_key.setdefault(record.api_key_id, []).append(record)
        by_api_key = []
        for key_id, rows in by_key.items():
            first = rows[0]
            credential = keys.get(key_id)
            by_api_key.append(UsageByApiKey(api_key_id=key_id, provider=first.provider, label=credential.label if credential else None, masked_secret=(f"{credential.key_prefix or ''}{'•' * 8}{credential.key_hint or ''}" if credential else None), calls=len(rows), input_tokens=sum(r.input_tokens for r in rows), output_tokens=sum(r.output_tokens for r in rows), total_tokens=sum(r.total_tokens for r in rows), cost=self._cost(rows)))
        grouped: dict[tuple[str, str], list[AIUsageRecord]] = {}
        for record in records:
            grouped.setdefault((record.provider, record.model), []).append(record)
        total_calls = len(records)
        by_model = [UsageByModel(provider=provider, model=model, calls=len(rows), input_tokens=sum(r.input_tokens for r in rows), output_tokens=sum(r.output_tokens for r in rows), total_tokens=sum(r.total_tokens for r in rows), cost=self._cost(rows), share=(len(rows) / total_calls if total_calls else 0.0)) for (provider, model), rows in sorted(grouped.items())]
        return UsageAnalyticsResponse(range={"from": start.isoformat(), "to": end.isoformat(), "timezone": query.timezone, "granularity": query.granularity}, totals=totals, trend=trend_items, by_api_key=by_api_key, by_model=by_model)

    @staticmethod
    def _bucket(value: datetime, granularity: str) -> datetime:
        return value.replace(minute=0, second=0, microsecond=0) if granularity == "hour" else value.replace(hour=0, minute=0, second=0, microsecond=0)

    @classmethod
    def _cost(cls, rows: list[AIUsageRecord]) -> str:
        return f"{sum((Decimal(str(row.cost or 0)) for row in rows), Decimal('0')):.8f}"

    @classmethod
    def _totals(cls, rows: list[AIUsageRecord]) -> UsageTotals:
        return UsageTotals(call_count=len(rows), success_count=sum(r.status == "succeeded" for r in rows), failure_count=sum(r.status != "succeeded" for r in rows), input_tokens=sum(r.input_tokens for r in rows), output_tokens=sum(r.output_tokens for r in rows), cached_input_tokens=sum(r.cached_input_tokens for r in rows), reasoning_tokens=sum(r.reasoning_tokens for r in rows), total_tokens=sum(r.total_tokens for r in rows), cost=cls._cost(rows))

    @classmethod
    def _trend_bucket(cls, bucket: datetime, rows: list[AIUsageRecord]) -> UsageTrendBucket:
        return UsageTrendBucket(bucket_start=bucket, calls=len(rows), success_calls=sum(r.status == "succeeded" for r in rows), failed_calls=sum(r.status != "succeeded" for r in rows), input_tokens=sum(r.input_tokens for r in rows), output_tokens=sum(r.output_tokens for r in rows), total_tokens=sum(r.total_tokens for r in rows), cost=cls._cost(rows))


__all__ = ["UsageAnalyticsError", "UsageAnalyticsService", "UsageEvent"]
