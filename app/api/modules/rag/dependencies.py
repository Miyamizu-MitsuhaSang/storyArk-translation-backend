"""FastAPI dependencies for RAG routes."""

from ....application.rag.service import RagService, get_rag_service as _get_rag_service


def get_rag_service() -> RagService:
    """Return the shared RAG application service."""
    return _get_rag_service()


__all__ = ["get_rag_service"]
