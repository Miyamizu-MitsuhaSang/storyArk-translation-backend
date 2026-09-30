from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import secrets
from typing import Any

import jwt

from ...domain.auth.policies import PasswordPolicy, TokenPolicy
from ...domain.auth.value_objects import AccessTokenClaims
from ...domain.shared.errors import DomainError
from ...core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from .schemas import (
    MeResponse,
    ProjectSummary,
    TokenResponse,
    UserResponse,
)
from ...core.config import security_settings
from ...models import RefreshToken, User
from ...repositories import MembershipRepository, RefreshTokenRepository, UserRepository


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
    def __init__(
        self,
        *,
        users: UserRepository | None = None,
        refresh_tokens: RefreshTokenRepository | None = None,
        memberships: MembershipRepository | None = None,
    ) -> None:
        self._users = users or UserRepository()
        self._refresh_tokens = refresh_tokens or RefreshTokenRepository()
        self._memberships = memberships or MembershipRepository()

    def hash_password(self, password: str) -> str:
        self._validate_password(password)
        return hash_password(password)

    def verify_password(self, password: str, password_hash: str) -> bool:
        return verify_password(password, password_hash)

    async def login(self, login: str, password: str, *, remember_me: bool) -> TokenResponse:
        user = await self._users.find_by_login(login)
        if user is None or not user.is_active or not self.verify_password(password, user.password_hash):
            raise AuthError("INVALID_CREDENTIALS", "用户名或密码错误")

        user.last_login_at = datetime.now(timezone.utc)
        await self._users.save(user, update_fields=["last_login_at", "updated_at"])
        return await self._issue_tokens(user, remember_me=remember_me)

    async def refresh(self, refresh_token: str) -> TokenResponse:
        token_hash = hash_refresh_token(refresh_token)
        stored = await self._refresh_tokens.find_by_hash(token_hash, with_user=True)
        now = datetime.now(timezone.utc)
        if (
            stored is None
            or stored.revoked_at is not None
            or stored.expires_at <= now
            or not stored.user.is_active
        ):
            raise AuthError("INVALID_REFRESH_TOKEN", "刷新令牌无效或已过期")

        await self._refresh_tokens.revoke(stored, revoked_at=now)
        return await self._issue_tokens(stored.user, remember_me=True)

    async def logout(self, refresh_token: str) -> None:
        stored = await self._refresh_tokens.find_by_hash(hash_refresh_token(refresh_token))
        if stored is not None and stored.revoked_at is None:
            await self._refresh_tokens.revoke(stored)

    async def user_from_access_token(self, access_token: str) -> User:
        try:
            payload = decode_access_token(access_token)
            if payload.get("type") != "access":
                raise ValueError("not an access token")
            user = await self._users.find_active(payload["sub"])
        except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
            user = None
        if user is None:
            raise AuthError("INVALID_TOKEN", "访问令牌无效或已过期")
        return user

    async def change_password(self, user: User, current_password: str, new_password: str) -> None:
        self._validate_password(new_password)
        if not self.verify_password(current_password, user.password_hash):
            raise AuthError("INVALID_CREDENTIALS", "当前密码错误")
        user.password_hash = self.hash_password(new_password)
        await self._users.save(user, update_fields=["password_hash", "updated_at"])
        await self._refresh_tokens.revoke_active_for_user(user, revoked_at=datetime.now(timezone.utc))

    async def me(self, user: User) -> MeResponse:
        memberships = await self._memberships.list_for_user(user, with_project=True)
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
        access_ttl = self._access_ttl_seconds()
        access_expires = now + timedelta(seconds=access_ttl)
        refresh_days = self._refresh_ttl_days(remember_me)
        refresh = _IssuedRefreshToken(
            value=secrets.token_urlsafe(48),
            expires_at=now + timedelta(days=refresh_days),
        )
        await self._refresh_tokens.create(
            user=user,
            token_hash=hash_refresh_token(refresh.value),
            expires_at=refresh.expires_at,
        )
        claims = AccessTokenClaims(str(user.id), now, access_expires)
        access_token = create_access_token(claims)
        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh.value,
            expires_in=access_ttl,
            user=UserResponse.model_validate(user),
        )

    @staticmethod
    def _validate_password(password: str) -> None:
        try:
            PasswordPolicy.validate_length(password)
        except DomainError as exc:
            raise ValueError(str(exc)) from exc

    @staticmethod
    def _access_ttl_seconds() -> int:
        try:
            return TokenPolicy.access_ttl_seconds(security_settings.auth_access_token_ttl_seconds)
        except DomainError as exc:
            raise ValueError(str(exc)) from exc

    @staticmethod
    def _refresh_ttl_days(remember_me: bool) -> int:
        try:
            return TokenPolicy.refresh_ttl_days(security_settings.auth_refresh_token_ttl_days, remember_me)
        except DomainError as exc:
            raise ValueError(str(exc)) from exc
