"""Framework-independent cryptographic helpers used by application services."""

from __future__ import annotations

import hashlib
from typing import Any

import jwt
from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from pwdlib import PasswordHash

from ..domain.auth.value_objects import AccessTokenClaims
from .config import app_settings, security_settings


_password_hash = PasswordHash.recommended()
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{app_settings.api_prefix}/auth/login",
    auto_error=False,
)
_auth_service = None
_api_key_service = None


def hash_password(password: str) -> str:
    """Hash a plaintext password with the configured password-hashing algorithm."""
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a plaintext password against a stored password hash."""
    try:
        return _password_hash.verify(password, password_hash)
    except (ValueError, TypeError):
        return False


def hash_refresh_token(value: str) -> str:
    """Return the one-way database representation of a refresh token."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def create_access_token(claims: AccessTokenClaims) -> str:
    """Encode access-token claims using the configured signing secret."""
    return jwt.encode(
        claims.as_payload(),
        security_settings.auth_jwt_secret,
        algorithm="HS256",
    )


def decode_access_token(access_token: str) -> dict[str, Any]:
    """Decode and signature-verify an access token, requiring its core claims."""
    return jwt.decode(
        access_token,
        security_settings.auth_jwt_secret,
        algorithms=["HS256"],
        options={"require": ["sub", "exp", "type"]},
    )


def get_auth_service():
    """Return the shared authentication application service."""
    global _auth_service
    if _auth_service is None:
        from ..application.auth.service import AuthService

        _auth_service = AuthService()
    return _auth_service


async def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    service=Depends(get_auth_service),
):
    """Resolve and validate the authenticated user from the bearer token."""
    if not token:
        from ..application.auth.service import AuthError

        raise AuthError("UNAUTHORIZED", "需要登录")
    return await service.user_from_access_token(token)


def get_api_key_service():
    """Return the shared user API-key application service."""
    global _api_key_service
    if _api_key_service is None:
        from ..application.auth.api_key.service import ApiKeyService

        _api_key_service = ApiKeyService()
    return _api_key_service


__all__ = [
    "create_access_token",
    "decode_access_token",
    "hash_password",
    "hash_refresh_token",
    "verify_password",
    "get_api_key_service",
    "get_auth_service",
    "get_current_user",
    "oauth2_scheme",
]
