"""FastAPI dependencies shared by multiple API modules."""

from __future__ import annotations

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer

from ...application.auth.service import AuthError, AuthService
from ...core.config import app_settings
from ...models import User


oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{app_settings.api_prefix}/auth/login",
    auto_error=False,
)
_auth_service = AuthService()


def get_auth_service() -> AuthService:
    """Return the shared authentication application service."""
    return _auth_service


async def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    service: AuthService = Depends(get_auth_service),
) -> User:
    """Resolve and validate the authenticated user from the bearer token."""
    if not token:
        raise AuthError("UNAUTHORIZED", "需要登录")
    return await service.user_from_access_token(token)


__all__ = ["get_auth_service", "get_current_user", "oauth2_scheme"]
