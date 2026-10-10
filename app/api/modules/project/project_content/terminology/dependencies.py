"""FastAPI dependencies for project terminology APIs."""

from ......application.project.terminology.service import TerminologyService
from ......application.project.terminology.workflows import TerminologyWorkflowService


_terminology_service = TerminologyService()


def get_terminology_service() -> TerminologyService:
    """Return the shared terminology application service."""
    return _terminology_service


_terminology_workflow_service = TerminologyWorkflowService()


def get_terminology_workflow_service() -> TerminologyWorkflowService:
    return _terminology_workflow_service


__all__ = ["get_terminology_service", "get_terminology_workflow_service"]
