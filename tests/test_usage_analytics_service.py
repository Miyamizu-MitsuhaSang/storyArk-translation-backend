from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from tortoise import Tortoise

from translation_backend.app.application.analytics.schemas import UsageAnalyticsQuery
from translation_backend.app.application.analytics.service import UsageAnalyticsError, UsageAnalyticsService, UsageEvent
from translation_backend.app.infrastructure.analytics.cache import build_usage_cache_key
from translation_backend.app.models import AIUsageRecord, Project, ProjectMember, User


def run_db_test(coro):
    async def scenario():
        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["translation_backend.app.models"]})
        await Tortoise.generate_schemas()
        try:
            return await coro()
        finally:
            await Tortoise.close_connections()

    return asyncio.run(scenario())


async def _setup():
    user = await User.create(username=f"analytics-{uuid4().hex}", email=f"analytics-{uuid4().hex}@example.com", password_hash="hash", display_name="Analytics")
    other = await User.create(username=f"analytics-other-{uuid4().hex}", email=f"analytics-other-{uuid4().hex}@example.com", password_hash="hash", display_name="Other")
    project = await Project.create(key=f"analytics-{uuid4().hex}", name="Analytics", created_by=user)
    other_project = await Project.create(key=f"analytics-other-{uuid4().hex}", name="Other analytics", created_by=other)
    await ProjectMember.create(project=project, user=user, role="owner")
    await ProjectMember.create(project=project, user=other, role="viewer")
    return user, other, project, other_project


def _event(*, user_id, project_id, request_id, completed_at, status="succeeded", api_key_id=None):
    return UsageEvent(
        user_id=user_id,
        project_id=project_id,
        api_key_id=api_key_id,
        provider="openai",
        model="gpt-test",
        provider_request_id=request_id,
        status=status,
        input_tokens=10,
        output_tokens=5,
        total_tokens=15,
        cost=Decimal("1.25000000"),
        completed_at=completed_at,
    )


def test_usage_record_is_idempotent_and_rejects_negative_values():
    async def scenario():
        user, _, project, _ = await _setup()
        service = UsageAnalyticsService()
        completed = datetime(2026, 10, 9, 2, tzinfo=timezone.utc)
        first = await service.record(_event(user_id=user.id, project_id=project.id, request_id="req-1", completed_at=completed))
        replay = await service.record(_event(user_id=user.id, project_id=project.id, request_id="req-1", completed_at=completed))
        assert replay.id == first.id
        assert await AIUsageRecord.all().count() == 1
        with pytest.raises(ValueError):
            await service.record(replace(_event(user_id=user.id, project_id=project.id, request_id="req-2", completed_at=completed), input_tokens=-1))

    run_db_test(scenario)


def test_user_analytics_fills_empty_buckets_and_isolates_projects():
    async def scenario():
        user, other, project, other_project = await _setup()
        service = UsageAnalyticsService()
        start = datetime(2026, 10, 1, tzinfo=timezone.utc)
        await service.record(_event(user_id=user.id, project_id=project.id, request_id="req-1", completed_at=start))
        await service.record(_event(user_id=other.id, project_id=other_project.id, request_id="req-2", completed_at=start))
        response = await service.for_user(user, UsageAnalyticsQuery(from_=start, to=start + timedelta(days=2), timezone="UTC", granularity="day"))
        assert len(response.trend) == 3
        assert response.trend[0].calls == 1
        assert response.trend[1].calls == 0
        assert response.totals.call_count == 1
        assert response.totals.cost == "1.25000000"

    run_db_test(scenario)


def test_analytics_rejects_invalid_windows_and_project_access():
    async def scenario():
        user, other, project, _ = await _setup()
        service = UsageAnalyticsService()
        with pytest.raises(UsageAnalyticsError) as raised:
            await service.for_user(user, UsageAnalyticsQuery(from_=datetime(2026, 1, 1, tzinfo=timezone.utc), to=datetime(2026, 2, 5, tzinfo=timezone.utc), granularity="day"))
        assert raised.value.code == "ANALYTICS_RANGE_TOO_LARGE"
        with pytest.raises(UsageAnalyticsError):
            await service.for_project(other, project.id, UsageAnalyticsQuery())

    run_db_test(scenario)


def test_usage_cache_key_contains_scope_and_all_filters():
    query = UsageAnalyticsQuery(provider="openai", model="gpt-test", timezone="Asia/Shanghai", granularity="hour")
    key = build_usage_cache_key("user", uuid4(), query)
    assert "analytics" in key
    assert "Asia/Shanghai" in key
    assert "gpt-test" in key
