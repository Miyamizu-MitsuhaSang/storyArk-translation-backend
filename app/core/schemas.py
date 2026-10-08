from typing import Any, Generic, TypeAlias, TypeVar

from pydantic import BaseModel, Field


PageItem = TypeVar("PageItem")


class CursorPage(BaseModel, Generic[PageItem]):
    """Shared cursor pagination envelope for project-scoped list APIs."""

    items: list[PageItem]
    next_cursor: str | None
    total: int = Field(ge=0)


class ApiErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None


class ApiErrorResponse(BaseModel):
    error: ApiErrorBody


class VersionConflictDetails(BaseModel):
    current_revision: int = Field(ge=1)


SparseVector: TypeAlias = list[tuple[int, float]]


class HealthResponse(BaseModel):
    status: str
    service: str


class RagDocument(BaseModel):
    id: str = Field(min_length=1)
    text: str
    vector: SparseVector


class RagIndexRequest(BaseModel):
    project_id: str = Field(default="default", min_length=1)
    num_features: int = Field(gt=0)
    documents: list[RagDocument]


class RagIndexResponse(BaseModel):
    indexed: int
    num_features: int


class RagSearchRequest(BaseModel):
    project_id: str = Field(default="default", min_length=1)
    query: SparseVector
    top_k: int = Field(default=5, gt=0)


class RagSearchResponse(BaseModel):
    results: list[dict[str, Any]]
