from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from starlette.responses import Response
from uuid import UUID

from ......application.project.worldview.schemas import (
    WorldviewEntryCreateRequest,
    WorldviewEntryPage,
    WorldviewEntryResponse,
    WorldviewEntryUpdateRequest,
    WorldviewEntryType,
    WorldviewResponse,
    WorldviewStatus,
    WorldviewUpdateRequest,
)
from ......application.project.worldview.service import WorldviewService
from ......models import User
from .....shared.dependencies import get_current_user
from .dependencies import get_worldview_service

project_worldview_router = APIRouter()


@project_worldview_router.get(
    "",
    response_model=WorldviewResponse,
    description="返回当前项目的世界观版本、摘要、风格指南和启用状态；项目成员可读取。",
)
async def get_worldview(
    project_id: UUID,
    user: User = Depends(get_current_user),
    service: WorldviewService = Depends(get_worldview_service),
) -> WorldviewResponse:
    return await service.get(user, project_id)


@project_worldview_router.patch(
    "",
    response_model=WorldviewResponse,
    description="创建或更新项目级世界观、风格指南和全局规则；需要 owner 或 manager 角色。",
)
async def update_worldview(
    project_id: UUID,
    request: WorldviewUpdateRequest,
    user: User = Depends(get_current_user),
    service: WorldviewService = Depends(get_worldview_service),
) -> WorldviewResponse:
    return await service.update(user, project_id, request)


@project_worldview_router.get(
    "/entries",
    response_model=WorldviewEntryPage,
    description="按条目类型、关键词、状态和游标分页查询项目世界观条目；已软删除条目不返回。",
)
async def list_worldview_entries(
    project_id: UUID,
    type: WorldviewEntryType | None = Query(default=None, alias="type", description="条目类型。"),
    q: str | None = Query(default=None, max_length=500, description="匹配名称、别名、标签或说明的关键词。"),
    status: WorldviewStatus | None = Query(default=None, description="条目状态。"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页返回数量。"),
    cursor: str | None = Query(default=None, description="不透明分页游标。"),
    user: User = Depends(get_current_user),
    service: WorldviewService = Depends(get_worldview_service),
) -> WorldviewEntryPage:
    return await service.list_entries(
        user,
        project_id,
        entry_type=type,
        query=q,
        status=status,
        page_size=page_size,
        cursor=cursor,
    )


@project_worldview_router.post(
    "/entries",
    response_model=WorldviewEntryResponse,
    status_code=201,
    description="创建世界观条目并记录初始版本；需要 owner 或 manager 角色。",
)
async def create_worldview_entry(
    project_id: UUID,
    request: WorldviewEntryCreateRequest,
    user: User = Depends(get_current_user),
    service: WorldviewService = Depends(get_worldview_service),
) -> WorldviewEntryResponse:
    return await service.create_entry(user, project_id, request)


@project_worldview_router.get(
    "/entries/{entry_id}",
    response_model=WorldviewEntryResponse,
    description="返回单条世界观条目及其版本历史摘要；项目成员可读取。",
)
async def get_worldview_entry(
    project_id: UUID,
    entry_id: UUID,
    user: User = Depends(get_current_user),
    service: WorldviewService = Depends(get_worldview_service),
) -> WorldviewEntryResponse:
    return await service.get_entry(user, project_id, entry_id)


@project_worldview_router.patch(
    "/entries/{entry_id}",
    response_model=WorldviewEntryResponse,
    description="更新世界观条目并生成新的不可变版本快照；需要 owner 或 manager 角色。",
)
async def update_worldview_entry(
    project_id: UUID,
    entry_id: UUID,
    request: WorldviewEntryUpdateRequest,
    user: User = Depends(get_current_user),
    service: WorldviewService = Depends(get_worldview_service),
) -> WorldviewEntryResponse:
    return await service.update_entry(user, project_id, entry_id, request)


@project_worldview_router.delete(
    "/entries/{entry_id}",
    status_code=204,
    description="软删除世界观条目并保留其版本历史；需要 owner 或 manager 角色。",
)
async def delete_worldview_entry(
    project_id: UUID,
    entry_id: UUID,
    user: User = Depends(get_current_user),
    service: WorldviewService = Depends(get_worldview_service),
) -> Response:
    await service.delete_entry(user, project_id, entry_id)
    return Response(status_code=204)
