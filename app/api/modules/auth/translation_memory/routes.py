from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from starlette.responses import JSONResponse, Response

from .....application.translation_memory.schemas import (
    TranslationMemoryEntryCreateRequest,
    TranslationMemoryEntryPage,
    TranslationMemoryEntryResponse,
    TranslationMemoryEntryUpdateRequest,
    TranslationMemoryLibraryPage,
    TranslationMemoryLibraryResponse,
    TranslationMemoryLibraryUpdateRequest,
)
from .....application.translation_memory.service import TranslationMemoryError, TranslationMemoryService
from ....shared.dependencies import get_current_user
from .....models import User
from .dependencies import get_translation_memory_service


user_translation_memory_router = APIRouter(prefix="/me/translation-memories", tags=["auth-translation-memory"])


async def _handle_translation_memory_error(request: Request, exc: TranslationMemoryError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": {"code": exc.code, "message": str(exc), "details": {}, "request_id": getattr(request.state, "request_id", None)}})


def register_translation_memory_exception_handler(app) -> None:
    app.add_exception_handler(TranslationMemoryError, _handle_translation_memory_error)


@user_translation_memory_router.get("", response_model=TranslationMemoryLibraryPage)
async def list_translation_memories(page_size: int = Query(20, ge=1, le=100), cursor: str | None = None, user: User = Depends(get_current_user), service: TranslationMemoryService = Depends(get_translation_memory_service)) -> TranslationMemoryLibraryPage:
    return await service.list_user_libraries(user, page_size, cursor)


@user_translation_memory_router.get("/{memory_id}", response_model=TranslationMemoryLibraryResponse)
async def get_translation_memory(memory_id: UUID, user: User = Depends(get_current_user), service: TranslationMemoryService = Depends(get_translation_memory_service)) -> TranslationMemoryLibraryResponse:
    return await service.get_user_library(user, memory_id)


@user_translation_memory_router.patch("/{memory_id}", response_model=TranslationMemoryLibraryResponse)
async def update_translation_memory(memory_id: UUID, request: TranslationMemoryLibraryUpdateRequest, user: User = Depends(get_current_user), service: TranslationMemoryService = Depends(get_translation_memory_service)) -> TranslationMemoryLibraryResponse:
    return await service.update_library(user, memory_id, request)


@user_translation_memory_router.get("/{memory_id}/entries", response_model=TranslationMemoryEntryPage)
async def list_translation_memory_entries(memory_id: UUID, page_size: int = Query(20, ge=1, le=100), cursor: str | None = None, user: User = Depends(get_current_user), service: TranslationMemoryService = Depends(get_translation_memory_service)) -> TranslationMemoryEntryPage:
    return await service.list_entries(user, memory_id, page_size=page_size, cursor=cursor)


@user_translation_memory_router.post("/{memory_id}/entries", response_model=TranslationMemoryEntryResponse, status_code=201)
async def create_translation_memory_entry(memory_id: UUID, request: TranslationMemoryEntryCreateRequest, user: User = Depends(get_current_user), service: TranslationMemoryService = Depends(get_translation_memory_service)) -> TranslationMemoryEntryResponse:
    return await service.create_entry(user, memory_id, request)


@user_translation_memory_router.patch("/{memory_id}/entries/{entry_id}", response_model=TranslationMemoryEntryResponse)
async def update_translation_memory_entry(memory_id: UUID, entry_id: UUID, request: TranslationMemoryEntryUpdateRequest, user: User = Depends(get_current_user), service: TranslationMemoryService = Depends(get_translation_memory_service)) -> TranslationMemoryEntryResponse:
    return await service.update_entry(user, memory_id, entry_id, request)


@user_translation_memory_router.delete("/{memory_id}/entries/{entry_id}", status_code=204)
async def archive_translation_memory_entry(memory_id: UUID, entry_id: UUID, expected_revision: int = Query(..., ge=1), user: User = Depends(get_current_user), service: TranslationMemoryService = Depends(get_translation_memory_service)) -> Response:
    await service.archive_entry(user, memory_id, entry_id, expected_revision)
    return Response(status_code=204)
