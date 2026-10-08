from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.responses import Response

from ....application.jobs.schemas import JobStatusResponse
from ....application.jobs.service import JobConflictError, JobNotFoundError, JobsService
from ....application.project.document.schemas import DocumentTaskStatusResponse
from ....application.translation_memory.schemas import TranslationMemoryTaskStatusResponse
from ....models import User
from ...shared.dependencies import get_current_user
# Kept as a compatibility export for existing integrations; runtime job handling uses JobsService.
from ..project.project_content.tm.dependencies import get_translation_memory_service
from .dependencies import get_jobs_service

jobs_router = APIRouter(prefix="/jobs", tags=["jobs"])


@jobs_router.get(
    "/{job_id}",
    response_model=JobStatusResponse | TranslationMemoryTaskStatusResponse | DocumentTaskStatusResponse,
    description="返回当前用户可见的异步任务状态、进度、脱敏结果和错误信息。",
)
async def get_job_status(
    job_id: UUID,
    user: User = Depends(get_current_user),
    service: JobsService = Depends(get_jobs_service),
) -> JobStatusResponse:
    try:
        return await service.get_status(user, job_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail="后台任务不存在") from exc


@jobs_router.post(
    "/{job_id}/cancel",
    response_model=JobStatusResponse,
    description="取消当前用户可见且仍处于 queued 或 running 状态的异步任务。",
)
async def cancel_job(
    job_id: UUID,
    user: User = Depends(get_current_user),
    service: JobsService = Depends(get_jobs_service),
) -> JobStatusResponse:
    try:
        return await service.cancel(user, job_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail="后台任务不存在") from exc
    except JobConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@jobs_router.get(
    "/{job_id}/download",
    description="下载已完成且当前用户可见的文档导出结果；签名链接 15 分钟后失效。",
    responses={200: {"content": {"application/octet-stream": {}}}},
)
async def download_export(
    job_id: UUID,
    expires: int = Query(..., description="签名链接到期的 Unix 时间戳。"),
    signature: str = Query(..., min_length=64, max_length=64, description="服务端签发的短时下载签名。"),
    user: User = Depends(get_current_user),
    service: JobsService = Depends(get_jobs_service),
) -> Response:
    try:
        content, filename = await service.download_export(
            user, job_id, expires=expires, signature=signature
        )
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail="导出文件不存在") from exc
    except JobConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    safe_filename = filename.replace('"', "")
    return Response(
        content=content,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{safe_filename}"'},
    )
