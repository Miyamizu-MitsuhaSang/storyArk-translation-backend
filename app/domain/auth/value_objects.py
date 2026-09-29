"""Immutable authentication value objects."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class AccessTokenClaims:
    subject: str
    issued_at: datetime
    expires_at: datetime

    def as_payload(self) -> dict[str, str | datetime]:
        return {
            "sub": self.subject,
            "type": "access",
            "iat": self.issued_at,
            "exp": self.expires_at,
        }
