from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from uuid import UUID

from ......application.project.context.schemas import ContextQuery, ContextResponse
from ......application.project.context.service import ContextService
from ......models import User
from .....shared.dependencies import get_current_user
from .dependencies import get_context_service

project_context_router = APIRouter()


@project_context_router.get(
    "",
    response_model=ContextResponse,
    description="聚合当前项目的世界观条目和项目风格规则，并预留术语、TM 与相邻 segment 上下文来源。",
)
async def get_project_context(
    project_id: UUID,
    query: ContextQuery = Depends(),
    user: User = Depends(get_current_user),
    service: ContextService = Depends(get_context_service),
) -> ContextResponse:
    try:
        return await service.get(user, project_id, query)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
