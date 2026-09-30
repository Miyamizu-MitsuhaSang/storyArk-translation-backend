from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from starlette.responses import JSONResponse

from ......application.translation_memory.schemas import (
    TranslationMemoryLibraryPage,
    TranslationMemoryReindexResponse,
    TranslationMemorySearchRequest,
    TranslationMemorySearchResponse,
)
from ......application.translation_memory.service import TranslationMemoryService
from ......models import User
from .....shared.dependencies import get_current_user
from .dependencies import get_translation_memory_service

project_translation_memory_router = APIRouter()


@project_translation_memory_router.get(
    "/translation-memories",
    response_model=TranslationMemoryLibraryPage,
    description="返回当前用户在项目中可使用的 platform 库和自己的 user 库。",
)
async def list_translation_memories(project_id: UUID, user: User = Depends(get_current_user), service: TranslationMemoryService = Depends(get_translation_memory_service)):
    return await service.list_effective_libraries(user, project_id)


@project_translation_memory_router.post(
    "/tm/search",
    response_model=TranslationMemorySearchResponse,
    description="在项目有效范围内按语言对和规范化原文精确检索翻译记忆。",
)
async def search_translation_memories(project_id: UUID, request: TranslationMemorySearchRequest, user: User = Depends(get_current_user), service: TranslationMemoryService = Depends(get_translation_memory_service)):
    return await service.search(user, project_id, request)


@project_translation_memory_router.post(
    "/translation-memories/reindex",
    response_model=list[TranslationMemoryReindexResponse],
    status_code=202,
    description="按当前可见翻译记忆库的 content_version 提交异步索引重建任务；索引后端不可用时返回 503。",
)
async def reindex_translation_memories(project_id: UUID, user: User = Depends(get_current_user), service: TranslationMemoryService = Depends(get_translation_memory_service)):
    return await service.reindex(user, project_id)
