"""Persistence operations for project worldviews and revisions."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from ..models import Project, Worldview, WorldviewEntry, WorldviewEntryRevision


class WorldviewRepository:
    async def find(self, project_id: UUID | str) -> Worldview | None:
        return await Worldview.filter(project_id=project_id).first()

    async def get_or_create(self, project: Project, *, name: str) -> Worldview:
        worldview = await Worldview.filter(project=project).first()
        if worldview is None:
            worldview = await Worldview.create(project=project, name=name)
        return worldview

    async def save(self, worldview: Worldview, *, update_fields: list[str]) -> Worldview:
        await worldview.save(update_fields=list(dict.fromkeys([*update_fields, "updated_at"])))
        return worldview

    async def list_entries(self, worldview: Worldview, *, offset: int = 0, limit: int | None = None) -> tuple[list[WorldviewEntry], int]:
        query = WorldviewEntry.filter(worldview=worldview, deleted_at=None).order_by("-updated_at")
        total = await query.count()
        query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)
        return await query, total

    async def find_entry(self, project_id: UUID | str, entry_id: UUID | str, *, include_deleted: bool = False) -> WorldviewEntry | None:
        query = WorldviewEntry.filter(id=entry_id, worldview__project_id=project_id)
        if not include_deleted:
            query = query.filter(deleted_at=None)
        return await query.first()

    async def create_entry(self, worldview: Worldview, **values: Any) -> WorldviewEntry:
        return await WorldviewEntry.create(worldview=worldview, **values)

    async def save_entry(self, entry: WorldviewEntry, *, update_fields: list[str]) -> WorldviewEntry:
        await entry.save(update_fields=list(dict.fromkeys([*update_fields, "updated_at"])))
        return entry

    async def list_revisions(self, entry: WorldviewEntry) -> list[WorldviewEntryRevision]:
        return await WorldviewEntryRevision.filter(entry=entry).order_by("-version")

    async def create_revision(self, **values: Any) -> WorldviewEntryRevision:
        return await WorldviewEntryRevision.create(**values)


__all__ = ["WorldviewRepository"]
