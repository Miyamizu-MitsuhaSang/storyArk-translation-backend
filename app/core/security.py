"""Framework-independent cryptographic helpers used by application services."""

from __future__ import annotations

import hashlib
from typing import Any

import jwt
from pwdlib import PasswordHash

from ..domain.auth.value_objects import AccessTokenClaims
from .config import security_settings


_password_hash = PasswordHash.recommended()


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


__all__ = [
    "create_access_token",
    "decode_access_token",
    "hash_password",
    "hash_refresh_token",
    "verify_password",
]
