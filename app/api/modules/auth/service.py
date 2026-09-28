"""Compatibility exports for the legacy auth service import path."""

from translation_backend.app.application.auth.service import AuthError, AuthService

__all__ = ["AuthError", "AuthService"]
