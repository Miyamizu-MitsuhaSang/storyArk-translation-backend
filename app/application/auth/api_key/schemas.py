from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ApiKeyProvider = Literal[
    "openai",
    "anthropic",
    "google",
    "qwen",
    "deepseek",
    "kimi",
    "doubao",
    "zhipu",
    "minimax",
    "mistral",
    "groq",
    "custom",
]
ApiKeyStatus = Literal["active", "inactive"]


class CreateApiKeyRequest(BaseModel):
    provider: ApiKeyProvider = Field(description="AI 服务提供方。")
    label: str | None = Field(default=None, max_length=120, description="凭据显示名称。")
    secret: str = Field(min_length=1, max_length=4096, description="一次性写入的 API key；服务端不会在响应中返回。")


class UpdateApiKeyRequest(BaseModel):
    label: str | None = Field(default=None, max_length=120, description="新的凭据显示名称；传 null 可清空。")
    status: ApiKeyStatus | None = Field(default=None, description="凭据状态。")


class ApiKeyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    provider: str
    label: str | None
    masked_secret: str
    last_four: str
    status: ApiKeyStatus
    created_at: datetime
    last_used_at: datetime | None = None


class CreatedApiKeyResponse(BaseModel):
    id: UUID
    provider: str
    label: str | None
    masked_secret: str
    last_four: str
    status: ApiKeyStatus
    created_at: datetime


class ApiKeyPage(BaseModel):
    items: list[ApiKeyResponse]
    next_cursor: str | None
    total: int
