from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TranslationMemoryLibraryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    scope: Literal["user", "platform"]
    name: str
    description: str | None
    status: str
    owner_user_id: UUID | None
    created_at: datetime
    updated_at: datetime
    content_version: int = 1


class TranslationMemoryLibraryUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = None
    status: Literal["active", "archived"] | None = None


class TranslationMemoryLibraryPage(BaseModel):
    items: list[TranslationMemoryLibraryResponse]
    next_cursor: str | None
    total: int


class TranslationMemoryEntryCreateRequest(BaseModel):
    source_language: str = Field(min_length=1, max_length=16)
    target_language: str = Field(min_length=1, max_length=16)
    source_text: str = Field(min_length=1)
    target_text: str = Field(min_length=1)
    origin: Literal["confirmed_segment", "imported", "machine_translated", "manual"] = "manual"
    metadata: dict[str, Any] = Field(default_factory=dict)


class TranslationMemoryEntryUpdateRequest(BaseModel):
    source_language: str | None = Field(default=None, min_length=1, max_length=16)
    target_language: str | None = Field(default=None, min_length=1, max_length=16)
    source_text: str | None = Field(default=None, min_length=1)
    target_text: str | None = Field(default=None, min_length=1)
    origin: Literal["confirmed_segment", "imported", "machine_translated", "manual"] | None = None
    metadata: dict[str, Any] | None = None
    expected_revision: int = Field(ge=1)
    change_note: str | None = None


class TranslationMemoryEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    library_id: UUID
    source_language: str
    target_language: str
    source_text: str
    target_text: str
    status: str
    origin: str
    revision: int
    deleted_at: datetime | None
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class TranslationMemoryEntryPage(BaseModel):
    items: list[TranslationMemoryEntryResponse]
    next_cursor: str | None
    total: int


class TranslationMemoryImportRow(BaseModel):
    source_language: str
    target_language: str
    source_text: str
    target_text: str
    origin: Literal["confirmed_segment", "imported", "machine_translated", "manual"] = "imported"
    metadata: dict[str, Any] = Field(default_factory=dict)


class JobReference(BaseModel):
    job_id: UUID
    status: Literal["queued", "running", "failed"]


class TranslationMemoryImportResult(BaseModel):
    imported: int = 0
    skipped: int = 0
    job: JobReference | None = None
