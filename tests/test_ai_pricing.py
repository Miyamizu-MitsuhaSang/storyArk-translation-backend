import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from tortoise import Tortoise

from translation_backend.app.application.analytics.schemas import UsageAnalyticsQuery
from translation_backend.app.application.analytics.service import UsageAnalyticsService, UsageEvent
from translation_backend.app.infrastructure.ai_provider.pricing import (
    TEST_PRICING_VERSION,
    calculate_token_cost,
    get_token_pricing,
)
from translation_backend.app.models import Project, ProjectMember, User


def run_db_test(coro):
    async def scenario():
        await Tortoise.init(
            db_url="sqlite://:memory:",
            modules={"models": ["translation_backend.app.models"]},
        )
        await Tortoise.generate_schemas()
        try:
            return await coro()
        finally:
            await Tortoise.close_connections()

    return asyncio.run(scenario())


def test_test_pricing_uses_cached_input_rate_without_double_counting():
    cost = calculate_token_cost(
        "openai",
        "gpt-4o-mini",
        input_tokens=2_400,
        output_tokens=650,
        cached_input_tokens=800,
        reasoning_tokens=0,
    )

    assert cost == Decimal("0.00069000")
    assert get_token_pricing("openai", "gpt-4o-mini").version == TEST_PRICING_VERSION


def test_unknown_model_uses_explicit_test_default_pricing():
    assert get_token_pricing("custom", "unknown-model").name == "test-default"
    assert calculate_token_cost(
        "custom",
        "unknown-model",
        input_tokens=1,
        output_tokens=1,
        cached_input_tokens=10,
    ) == Decimal("0.00000150")


def test_usage_event_calculates_cost_when_cost_is_omitted():
    async def scenario():
        user = await User.create(
            username=f"pricing-{uuid4().hex}",
            email=f"pricing-{uuid4().hex}@example.com",
            password_hash="hash",
            display_name="Pricing",
        )
        project = await Project.create(
            key=f"pricing-{uuid4().hex}",
            name="Pricing",
            created_by=user,
        )
        await ProjectMember.create(project=project, user=user, role="owner")
        service = UsageAnalyticsService()
        record = await service.record(
            UsageEvent(
                user_id=user.id,
                project_id=project.id,
                api_key_id=None,
                provider="deepseek",
                model="deepseek-chat",
                provider_request_id="pricing-request-1",
                status="succeeded",
                input_tokens=1_000,
                output_tokens=500,
                total_tokens=1_500,
                cost=None,
                completed_at=datetime(2026, 10, 12, tzinfo=timezone.utc),
            )
        )

        assert record.cost == Decimal("0.00082000")
        assert record.pricing_version == TEST_PRICING_VERSION

    run_db_test(scenario)
