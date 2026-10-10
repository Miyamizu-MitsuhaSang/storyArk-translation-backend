from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse
from starlette.datastructures import UploadFile
from starlette.responses import Response

from ......application.project.terminology.schemas import (
    TerminologyBaseCreateRequest,
    TerminologyBasePage,
    TerminologyBaseResponse,
    TerminologySearchRequest,
    TerminologySearchResponse,
    TerminologyTermCreateRequest,
    TerminologyTermPage,
    TerminologyTermQuery,
    TerminologyTermResponse,
    TerminologyTermUpdateRequest,
    BulkActionRequest,
    BulkActionResponse,
    ClearResult,
    ClearRequest,
    ExportRequest,
    ExtractRequest,
    ImportResult,
    JobAccepted,
    MineRequest,
)
from ......application.project.terminology.service import TerminologyService
from ......application.project.terminology.workflows import TerminologyWorkflowService
from ......models import User
from .....shared.dependencies import get_current_user
from .dependencies import get_terminology_service, get_terminology_workflow_service


project_terminology_router = APIRouter()


@project_terminology_router.get(
    "/terminology-bases",
    response_model=TerminologyBasePage,
    description="返回当前项目的术语库列表，包括语言对、优先级、状态和术语数量；项目成员可读取。",
)
async def list_terminology_bases(
    project_id: UUID,
    page_size: int = Query(default=20, ge=1, le=100, description="每页返回数量。"),
    cursor: str | None = Query(default=None, description="不透明分页游标。"),
    user: User = Depends(get_current_user),
    service: TerminologyService = Depends(get_terminology_service),
) -> TerminologyBasePage:
    return await service.list_bases(user, project_id, page_size=page_size, cursor=cursor)


@project_terminology_router.post(
    "/terminology-bases",
    response_model=TerminologyBaseResponse,
    status_code=201,
    description="创建项目术语库；需要 owner 或 manager 角色。",
)
async def create_terminology_base(
    project_id: UUID,
    request: TerminologyBaseCreateRequest,
    user: User = Depends(get_current_user),
    service: TerminologyService = Depends(get_terminology_service),
) -> TerminologyBaseResponse:
    return await service.create_base(user, project_id, request)


@project_terminology_router.get(
    "/terminology-bases/{base_id}/terms",
    response_model=TerminologyTermPage,
    description="按关键词、术语类型、状态、目标语言和游标分页查询术语；项目成员可读取。",
)
async def list_terminology_terms(
    project_id: UUID,
    base_id: UUID,
    query: TerminologyTermQuery = Depends(),
    user: User = Depends(get_current_user),
    service: TerminologyService = Depends(get_terminology_service),
) -> TerminologyTermPage:
    return await service.list_terms(user, project_id, base_id, query)


@project_terminology_router.post(
    "/terminology-bases/{base_id}/terms",
    response_model=TerminologyTermResponse,
    status_code=201,
    description="创建术语并记录初始版本；需要 owner 或 manager 角色。",
)
async def create_terminology_term(
    project_id: UUID,
    base_id: UUID,
    request: TerminologyTermCreateRequest,
    user: User = Depends(get_current_user),
    service: TerminologyService = Depends(get_terminology_service),
) -> TerminologyTermResponse:
    return await service.create_term(user, project_id, base_id, request)


@project_terminology_router.get(
    "/terminology-bases/{base_id}/terms/{term_id}",
    response_model=TerminologyTermResponse,
    description="返回术语的语言变体、状态、来源、版本和历史摘要；项目成员可读取。",
)
async def get_terminology_term(
    project_id: UUID,
    base_id: UUID,
    term_id: UUID,
    user: User = Depends(get_current_user),
    service: TerminologyService = Depends(get_terminology_service),
) -> TerminologyTermResponse:
    return await service.get_term(user, project_id, base_id, term_id)


@project_terminology_router.patch(
    "/terminology-bases/{base_id}/terms/{term_id}",
    response_model=TerminologyTermResponse,
    description="更新术语并生成新的版本快照；需要 owner 或 manager 角色。",
)
async def update_terminology_term(
    project_id: UUID,
    base_id: UUID,
    term_id: UUID,
    request: TerminologyTermUpdateRequest,
    user: User = Depends(get_current_user),
    service: TerminologyService = Depends(get_terminology_service),
) -> TerminologyTermResponse:
    return await service.update_term(user, project_id, base_id, term_id, request)


@project_terminology_router.delete(
    "/terminology-bases/{base_id}/terms/{term_id}",
    status_code=204,
    description="软删除或归档术语并保留版本历史；需要 owner 或 manager 角色。",
)
async def delete_terminology_term(
    project_id: UUID,
    base_id: UUID,
    term_id: UUID,
    user: User = Depends(get_current_user),
    service: TerminologyService = Depends(get_terminology_service),
) -> Response:
    await service.delete_term(user, project_id, base_id, term_id)
    return Response(status_code=204)


