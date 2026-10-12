from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


Theme = Literal["light", "dark", "system"]


class AppearanceSettingsUpdate(BaseModel):
    theme: Theme | None = Field(default=None, description="界面主题：light、dark 或 system。")
    revision: int | None = Field(default=None, ge=1, description="提交时的外观设置版本。")


class UserPreferencesUpdate(BaseModel):
    locale: str | None = Field(default=None, min_length=2, max_length=35, description="网站界面语言代码。")
    allow_member_search: bool | None = Field(default=None, description="是否允许被项目管理员搜索。")
    revision: int | None = Field(default=None, ge=1, description="提交时的用户偏好版本。")


class UserSettingsUpdateRequest(BaseModel):
    appearance: AppearanceSettingsUpdate | None = Field(default=None, description="用户外观设置的部分更新。")
    preferences: UserPreferencesUpdate | None = Field(default=None, description="用户偏好的部分更新。")


class AppearanceSettingsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    theme: Theme
    revision: int
    updated_at: datetime


class UserPreferencesResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    locale: str
    allow_member_search: bool
    revision: int
    updated_at: datetime


class UserSettingsResponse(BaseModel):
    appearance: AppearanceSettingsResponse
    preferences: UserPreferencesResponse
