"""Framework-independent cryptographic helpers used by application services."""

from __future__ import annotations

import hashlib
from typing import Any

import jwt
from pwdlib import PasswordHash
from starlette.responses import JSONResponse

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


def is_secure_api_key_transport(request: Any, *, trust_forwarded_proto: bool = False) -> bool:
    """Return whether an API-key submission arrived over an authenticated HTTPS hop.

    ``X-Forwarded-Proto`` is accepted only when the deployment explicitly trusts
    its reverse proxy. Clients must never be able to opt into this behavior by
    sending the header themselves.
    """
    if getattr(getattr(request, "url", None), "scheme", "") == "https":
        return True
    if not trust_forwarded_proto:
        return False
    forwarded = request.headers.get("x-forwarded-proto", "")
    return forwarded.split(",", 1)[0].strip().lower() == "https"


def install_api_key_transport_guard(app: Any, *, path: str) -> None:
    """Reject API-key creation before FastAPI parses a plaintext request body."""

    @app.middleware("http")
    async def api_key_transport_guard(request: Any, call_next: Any) -> Any:
        from .config import security_settings

        if (
            security_settings.auth_api_key_require_https
            and request.method == "POST"
            and request.url.path == path
            and not is_secure_api_key_transport(
                request,
                trust_forwarded_proto=security_settings.auth_api_key_trust_forwarded_proto,
            )
        ):
            return JSONResponse(
                status_code=400,
                content={
                    "error": {
                        "code": "API_KEY_HTTPS_REQUIRED",
                        "message": "创建 API key 必须通过 HTTPS 传输",
                        "details": {},
                        "request_id": getattr(request.state, "request_id", None),
                    }
                },
            )
        return await call_next(request)


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
    "install_api_key_transport_guard",
    "is_secure_api_key_transport",
    "verify_password",
]
