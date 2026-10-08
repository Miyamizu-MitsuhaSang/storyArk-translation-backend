from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, Query, Request, UploadFile
from starlette.responses import JSONResponse

from .....application.project.document.schemas import (
    DocumentExportRequest,
    DocumentEnvelopeResponse,
    DocumentListQuery,
    DocumentPage,
    DocumentParseRequest,
    DocumentResponse,
    DocumentSegmentPage,
    DocumentTaskResponse,
)
from .....application.project.document.service import DocumentError, DocumentService
from ....shared.dependencies import get_current_user
from .....models import User
from .dependencies import get_document_service

project_document_router = APIRouter()


async def _handle_document_error(request: Request, exc: DocumentError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": str(exc),
                "details": {},
                "request_id": getattr(request.state, "request_id", None),
            }
        },
    )


def register_document_exception_handler(app) -> None:
    """Register document workflow errors as the shared API error shape."""
    app.add_exception_handler(DocumentError, _handle_document_error)


@project_document_router.get(
    "",
    response_model=DocumentPage,
    description="按语言对、状态、文件名和创建人分页返回当前项目可见的文档。",
)
async def list_documents(
    project_id: UUID,
    query: DocumentListQuery = Depends(),
    user: User = Depends(get_current_user),
    service: DocumentService = Depends(get_document_service),
) -> DocumentPage:
    return await service.list(user, project_id, query)


@project_document_router.post(
    "",
    response_model=DocumentTaskResponse,
    status_code=202,
    description="上传受支持的本地化文件，保存文件元数据并创建异步导入任务。",
)
async def upload_document(
    project_id: UUID,
    file: Annotated[UploadFile, File(description="XLIFF、CSV、JSON、PO 或 TXT 文件。")],
    source_language: Annotated[str, Form(description="源语言 BCP 47 标签。")],
    target_language: Annotated[str, Form(description="目标语言 BCP 47 标签。")],
    name: Annotated[str | None, Form(description="可选的项目内显示名称。")] = None,
    tm_ids: Annotated[list[UUID] | None, Form(description="可选的翻译记忆库 ID 列表。", alias="tm_ids[]")] = None,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", description="可重试上传的幂等键。"),
    user: User = Depends(get_current_user),
    service: DocumentService = Depends(get_document_service),
) -> DocumentTaskResponse:
    content = await file.read()
    return await service.upload(
        user,
        project_id,
        filename=file.filename or "upload.txt",
        content_type=file.content_type,
        content=content,
        name=name,
        source_language=source_language,
        target_language=target_language,
        translation_memory_ids=tm_ids,
        idempotency_key=idempotency_key,
    )


@project_document_router.get(
    "/{document_id}",
    response_model=DocumentResponse,
    description="返回文档状态、片段统计、语言对、版本和导入错误；不返回服务器文件路径。",
)
async def get_document(
    project_id: UUID,
    document_id: UUID,
    user: User = Depends(get_current_user),
    service: DocumentService = Depends(get_document_service),
) -> DocumentResponse:
    return await service.get(user, project_id, document_id)


@project_document_router.post(
    "/{document_id}/archive",
    response_model=DocumentEnvelopeResponse,
    description="归档项目文档，保留文件、片段、TM 来源和审计记录。",
)
async def archive_document(
    project_id: UUID,
    document_id: UUID,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", description="归档请求幂等键。"),
    user: User = Depends(get_current_user),
    service: DocumentService = Depends(get_document_service),
) -> DocumentEnvelopeResponse:
    return await service.archive(user, project_id, document_id, idempotency_key=idempotency_key)


@project_document_router.delete(
    "/{document_id}",
    response_model=DocumentTaskResponse,
    status_code=202,
    description="软删除文档并创建延迟物理清理任务；数据库记录和审计信息保留。",
)
async def delete_document(
    project_id: UUID,
    document_id: UUID,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", description="删除请求幂等键。"),
    user: User = Depends(get_current_user),
    service: DocumentService = Depends(get_document_service),
) -> DocumentTaskResponse:
    return await service.delete(user, project_id, document_id, idempotency_key=idempotency_key)


@project_document_router.post(
    "/{document_id}/parse",
    response_model=DocumentTaskResponse,
    status_code=202,
    description="重新解析文档并返回异步任务；已有译文时必须显式保留译文。",
)
async def parse_document(
    project_id: UUID,
    document_id: UUID,
    request: DocumentParseRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", description="解析请求幂等键。"),
    user: User = Depends(get_current_user),
    service: DocumentService = Depends(get_document_service),
) -> DocumentTaskResponse:
    return await service.parse(user, project_id, document_id, request, idempotency_key=idempotency_key)


@project_document_router.get(
    "/{document_id}/segments",
    response_model=DocumentSegmentPage,
    description="返回文档片段工作台列表，支持状态、分配人、关键词、编号范围和游标分页。",
)
async def list_document_segments(
    project_id: UUID,
    document_id: UUID,
    status: str | None = Query(default=None, description="按片段状态筛选。"),
    workflow_state: str | None = Query(default=None, description="按工作流状态筛选。"),
    assigned_to: UUID | None = Query(default=None, description="按分配用户筛选。"),
    q: str | None = Query(default=None, max_length=4096, description="搜索源文或译文。"),
    segment_no_from: int | None = Query(default=None, ge=1, description="起始片段编号。"),
    segment_no_to: int | None = Query(default=None, ge=1, description="结束片段编号。"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页片段数量。"),
    cursor: str | None = Query(default=None, description="不透明分页游标。"),
    sort: str = Query(default="segment_no", description="排序字段。"),
    user: User = Depends(get_current_user),
    service: DocumentService = Depends(get_document_service),
) -> DocumentSegmentPage:
    return await service.segments(
        user,
        project_id,
        document_id,
        status=status,
        workflow_state=workflow_state,
        assigned_to=assigned_to,
        q=q,
        segment_no_from=segment_no_from,
        segment_no_to=segment_no_to,
        page_size=page_size,
        cursor=cursor,
        sort=sort,
    )


@project_document_router.post(
    "/{document_id}/export",
    response_model=DocumentTaskResponse,
    status_code=202,
    description="按指定格式异步导出文档并返回后台任务 ID。",
)
async def export_document(
    project_id: UUID,
    document_id: UUID,
    request: DocumentExportRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", description="导出请求幂等键。"),
    user: User = Depends(get_current_user),
    service: DocumentService = Depends(get_document_service),
) -> DocumentTaskResponse:
    return await service.export(user, project_id, document_id, request, idempotency_key=idempotency_key)
