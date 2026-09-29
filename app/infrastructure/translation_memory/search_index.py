from __future__ import annotations

import hashlib
from uuid import UUID, uuid4

from tortoise.expressions import Q

from ...models import TranslationMemoryEntry, TranslationMemoryLibrary
from ...application.translation_memory.schemas import (
    EffectiveTranslationMemoryScope,
    TranslationMemoryMatch,
    TranslationMemorySearchRequest,
    JobReference,
)


def normalize_text(value: str) -> str:
    return " ".join(value.split()).casefold()


def source_hash(value: str) -> str:
    return hashlib.sha256(normalize_text(value).encode()).hexdigest()


class ExactTranslationMemorySearch:
    async def search(
        self,
        scope: list[EffectiveTranslationMemoryScope],
        request: TranslationMemorySearchRequest,
    ) -> list[TranslationMemoryMatch]:
        allowed = {item.library_id: item for item in scope}
        library_ids = set(allowed)
        if request.include_library_ids is not None:
            library_ids.intersection_update(request.include_library_ids)
        if not library_ids:
            return []
        query = TranslationMemoryEntry.filter(
            library_id__in=list(library_ids),
            source_language=request.source_language,
            target_language=request.target_language,
            source_hash=source_hash(request.source_text),
            status="active",
            deleted_at=None,
        ).select_related("library")
        if request.updated_after is not None:
            query = query.filter(updated_at__gte=request.updated_after)
        if request.updated_before is not None:
            query = query.filter(updated_at__lte=request.updated_before)
        rows = await query
        matches = []
        for entry in rows:
            library = allowed[entry.library_id]
            matches.append(TranslationMemoryMatch(
                entry_id=entry.id,
                library_id=entry.library_id,
                scope=library.scope,
                owner_user_id=library.owner_user_id,
                source_language=entry.source_language,
                target_language=entry.target_language,
                source_text=entry.source_text,
                target_text=entry.target_text,
                score=1.0,
                priority=getattr(library, "priority", 0),
                quality_score=float((entry.metadata or {}).get("quality_score", 0) or 0),
                updated_at=entry.updated_at,
                metadata=entry.metadata or {},
            ))
        matches = [item for item in matches if item.score >= request.min_score]
        matches.sort(key=lambda item: (-item.score, 0 if item.scope == "user" else 1, -item.priority, -item.quality_score, -item.updated_at.timestamp()))
        # Keep every response bounded even when a caller bypasses request validation.
        return matches[: min(request.top_k, 50)]


class TranslationMemorySearchIndex(ExactTranslationMemorySearch):
    def enqueue_rebuild(self, library_id: UUID, content_version: int) -> JobReference:
        return JobReference(job_id=uuid4(), status="queued")


async def build_effective_scope(user_id: UUID) -> list[EffectiveTranslationMemoryScope]:
    libraries = await TranslationMemoryLibrary.filter(
        status="active",
    ).filter(Q(scope="platform") | Q(scope="user", owner_user_id=user_id)).order_by("scope", "created_at")
    result = []
    for library in libraries:
        entries = TranslationMemoryEntry.filter(library_id=library.id, status="active", deleted_at=None)
        pairs = await entries.distinct().values_list("source_language", "target_language")
        result.append(EffectiveTranslationMemoryScope(
            id=library.id,
            library_id=library.id,
            scope=library.scope,
            owner_user_id=library.owner_user_id,
            name=library.name,
            status=library.status,
            priority=getattr(library, "priority", 0),
            entry_count=await entries.count(),
            language_pairs=[tuple(pair) for pair in pairs],
            content_version=library.content_version,
        ))
    return result
