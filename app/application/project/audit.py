from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from ...models import ProjectAuditEvent, User
from ...repositories import MembershipRepository
from .service import ProjectNotFoundError


class AuditEventResponse(BaseModel):
    id: UUID = Field(description="审计事件 ID。")
    actor_user_id: UUID | None = Field(description="操作者用户 ID 快照。")
    resource_type: str = Field(description="资源类型。")
    resource_id: UUID | None = Field(description="资源 ID 快照。")
    action: str = Field(description="业务动作标识。")
    details: dict = Field(description="脱敏后的业务摘要。")
    created_at: datetime = Field(description="事件发生时间。")


class AuditEventPage(BaseModel):
    items: list[AuditEventResponse] = Field(description="按时间倒序排列的审计事件。")
    next_cursor: str | None = Field(description="下一页游标。")
    total: int = Field(description="符合条件的事件总数。")


class ProjectAuditService:
    def __init__(self, memberships: MembershipRepository | None = None) -> None:
        self._memberships = memberships or MembershipRepository()

    @staticmethod
    async def record(
        project_id: UUID,
        *,
        actor_user_id: UUID | None,
        resource_type: str,
        resource_id: UUID | None,
        action: str,
        details: dict | None = None,
    ) -> ProjectAuditEvent:
        return await ProjectAuditEvent.create(
            project_id=project_id,
            actor_user_id=actor_user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            action=action,
            details=details or {},
        )

    async def list_events(
        self,
        user: User,
        project_id: UUID,
        *,
        actor_user_id: UUID | None = None,
        resource_type: str | None = None,
        action: str | None = None,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
        page_size: int = 20,
        cursor: str | None = None,
    ) -> AuditEventPage:
        if await self._memberships.find(project_id, user.id) is None:
            raise ProjectNotFoundError("项目不存在或当前用户不可见")
        query = ProjectAuditEvent.filter(project_id=project_id)
        if actor_user_id is not None:
            query = query.filter(actor_user_id=actor_user_id)
        if resource_type:
            query = query.filter(resource_type=resource_type)
        if action:
            query = query.filter(action=action)
        if from_time:
            query = query.filter(created_at__gte=from_time)
        if to_time:
            query = query.filter(created_at__lte=to_time)
        total = await query.count()
        try:
            offset = int(cursor or "0")
        except ValueError as exc:
            raise ValueError("cursor 格式无效") from exc
        if offset < 0:
            raise ValueError("cursor 格式无效")
        rows = await query.order_by("-created_at", "-id").offset(offset).limit(page_size)
        next_offset = offset + len(rows)
        return AuditEventPage(
            items=[AuditEventResponse.model_validate(row, from_attributes=True) for row in rows],
            next_cursor=str(next_offset) if next_offset < total else None,
            total=total,
        )


__all__ = ["AuditEventPage", "AuditEventResponse", "ProjectAuditService"]
