"""FastAPI dependencies for project API-key bindings."""

from .....application.project.api_key.service import ProjectApiKeyService


_project_api_key_service = ProjectApiKeyService()


def get_project_api_key_service() -> ProjectApiKeyService:
    """Return the shared project API-key application service."""
    return _project_api_key_service


__all__ = ["get_project_api_key_service"]
