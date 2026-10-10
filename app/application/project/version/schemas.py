"""HTTP and application contracts for project business versions."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ....core.schemas import CursorPage


VersionSort = Literal["version_number", "created_at", "name"]


def _normalize_name(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _unique_languages(value: list[str]) -> list[str]:
    normalized = [item.strip() for item in value]
    if any(not item for item in normalized):
        raise ValueError("语言标签不能为空")
    if len(set(normalized)) != len(normalized):
        raise ValueError("目标语言不能重复")
    return normalized


class VersionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=160, description="可选的用户自定义展示名称。")
    description: str | None = Field(default=None, description="版本用途或交付说明。")
    source_language: str | None = Field(default=None, max_length=16, description="可选的版本源语言。")
    target_languages: list[str] = Field(default_factory=list, description="可选的版本目标语言列表。")

    _normalize_display_name = field_validator("name", mode="before")(_normalize_name)
    _validate_target_languages = field_validator("target_languages")(_unique_languages)


class VersionListQuery(BaseModel):
    page_size: int = Field(default=20, ge=1, le=100, description="每页返回的版本数量。")
    cursor: str | None = Field(default=None, description="不透明分页游标。")
    q: str | None = Field(default=None, max_length=160, description="按版本展示名称搜索。")
    sort: VersionSort = Field(default="version_number", description="排序字段，默认按系统版本号倒序。")


class VersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    version_number: int = Field(ge=1)
    name: str | None
    description: str | None
    source_language: str | None
    target_languages: list[str]
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime


class VersionPage(CursorPage[VersionResponse]):
    pass


class VersionFileResponse(BaseModel):
    id: UUID
    name: str
    source_language: str
    format: str
    updated_at: datetime
    size_bytes: int = Field(ge=0)


class FilePage(CursorPage[VersionFileResponse]):
    pass


__all__ = [
    "FilePage",
    "VersionCreateRequest",
    "VersionFileResponse",
    "VersionListQuery",
    "VersionPage",
    "VersionResponse",
]
