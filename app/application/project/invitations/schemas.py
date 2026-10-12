from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

ProjectRole = Literal["manager", "translator", "reviewer", "viewer"]
InvitationStatus = Literal["pending", "accepted", "declined", "revoked", "expired"]
InviteCodeStatus = Literal["active", "revoked", "expired", "exhausted"]


class CreateProjectInvitationRequest(BaseModel):
    user_id: UUID = Field(description="已注册的目标用户 ID。")
    role: ProjectRole = Field(default="translator", description="接受邀请后授予的项目角色。")
    expires_in: int = Field(default=259200, ge=3600, le=604800, description="邀请有效秒数，默认 72 小时。")


class CreateInviteCodeRequest(BaseModel):
    role: ProjectRole = Field(default="translator", description="兑换后授予的项目角色。")
    expires_in: int = Field(default=259200, ge=3600, le=604800, description="邀请码有效秒数，默认 72 小时。")
    max_uses: int = Field(default=1, ge=1, le=100, description="邀请码最多兑换次数。")


class RedeemInviteCodeRequest(BaseModel):
    code: str = Field(min_length=8, max_length=128, description="项目邀请码明文。")


class UserCandidateResponse(BaseModel):
    id: UUID
    username: str
    display_name: str
    email_masked: str


class UserCandidatePage(BaseModel):
    items: list[UserCandidateResponse]
    next_cursor: str | None = None
    total: int


class ProjectInvitationResponse(BaseModel):
    id: UUID
    project_id: UUID
    project_name: str
    invited_by_user_id: UUID
    target_user_id: UUID
    role: str
    status: InvitationStatus
    expires_at: datetime
    accepted_at: datetime | None = None
    declined_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime


class InvitationPage(BaseModel):
    items: list[ProjectInvitationResponse]
    next_cursor: str | None = None
    total: int


class ProjectInvitationListQuery(BaseModel):
    status: InvitationStatus | None = Field(default=None, description="按邀请状态筛选。")
    page_size: int = Field(default=20, ge=1, le=100, description="每页返回数量。")
    cursor: str | None = Field(default=None, description="不透明分页游标。")


class ReceivedInvitationQuery(ProjectInvitationListQuery):
    """分页筛选当前用户收到的项目邀请。"""


class InviteCodeResponse(BaseModel):
    id: UUID
    project_id: UUID
    role: str
    status: InviteCodeStatus
    expires_at: datetime
    max_uses: int
    used_count: int
    code: str | None = Field(default=None, description="仅创建响应返回一次的邀请码明文。")
    created_at: datetime


class InviteCodeListQuery(BaseModel):
    status: InviteCodeStatus | None = Field(default=None, description="按邀请码状态筛选。")
    page_size: int = Field(default=20, ge=1, le=100, description="每页返回数量。")
    cursor: str | None = Field(default=None, description="不透明分页游标。")


class InviteCodePage(BaseModel):
    items: list[InviteCodeResponse]
    next_cursor: str | None = None
    total: int


__all__ = [
    "CreateInviteCodeRequest",
    "CreateProjectInvitationRequest",
    "InviteCodeResponse",
    "InviteCodeListQuery",
    "InviteCodePage",
    "InviteCodeStatus",
    "InvitationPage",
    "ProjectInvitationListQuery",
    "ReceivedInvitationQuery",
    "ProjectInvitationResponse",
    "RedeemInviteCodeRequest",
    "UserCandidatePage",
    "UserCandidateResponse",
]
