from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from starlette.responses import FileResponse, JSONResponse

from .....application.project.translation_task.schemas import TaskStatus, TranslationTaskCreateRequest, TranslationTaskPage, TranslationTaskResponse
from .....application.project.translation_task.service import TranslationTaskError, TranslationTaskService
from ....shared.dependencies import get_current_user
from .....models import User
from .dependencies import get_translation_task_service
from .....core.config import app_settings
from .....infrastructure.document.storage import LocalDocumentStorage

translation_task_router = APIRouter()


async def _handle_translation_task_error(request: Request, exc: TranslationTaskError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": str(exc), "details": exc.details, "request_id": getattr(request.state, "request_id", None)}},
    )


def register_translation_task_exception_handler(app) -> None:
    app.add_exception_handler(TranslationTaskError, _handle_translation_task_error)


@translation_task_router.get("", response_model=TranslationTaskPage, description="返回当前项目可见的翻译任务列表。")
async def list_translation_tasks(
    project_id: UUID,
    page_size: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None),
    source_language: str | None = Query(default=None, max_length=16),
    target_language: str | None = Query(default=None, max_length=16),
    status: TaskStatus | None = Query(default=None),
    version_id: UUID | None = Query(default=None),
    q: str | None = Query(default=None, max_length=160),
    user: User = Depends(get_current_user),
    service: TranslationTaskService = Depends(get_translation_task_service),
) -> TranslationTaskPage:
    return await service.list(
        user,
        project_id,
        page_size=page_size,
        cursor=cursor,
        source_language=source_language,
        target_language=target_language,
        status=status,
        version_id=version_id,
        q=q,
    )


@translation_task_router.post("", response_model=TranslationTaskResponse, status_code=201, description="创建翻译任务；任务直接引用当前用户拥有的 API key，支持 Idempotency-Key。")
async def create_translation_task(
    project_id: UUID,
    request_body: TranslationTaskCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user: User = Depends(get_current_user),
    service: TranslationTaskService = Depends(get_translation_task_service),
) -> TranslationTaskResponse:
    return await service.create(user, project_id, request_body, idempotency_key=idempotency_key)


@translation_task_router.get("/{task_id}", response_model=TranslationTaskResponse, description="返回翻译任务元数据和 worker 状态。")
async def get_translation_task(
    project_id: UUID,
    task_id: UUID,
    user: User = Depends(get_current_user),
    service: TranslationTaskService = Depends(get_translation_task_service),
) -> TranslationTaskResponse:
    return await service.get(user, project_id, task_id)


@translation_task_router.post("/{task_id}/cancel", response_model=TranslationTaskResponse, description="取消尚未完成的批量翻译任务。")
async def cancel_translation_task(
    project_id: UUID,
    task_id: UUID,
    user: User = Depends(get_current_user),
    service: TranslationTaskService = Depends(get_translation_task_service),
) -> TranslationTaskResponse:
    return await service.cancel(user, project_id, task_id)


@translation_task_router.get("/{task_id}/output", response_class=FileResponse, description="下载已进入 review 状态的批量翻译结果。")
async def download_translation_task_output(
    project_id: UUID,
    task_id: UUID,
    user: User = Depends(get_current_user),
    service: TranslationTaskService = Depends(get_translation_task_service),
) -> FileResponse:
    storage_key, file_name, _ = await service.output_file(user, project_id, task_id)
    storage = LocalDocumentStorage(app_settings.document_storage_dir)
    path = storage.path_for(storage_key=storage_key)
    if not path.is_file():
        raise TranslationTaskError("翻译任务输出文件不存在")
    return FileResponse(path, filename=file_name)


__all__ = ["register_translation_task_exception_handler", "translation_task_router"]
