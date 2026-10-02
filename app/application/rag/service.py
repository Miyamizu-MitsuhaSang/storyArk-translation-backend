"""Project-scoped business functions for the RAG SDK integration."""

from __future__ import annotations

from typing import Callable, TypeAlias
from uuid import UUID

from ...core.config import app_settings
from ...core.schemas import RagDocument, SparseVector
from ...infrastructure.rag.sdk_adapter import RagRetriever, RagSdkAdapter


ProjectId: TypeAlias = str | UUID


class RagIndexNotBuiltError(RuntimeError):
    """Raised when a project has no in-memory RAG index."""

    def __init__(self, project_id: ProjectId) -> None:
        self.project_id = str(project_id)
        super().__init__(f"RAG index has not been built for project {self.project_id}")


class RagService:
    """Keep project isolation and lifecycle rules above the external SDK."""

    def __init__(
        self,
        retriever_factory: Callable[[], RagRetriever] | None = None,
        *,
        candidate_threshold: float = 0.0,
    ) -> None:
        self._retriever_factory = retriever_factory
        self._candidate_threshold = candidate_threshold
        self._indexes: dict[str, RagSdkAdapter] = {}

    def _adapter_for(self, project_id: ProjectId) -> RagSdkAdapter:
        key = str(project_id)
        adapter = self._indexes.get(key)
        if adapter is None:
            retriever = self._retriever_factory() if self._retriever_factory else None
            adapter = RagSdkAdapter(
                retriever=retriever,
                candidate_threshold=self._candidate_threshold,
            )
            self._indexes[key] = adapter
        return adapter

    def index_project(
        self,
        project_id: ProjectId,
        *,
        documents: list[RagDocument],
        num_features: int,
    ) -> dict[str, int]:
        self._adapter_for(project_id).index(documents, num_features)
        return {"indexed": len(documents), "num_features": num_features}

    def search_project(
        self,
        project_id: ProjectId,
        *,
        query: SparseVector,
        top_k: int = 5,
    ) -> list[dict]:
        key = str(project_id)
        adapter = self._indexes.get(key)
        if adapter is None:
            raise RagIndexNotBuiltError(project_id)
        return adapter.search(query=query, top_k=top_k)

    def clear_project(self, project_id: ProjectId) -> None:
        self._indexes.pop(str(project_id), None)

    def index(self, documents: list[RagDocument], num_features: int) -> dict[str, int]:
        return self.index_project("default", documents=documents, num_features=num_features)

    def search(self, query: SparseVector, top_k: int = 5) -> list[dict]:
        return self.search_project("default", query=query, top_k=top_k)


_default_service = RagService(candidate_threshold=app_settings.rag_candidate_threshold)


def get_rag_service() -> RagService:
    return _default_service


def index_project(
    project_id: ProjectId,
    *,
    documents: list[RagDocument],
    num_features: int,
) -> dict[str, int]:
    return _default_service.index_project(project_id, documents=documents, num_features=num_features)


def search_project(
    project_id: ProjectId,
    *,
    query: SparseVector,
    top_k: int = 5,
) -> list[dict]:
    return _default_service.search_project(project_id, query=query, top_k=top_k)


def clear_project(project_id: ProjectId) -> None:
    _default_service.clear_project(project_id)


__all__ = [
    "ProjectId",
    "RagIndexNotBuiltError",
    "RagService",
    "clear_project",
    "get_rag_service",
    "index_project",
    "search_project",
]
