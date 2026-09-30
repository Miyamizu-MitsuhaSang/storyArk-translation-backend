"""Application hooks used by segment confirmation and import workflows."""

from typing import Iterable
from uuid import UUID

from ...models import TranslationMemoryEntry, User
from .schemas import TranslationMemoryImportResult, TranslationMemoryImportRow
from .service import TranslationMemoryService


async def confirm_segment(
    user: User,
    project_id: UUID,
    segment_id: UUID,
    source_text: str,
    target_text: str,
    *,
    document_id: UUID | None = None,
    source_language: str | None = None,
    target_language: str | None = None,
    service: TranslationMemoryService | None = None,
) -> TranslationMemoryEntry:
    return await (service or TranslationMemoryService()).upsert_confirmed_segment(
        user, project_id, document_id, segment_id, source_language, target_language, source_text, target_text
    )


async def import_entries(
    user: User,
    memory_id: UUID,
    rows: Iterable[TranslationMemoryImportRow],
    idempotency_key: str,
    *,
    service: TranslationMemoryService | None = None,
) -> TranslationMemoryImportResult:
    return await (service or TranslationMemoryService()).import_entries(user, memory_id, rows, idempotency_key)
