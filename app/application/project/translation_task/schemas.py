from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from ....core.schemas import CursorPage
from ....infrastructure.spreadsheet.contracts import TableColumn

TaskStatus = Literal["queued", "translating", "review", "completed", "failed", "cancelled"]


class TranslationTaskCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    source_language: str = Field(min_length=1, max_length=16)
    target_languages: list[str] = Field(min_length=1)
    file_ids: list[UUID] = Field(min_length=1)
    version_id: UUID | None = None
    api_key_id: UUID
    model_type: str | None = Field(default=None, max_length=64)
    model: str | None = Field(default=None, max_length=128)
    source_column: str | None = Field(default=None, max_length=128)
    target_columns: list[TableColumn] | None = Field(default=None, max_length=32)
    sheet_names: list[str] | None = None
    overwrite: bool = False

    @field_validator("name", "source_language", mode="before")
    @classmethod
    def strip_text(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("不能为空")
        return value.strip()

    @field_validator("target_languages")
    @classmethod
    def validate_targets(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError("目标语言不能为空")
        if len(set(normalized)) != len(normalized):
            raise ValueError("目标语言不能重复")
        return normalized

    @field_validator("file_ids")
    @classmethod
    def validate_files(cls, value: list[UUID]) -> list[UUID]:
        if len(set(value)) != len(value):
            raise ValueError("文件不能重复")
        return value

    @model_validator(mode="after")
    def validate_source_target(self) -> "TranslationTaskCreateRequest":
        if self.source_language in self.target_languages:
            raise ValueError("目标语言不能等于源语言")
        spreadsheet_fields = (self.model_type, self.model, self.source_column, self.target_columns)
        if any(value is not None for value in spreadsheet_fields):
            if not all(value is not None for value in spreadsheet_fields):
                raise ValueError("表格翻译任务必须同时提供 model_type、model、source_column 和 target_columns")
            target_languages = [item.language for item in self.target_columns or []]
            if target_languages != self.target_languages:
                raise ValueError("target_columns 必须与 target_languages 一一对应")
        return self


class TranslationTaskApiKeyResponse(BaseModel):
    id: UUID
    provider: str
    label: str | None
    masked_secret: str


class TranslationTaskOutputResponse(BaseModel):
    file_name: str | None
    size_bytes: int | None


class TranslationTaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    name: str
    source_language: str
    target_languages: list[str]
    file_ids: list[UUID]
    version_id: UUID | None
    api_key: TranslationTaskApiKeyResponse
    model_type: str | None
    model: str | None
    source_column: str | None
    target_columns: list[TableColumn] | None
    sheet_names: list[str] | None
    overwrite: bool
    job_id: UUID | None
    output: TranslationTaskOutputResponse | None
    status: TaskStatus
    progress: int = Field(ge=0, le=100)
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class TranslationTaskPage(CursorPage[TranslationTaskResponse]):
    pass


__all__ = ["TableColumn", "TaskStatus", "TranslationTaskApiKeyResponse", "TranslationTaskCreateRequest", "TranslationTaskOutputResponse", "TranslationTaskPage", "TranslationTaskResponse"]
