from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Granularity = Literal["day", "hour"]


class UsageAnalyticsQuery(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    range: Literal["7d", "30d"] | None = "7d"
    from_: datetime | None = Field(default=None, alias="from")
    to: datetime | None = None
    timezone: str = "UTC"
    granularity: Granularity = "day"
    api_key_id: UUID | None = None
    project_id: UUID | None = None
    provider: str | None = Field(default=None, max_length=32)
    model: str | None = Field(default=None, max_length=120)

    @field_validator("from_", "to")
    @classmethod
    def ensure_aware(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("时间必须包含时区")
        return value

    @model_validator(mode="after")
    def validate_window(self) -> "UsageAnalyticsQuery":
        if (self.from_ is None) != (self.to is None):
            raise ValueError("from 和 to 必须同时提供")
        if self.from_ is not None and self.to is not None and self.from_ > self.to:
            raise ValueError("from 不能晚于 to")
        return self

    def window(self) -> tuple[datetime, datetime]:
        if self.from_ is not None and self.to is not None:
            return self.from_.astimezone(timezone.utc), self.to.astimezone(timezone.utc)
        end = datetime.now(timezone.utc)
        days = 30 if self.range == "30d" else 7
        return end - timedelta(days=days), end


class UsageTotals(BaseModel):
    call_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    cost: str = "0.00000000"
    currency: str = "USD"


class UsageTrendBucket(BaseModel):
    bucket_start: datetime
    calls: int = 0
    success_calls: int = 0
    failed_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost: str = "0.00000000"
    currency: str = "USD"


class UsageByApiKey(BaseModel):
    api_key_id: UUID | None
    provider: str
    label: str | None = None
    masked_secret: str | None = None
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost: str = "0.00000000"
    currency: str = "USD"


class UsageByModel(BaseModel):
    provider: str
    model: str
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost: str = "0.00000000"
    share: float = 0.0
    currency: str = "USD"


class UsageAnalyticsResponse(BaseModel):
    range: dict[str, object]
    totals: UsageTotals
    trend: list[UsageTrendBucket]
    by_api_key: list[UsageByApiKey]
    by_model: list[UsageByModel]


class TranslationReportResponse(BaseModel):
    filters: dict[str, object]
    summary: dict[str, int]
    daily: list[dict[str, object]]


__all__ = ["TranslationReportResponse", "UsageAnalyticsQuery", "UsageAnalyticsResponse", "UsageTotals"]
