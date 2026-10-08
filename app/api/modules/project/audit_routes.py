from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from ....application.project.audit import AuditEventPage, ProjectAuditService
from ....models import User
from ...shared.dependencies import get_current_user


project_audit_router = APIRouter()


def get_project_audit_service() -> ProjectAuditService:
    return ProjectAuditService()


@project_audit_router.get(
    "/{project_id}/audit-events",
    response_model=AuditEventPage,
    description="按操作者、资源类型、动作和时间范围分页查询当前项目的脱敏审计事件。",
)
async def list_project_audit_events(
    project_id: UUID,
    actor_user_id: UUID | None = Query(default=None, description="按操作者筛选。"),
    resource_type: str | None = Query(default=None, max_length=64, description="按资源类型筛选。"),
    action: str | None = Query(default=None, max_length=96, description="按动作标识筛选。"),
    from_time: datetime | None = Query(default=None, alias="from", description="包含的起始时间。"),
    to_time: datetime | None = Query(default=None, alias="to", description="包含的结束时间。"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页事件数量。"),
    cursor: str | None = Query(default=None, description="不透明分页游标。"),
    user: User = Depends(get_current_user),
    service: ProjectAuditService = Depends(get_project_audit_service),
) -> AuditEventPage:
    if from_time and to_time and from_time > to_time:
        from fastapi import HTTPException

        raise HTTPException(status_code=422, detail="from 必须早于或等于 to")
    return await service.list_events(
        user,
        project_id,
        actor_user_id=actor_user_id,
        resource_type=resource_type,
        action=action,
        from_time=from_time,
        to_time=to_time,
        page_size=page_size,
        cursor=cursor,
    )
