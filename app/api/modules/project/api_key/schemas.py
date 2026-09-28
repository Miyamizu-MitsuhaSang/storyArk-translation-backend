from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


ProjectApiKeyStatus = Literal["active", "inactive"]


class CreateProjectApiKeyRequest(BaseModel):
    api_key_id: UUID = Field(description="当前用户拥有的用户级 API key ID。")
    is_default: bool = Field(default=False, description="是否设为项目默认 API key。")


class UpdateProjectApiKeyRequest(BaseModel):
    status: ProjectApiKeyStatus | None = Field(default=None, description="项目绑定状态。")
    is_default: bool | None = Field(default=None, description="是否设为项目默认 API key。")


class ProjectApiKeyResponse(BaseModel):
    id: UUID
    api_key_id: UUID
    provider: str
    label: str | None
    masked_secret: str
    status: ProjectApiKeyStatus
    is_default: bool
    created_at: datetime


class ProjectApiKeyPage(BaseModel):
    items: list[ProjectApiKeyResponse]
    next_cursor: str | None
    total: int
