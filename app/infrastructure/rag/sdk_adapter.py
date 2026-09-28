from __future__ import annotations

from typing import Any, Protocol

from translate_manager_rag import SparseMipsRetriever

from translation_backend.app.core.schemas import RagDocument, SparseVector


class RagRetriever(Protocol):
    def index(self, documents: list[RagDocument], num_features: int) -> None: ...

    def search(self, *, query: SparseVector, top_k: int) -> list[dict[str, Any]]: ...


class RagSdkAdapter:
    """First backend layer over the external storyArk RAG SDK."""

    def __init__(self, retriever: RagRetriever | None = None) -> None:
        self._retriever = retriever or SparseMipsRetriever()

    def index(self, documents: list[RagDocument], num_features: int) -> None:
        self._retriever.build(
            documents=[document.model_dump(exclude={"vector"}) for document in documents],
            vectors=[document.vector for document in documents],
            num_features=num_features,
        )

    def build(self, documents: list[RagDocument], num_features: int) -> None:
        self.index(documents, num_features)

    def search(self, query: SparseVector, top_k: int) -> list[dict[str, Any]]:
        return self._retriever.search(query=query, top_k=top_k)

