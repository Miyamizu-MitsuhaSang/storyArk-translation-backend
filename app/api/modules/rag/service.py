from typing import Any

from translate_manager_rag import SparseMipsRetriever

from app.core.schemas import RagDocument, SparseVector


class RagService:
    """Application boundary around the local RAG SDK.

    Persistence, tenancy and embedding generation deliberately remain outside
    this adapter so they can be added without changing the SDK contract.
    """

    def __init__(self, retriever: SparseMipsRetriever | None = None) -> None:
        self._retriever = retriever or SparseMipsRetriever()
        self._indexed = False

    def index(self, documents: list[RagDocument], num_features: int) -> dict[str, int]:
        self._retriever.build(
            documents=[document.model_dump(exclude={"vector"}) for document in documents],
            vectors=[document.vector for document in documents],
            num_features=num_features,
        )
        self._indexed = True
        return {"indexed": len(documents), "num_features": num_features}

    def search(self, query: SparseVector, top_k: int) -> list[dict[str, Any]]:
        if not self._indexed:
            raise RuntimeError("RAG index has not been built")
        return self._retriever.search(query=query, top_k=top_k)
