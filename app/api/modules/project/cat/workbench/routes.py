from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status
from starlette.responses import Response

from ......application.project.cat.schemas import (
    QARequest,
    QAResponse,
    SegmentDetailResponse,
    SegmentLockReleaseRequest,
    SegmentLockRenewRequest,
    SegmentLockRequest,
    SegmentLockResponse,
    SegmentResponse,
    SegmentUpdateRequest,
    SuggestionRequest,
    SuggestionsResponse,
)
from ......application.project.cat.workbench.service import CatWorkbenchService
from ......models import User
from .....shared.dependencies import get_current_user
from ..dependencies import get_cat_workbench_service

cat_workbench_router = APIRouter()


@cat_workbench_router.get(
    "/segments/{segment_id}",
    response_model=SegmentDetailResponse,
    description="返回 segment、前后文、当前锁、术语命中、世界观命中和最近修改摘要。",
)
async def get_segment_detail(
    project_id: UUID,
    segment_id: UUID,
    user: User = Depends(get_current_user),
    service: CatWorkbenchService = Depends(get_cat_workbench_service),
) -> SegmentDetailResponse:
    return await service.get(user, project_id, segment_id)


@cat_workbench_router.post(
    "/segments/{segment_id}/lock",
    response_model=SegmentLockResponse,
    description="锁定 segment；同一用户重复锁定时返回当前有效锁。",
)
async def lock_segment(
    project_id: UUID,
    segment_id: UUID,
    request: SegmentLockRequest | None = None,
    user: User = Depends(get_current_user),
    service: CatWorkbenchService = Depends(get_cat_workbench_service),
) -> SegmentLockResponse:
    return await service.lock(user, project_id, segment_id, request or SegmentLockRequest())


@cat_workbench_router.post(
    "/segments/{segment_id}/lock/renew",
    response_model=SegmentLockResponse,
    description="使用 lock_token 续租当前用户持有的 segment 锁。",
)
async def renew_segment_lock(
    project_id: UUID,
    segment_id: UUID,
    request: SegmentLockRenewRequest,
    user: User = Depends(get_current_user),
    service: CatWorkbenchService = Depends(get_cat_workbench_service),
) -> SegmentLockResponse:
    return await service.renew(user, project_id, segment_id, request)


@cat_workbench_router.delete(
    "/segments/{segment_id}/lock",
    status_code=status.HTTP_204_NO_CONTENT,
    description="释放当前用户持有的 segment 锁。",
)
async def release_segment_lock(
    project_id: UUID,
    segment_id: UUID,
    request: SegmentLockReleaseRequest,
    user: User = Depends(get_current_user),
    service: CatWorkbenchService = Depends(get_cat_workbench_service),
) -> Response:
    await service.release(user, project_id, segment_id, request)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@cat_workbench_router.patch(
    "/segments/{segment_id}",
    response_model=SegmentResponse,
    description="保存译文草稿或译者备注；要求持有锁并提交当前 segment version。",
)
async def update_segment(
    project_id: UUID,
    segment_id: UUID,
    request: SegmentUpdateRequest,
    user: User = Depends(get_current_user),
    service: CatWorkbenchService = Depends(get_cat_workbench_service),
) -> SegmentResponse:
    return await service.update(user, project_id, segment_id, request)


@cat_workbench_router.post(
    "/segments/{segment_id}/suggestions",
    response_model=SuggestionsResponse,
    description="生成来自 TM、术语库和世界观的本地建议；RAG/LLM provider 本版本只返回未实现警告。",
)
async def get_segment_suggestions(
    project_id: UUID,
    segment_id: UUID,
    request: SuggestionRequest,
    user: User = Depends(get_current_user),
    service: CatWorkbenchService = Depends(get_cat_workbench_service),
) -> SuggestionsResponse:
    return await service.suggestions(user, project_id, segment_id, request)


@cat_workbench_router.post(
    "/segments/{segment_id}/qa",
    response_model=QAResponse,
    description="执行 placeholders、numbers、tags、terminology、length 和 style QA 检查，并可保存结果。",
)
async def qa_segment(
    project_id: UUID,
    segment_id: UUID,
    request: QARequest,
    user: User = Depends(get_current_user),
    service: CatWorkbenchService = Depends(get_cat_workbench_service),
) -> QAResponse:
    return await service.qa(user, project_id, segment_id, request)


__all__ = ["cat_workbench_router"]
