from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from starlette.responses import JSONResponse, Response
from uuid import UUID

from .api_key.routes import project_api_key_router
from ....core.security import get_current_user
from ....application.project.schemas import (
    AddMemberRequest,
    CreateProjectRequest,
    LanguagePairListQuery,
    LanguagePairPage,
    LanguagePairRequest,
    LanguagePairResponse,
    MemberListQuery,
    MemberPage,
    ProjectListQuery,
    ProjectMemberResponse,
    ProjectPage,
    ProjectResponse,
    UpdateMemberRequest,
    UpdateProjectRequest,
)
from ....application.project.service import ProjectError, ProjectService
from ....models import User


project_router = APIRouter(prefix="/projects", tags=["projects"])
project_router.include_router(project_api_key_router, prefix="/{project_id}/api-keys", tags=["api-key"])
_project_service = ProjectService()


def get_project_service() -> ProjectService:
    return _project_service


async def _handle_project_error(request: Request, exc: ProjectError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": str(exc),
                "details": {},
                "request_id": getattr(request.state, "request_id", None),
            }
        },
    )


def register_project_exception_handler(app) -> None:
    app.add_exception_handler(ProjectError, _handle_project_error)


@project_router.get(
    "",
    response_model=ProjectPage,
    description="返回当前用户可访问的项目列表，支持状态、关键词和不透明游标分页。",
)
async def list_projects(
    query: ProjectListQuery = Depends(),
    user: User = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
) -> ProjectPage:
    return await service.list_projects(user, query)


@project_router.post(
    "",
    response_model=ProjectResponse,
    status_code=201,
    description="创建项目并将当前用户自动加入为 owner，同时初始化项目语言对。",
)
async def create_project(
    request: CreateProjectRequest,
    user: User = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
) -> ProjectResponse:
    return await service.create_project(user, request)


@project_router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    description="返回当前用户可见的项目配置、成员统计和语言对。",
)
async def get_project(
    project_id: UUID,
    user: User = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
) -> ProjectResponse:
    return await service.get_project(user, project_id)


@project_router.patch(
    "/{project_id}",
    response_model=ProjectResponse,
    description="更新项目名称、描述、状态或默认语言对；需要 owner 或 manager 角色。",
)
async def update_project(
    project_id: UUID,
    request: UpdateProjectRequest,
    user: User = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
) -> ProjectResponse:
    return await service.update_project(user, project_id, request)


@project_router.get(
    "/{project_id}/members",
    response_model=MemberPage,
    description="返回项目成员列表，支持角色、关键词和不透明游标分页筛选。",
)
async def list_members(
    project_id: UUID,
    query: MemberListQuery = Depends(),
    user: User = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
) -> MemberPage:
    return await service.list_members(user, project_id, query)


@project_router.post(
    "/{project_id}/members",
    response_model=ProjectMemberResponse,
    status_code=201,
    description="向项目添加成员；需要 owner 或 manager 角色。",
)
async def add_member(
    project_id: UUID,
    request: AddMemberRequest,
    user: User = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
) -> ProjectMemberResponse:
    return await service.add_member(user, project_id, request)


@project_router.patch(
    "/{project_id}/members/{user_id}",
    response_model=ProjectMemberResponse,
    description="修改项目成员角色；不能移除项目最后一个 owner。",
)
async def update_member(
    project_id: UUID,
    user_id: UUID,
    request: UpdateMemberRequest,
    user: User = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
) -> ProjectMemberResponse:
    return await service.update_member(user, project_id, user_id, request)


@project_router.delete(
    "/{project_id}/members/{user_id}",
    status_code=204,
    description="从项目移除成员；不能移除项目最后一个 owner。",
)
async def remove_member(
    project_id: UUID,
    user_id: UUID,
    user: User = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
) -> Response:
    await service.remove_member(user, project_id, user_id)
    return Response(status_code=204)


@project_router.get(
    "/{project_id}/language-pairs",
    response_model=LanguagePairPage,
    description="返回项目配置的源语言、目标语言组合及其启用状态。",
)
async def list_language_pairs(
    project_id: UUID,
    query: LanguagePairListQuery = Depends(),
    user: User = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
) -> LanguagePairPage:
    return await service.list_language_pairs(user, project_id, query)


@project_router.post(
    "/{project_id}/language-pairs",
    response_model=LanguagePairResponse,
    status_code=201,
    description="为项目添加语言对；可将其设为默认语言对，需要 owner 或 manager 角色。",
)
async def add_language_pair(
    project_id: UUID,
    request: LanguagePairRequest,
    user: User = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
) -> LanguagePairResponse:
    return await service.add_language_pair(user, project_id, request)
