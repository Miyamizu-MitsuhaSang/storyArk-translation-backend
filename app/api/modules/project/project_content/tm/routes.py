from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

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

project_tm_router = APIRouter()


@project_tm_router.get(
    "/translation-memories",
    response_model=TranslationMemoryLibraryPage,
    description="返回当前用户在项目中可使用的 platform 库和自己的 user 库，包括语言对、内容版本和索引状态。",
)
async def list_translation_memories(
    project_id: UUID,
    user: User = Depends(get_current_user),
    service: TranslationMemoryService = Depends(get_translation_memory_service),
) -> TranslationMemoryLibraryPage:
    return await service.list_effective_libraries(user, project_id)


@project_tm_router.post(
    "/tm/search",
    response_model=TranslationMemorySearchResponse,
    description="在项目有效 TM 范围内按语言对检索翻译记忆；支持 exact 数据库检索和已发布索引的 fuzzy 检索。",
)
async def search_translation_memories(
    project_id: UUID,
    request: TranslationMemorySearchRequest,
    user: User = Depends(get_current_user),
    service: TranslationMemoryService = Depends(get_translation_memory_service),
) -> TranslationMemorySearchResponse:
    return await service.search(user, project_id, request)


@project_tm_router.post(
    "/translation-memories/reindex",
    response_model=list[TranslationMemoryReindexResponse],
    status_code=202,
    description="按项目当前可见 TM 库的 content_version 提交异步索引重建任务；索引队列或存储不可用时返回 503。",
)
async def reindex_translation_memories(
    project_id: UUID,
    user: User = Depends(get_current_user),
    service: TranslationMemoryService = Depends(get_translation_memory_service),
) -> list[TranslationMemoryReindexResponse]:
    return await service.reindex(user, project_id)


__all__ = [
    "list_translation_memories",
    "project_tm_router",
    "reindex_translation_memories",
    "search_translation_memories",
]
