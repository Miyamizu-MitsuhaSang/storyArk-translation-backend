from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from starlette.responses import JSONResponse, Response

from .....application.translation_memory.schemas import (
    TranslationMemoryEntryCreateRequest,
    TranslationMemoryEntryPage,
    TranslationMemoryEntryResponse,
    TranslationMemoryEntryUpdateRequest,
    TranslationMemoryLibraryPage,
    TranslationMemoryLibraryResponse,
    TranslationMemoryLibraryUpdateRequest,
    TranslationMemoryImportResult,
)
from .....application.translation_memory.service import TranslationMemoryError, TranslationMemoryService
from ....shared.dependencies import get_current_user
from .....models import User
from .dependencies import get_translation_memory_service


user_translation_memory_router = APIRouter(prefix="/me/translation-memories", tags=["auth-translation-memory"])


async def _handle_translation_memory_error(request: Request, exc: TranslationMemoryError) -> JSONResponse:
    headers = {"Retry-After": "5"} if exc.code == "INDEX_NOT_AVAILABLE" else None
    return JSONResponse(status_code=exc.status_code, headers=headers, content={"error": {"code": exc.code, "message": str(exc), "details": {}, "request_id": getattr(request.state, "request_id", None)}})


def register_translation_memory_exception_handler(app) -> None:
    app.add_exception_handler(TranslationMemoryError, _handle_translation_memory_error)


@user_translation_memory_router.get(
    "",
    response_model=TranslationMemoryLibraryPage,
    description="列出当前用户拥有的 user 作用域翻译记忆库，支持游标分页。",
)
async def list_translation_memories(page_size: int = Query(20, ge=1, le=100), cursor: str | None = None, user: User = Depends(get_current_user), service: TranslationMemoryService = Depends(get_translation_memory_service)) -> TranslationMemoryLibraryPage:
    return await service.list_user_libraries(user, page_size, cursor)


@user_translation_memory_router.get(
    "/{memory_id}",
    response_model=TranslationMemoryLibraryResponse,
    description="读取当前用户拥有的翻译记忆库及其统计信息。",
)
async def get_translation_memory(memory_id: UUID, user: User = Depends(get_current_user), service: TranslationMemoryService = Depends(get_translation_memory_service)) -> TranslationMemoryLibraryResponse:
    return await service.get_user_library(user, memory_id)


@user_translation_memory_router.patch(
    "/{memory_id}",
    response_model=TranslationMemoryLibraryResponse,
    description="更新当前用户翻译记忆库名称、描述或 active/archived 状态。",
)
async def update_translation_memory(memory_id: UUID, request: TranslationMemoryLibraryUpdateRequest, user: User = Depends(get_current_user), service: TranslationMemoryService = Depends(get_translation_memory_service)) -> TranslationMemoryLibraryResponse:
    return await service.update_library(user, memory_id, request)


@user_translation_memory_router.get(
    "/{memory_id}/entries",
    response_model=TranslationMemoryEntryPage,
    description="列出翻译记忆库中的活动条目，支持游标分页。",
)
async def list_translation_memory_entries(memory_id: UUID, page_size: int = Query(20, ge=1, le=100), cursor: str | None = None, user: User = Depends(get_current_user), service: TranslationMemoryService = Depends(get_translation_memory_service)) -> TranslationMemoryEntryPage:
    return await service.list_entries(user, memory_id, page_size=page_size, cursor=cursor)


@user_translation_memory_router.post(
    "/{memory_id}/entries",
    response_model=TranslationMemoryEntryResponse,
    status_code=201,
    description="向当前用户的活动翻译记忆库创建条目。",
)
async def create_translation_memory_entry(memory_id: UUID, request: TranslationMemoryEntryCreateRequest, user: User = Depends(get_current_user), service: TranslationMemoryService = Depends(get_translation_memory_service)) -> TranslationMemoryEntryResponse:
    return await service.create_entry(user, memory_id, request)


@user_translation_memory_router.patch(
    "/{memory_id}/entries/{entry_id}",
    response_model=TranslationMemoryEntryResponse,
    description="携带 expected_revision 更新条目并保留修订历史。",
)
async def update_translation_memory_entry(memory_id: UUID, entry_id: UUID, request: TranslationMemoryEntryUpdateRequest, user: User = Depends(get_current_user), service: TranslationMemoryService = Depends(get_translation_memory_service)) -> TranslationMemoryEntryResponse:
    return await service.update_entry(user, memory_id, entry_id, request)


@user_translation_memory_router.delete(
    "/{memory_id}/entries/{entry_id}",
    status_code=204,
    description="携带 expected_revision 归档条目，不物理删除历史版本。",
)
async def archive_translation_memory_entry(memory_id: UUID, entry_id: UUID, expected_revision: int = Query(..., ge=1), user: User = Depends(get_current_user), service: TranslationMemoryService = Depends(get_translation_memory_service)) -> Response:
    await service.archive_entry(user, memory_id, entry_id, expected_revision)
    return Response(status_code=204)


@user_translation_memory_router.post(
    "/{memory_id}/imports",
    response_model=TranslationMemoryImportResult,
    responses={202: {"model": TranslationMemoryImportResult, "description": "批量导入已提交后台任务。"}},
    description="使用 Idempotency-Key 批量导入条目；小批量同步处理，超过阈值返回 queued job。",
)
async def import_translation_memory_entries(
    memory_id: UUID,
    rows: list[dict[str, Any]],
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    user: User = Depends(get_current_user),
    service: TranslationMemoryService = Depends(get_translation_memory_service),
) -> TranslationMemoryImportResult:
    result = await service.import_entries(user, memory_id, rows, idempotency_key)
    if result.job is not None:
        return JSONResponse(status_code=202, content=result.model_dump(mode="json"))
    return result
