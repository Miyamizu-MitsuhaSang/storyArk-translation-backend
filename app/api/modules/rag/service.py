"""Compatibility exports for the legacy RAG service import path."""

from translation_backend.app.application.rag.service import (
    ProjectId,
    RagIndexNotBuiltError,
    RagService,
    clear_project,
    get_rag_service,
    index_project,
    search_project,
)

__all__ = [
    "RagIndexNotBuiltError",
    "RagService",
    "clear_project",
    "get_rag_service",
    "index_project",
    "search_project",
]
