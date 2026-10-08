"""FastAPI dependencies shared by multiple API modules."""

from __future__ import annotations

from ...core.security import get_auth_service, get_current_user, oauth2_scheme


__all__ = ["get_auth_service", "get_current_user", "oauth2_scheme"]
