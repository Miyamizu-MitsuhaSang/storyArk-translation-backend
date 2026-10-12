from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from starlette.responses import JSONResponse, Response

from ....application.jobs.schemas import JobListQuery, JobPage, JobStatusResponse
from ....application.jobs.service import JobConflictError, JobNotFoundError, JobsService
from ....application.project.document.schemas import DocumentTaskStatusResponse
from ....application.translation_memory.schemas import TranslationMemoryTaskStatusResponse
from ....models import User
from ...shared.dependencies import get_current_user
from .dependencies import get_jobs_service

jobs_router = APIRouter(prefix="/jobs", tags=["jobs"])


async def _handle_jobs_error(request: Request, exc: JobConflictError | JobNotFoundError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": str(exc), "details": exc.details,
                            "request_id": getattr(request.state, "request_id", None) or request.headers.get("X-Request-ID")}},
    )


def register_jobs_exception_handler(app) -> None:
    app.add_exception_handler(JobConflictError, _handle_jobs_error)
    app.add_exception_handler(JobNotFoundError, _handle_jobs_error)


@jobs_router.get(
    "",
    response_model=JobPage,
    description="分页查询当前用户可见的后台任务，支持状态、类型、项目、资源类型、时间范围和 active_only 筛选。",
)
async def list_jobs(
    query: JobListQuery = Depends(),
    user: User = Depends(get_current_user),
    service: JobsService = Depends(get_jobs_service),
) -> JobPage:
    return await service.list(user, query)


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
    return await service.get_status(user, job_id)


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
    return await service.cancel(user, job_id)


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
    content, filename = await service.download_export(user, job_id, expires=expires, signature=signature)
    safe_filename = filename.replace('"', "")
    return Response(
        content=content,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{safe_filename}"'},
    )
