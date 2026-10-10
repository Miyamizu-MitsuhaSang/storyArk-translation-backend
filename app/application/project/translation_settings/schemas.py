from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ....core.schemas import CursorPage


TranslationRuleType = Literal["general", "category"]


class TranslationSettingsResponse(BaseModel):
    project_id: UUID
    revision: int = Field(ge=1)
    worldview: str | None
    tone: str | None
    updated_at: datetime


class SettingsUpdateRequest(BaseModel):
    revision: int | None = Field(default=None, ge=1)
    worldview: str | None = None
    tone: str | None = Field(default=None, max_length=80)


class TranslationRoleCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = None
    detailed_injection: str | None = None
    sort_order: int = 0


RoleCreateRequest = TranslationRoleCreateRequest


class TranslationRoleUpdateRequest(BaseModel):
    revision: int | None = Field(default=None, ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = None
    detailed_injection: str | None = None
    sort_order: int | None = None


class TranslationRoleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    name: str
    description: str | None
    detailed_injection: str | None
    sort_order: int
    revision: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime


class TranslationRolePage(CursorPage[TranslationRoleResponse]):
    pass


class TranslationRuleCreateRequest(BaseModel):
    type: TranslationRuleType
    name: str = Field(min_length=1, max_length=160)
    text: str = Field(min_length=1)
    category: str | None = Field(default=None, max_length=80)
    enabled: bool = True

    @model_validator(mode="after")
    def validate_category(self) -> "TranslationRuleCreateRequest":
        if self.type == "category" and not self.category:
            raise ValueError("category 类型规则必须提供 category")
        if self.type == "general":
            self.category = None
        return self


class RuleCreateRequest(TranslationRuleCreateRequest):
    pass


class TranslationRuleUpdateRequest(BaseModel):
    revision: int | None = Field(default=None, ge=1)
    type: TranslationRuleType | None = None
    name: str | None = Field(default=None, min_length=1, max_length=160)
    text: str | None = Field(default=None, min_length=1)
    category: str | None = Field(default=None, max_length=80)
    enabled: bool | None = None


class TranslationRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    type: TranslationRuleType
    name: str
    text: str
    category: str | None
    enabled: bool
    revision: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime


class TranslationRulePage(CursorPage[TranslationRuleResponse]):
    pass


class CultureRuleCreateRequest(BaseModel):
    language: str = Field(min_length=1, max_length=16)
    name: str = Field(min_length=1, max_length=160)
    text: str = Field(min_length=1)
    category: str | None = Field(default=None, max_length=80)


class CultureRuleUpdateRequest(BaseModel):
    revision: int | None = Field(default=None, ge=1)
    language: str | None = Field(default=None, min_length=1, max_length=16)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    text: str | None = Field(default=None, min_length=1)
    category: str | None = Field(default=None, max_length=80)


class CultureRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    language: str
    name: str
    text: str
    category: str | None
    revision: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime


class CultureRulePage(CursorPage[CultureRuleResponse]):
    pass


class TranslationTemplateResponse(BaseModel):
    id: str
    name: str
    description: str


class TranslationTemplatePage(BaseModel):
    items: list[TranslationTemplateResponse]


class SettingsInitializeRequest(BaseModel):
    template_id: str = Field(min_length=1, max_length=64)
    confirm_replace: bool = False
    expected_revision: int | None = Field(default=None, ge=1)


TranslationSettingsUpdateRequest = SettingsUpdateRequest
TranslationSettingsInitializeRequest = SettingsInitializeRequest


__all__ = [
    "CultureRuleCreateRequest",
    "CultureRulePage",
    "CultureRuleResponse",
    "CultureRuleUpdateRequest",
    "RuleCreateRequest",
    "RoleCreateRequest",
    "SettingsInitializeRequest",
    "SettingsUpdateRequest",
    "TranslationRoleCreateRequest",
    "TranslationRolePage",
    "TranslationRoleResponse",
    "TranslationRoleUpdateRequest",
    "TranslationRuleCreateRequest",
    "TranslationRulePage",
    "TranslationRuleResponse",
    "TranslationRuleUpdateRequest",
    "TranslationSettingsResponse",
    "TranslationSettingsUpdateRequest",
    "TranslationSettingsInitializeRequest",
    "TranslationTemplatePage",
    "TranslationTemplateResponse",
]
