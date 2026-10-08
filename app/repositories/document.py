from __future__ import annotations

from uuid import UUID

from tortoise.expressions import Q

from ..models import Document, DocumentSegment


class DocumentRepository:
    async def get(self, project_id: UUID, document_id: UUID) -> Document | None:
        return await Document.filter(project_id=project_id, id=document_id).first()

    async def list(
        self,
        project_id: UUID,
        *,
        status: str | None = None,
        file_name: str | None = None,
        created_by: UUID | None = None,
        source_language: str | None = None,
        target_language: str | None = None,
        order_by: str = "-created_at",
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[Document], int]:
        query = Document.filter(project_id=project_id)
        if status:
            query = query.filter(status=status)
        if file_name:
            query = query.filter(file_name__icontains=file_name)
        if created_by:
            query = query.filter(created_by_id=created_by)
        if source_language:
            query = query.filter(source_language=source_language)
        if target_language:
            query = query.filter(target_language=target_language)
        total = await query.count()
        return await query.order_by(order_by).offset(offset).limit(limit), total
    async def list_segments(
        self,
        document_id: UUID,
        *,
        status: str | None = None,
        workflow_state: str | None = None,
        assigned_to: UUID | None = None,
        q: str | None = None,
        segment_no_from: int | None = None,
        segment_no_to: int | None = None,
        order_by: str = "segment_no",
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[DocumentSegment], int]:
        query = DocumentSegment.filter(document_id=document_id, deleted_at=None)
        if status:
            query = query.filter(status=status)
        if workflow_state:
            query = query.filter(workflow_state=workflow_state)
        if assigned_to:
            query = query.filter(assigned_to_id=assigned_to)
        if q:
            query = query.filter(Q(source_text__icontains=q) | Q(target_text__icontains=q))
        if segment_no_from is not None:
            query = query.filter(segment_no__gte=segment_no_from)
        if segment_no_to is not None:
            query = query.filter(segment_no__lte=segment_no_to)
        total = await query.count()
        return await query.order_by(order_by).offset(offset).limit(limit), total
