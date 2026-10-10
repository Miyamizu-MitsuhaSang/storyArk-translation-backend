"""Persistence operations for terminology bases, terms, and revisions."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from ..models import TerminologyBase, TerminologyTerm, TerminologyTermRevision, WorldviewEntry


class TerminologyRepository:
    async def list_bases(self, project_id: UUID | str) -> list[TerminologyBase]:
        return await TerminologyBase.filter(project_id=project_id).order_by("-priority", "-created_at")

    async def create_base(self, project, **values: Any) -> TerminologyBase:
        return await TerminologyBase.create(project=project, **values)

    async def find_base(self, project_id: UUID | str, base_id: UUID | str) -> TerminologyBase | None:
        return await TerminologyBase.filter(id=base_id, project_id=project_id).first()

    async def list_terms(self, base: TerminologyBase, *, include_deleted: bool = False) -> list[TerminologyTerm]:
        query = TerminologyTerm.filter(base=base)
        if not include_deleted:
            query = query.filter(deleted_at=None)
        return await query.order_by("-updated_at")

    async def create_term(self, base: TerminologyBase, **values: Any) -> TerminologyTerm:
        return await TerminologyTerm.create(base=base, **values)

    async def find_term(self, base_id: UUID | str, term_id: UUID | str, *, include_deleted: bool = False) -> TerminologyTerm | None:
        query = TerminologyTerm.filter(id=term_id, base_id=base_id)
        if not include_deleted:
            query = query.filter(deleted_at=None)
        return await query.first()

    async def find_term_by_source(
        self,
        base_id: UUID | str,
        source_term: str,
        *,
        include_deleted: bool = False,
    ) -> TerminologyTerm | None:
        query = TerminologyTerm.filter(base_id=base_id, source_term__iexact=source_term)
        if not include_deleted:
            query = query.filter(deleted_at=None)
        return await query.order_by("-updated_at").first()

    async def list_terms_by_ids(
        self,
        base_id: UUID | str,
        term_ids: list[UUID | str],
        *,
        include_deleted: bool = False,
    ) -> list[TerminologyTerm]:
        query = TerminologyTerm.filter(base_id=base_id, id__in=term_ids)
        if not include_deleted:
            query = query.filter(deleted_at=None)
        return await query.order_by("id")

    async def count_terms(self, base: TerminologyBase) -> int:
        return await TerminologyTerm.filter(base=base, deleted_at=None).count()

    async def save_term(self, term: TerminologyTerm, *, update_fields: list[str]) -> TerminologyTerm:
        await term.save(update_fields=list(dict.fromkeys([*update_fields, "updated_at"])))
        return term

    async def save_base(self, base: TerminologyBase, *, update_fields: list[str]) -> TerminologyBase:
        await base.save(update_fields=list(dict.fromkeys([*update_fields, "updated_at"])))
        return base

    async def list_revisions(self, term: TerminologyTerm) -> list[TerminologyTermRevision]:
        return await TerminologyTermRevision.filter(term=term).order_by("-version")

    async def create_revision(self, **values: Any) -> TerminologyTermRevision:
        return await TerminologyTermRevision.create(**values)

    async def worldview_entry_exists(self, project_id: UUID | str, entry_id: UUID | str) -> bool:
        return await WorldviewEntry.filter(
            id=entry_id,
            worldview__project_id=project_id,
            deleted_at=None,
        ).exists()


__all__ = ["TerminologyRepository"]
