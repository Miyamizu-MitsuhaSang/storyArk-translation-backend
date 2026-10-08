from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from starlette.responses import JSONResponse

from ......application.project.cat.schemas import (
    BulkActionRequest,
    BulkActionResponse,
    SegmentResponse,
    WorkflowApproveRequest,
    WorkflowConfirmRequest,
    WorkflowRejectRequest,
    WorkflowSubmitReviewRequest,
    WorkflowUnconfirmRequest,
)
from ......application.project.cat.workflow.service import CatWorkflowService
from ......models import User
from .....shared.dependencies import get_current_user
from ..dependencies import get_cat_workflow_service

cat_workflow_router = APIRouter()


@cat_workflow_router.post(
    "/segments/{segment_id}/submit-review",
    response_model=SegmentResponse,
    description="将有译文且 QA 错误已处理的 segment 从 draft/rejected 提交到 in_review。",
)
async def submit_segment_review(
    project_id: UUID,
    segment_id: UUID,
    request: WorkflowSubmitReviewRequest,
    user: User = Depends(get_current_user),
    service: CatWorkflowService = Depends(get_cat_workflow_service),
) -> SegmentResponse:
    return await service.submit_review(user, project_id, segment_id, request)


@cat_workflow_router.post(
    "/segments/{segment_id}/approve",
    response_model=SegmentResponse,
    description="由 reviewer、manager 或 owner 将 in_review segment 批准为 approved。",
)
async def approve_segment(
    project_id: UUID,
    segment_id: UUID,
    request: WorkflowApproveRequest,
    user: User = Depends(get_current_user),
    service: CatWorkflowService = Depends(get_cat_workflow_service),
) -> SegmentResponse:
    return await service.approve(user, project_id, segment_id, request)


@cat_workflow_router.post(
    "/segments/{segment_id}/reject",
    response_model=SegmentResponse,
    description="退回审核中的 segment；必须填写退回原因并保留关联 QA 问题。",
)
async def reject_segment(
    project_id: UUID,
    segment_id: UUID,
    request: WorkflowRejectRequest,
    user: User = Depends(get_current_user),
    service: CatWorkflowService = Depends(get_cat_workflow_service),
) -> SegmentResponse:
    return await service.reject(user, project_id, segment_id, request)


@cat_workflow_router.post(
    "/segments/{segment_id}/confirm",
    response_model=SegmentResponse,
    description="将 approved segment 幂等确认并写入当前用户的翻译记忆库。",
)
async def confirm_segment(
    project_id: UUID,
    segment_id: UUID,
    request: WorkflowConfirmRequest,
    user: User = Depends(get_current_user),
    service: CatWorkflowService = Depends(get_cat_workflow_service),
) -> SegmentResponse:
    return await service.confirm(user, project_id, segment_id, request)


@cat_workflow_router.post(
    "/segments/{segment_id}/unconfirm",
    response_model=SegmentResponse,
    description="由 owner 或 manager 撤销 segment 确认；不删除翻译记忆历史。",
)
async def unconfirm_segment(
    project_id: UUID,
    segment_id: UUID,
    request: WorkflowUnconfirmRequest,
    user: User = Depends(get_current_user),
    service: CatWorkflowService = Depends(get_cat_workflow_service),
) -> SegmentResponse:
    return await service.unconfirm(user, project_id, segment_id, request)


@cat_workflow_router.post(
    "/segments/bulk-action",
    response_model=BulkActionResponse,
    description="批量执行提交审核、QA、批准、退回或确认；同步批量最多处理 100 个 segment。",
)
async def bulk_segment_action(
    project_id: UUID,
    request: BulkActionRequest,
    user: User = Depends(get_current_user),
    service: CatWorkflowService = Depends(get_cat_workflow_service),
) -> BulkActionResponse | JSONResponse:
    result = await service.bulk_action(user, project_id, request)
    if result.job_id is not None:
        return JSONResponse(status_code=202, content=result.model_dump(mode="json"))
    return result


__all__ = ["cat_workflow_router"]
