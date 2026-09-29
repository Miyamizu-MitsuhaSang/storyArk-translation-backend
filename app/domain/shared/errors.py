"""Errors raised by pure domain policies."""

from __future__ import annotations


class DomainError(Exception):
    """A stable, framework-independent business rule violation."""

    code = "DOMAIN_ERROR"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
