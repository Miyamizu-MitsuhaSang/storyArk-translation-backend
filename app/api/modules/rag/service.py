"""Compatibility exports for the RAG application service."""

from ....application.rag.service import (
    ProjectId,
    RagIndexNotBuiltError,
    RagService,
    clear_project,
    get_rag_service,
    index_project,
    search_project,
)

__all__ = [
    "ProjectId",
    "RagIndexNotBuiltError",
    "RagService",
    "clear_project",
    "get_rag_service",
    "index_project",
    "search_project",
]
