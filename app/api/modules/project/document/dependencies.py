"""Dependencies for project document routes."""

from .....application.project.document.service import DocumentService


_document_service = DocumentService()


def get_document_service() -> DocumentService:
    return _document_service


__all__ = ["get_document_service"]
