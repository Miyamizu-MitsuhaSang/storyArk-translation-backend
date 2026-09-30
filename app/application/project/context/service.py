from __future__ import annotations

from uuid import UUID

from ....models import User
from ....repositories import MembershipRepository
from ..service import ProjectNotFoundError
from ..worldview.service import WorldviewNotFoundError, WorldviewService
from .schemas import ContextQuery, ContextResponse


class ContextService:
    def __init__(self, worldview_service: WorldviewService | None = None, memberships: MembershipRepository | None = None) -> None:
        self._worldview_service = worldview_service or WorldviewService()
        self._memberships = memberships or MembershipRepository()

    async def get(self, user: User, project_id: UUID, query: ContextQuery) -> ContextResponse:
        membership = await self._memberships.find(project_id, user.id)
        if membership is None:
            raise ProjectNotFoundError("项目不存在或当前用户不可见")
        sources = query.requested_sources()
        worldview = None
        entries = []
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
        return ContextResponse(
            project_id=project_id,
            segment_id=query.segment_id,
            query=query.q,
            included_sources=sources,
            worldview=worldview,
            worldview_entries=entries,
            terms=[],
            tm_matches=[],
            neighbors=[],
        )
