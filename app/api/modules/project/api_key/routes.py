from fastapi import APIRouter, Depends, Query, Request
from starlette.responses import JSONResponse, Response
from uuid import UUID

from translation_backend.app.api.modules.project.api_key.schemas import (
    CreateProjectApiKeyRequest,
    ProjectApiKeyPage,
    ProjectApiKeyResponse,
    UpdateProjectApiKeyRequest,
)
from translation_backend.app.api.modules.project.api_key.service import (
    ProjectApiKeyError,
    ProjectApiKeyService,
)
from translation_backend.app.core.security import get_current_user
from app.models import User

project_api_key_router = APIRouter(tags=["project-api-keys"])
_project_api_key_service = ProjectApiKeyService()


def get_project_api_key_service() -> ProjectApiKeyService:
    return _project_api_key_service


async def _handle_project_api_key_error(request: Request, exc: ProjectApiKeyError) -> JSONResponse:
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


def register_project_api_key_exception_handler(app) -> None:
    app.add_exception_handler(ProjectApiKeyError, _handle_project_api_key_error)


@project_api_key_router.get(
    "",
    response_model=ProjectApiKeyPage,
    description="返回项目已授权的 API key 脱敏元数据；项目成员可查看，不能看到 secret。",
)
async def list_project_api_keys(
    project_id: UUID,
    page_size: int = Query(default=20, ge=1, le=100, description="每页返回数量。"),
    cursor: str | None = Query(default=None, description="不透明分页游标。"),
    user: User = Depends(get_current_user),
    service: ProjectApiKeyService = Depends(get_project_api_key_service),
) -> ProjectApiKeyPage:
    return await service.list(user, project_id, page_size=page_size, cursor=cursor)


@project_api_key_router.post(
    "",
    response_model=ProjectApiKeyResponse,
    status_code=201,
    description="将当前用户拥有且 active 的 API key 绑定到项目；owner 或 manager 可操作，重复绑定幂等。",
)
async def create_project_api_key(
    project_id: UUID,
    request: CreateProjectApiKeyRequest,
    user: User = Depends(get_current_user),
    service: ProjectApiKeyService = Depends(get_project_api_key_service),
) -> ProjectApiKeyResponse:
    return await service.create(user, project_id, request)


@project_api_key_router.patch(
    "/{binding_id}",
    response_model=ProjectApiKeyResponse,
    description="修改项目 API key 绑定的 status 或默认状态；同一项目最多一个默认绑定。",
)
async def update_project_api_key(
    project_id: UUID,
    binding_id: UUID,
    request: UpdateProjectApiKeyRequest,
    user: User = Depends(get_current_user),
    service: ProjectApiKeyService = Depends(get_project_api_key_service),
) -> ProjectApiKeyResponse:
    return await service.update(user, project_id, binding_id, request)


@project_api_key_router.delete(
    "/{binding_id}",
    status_code=204,
    description="解除项目 API key 绑定，不删除用户级 API key；活动任务引用时返回 API_KEY_IN_USE。",
)
async def delete_project_api_key(
    project_id: UUID,
    binding_id: UUID,
    user: User = Depends(get_current_user),
    service: ProjectApiKeyService = Depends(get_project_api_key_service),
) -> Response:
    await service.delete(user, project_id, binding_id)
    return Response(status_code=204)
