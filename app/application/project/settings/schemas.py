from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ProjectSettingsUpdateRequest(BaseModel):
    default_source_language: str | None = Field(default=None, min_length=1, max_length=16)
    default_target_language: str | None = Field(default=None, min_length=1, max_length=16)
    terminology_enabled: bool | None = None
    translation_memory_enabled: bool | None = None
    default_model: str | None = Field(default=None, min_length=1, max_length=160)
    quality_threshold: float | None = Field(default=None, ge=0, le=1)
    revision: int | None = Field(default=None, ge=1)


class ProjectSettingsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    project_id: UUID
    default_source_language: str | None
    default_target_language: str | None
    terminology_enabled: bool
    translation_memory_enabled: bool
    default_model: str | None
    quality_threshold: float
    revision: int
    updated_at: datetime
