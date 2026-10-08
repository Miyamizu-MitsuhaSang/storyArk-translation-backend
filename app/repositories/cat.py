"""Persistence operations for CAT segments, locks and suggestions."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from tortoise import transactions

from ..models import DocumentSegment, SegmentLock, SegmentSuggestion


class CatRepository:
    async def get_segment(self, project_id: UUID | str, segment_id: UUID | str) -> DocumentSegment | None:
        return await DocumentSegment.filter(
            id=segment_id,
            document__project_id=project_id,
            deleted_at=None,
        ).select_related("document", "assigned_to").first()

    async def get_segment_for_update(self, project_id: UUID | str, segment_id: UUID | str) -> DocumentSegment | None:
        async with transactions.in_transaction() as connection:
            return await DocumentSegment.filter(
                id=segment_id,
                document__project_id=project_id,
                deleted_at=None,
            ).using_db(connection).select_for_update().select_related("document", "assigned_to").first()

    async def neighbors(self, segment: DocumentSegment) -> tuple[DocumentSegment | None, DocumentSegment | None]:
        previous = await DocumentSegment.filter(
            document_id=segment.document_id,
            segment_no__lt=segment.segment_no,
            deleted_at=None,
        ).order_by("-segment_no").first()
        following = await DocumentSegment.filter(
            document_id=segment.document_id,
            segment_no__gt=segment.segment_no,
            deleted_at=None,
        ).order_by("segment_no").first()
        return previous, following

    async def get_lock(self, segment_id: UUID | str, *, active_only: bool = True) -> SegmentLock | None:
        query = SegmentLock.filter(segment_id=segment_id)
        if active_only:
            query = query.filter(released_at=None)
        return await query.select_related("user").first()

    async def save_segment(self, segment: DocumentSegment, *, update_fields: list[str]) -> DocumentSegment:
        await segment.save(update_fields=list(dict.fromkeys([*update_fields, "updated_at"])))
        return segment

    async def create_lock(self, **values: Any) -> SegmentLock:
        return await SegmentLock.create(**values)

    async def save_lock(self, lock: SegmentLock, *, update_fields: list[str]) -> SegmentLock:
        await lock.save(update_fields=list(dict.fromkeys([*update_fields, "updated_at"])))
        return lock

    async def delete_lock(self, lock: SegmentLock) -> None:
        await lock.delete()

    async def create_suggestion(self, **values: Any) -> SegmentSuggestion:
        return await SegmentSuggestion.create(**values)

    async def list_suggestions(self, segment_id: UUID | str, *, limit: int = 20) -> list[SegmentSuggestion]:
        return await SegmentSuggestion.filter(segment_id=segment_id).order_by("-created_at").limit(limit)


__all__ = ["CatRepository"]
