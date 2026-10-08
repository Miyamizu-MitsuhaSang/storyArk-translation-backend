"""FastAPI dependencies for user-owned API-key management."""

from .....core.security import get_api_key_service


__all__ = ["get_api_key_service"]
