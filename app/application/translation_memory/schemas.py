from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_FORBIDDEN_METADATA_KEYS = {"prompt", "completion", "api_key", "apikey", "secret", "token"}


def _validate_metadata(value: dict[str, Any]) -> dict[str, Any]:
    if {str(key).casefold() for key in value} & _FORBIDDEN_METADATA_KEYS:
        raise ValueError("metadata 不得包含凭据、token、prompt 或 completion 字段")
    if len(str(value).encode("utf-8")) > 8192:
        raise ValueError("metadata 超过 8192 字节限制")
    return value


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
    priority: int = 0
    entry_count: int = 0
    language_pairs: list[tuple[str, str]] = Field(default_factory=list)
    index_status: str = "database"


class TranslationMemoryLibraryUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = None
    status: Literal["active", "archived"] | None = None


class TranslationMemoryLibraryPage(BaseModel):
    items: list[TranslationMemoryLibraryResponse]
    next_cursor: str | None
    total: int


class EffectiveTranslationMemoryScope(BaseModel):
    id: UUID
    library_id: UUID
    scope: Literal["platform", "user"]
    owner_user_id: UUID | None = None
    name: str
    status: str = "active"
    priority: int = 0
    entry_count: int = 0
    language_pairs: list[tuple[str, str]] = Field(default_factory=list)
    content_version: int = 1


class TranslationMemoryMatch(BaseModel):
    entry_id: UUID
    library_id: UUID
    scope: Literal["platform", "user"]
    owner_user_id: UUID | None = None
    source_language: str
    target_language: str
    source_text: str
    target_text: str
    match_type: Literal["exact"] = "exact"
    score: float = 1.0
    priority: int = 0
    quality_score: float = 0.0
    updated_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class TranslationMemorySearchRequest(BaseModel):
    source_text: str = Field(min_length=1, max_length=16384)
    source_language: str = Field(min_length=1, max_length=16)
    target_language: str = Field(min_length=1, max_length=16)
    top_k: int = Field(default=20, ge=1, le=50)
    min_score: float = Field(default=0.0, ge=0.0, le=1.0)
    match_mode: Literal["exact"] = "exact"
    include_library_ids: list[UUID] | None = None
    updated_after: datetime | None = None
    updated_before: datetime | None = None

    @model_validator(mode="after")
    def validate_updated_window(self) -> "TranslationMemorySearchRequest":
        if self.updated_after and self.updated_before and self.updated_after > self.updated_before:
            raise ValueError("updated_after must be before updated_before")
        return self


class TranslationMemorySearchResponse(BaseModel):
    items: list[TranslationMemoryMatch]
    total: int
    source_hash: str
    index_status: str = "database"


class TranslationMemoryReindexResponse(BaseModel):
    job_id: UUID
    status: Literal["queued", "running", "failed"]


class TranslationMemoryEntryCreateRequest(BaseModel):
    source_language: str = Field(min_length=1, max_length=16)
    target_language: str = Field(min_length=1, max_length=16)
    source_text: str = Field(min_length=1)
    target_text: str = Field(min_length=1)
    origin: Literal["platform_seed", "confirmed_segment", "manual", "import", "imported", "machine_translated"] = "manual"
    metadata: dict[str, Any] = Field(default_factory=dict)
    _metadata_policy = field_validator("metadata")(_validate_metadata)


class TranslationMemoryEntryUpdateRequest(BaseModel):
    source_language: str | None = Field(default=None, min_length=1, max_length=16)
    target_language: str | None = Field(default=None, min_length=1, max_length=16)
    source_text: str | None = Field(default=None, min_length=1)
    target_text: str | None = Field(default=None, min_length=1)
    origin: Literal["platform_seed", "confirmed_segment", "manual", "import", "imported", "machine_translated"] | None = None
    metadata: dict[str, Any] | None = None
    expected_revision: int = Field(ge=1)
    change_note: str | None = None
    _metadata_policy = field_validator("metadata")(_validate_metadata)


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
    source_language: str = Field(min_length=1, max_length=16)
    target_language: str = Field(min_length=1, max_length=16)
    source_text: str = Field(min_length=1)
    target_text: str = Field(min_length=1)
    origin: Literal["platform_seed", "confirmed_segment", "manual", "import", "imported", "machine_translated"] = "import"
    metadata: dict[str, Any] = Field(default_factory=dict)
    _metadata_policy = field_validator("metadata")(_validate_metadata)


class JobReference(BaseModel):
    job_id: UUID
    status: Literal["queued", "running", "failed"]


class TranslationMemoryImportResult(BaseModel):
    imported: int = 0
    skipped: int = 0
    invalid_rows: list[dict[str, object]] = Field(default_factory=list)
    job: JobReference | None = None


class TranslationMemoryReindexResponse(BaseModel):
    job_id: UUID
    status: Literal["queued", "running", "failed"]
