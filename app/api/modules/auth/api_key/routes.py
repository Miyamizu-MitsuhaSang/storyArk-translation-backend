from fastapi import APIRouter, Depends, Query, Request
from starlette.responses import JSONResponse, Response
from uuid import UUID

from .....application.auth.api_key.schemas import (
    ApiKeyPage,
    ApiKeyResponse,
    CreatedApiKeyResponse,
    CreateApiKeyRequest,
    UpdateApiKeyRequest,
)
from .....application.auth.api_key.service import ApiKeyError, ApiKeyService
from ....shared.dependencies import get_current_user
from .dependencies import get_api_key_service
from .....models import User


user_api_router = APIRouter(prefix="/me/api-keys", tags=["auth-api-keys"])


async def _handle_api_key_error(request: Request, exc: ApiKeyError) -> JSONResponse:
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


def register_api_key_exception_handler(app) -> None:
    app.add_exception_handler(ApiKeyError, _handle_api_key_error)


@user_api_router.get(
    "",
    response_model=ApiKeyPage,
    description="返回当前用户拥有的 AI provider API key 脱敏元数据，不返回 secret。",
)
async def list_api_keys(
    page_size: int = Query(default=20, ge=1, le=100, description="每页返回数量。"),
    cursor: str | None = Query(default=None, description="不透明分页游标。"),
    user: User = Depends(get_current_user),
    service: ApiKeyService = Depends(get_api_key_service),
) -> ApiKeyPage:
    return await service.list(user, page_size=page_size, cursor=cursor)


@user_api_router.post(
    "",
    response_model=CreatedApiKeyResponse,
    status_code=201,
    description="创建当前用户的 AI provider API key；secret 仅接收一次且永不在响应中返回。",
)
async def create_api_key(
    request: CreateApiKeyRequest,
    user: User = Depends(get_current_user),
    service: ApiKeyService = Depends(get_api_key_service),
) -> CreatedApiKeyResponse:
    return await service.create(user, request)


@user_api_router.get(
    "/{key_id}",
    response_model=ApiKeyResponse,
    description="返回当前用户指定 API key 的脱敏元数据。",
)
async def get_api_key(
    key_id: UUID,
    user: User = Depends(get_current_user),
    service: ApiKeyService = Depends(get_api_key_service),
) -> ApiKeyResponse:
    return await service.get(user, key_id)


@user_api_router.patch(
    "/{key_id}",
    response_model=ApiKeyResponse,
    description="更新 API key 的 label 或 status；不接受 secret 轮换。",
)
async def update_api_key(
    key_id: UUID,
    request: UpdateApiKeyRequest,
    user: User = Depends(get_current_user),
    service: ApiKeyService = Depends(get_api_key_service),
) -> ApiKeyResponse:
    return await service.update(user, key_id, request)


@user_api_router.delete(
    "/{key_id}",
    status_code=204,
    description="永久删除当前用户的 API key；已绑定项目时应返回 API_KEY_IN_USE。",
)
async def delete_api_key(
    key_id: UUID,
    user: User = Depends(get_current_user),
    service: ApiKeyService = Depends(get_api_key_service),
) -> Response:
    await service.delete(user, key_id)
    return Response(status_code=204)
