from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from .....application.project.version.schemas import (
    FilePage,
    VersionCreateRequest,
    VersionListQuery,
    VersionPage,
    VersionResponse,
)
from .....application.project.version.service import VersionService
from ....shared.dependencies import get_current_user
from .....models import User
from .dependencies import get_version_service


project_version_router = APIRouter()


@project_version_router.get("", response_model=VersionPage, description="按系统版本号查询当前项目的业务版本列表。")
async def list_versions(
    project_id: UUID,
    query: VersionListQuery = Depends(),
    user: User = Depends(get_current_user),
    service: VersionService = Depends(get_version_service),
) -> VersionPage:
    return await service.list(user, project_id, query)


@project_version_router.post(
    "",
    response_model=VersionResponse,
    status_code=201,
    description="创建项目业务版本；版本号由系统按项目独立分配，不能由客户端传入。",
)
async def create_version(
    project_id: UUID,
    request_body: VersionCreateRequest,
    user: User = Depends(get_current_user),
    service: VersionService = Depends(get_version_service),
) -> VersionResponse:
    return await service.create(user, project_id, request_body)


@project_version_router.get(
    "/{version_id}/files",
    response_model=FilePage,
    description="分页返回指定业务版本实际关联的项目源文件。",
)
async def list_version_files(
    project_id: UUID,
    version_id: UUID,
    page_size: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    service: VersionService = Depends(get_version_service),
) -> FilePage:
    return await service.list_files(
        user,
        project_id,
        version_id,
        page_size=page_size,
        cursor=cursor,
    )


__all__ = ["project_version_router"]
