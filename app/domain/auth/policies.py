"""Pure authentication policies."""

from __future__ import annotations

from ..shared.errors import DomainError


class PasswordPolicy:
    minimum_length = 8
    maximum_length = 256

    @classmethod
    def validate_length(cls, password: str) -> None:
        if not cls.minimum_length <= len(password) <= cls.maximum_length:
            raise DomainError(
                "密码长度必须在 8 到 256 个字符之间",
                code="PASSWORD_LENGTH_INVALID",
            )


class TokenPolicy:
    @staticmethod
    def access_ttl_seconds(configured_seconds: int) -> int:
        if configured_seconds <= 0:
            raise DomainError("访问令牌有效期必须为正数", code="TOKEN_TTL_INVALID")
        return configured_seconds

    @staticmethod
    def refresh_ttl_days(configured_days: int, remember_me: bool) -> int:
        if configured_days <= 0:
            raise DomainError("刷新令牌有效期必须为正数", code="TOKEN_TTL_INVALID")
        return configured_days if remember_me else 1
