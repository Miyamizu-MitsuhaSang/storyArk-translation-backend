from __future__ import annotations

from uuid import UUID

from ....models import DocumentSegment, User
from ....repositories import CatRepository, MembershipRepository
from ..terminology.schemas import TerminologySearchRequest
from ..terminology.service import TerminologyService
from ...translation_memory.schemas import TranslationMemorySearchRequest
from ...translation_memory.service import TranslationMemoryService
from ..service import ProjectNotFoundError
from ..worldview.service import WorldviewNotFoundError, WorldviewService
from .schemas import ContextQuery, ContextResponse


class ContextService:
    def __init__(
        self,
        worldview_service: WorldviewService | None = None,
        memberships: MembershipRepository | None = None,
        terminology_service: TerminologyService | None = None,
        translation_memory_service: TranslationMemoryService | None = None,
        cat_repository: CatRepository | None = None,
    ) -> None:
        self._worldview_service = worldview_service or WorldviewService()
        self._memberships = memberships or MembershipRepository()
        self._terminology = terminology_service or TerminologyService()
        self._translation_memory = translation_memory_service or TranslationMemoryService()
        self._cat = cat_repository or CatRepository()

    async def get(self, user: User, project_id: UUID, query: ContextQuery) -> ContextResponse:
        membership = await self._memberships.find(project_id, user.id)
        if membership is None:
            raise ProjectNotFoundError("项目不存在或当前用户不可见")
        sources = query.requested_sources()
        segment = None
        if query.segment_id:
            try:
                segment_uuid = UUID(query.segment_id)
            except ValueError as exc:
                raise ValueError("segment_id 格式无效") from exc
            segment = await self._cat.get_segment(project_id, segment_uuid)
            if segment is None:
                raise ProjectNotFoundError("片段不存在或当前用户不可见")
        source_text = query.q or (segment.source_text if segment else None)
        worldview = None
        entries = []
        terms = []
        tm_matches = []
        neighbors = []
        if "worldview" in sources:
            try:
                worldview = await self._worldview_service.get(user, project_id)
                entry_page = await self._worldview_service.list_entries(
                    user,
                    project_id,
                    entry_type=None,
                    query=query.q,
                    status="active",
                    page_size=100,
                    cursor=None,
                )
                entries = entry_page.items
            except WorldviewNotFoundError:
                worldview = None
        if "terms" in sources and source_text:
            term_results = await self._terminology.search(
                user,
                project_id,
                TerminologySearchRequest(
                    text=source_text,
                    source_language=segment.source_language if segment else None,
                    target_language=segment.target_language if segment else None,
                ),
            )
            terms = [item.model_dump(mode="json") for item in term_results.items]
        if "tm" in sources and segment is not None:
            tm_result = await self._translation_memory.search(
                user,
                project_id,
                TranslationMemorySearchRequest(
                    source_text=segment.source_text,
                    source_language=segment.source_language,
                    target_language=segment.target_language,
                    match_mode="exact",
                ),
            )
            tm_matches = [item.model_dump(mode="json") for item in tm_result.items]
        if "neighbors" in sources and segment is not None:
            previous, following = await self._cat.neighbors(segment)
            neighbors = [self._neighbor_response(item) for item in (previous, following) if item is not None]
        return ContextResponse(
            project_id=project_id,
            segment_id=query.segment_id,
            query=query.q,
            included_sources=sources,
            worldview=worldview,
            worldview_entries=entries,
            terms=terms,
            tm_matches=tm_matches,
            neighbors=neighbors,
        )

    @staticmethod
    def _neighbor_response(segment: DocumentSegment) -> dict[str, object]:
        return {
            "id": str(segment.id),
            "document_id": str(segment.document_id),
            "segment_no": segment.segment_no,
            "source": segment.source_text,
            "target": segment.target_text,
            "source_language": segment.source_language,
            "target_language": segment.target_language,
            "status": segment.status,
            "workflow_state": segment.workflow_state,
            "version": segment.version,
        }
