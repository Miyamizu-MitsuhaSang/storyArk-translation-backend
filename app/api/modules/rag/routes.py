from fastapi import APIRouter, Depends, HTTPException

from app.core.config import app_settings
from app.core.schemas import (
    RagIndexRequest,
    RagIndexResponse,
    RagSearchRequest,
    RagSearchResponse,
)
from app.api.modules.rag.service import RagService

router = APIRouter(prefix=f"{app_settings.api_prefix}/rag", tags=["rag"])
_rag_service = RagService()


def get_rag_service() -> RagService:
    return _rag_service


@router.post("/index", response_model=RagIndexResponse)
def index(request: RagIndexRequest, service: RagService = Depends(get_rag_service)) -> RagIndexResponse:
    return RagIndexResponse(**service.index(request.documents, request.num_features))


@router.post("/search", response_model=RagSearchResponse)
def search(request: RagSearchRequest, service: RagService = Depends(get_rag_service)) -> RagSearchResponse:
    try:
        results = service.search(request.query, request.top_k)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return RagSearchResponse(results=results)
