"""FastAPI dependencies for project worldview APIs."""

from ......application.project.worldview.service import WorldviewService


_worldview_service = WorldviewService()


def get_worldview_service() -> WorldviewService:
    """Return the shared worldview application service."""
    return _worldview_service


__all__ = ["get_worldview_service"]
