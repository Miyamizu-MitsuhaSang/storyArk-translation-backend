from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from typing import Any

import jwt
from pwdlib import PasswordHash
from tortoise.expressions import Q

from app.api.modules.auth.auth_schemas import (
    MeResponse,
    ProjectSummary,
    TokenResponse,
    UserResponse,
)
from app.core.config import app_settings
from models import ProjectMember, RefreshToken, User


class AuthError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 401,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


@dataclass(frozen=True)
class _IssuedRefreshToken:
    value: str
    expires_at: datetime


class AuthService:
    _password_hash = PasswordHash.recommended()

    def hash_password(self, password: str) -> str:
        return self._password_hash.hash(password)

    def verify_password(self, password: str, password_hash: str) -> bool:
        try:
            return self._password_hash.verify(password, password_hash)
        except (ValueError, TypeError):
            return False

    async def login(self, login: str, password: str, *, remember_me: bool) -> TokenResponse:
        user = await User.filter(Q(username=login) | Q(email=login)).first()
        if user is None or not user.is_active or not self.verify_password(password, user.password_hash):
            raise AuthError("INVALID_CREDENTIALS", "用户名或密码错误")

        user.last_login_at = datetime.now(timezone.utc)
        await user.save(update_fields=["last_login_at", "updated_at"])
        return await self._issue_tokens(user, remember_me=remember_me)

    async def refresh(self, refresh_token: str) -> TokenResponse:
        token_hash = self._hash_refresh_token(refresh_token)
        stored = await RefreshToken.filter(token_hash=token_hash).select_related("user").first()
        now = datetime.now(timezone.utc)
        if (
            stored is None
            or stored.revoked_at is not None
            or stored.expires_at <= now
            or not stored.user.is_active
        ):
            raise AuthError("INVALID_REFRESH_TOKEN", "刷新令牌无效或已过期")

        stored.revoked_at = now
        await stored.save(update_fields=["revoked_at", "updated_at"])
        return await self._issue_tokens(stored.user, remember_me=True)

    async def logout(self, refresh_token: str) -> None:
        stored = await RefreshToken.filter(token_hash=self._hash_refresh_token(refresh_token)).first()
        if stored is not None and stored.revoked_at is None:
            stored.revoked_at = datetime.now(timezone.utc)
            await stored.save(update_fields=["revoked_at", "updated_at"])

    async def user_from_access_token(self, access_token: str) -> User:
        try:
            payload = jwt.decode(
                access_token,
                app_settings.auth_jwt_secret,
                algorithms=["HS256"],
                options={"require": ["sub", "exp", "type"]},
            )
            if payload.get("type") != "access":
                raise ValueError("not an access token")
            user = await User.get_or_none(id=payload["sub"], is_active=True)
        except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
            user = None
        if user is None:
            raise AuthError("INVALID_TOKEN", "访问令牌无效或已过期")
        return user

    async def change_password(self, user: User, current_password: str, new_password: str) -> None:
        if not self.verify_password(current_password, user.password_hash):
            raise AuthError("INVALID_CREDENTIALS", "当前密码错误")
        user.password_hash = self.hash_password(new_password)
        await user.save(update_fields=["password_hash", "updated_at"])
        await RefreshToken.filter(user=user, revoked_at=None).update(
            revoked_at=datetime.now(timezone.utc)
        )

    async def me(self, user: User) -> MeResponse:
        memberships = await ProjectMember.filter(user=user).select_related("project")
        return MeResponse(
            user=UserResponse.model_validate(user),
            projects=[
                ProjectSummary(
                    id=membership.project.id,
                    name=membership.project.name,
                    description=membership.project.description,
                    status=membership.project.status,
                    role=membership.role,
                )
                for membership in memberships
            ],
        )

    async def _issue_tokens(self, user: User, *, remember_me: bool) -> TokenResponse:
        now = datetime.now(timezone.utc)
        access_expires = now + timedelta(seconds=app_settings.auth_access_token_ttl_seconds)
        refresh_days = app_settings.auth_refresh_token_ttl_days if remember_me else 1
        refresh = _IssuedRefreshToken(
            value=secrets.token_urlsafe(48),
            expires_at=now + timedelta(days=refresh_days),
        )
        await RefreshToken.create(
            user=user,
            token_hash=self._hash_refresh_token(refresh.value),
            expires_at=refresh.expires_at,
        )
        access_token = jwt.encode(
            {
                "sub": str(user.id),
                "type": "access",
                "iat": now,
                "exp": access_expires,
            },
            app_settings.auth_jwt_secret,
            algorithm="HS256",
        )
        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh.value,
            expires_in=app_settings.auth_access_token_ttl_seconds,
            user=UserResponse.model_validate(user),
        )

    @staticmethod
    def _hash_refresh_token(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()
