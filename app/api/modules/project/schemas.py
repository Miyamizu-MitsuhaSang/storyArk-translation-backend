from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

ProjectStatus = Literal["draft", "active", "archived"]
ProjectRole = Literal["owner", "manager", "translator", "reviewer", "viewer"]


def _unique_languages(value: list[str]) -> list[str]:
    normalized = [item.strip() for item in value]
    if any(not item for item in normalized):
        raise ValueError("language tags must not be empty")
    if len(set(normalized)) != len(normalized):
        raise ValueError("language tags must be unique")
    return normalized


class LanguagePairRef(BaseModel):
    source: str = Field(min_length=1, max_length=16, description="源语言 BCP 47 标签，例如 zh-CN。")
    target: str = Field(min_length=1, max_length=16, description="目标语言 BCP 47 标签，例如 en-US。")


class CreateProjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160, description="项目名称。")
    description: str | None = Field(default=None, description="项目用途和背景说明。")
    source_languages: list[str] = Field(min_length=1, description="项目支持的源语言标签。")
    target_languages: list[str] = Field(min_length=1, description="项目支持的目标语言标签。")

    _source_languages_unique = field_validator("source_languages")(_unique_languages)
    _target_languages_unique = field_validator("target_languages")(_unique_languages)


class UpdateProjectRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160, description="新的项目名称。")
    description: str | None = Field(default=None, description="新的项目描述；传 null 可清空。")
    status: ProjectStatus | None = Field(default=None, description="项目状态。")
    default_language_pair: LanguagePairRef | None = Field(
        default=None,
        description="新的默认语言对，必须已经存在于项目中。",
    )


class AddMemberRequest(BaseModel):
    user_id: UUID = Field(description="要加入项目的用户 ID。")
    role: ProjectRole = Field(default="translator", description="项目角色。")


class UpdateMemberRequest(BaseModel):
    role: ProjectRole = Field(description="新的项目角色。")


class LanguagePairRequest(BaseModel):
    source_language: str = Field(min_length=1, max_length=16, description="源语言 BCP 47 标签。")
    target_language: str = Field(min_length=1, max_length=16, description="目标语言 BCP 47 标签。")
    is_default: bool = Field(default=False, description="是否设为项目默认语言对。")


class ProjectListQuery(BaseModel):
    page_size: int = Field(default=20, ge=1, le=100, description="每页返回数量。")
    cursor: str | None = Field(default=None, description="不透明分页游标。")
    q: str | None = Field(default=None, max_length=160, description="按项目名称或业务 key 搜索。")
    status: ProjectStatus | None = Field(default=None, description="按项目状态筛选。")
    sort: Literal["created_at", "updated_at", "name"] = Field(
        default="created_at",
        description="排序字段；默认按创建时间倒序。",
    )


class MemberListQuery(BaseModel):
    page_size: int = Field(default=20, ge=1, le=100, description="每页返回数量。")
    cursor: str | None = Field(default=None, description="不透明分页游标。")
    q: str | None = Field(default=None, max_length=160, description="按用户名、邮箱或显示名称搜索。")
    role: ProjectRole | None = Field(default=None, description="按项目角色筛选。")
    sort: Literal["created_at", "updated_at", "username"] = Field(
        default="created_at",
        description="排序字段；默认按加入时间倒序。",
    )


class LanguagePairListQuery(BaseModel):
    page_size: int = Field(default=20, ge=1, le=100, description="每页返回数量。")
    cursor: str | None = Field(default=None, description="不透明分页游标。")


class UserSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(description="用户 ID。")
    username: str = Field(description="用户登录名。")
    email: str = Field(description="用户邮箱。")
    display_name: str = Field(description="用户显示名称。")


class ProjectMemberResponse(BaseModel):
    user: UserSummary = Field(description="成员用户摘要。")
    role: ProjectRole = Field(description="成员在项目中的角色。")
    created_at: datetime = Field(description="成员加入项目的时间。")


class LanguagePairResponse(BaseModel):
    id: UUID = Field(description="语言对记录 ID。")
    source_language: str = Field(description="源语言标签。")
    target_language: str = Field(description="目标语言标签。")
    is_default: bool = Field(description="是否为项目默认语言对。")
    is_active: bool = Field(description="语言对是否启用。")
    created_at: datetime = Field(description="语言对创建时间。")


class ProjectListItem(BaseModel):
    id: UUID = Field(description="项目 ID。")
    key: str = Field(description="项目业务 key。")
    name: str = Field(description="项目名称。")
    description: str | None = Field(description="项目描述。")
    status: ProjectStatus = Field(description="项目状态。")
    role: ProjectRole = Field(description="当前用户在项目中的角色。")
    updated_at: datetime = Field(description="项目最后更新时间。")


class ProjectResponse(ProjectListItem):
    source_languages: list[str] = Field(description="项目源语言列表。")
    target_languages: list[str] = Field(description="项目目标语言列表。")
    default_language_pair: LanguagePairRef | None = Field(description="项目默认语言对。")
    member_count: int = Field(description="项目成员总数。")
    language_pairs: list[LanguagePairResponse] = Field(description="项目语言对列表。")


class ProjectPage(BaseModel):
    items: list[ProjectListItem] = Field(description="项目列表。")
    next_cursor: str | None = Field(description="下一页游标；没有下一页时为 null。")
    total: int = Field(description="符合条件的项目总数。")


class MemberPage(BaseModel):
    items: list[ProjectMemberResponse] = Field(description="项目成员列表。")
    next_cursor: str | None = Field(description="下一页游标；没有下一页时为 null。")
    total: int = Field(description="符合条件的成员总数。")


class LanguagePairPage(BaseModel):
    items: list[LanguagePairResponse] = Field(description="项目语言对列表。")
    next_cursor: str | None = Field(description="下一页游标；没有下一页时为 null。")
    total: int = Field(description="项目语言对总数。")
