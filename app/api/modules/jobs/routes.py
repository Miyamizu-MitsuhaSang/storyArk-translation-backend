from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from ....application.translation_memory.schemas import TranslationMemoryTaskStatusResponse
from ....application.translation_memory.service import TranslationMemoryService
from ....models import User
from ...shared.dependencies import get_current_user
from ..project.project_content.translation_memory.dependencies import get_translation_memory_service

jobs_router = APIRouter(prefix="/jobs", tags=["jobs"])


@jobs_router.get(
    "/{job_id}",
    response_model=TranslationMemoryTaskStatusResponse,
    description="返回当前用户可见的翻译记忆索引任务状态及脱敏结果。",
)
async def get_job_status(
    job_id: UUID,
    user: User = Depends(get_current_user),
    service: TranslationMemoryService = Depends(get_translation_memory_service),
) -> TranslationMemoryTaskStatusResponse:
    return await service.get_job_status(user, job_id)
