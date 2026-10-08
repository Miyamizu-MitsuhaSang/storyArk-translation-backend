"""FastAPI dependencies shared by multiple API modules."""

from __future__ import annotations

from uuid import UUID

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer

from ...application.project.shared import (
    get_project_manager as _get_project_manager,
    get_project_member as _get_project_member,
    get_project_owner as _get_project_owner,
    get_project_report_reader as _get_project_report_reader,
    require_project_member,
    require_project_role,
)
from ...application.auth.service import AuthError, AuthService
from ...core.config import app_settings
from ...models import ProjectMember, User


oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{app_settings.api_prefix}/auth/login",
    auto_error=False,
)
_auth_service: AuthService | None = None


def get_auth_service() -> AuthService:
    """Return the shared authentication application service for HTTP handlers."""
    global _auth_service
    if _auth_service is None:
        _auth_service = AuthService()
    return _auth_service


async def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    service: AuthService = Depends(get_auth_service),
) -> User:
    """Resolve the active user from the bearer token in the current request."""
    if not token:
        raise AuthError("UNAUTHORIZED", "需要登录")
    return await service.user_from_access_token(token)


async def get_project_member(
    project_id: UUID,
    user: User = Depends(get_current_user),
) -> ProjectMember:
    return await _get_project_member(project_id, user)


async def get_project_manager(
    project_id: UUID,
    user: User = Depends(get_current_user),
) -> ProjectMember:
    return await _get_project_manager(project_id, user)


async def get_project_owner(
    project_id: UUID,
    user: User = Depends(get_current_user),
) -> ProjectMember:
    return await _get_project_owner(project_id, user)


async def get_project_report_reader(
    project_id: UUID,
    user: User = Depends(get_current_user),
) -> ProjectMember:
    return await _get_project_report_reader(project_id, user)


__all__ = [
    "get_auth_service",
    "get_current_user",
    "get_project_manager",
    "get_project_member",
    "get_project_owner",
    "get_project_report_reader",
    "oauth2_scheme",
    "require_project_member",
    "require_project_role",
]
