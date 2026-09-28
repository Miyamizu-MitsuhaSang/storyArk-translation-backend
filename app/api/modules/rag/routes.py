from fastapi import APIRouter, Depends, HTTPException

from ....core.schemas import (
    RagIndexRequest,
    RagIndexResponse,
    RagSearchRequest,
    RagSearchResponse,
)
from ....application.rag.service import (
    RagIndexNotBuiltError,
    RagService,
    get_rag_service as get_service,
)

router = APIRouter(prefix="/rag", tags=["rag"])


def get_rag_service() -> RagService:
    return get_service()


@router.post(
    "/index",
    response_model=RagIndexResponse,
    deprecated=True,
)
def index(request: RagIndexRequest, service: RagService = Depends(get_rag_service)) -> RagIndexResponse:
    return RagIndexResponse(
        **service.index_project(
            request.project_id,
            documents=request.documents,
            num_features=request.num_features,
        )
    )


@router.post(
    "/search",
    response_model=RagSearchResponse,
    deprecated=True,
)
def search(request: RagSearchRequest, service: RagService = Depends(get_rag_service)) -> RagSearchResponse:
    try:
        results = service.search_project(request.project_id, query=request.query, top_k=request.top_k)
    except RagIndexNotBuiltError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return RagSearchResponse(results=results)
