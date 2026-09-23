from typing import Any, TypeAlias

from pydantic import BaseModel, Field


SparseVector: TypeAlias = list[tuple[int, float]]


class HealthResponse(BaseModel):
    status: str
    service: str


class RagDocument(BaseModel):
    id: str = Field(min_length=1)
    text: str
    vector: SparseVector


class RagIndexRequest(BaseModel):
    num_features: int = Field(gt=0)
    documents: list[RagDocument]


class RagIndexResponse(BaseModel):
    indexed: int
    num_features: int


class RagSearchRequest(BaseModel):
    query: SparseVector
    top_k: int = Field(default=5, gt=0)


class RagSearchResponse(BaseModel):
    results: list[dict[str, Any]]