@project_terminology_router.post(
    "/terminology/search",
    response_model=TerminologySearchResponse,
    description="在当前项目 active 术语库中查询文本命中，返回 approved、suggested 和可选 forbidden 译法及其位置。",
)
async def search_terminology(
    project_id: UUID,
    request: TerminologySearchRequest,
    user: User = Depends(get_current_user),
    service: TerminologyService = Depends(get_terminology_service),
) -> TerminologySearchResponse:
    return await service.search(user, project_id, request)


@project_terminology_router.post(
    "/terminology-bases/{base_id}/terms/import",
    response_model=ImportResult,
    description="导入 CSV 或 JSON 术语；保留行号错误并支持 update、skip、error 冲突策略。",
)
async def import_terminology_terms(
    project_id: UUID,
    base_id: UUID,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user: User = Depends(get_current_user),
    service: TerminologyWorkflowService = Depends(get_terminology_workflow_service),
) -> ImportResult:
    # JSON and multipart are accepted on the same contract path. Header is read
    # explicitly so clients cannot accidentally put an idempotency key in data.
    idempotency_key = request.headers.get("Idempotency-Key") or idempotency_key
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/"):
        form = await request.form()
        upload = form.get("file")
        if not isinstance(upload, UploadFile):
            raise ValueError("multipart 请求必须包含 file")
        payload = await upload.read()
        format_name = str(form.get("format") or (upload.filename or "").rsplit(".", 1)[-1]).casefold()
        on_conflict = str(form.get("on_conflict") or "update")
        body = TerminologyImportRequest(format=format_name, content=payload.decode("utf-8-sig"), on_conflict=on_conflict)
    else:
        body = TerminologyImportRequest.model_validate(await request.json())
    result = await service.import_terms(user, project_id, base_id, body, idempotency_key=idempotency_key)
    if result.job is not None:
        return JSONResponse(status_code=202, content=result.model_dump(mode="json"))
    return result


@project_terminology_router.post(
    "/terminology-bases/{base_id}/terms/export",
    description="导出当前项目术语；大数据集返回后台任务。",
)
async def export_terminology_terms(
    project_id: UUID,
    base_id: UUID,
    http_request: Request,
    request: ExportRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user: User = Depends(get_current_user),
    service: TerminologyWorkflowService = Depends(get_terminology_workflow_service),
):
    key = http_request.headers.get("Idempotency-Key") or idempotency_key
    result = await service.export_terms(user, project_id, base_id, request, idempotency_key=key)
    if isinstance(result, JobAccepted):
        return JSONResponse(status_code=202, content=result.model_dump(mode="json"))
    safe_filename = result.filename.replace('"', "").replace("\r", "").replace("\n", "")
    return Response(
        content=result.content,
        media_type=result.media_type,
        headers={"Content-Disposition": f'attachment; filename="{safe_filename}"'},
    )


@project_terminology_router.post(
    "/terminology-bases/{base_id}/terms/bulk-action",
    response_model=BulkActionResponse,
    description="在当前术语库中批量删除、设置必填或添加禁用译文。",
)
async def bulk_terminology_action(
    project_id: UUID,
    base_id: UUID,
    request: BulkActionRequest,
    http_request: Request,
    user: User = Depends(get_current_user),
    service: TerminologyWorkflowService = Depends(get_terminology_workflow_service),
) -> BulkActionResponse:
    return await service.bulk_action(
        user,
        project_id,
        base_id,
        request,
        idempotency_key=http_request.headers.get("Idempotency-Key"),
    )


@project_terminology_router.post(
    "/terminology-bases/{base_id}/terms/clear",
    response_model=ClearResult,
    description="清空当前术语库；需要 owner、二次确认、幂等键和精确计数。",
)
async def clear_terminology_terms(
    project_id: UUID,
    base_id: UUID,
    request: ClearRequest,
    http_request: Request,
    user: User = Depends(get_current_user),
    service: TerminologyWorkflowService = Depends(get_terminology_workflow_service),
) -> ClearResult:
    result = await service.clear(
        user,
        project_id,
        base_id,
        request,
        idempotency_key=http_request.headers.get("Idempotency-Key"),
    )
    if result.job is not None:
        return JSONResponse(status_code=202, content=result.model_dump(mode="json"))
    return result


@project_terminology_router.post(
    "/terminology/extract",
    response_model=JobAccepted,
    status_code=202,
    description="从项目文件异步提取候选术语。",
)
async def extract_terminology(
    project_id: UUID,
    request: ExtractRequest,
    http_request: Request,
    user: User = Depends(get_current_user),
    service: TerminologyWorkflowService = Depends(get_terminology_workflow_service),
) -> JobAccepted:
    return await service.extract(user, project_id, request, idempotency_key=http_request.headers.get("Idempotency-Key"))


@project_terminology_router.post(
    "/terminology/mine",
    response_model=JobAccepted,
    status_code=202,
    description="从项目可访问的翻译记忆库异步挖掘候选术语。",
)
async def mine_terminology(
    project_id: UUID,
    request: MineRequest,
    http_request: Request,
    user: User = Depends(get_current_user),
    service: TerminologyWorkflowService = Depends(get_terminology_workflow_service),
) -> JobAccepted:
    return await service.mine(user, project_id, request, idempotency_key=http_request.headers.get("Idempotency-Key"))
