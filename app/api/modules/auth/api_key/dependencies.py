"""FastAPI dependencies for user-owned API-key management."""

from .....application.auth.api_key.service import ApiKeyService


_api_key_service: ApiKeyService | None = None


def get_api_key_service() -> ApiKeyService:
    """Return the lazily initialized user API-key service."""
    global _api_key_service
    if _api_key_service is None:
        _api_key_service = ApiKeyService()
    return _api_key_service


__all__ = ["get_api_key_service"]
