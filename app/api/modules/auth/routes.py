from fastapi import APIRouter, Depends, Request
from starlette.responses import JSONResponse, Response

from ....application.auth.schemas import (
    ChangePasswordRequest,
    ErrorResponse,
    LoginRequest,
    MeResponse,
    RefreshRequest,
    TokenResponse,
)
from ....application.auth.service import AuthError, AuthService
from ...shared.dependencies import (
    get_auth_service,
    get_current_user,
    oauth2_scheme,
)
from ....models import User


auth_router = APIRouter()


async def _handle_auth_error(request: Request, exc: AuthError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None) or request.headers.get("X-Request-ID")
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
                "request_id": request_id,
            }
        },
    )


def register_auth_exception_handler(app) -> None:
    app.add_exception_handler(AuthError, _handle_auth_error)
    from .translation_memory.routes import register_translation_memory_exception_handler
    register_translation_memory_exception_handler(app)


@auth_router.post("/login", response_model=TokenResponse, responses={401: {"model": ErrorResponse}})
async def login(
    request: LoginRequest,
    service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    return await service.login(request.login, request.password, remember_me=request.remember_me)


@auth_router.post("/refresh", response_model=TokenResponse, responses={401: {"model": ErrorResponse}})
async def refresh(
    request: RefreshRequest,
    service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    return await service.refresh(request.refresh_token)


@auth_router.post("/logout", status_code=204, responses={204: {"description": "令牌已撤销"}})
async def logout(
    request: RefreshRequest,
    service: AuthService = Depends(get_auth_service),
) -> Response:
    await service.logout(request.refresh_token)
    return Response(status_code=204)


@auth_router.get("/me", response_model=MeResponse, responses={401: {"model": ErrorResponse}})
async def me(
    user: User = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
) -> MeResponse:
    return await service.me(user)


@auth_router.patch(
    "/me/password",
    status_code=204,
    responses={401: {"model": ErrorResponse}, 204: {"description": "密码已更新"}},
)
async def change_password(
    request: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
) -> Response:
    await service.change_password(user, request.current_password, request.new_password)
    return Response(status_code=204)


from .api_key.routes import user_api_router
from .translation_memory.routes import user_translation_memory_router

auth_router.include_router(user_api_router)
auth_router.include_router(user_translation_memory_router)
