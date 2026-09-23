from fastapi import APIRouter, Depends, Request
from fastapi.security import OAuth2PasswordBearer
from starlette.responses import JSONResponse, Response

from translation_backend.app.api.modules.auth.auth_schemas import (
    ChangePasswordRequest,
    ErrorResponse,
    LoginRequest,
    MeResponse,
    RefreshRequest,
    TokenResponse,
)
from translation_backend.app.api.modules.auth.service import AuthError, AuthService
from translation_backend.app.core.config import app_settings
from translation_backend.models import User


auth_router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{app_settings.api_prefix}/auth/login",
    auto_error=False,
)
_auth_service = AuthService()


def get_auth_service() -> AuthService:
    return _auth_service


async def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    service: AuthService = Depends(get_auth_service),
) -> User:
    if not token:
        raise AuthError("UNAUTHORIZED", "需要登录")
    return await service.user_from_access_token(token)


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
