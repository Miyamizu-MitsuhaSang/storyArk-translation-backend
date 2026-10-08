from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from .....core.config import app_settings
from .....models import BackgroundJob, DocumentSegment, User
from ...audit import ProjectAuditService
from .....repositories import CatRepository, MembershipRepository
from ....translation_memory.service import TranslationMemoryService
from ..schemas import (
    BulkActionRequest,
    BulkActionResponse,
    QARequest,
    SegmentResponse,
    WorkflowApproveRequest,
    WorkflowConfirmRequest,
    WorkflowRejectRequest,
    WorkflowSubmitReviewRequest,
    WorkflowUnconfirmRequest,
)
from ..workbench.service import (
    CatError,
    CatForbiddenError,
    CatLockedError,
    CatNotFoundError,
    CatStateConflictError,
    CatValidationError,
    CatVersionConflictError,
    CatWorkbenchService,
)


class CatWorkflowService(CatWorkbenchService):
    def __init__(
        self,
        *,
        repository: CatRepository | None = None,
        memberships: MembershipRepository | None = None,
        translation_memory: TranslationMemoryService | None = None,
        workbench: CatWorkbenchService | None = None,
    ) -> None:
        super().__init__(repository=repository, memberships=memberships, translation_memory=translation_memory)
        if workbench is not None:
            self._workbench = workbench
        else:
            self._workbench = self

    async def submit_review(self, user: User, project_id: UUID, segment_id: UUID, request: WorkflowSubmitReviewRequest) -> SegmentResponse:
        membership = await self._membership(user, project_id)
        segment = await self._segment(project_id, segment_id)
        self._ensure_version(segment, request.version)
        self._ensure_owned_lock(await self._active_lock(segment.id), user, request.lock_token)
        if not segment.target_text or not segment.target_text.strip():
            raise CatStateConflictError("译文不能为空")
        if segment.workflow_state not in {"draft", "rejected"} or segment.status not in {"translated", "rejected"}:
            raise CatStateConflictError("当前状态不能提交审核")
        if self._qa_has_errors(segment):
            raise CatStateConflictError("存在未处理的 QA 错误")
        segment.status = "reviewed"
        segment.workflow_state = "in_review"
        segment.version += 1
        self._record_change(segment, "submit_review", user.id)
        await self._repository.save_segment(segment, update_fields=["status", "workflow_state", "version", "change_history"])
        await ProjectAuditService.record(
            project_id, actor_user_id=user.id, resource_type="segment", resource_id=segment.id,
            action="segment.submit_review",
        )
        return self._segment_response(segment)

    async def approve(self, user: User, project_id: UUID, segment_id: UUID, request: WorkflowApproveRequest) -> SegmentResponse:
        await self._require_reviewer(user, project_id)
        segment = await self._segment(project_id, segment_id)
        self._ensure_version(segment, request.version)
        if segment.workflow_state != "in_review":
            raise CatStateConflictError("只有审核中的片段可以批准")
        segment.status = "approved"
        segment.workflow_state = "approved"
        segment.version += 1
        if request.comment:
            notes = list(segment.review_notes or [])
            notes.append({"type": "approve", "text": request.comment, "user_id": str(user.id), "created_at": datetime.now(timezone.utc).isoformat()})
            segment.review_notes = notes[-20:]
        self._record_change(segment, "approve", user.id)
        await self._repository.save_segment(segment, update_fields=["status", "workflow_state", "version", "review_notes", "change_history"])
        await ProjectAuditService.record(
            project_id, actor_user_id=user.id, resource_type="segment", resource_id=segment.id,
            action="segment.approved",
        )
        return self._segment_response(segment)

    async def reject(self, user: User, project_id: UUID, segment_id: UUID, request: WorkflowRejectRequest) -> SegmentResponse:
        await self._require_reviewer(user, project_id)
        segment = await self._segment(project_id, segment_id)
        self._ensure_version(segment, request.version)
        if segment.workflow_state != "in_review":
            raise CatStateConflictError("只有审核中的片段可以退回")
        segment.status = "rejected"
        segment.workflow_state = "rejected"
        segment.version += 1
        notes = list(segment.review_notes or [])
        notes.append({"type": "reject", "text": request.reason, "issue_ids": request.issue_ids, "user_id": str(user.id), "created_at": datetime.now(timezone.utc).isoformat()})
        segment.review_notes = notes[-20:]
        self._record_change(segment, "reject", user.id)
        await self._repository.save_segment(segment, update_fields=["status", "workflow_state", "version", "review_notes", "change_history"])
        await ProjectAuditService.record(
            project_id, actor_user_id=user.id, resource_type="segment", resource_id=segment.id,
            action="segment.rejected",
        )
        return self._segment_response(segment)

    async def confirm(self, user: User, project_id: UUID, segment_id: UUID, request: WorkflowConfirmRequest) -> SegmentResponse:
        await self._require_reviewer(user, project_id)
        segment = await self._segment(project_id, segment_id)
        self._ensure_version(segment, request.version)
        if segment.status == "confirmed":
            return self._segment_response(segment)
        if segment.workflow_state != "approved" or not segment.target_text:
            raise CatStateConflictError("只有已批准且有译文的片段可以确认")
        await self._translation_memory.upsert_confirmed_segment(
            user,
            project_id,
            segment.document_id,
            segment.id,
            segment.source_language,
            segment.target_language,
            segment.source_text,
            segment.target_text,
        )
        segment.status = "confirmed"
        segment.workflow_state = "approved"
        segment.version += 1
        self._record_change(segment, "confirm", user.id)
        await self._repository.save_segment(segment, update_fields=["status", "workflow_state", "version", "change_history"])
        await ProjectAuditService.record(
            project_id, actor_user_id=user.id, resource_type="segment", resource_id=segment.id,
            action="segment.confirmed",
        )
        return self._segment_response(segment)

    async def unconfirm(self, user: User, project_id: UUID, segment_id: UUID, request: WorkflowUnconfirmRequest) -> SegmentResponse:
        membership = await self._membership(user, project_id)
        if membership.role not in {"owner", "manager"}:
            raise CatForbiddenError("当前角色没有撤销确认权限")
        segment = await self._segment(project_id, segment_id)
        self._ensure_version(segment, request.version)
        if segment.status != "confirmed":
            raise CatStateConflictError("当前片段未确认")
        segment.status = "approved"
        segment.workflow_state = "approved"
        segment.version += 1
        self._record_change(segment, "unconfirm", user.id)
        await self._repository.save_segment(segment, update_fields=["status", "workflow_state", "version", "change_history"])
        await self._translation_memory.invalidate_confirmed_segment(user, segment.id)
        await ProjectAuditService.record(
            project_id, actor_user_id=user.id, resource_type="segment", resource_id=segment.id,
            action="segment.unconfirmed",
        )
        return self._segment_response(segment)

    async def bulk_action(self, user: User, project_id: UUID, request: BulkActionRequest) -> BulkActionResponse:
        if len(request.segment_ids) > 100:
            job = await BackgroundJob.create(
                type="cat_bulk_action",
                status="queued",
                resource_type="project",
                resource_id=project_id,
                requested_version=1,
                result={"user_id": str(user.id), "request": request.model_dump(mode="json")},
            )
            if app_settings.cat_tasks_enabled:
                from .....tasks.cat import process_cat_bulk_action_task

                try:
                    await asyncio.to_thread(
                        process_cat_bulk_action_task.apply_async,
                        args=[str(job.id)],
                        task_id=str(job.id),
                    )
                except Exception as exc:
                    job.status = "failed"
                    job.error_code = "CAT_TASK_DISPATCH_FAILED"
                    job.error_message = "CAT 批量任务队列暂时不可用"
                    await job.save(update_fields=["status", "error_code", "error_message", "updated_at"])
                    raise CatError("CAT 批量任务队列暂时不可用") from exc
            return BulkActionResponse(affected=0, items=[], job_id=job.id)
        if len(set(request.segment_ids)) != len(request.segment_ids):
            raise CatValidationError("segment_ids 不能重复")
        items: list[SegmentResponse] = []
        for segment_id in request.segment_ids:
            version = request.expected_versions.get(segment_id)
            if version is None:
                raise CatValidationError("expected_versions 缺少片段版本")
            if request.action == "submit_review":
                lock = await self._active_lock(segment_id)
                if lock is None or lock.user_id != user.id:
                    raise CatLockedError("批量提交审核要求当前用户持有所有片段锁")
                item = await self.submit_review(user, project_id, segment_id, WorkflowSubmitReviewRequest(version=version, lock_token=lock.lock_token))
            elif request.action == "approve":
                item = await self.approve(user, project_id, segment_id, WorkflowApproveRequest(version=version))
            elif request.action == "reject":
                if not request.confirm:
                    raise CatValidationError("批量退回必须确认")
                from ..schemas import WorkflowRejectRequest

                item = await self.reject(user, project_id, segment_id, WorkflowRejectRequest(version=version, reason="批量退回"))
            elif request.action == "confirm":
                if not request.confirm:
                    raise CatValidationError("批量确认必须确认")
                item = await self.confirm(user, project_id, segment_id, WorkflowConfirmRequest(version=version))
            else:
                await self._workbench.qa(user, project_id, segment_id, QARequest(save_results=True))
                segment = await self._segment(project_id, segment_id)
                item = self._segment_response(segment)
            items.append(item)
        return BulkActionResponse(affected=len(items), items=items)

    async def _require_reviewer(self, user: User, project_id: UUID) -> None:
        membership = await self._membership(user, project_id)
        if membership.role not in {"owner", "manager", "reviewer"}:
            raise CatForbiddenError("当前角色没有审核工作流权限")

    @staticmethod
    def _qa_has_errors(segment: DocumentSegment) -> bool:
        summary = (segment.qa_results or {}).get("summary", {})
        return int(summary.get("error", 0)) > 0


__all__ = ["CatWorkflowService"]
