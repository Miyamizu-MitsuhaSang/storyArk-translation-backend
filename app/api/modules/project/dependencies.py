"""FastAPI dependencies for project routes."""

from ....application.project.service import ProjectService


_project_service = ProjectService()


def get_project_service() -> ProjectService:
    """Return the shared project application service."""
    return _project_service


__all__ = ["get_project_service"]
