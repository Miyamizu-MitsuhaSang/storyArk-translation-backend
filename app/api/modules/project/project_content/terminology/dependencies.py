"""FastAPI dependencies for project terminology APIs."""

from ......application.project.terminology.service import TerminologyService


_terminology_service = TerminologyService()


def get_terminology_service() -> TerminologyService:
    """Return the shared terminology application service."""
    return _terminology_service


__all__ = ["get_terminology_service"]
