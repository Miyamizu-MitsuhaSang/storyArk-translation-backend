"""Persistence operations for immutable AI usage records."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID
from tortoise.exceptions import IntegrityError

from ..models import AIUsageRecord


class AIUsageRepository:
    async def create(self, **values) -> AIUsageRecord:
        provider = values.get("provider")
        provider_request_id = values.get("provider_request_id")
        if provider and provider_request_id:
            existing = await self.find_by_provider_request_id(provider, provider_request_id)
            if existing is not None:
                return existing
        try:
            return await AIUsageRecord.create(**values)
        except IntegrityError:
            if provider and provider_request_id:
                existing = await self.find_by_provider_request_id(provider, provider_request_id)
                if existing is not None:
                    return existing
            raise

    async def find_by_provider_request_id(
        self,
        provider: str,
        provider_request_id: str,
    ) -> AIUsageRecord | None:
        return await AIUsageRecord.filter(
            provider=provider,
            provider_request_id=provider_request_id,
        ).first()

    async def list_for_user(
        self,
        user_id: UUID | str,
        *,
        completed_after: datetime | None = None,
        completed_before: datetime | None = None,
    ) -> list[AIUsageRecord]:
        query = AIUsageRecord.filter(user_id=user_id)
        if completed_after is not None:
            query = query.filter(completed_at__gte=completed_after)
        if completed_before is not None:
            query = query.filter(completed_at__lt=completed_before)
        return await query.order_by("-completed_at")

    async def list_for_project(
        self,
        project_id: UUID | str,
        *,
        completed_after: datetime | None = None,
        completed_before: datetime | None = None,
    ) -> list[AIUsageRecord]:
        query = AIUsageRecord.filter(project_id=project_id)
        if completed_after is not None:
            query = query.filter(completed_at__gte=completed_after)
        if completed_before is not None:
            query = query.filter(completed_at__lt=completed_before)
        return await query.order_by("-completed_at")


__all__ = ["AIUsageRepository"]
