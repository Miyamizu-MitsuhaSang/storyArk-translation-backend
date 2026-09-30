from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


WorldviewStatus = Literal["draft", "active", "archived"]
WorldviewEntryType = Literal[
    "character",
    "faction",
    "location",
    "item",
    "skill",
    "quest",
    "creature",
    "system",
    "lore",
    "rule",
    "style_guide",
]


class WorldviewUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160, description="世界观文档名称。")
    style_guide: str | None = Field(default=None, description="项目级翻译风格指南和全局规则；传 null 可清空。")
    default_tone: str | None = Field(default=None, max_length=80, description="项目文本的默认语气或风格标签。")
    version_note: str | None = Field(default=None, description="当前世界观版本的变更摘要。")
    status: WorldviewStatus | None = Field(default=None, description="世界观状态。")


class WorldviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(description="世界观 ID。")
    project_id: UUID = Field(description="所属项目 ID。")
    name: str = Field(description="世界观文档名称。")
    style_guide: str | None = Field(description="项目级翻译风格指南和全局规则。")
    default_tone: str | None = Field(description="项目文本的默认语气或风格标签。")
    version_note: str | None = Field(description="当前世界观版本的变更摘要。")
    status: WorldviewStatus = Field(description="世界观状态。")
    version: int = Field(description="世界观当前版本号。")
    created_at: datetime = Field(description="世界观创建时间。")
    updated_at: datetime = Field(description="世界观最后更新时间。")


class WorldviewEntryCreateRequest(BaseModel):
    type: WorldviewEntryType = Field(description="条目类型。")
    name: str = Field(min_length=1, max_length=160, description="条目的规范名称。")
    aliases: list[str] = Field(default_factory=list, description="条目的别名列表。")
    description: str | None = Field(default=None, description="条目的背景、定义或使用说明。")
    attributes: dict[str, Any] = Field(default_factory=dict, description="条目的结构化属性。")
    language_variants: dict[str, str] = Field(default_factory=dict, description="按语言标签记录的官方名称或表达。")
    tags: list[str] = Field(default_factory=list, description="用于筛选和分类的标签列表。")
    status: WorldviewStatus = Field(default="active", description="条目状态。")


class WorldviewEntryUpdateRequest(BaseModel):
    type: WorldviewEntryType | None = Field(default=None, description="新的条目类型。")
    name: str | None = Field(default=None, min_length=1, max_length=160, description="新的规范名称。")
    aliases: list[str] | None = Field(default=None, description="新的别名列表。")
    description: str | None = Field(default=None, description="新的条目说明；传 null 可清空。")
    attributes: dict[str, Any] | None = Field(default=None, description="新的结构化属性。")
    language_variants: dict[str, str] | None = Field(default=None, description="新的语言变体。")
    tags: list[str] | None = Field(default=None, description="新的标签列表。")
    status: WorldviewStatus | None = Field(default=None, description="新的条目状态。")
    change_note: str | None = Field(default=None, description="本次版本变更说明。")


class WorldviewEntryRevisionSummary(BaseModel):
    id: UUID = Field(description="版本快照 ID。")
    version: int = Field(description="条目版本号。")
    changed_by_id: UUID | None = Field(description="产生该版本的用户 ID。")
    change_note: str | None = Field(description="版本变更说明。")
    changed_at: datetime = Field(description="版本生成时间。")


class WorldviewEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(description="世界观条目 ID。")
    entry_key: str = Field(description="世界观内稳定的条目业务键。")
    type: WorldviewEntryType = Field(description="条目类型。")
    name: str = Field(description="条目的规范名称。")
    aliases: list[str] = Field(description="条目的别名列表。")
    description: str | None = Field(description="条目的背景、定义或使用说明。")
    attributes: dict[str, Any] = Field(description="条目的结构化属性。")
    language_variants: dict[str, str] = Field(description="按语言标签记录的官方名称或表达。")
    tags: list[str] = Field(description="用于筛选和分类的标签列表。")
    status: WorldviewStatus = Field(description="条目状态。")
    version: int = Field(description="条目当前版本号。")
    deleted_at: datetime | None = Field(description="软删除时间；未删除时为 null。")
    created_at: datetime = Field(description="条目创建时间。")
    updated_at: datetime = Field(description="条目最后更新时间。")
    history: list[WorldviewEntryRevisionSummary] = Field(default_factory=list, description="版本历史摘要。")


class WorldviewEntryPage(BaseModel):
    items: list[WorldviewEntryResponse] = Field(description="世界观条目列表。")
    next_cursor: str | None = Field(description="下一页游标；没有下一页时为 null。")
    total: int = Field(description="符合筛选条件的条目总数。")
