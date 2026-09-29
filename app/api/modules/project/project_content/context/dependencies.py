"""FastAPI dependencies for project context APIs."""

from ......application.project.context.service import ContextService


_context_service = ContextService()


def get_context_service() -> ContextService:
    """Return the shared project context application service."""
    return _context_service


__all__ = ["get_context_service"]
