from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from tortoise.transactions import in_transaction

from ....models import Project, ProjectInvitation, ProjectInviteCode, ProjectMember, User, UserPreferences
from ...project.schemas import ProjectMemberResponse, UserSummary
from ...project.service import ProjectError
from ..audit import ProjectAuditService
from ..shared import decode_cursor, encode_cursor
from .schemas import (
    CreateInviteCodeRequest,
    CreateProjectInvitationRequest,
    InviteCodeResponse,
    InvitationPage,
    InviteCodeListQuery,
    InviteCodePage,
    ProjectInvitationResponse,
    UserCandidatePage,
    UserCandidateResponse,
    ProjectInvitationListQuery,
)


class ProjectInvitationError(ProjectError):
    status_code = 400
    code = "PROJECT_INVITATION_ERROR"

    def __init__(self, message: str, *, code: str | None = None, status_code: int | None = None, details: dict[str, Any] | None = None):
        super().__init__(message, details=details)
        if code:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.details = details or {}


class ProjectInvitationNotFoundError(ProjectInvitationError):
    status_code = 404
    code = "PROJECT_INVITATION_NOT_FOUND"


class ProjectInvitationForbiddenError(ProjectInvitationError):
    status_code = 403
    code = "PROJECT_FORBIDDEN"


class ProjectInvitationConflictError(ProjectInvitationError):
    status_code = 409
    code = "PROJECT_INVITATION_CONFLICT"


class ProjectInvitationService:
    async def _manager_project(self, user: User, project_id: UUID) -> tuple[Project, ProjectMember]:
        membership = await ProjectMember.filter(project_id=project_id, user_id=user.id).select_related("project").first()
        if membership is None:
            raise ProjectInvitationNotFoundError("项目不存在或当前用户不可见", code="PROJECT_NOT_FOUND")
        if membership.role not in {"owner", "manager"}:
            raise ProjectInvitationForbiddenError("当前角色不能管理项目邀请")
        return membership.project, membership

    async def list_candidates(self, user: User, project_id: UUID, *, q: str) -> UserCandidatePage:
        await self._manager_project(user, project_id)
        query = q.strip()
        if len(query) < 2:
            raise ProjectInvitationError("搜索关键词至少需要 2 个字符", code="SEARCH_QUERY_TOO_SHORT", status_code=422)
        members = await ProjectMember.filter(project_id=project_id).values_list("user_id", flat=True)
        from tortoise.expressions import Q

        candidates = await User.filter(
            is_active=True,
            id__not_in=members,
            user_preferences__allow_member_search=True,
        ).filter(Q(username__icontains=query) | Q(email__icontains=query) | Q(display_name__icontains=query)).order_by("username").limit(50)
        items = [
            UserCandidateResponse(id=item.id, username=item.username, display_name=item.display_name, email_masked=self._mask_email(item.email))
            for item in candidates
        ]
        return UserCandidatePage(items=items, total=len(items), next_cursor=None)

    async def create_invitation(self, user: User, project_id: UUID, request: CreateProjectInvitationRequest) -> ProjectInvitationResponse:
        project, _ = await self._manager_project(user, project_id)
        if project.status == "archived":
            raise ProjectInvitationConflictError("归档项目不能创建邀请", code="PROJECT_ARCHIVED")
        target = await User.get_or_none(id=request.user_id, is_active=True)
        if target is None:
            raise ProjectInvitationNotFoundError("项目邀请目标不存在", code="PROJECT_INVITATION_NOT_FOUND")
        if await ProjectMember.filter(project_id=project.id, user_id=target.id).exists():
            raise ProjectInvitationConflictError("用户已经是项目成员", code="PROJECT_MEMBER_EXISTS")
        current = await ProjectInvitation.filter(project_id=project.id, target_user_id=target.id, status="pending").first()
        if current:
            return self._invitation_response(current, project)
        invitation = await ProjectInvitation.create(
            project=project,
            invited_by=user,
            target_user=target,
            role=request.role,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=request.expires_in),
        )
        await ProjectAuditService.record(
            project.id,
            actor_user_id=user.id,
            resource_type="project_invitation",
            resource_id=invitation.id,
            action="project_invitation.created",
            details={"target_user_id": str(target.id), "role": request.role},
        )
        return self._invitation_response(invitation, project)

    async def accept_invitation(self, user: User, invitation_id: UUID) -> ProjectMemberResponse:
        async with in_transaction() as connection:
            invitation = await ProjectInvitation.filter(id=invitation_id, target_user_id=user.id).using_db(connection).select_for_update().select_related("project", "invited_by", "target_user").first()
            if invitation is None:
                raise ProjectInvitationNotFoundError("项目邀请不存在")
            if await ProjectMember.filter(project_id=invitation.project_id, user_id=user.id).using_db(connection).exists():
                raise ProjectInvitationConflictError("用户已经是项目成员", code="PROJECT_MEMBER_EXISTS")
            self._refresh_status(invitation)
            if invitation.status != "pending":
                if invitation.status == "expired":
                    raise ProjectInvitationConflictError("项目邀请已过期", code="PROJECT_INVITATION_EXPIRED")
                raise ProjectInvitationConflictError("项目邀请已处理", code="PROJECT_INVITATION_CONFLICT")
            if invitation.project.status == "archived":
                raise ProjectInvitationConflictError("归档项目不能加入", code="PROJECT_ARCHIVED")
            member = await ProjectMember.create(project_id=invitation.project_id, user_id=user.id, role=invitation.role, using_db=connection)
            invitation.status = "accepted"
            invitation.accepted_at = datetime.now(timezone.utc)
            await invitation.save(using_db=connection, update_fields=["status", "accepted_at", "updated_at"])
        await ProjectAuditService.record(
            invitation.project_id,
            actor_user_id=user.id,
            resource_type="project_invitation",
            resource_id=invitation.id,
            action="project_invitation.accepted",
        )
        await member.fetch_related("user")
        return ProjectMemberResponse(user=UserSummary.model_validate(member.user), role=member.role, created_at=member.created_at)

    async def decline_invitation(self, user: User, invitation_id: UUID) -> ProjectInvitationResponse:
        invitation = await ProjectInvitation.filter(id=invitation_id, target_user_id=user.id).select_related("project").first()
        if invitation is None:
            raise ProjectInvitationNotFoundError("项目邀请不存在")
        self._refresh_status(invitation)
        if invitation.status != "pending":
            raise ProjectInvitationConflictError("项目邀请已处理")
        invitation.status = "declined"
        invitation.declined_at = datetime.now(timezone.utc)
        await invitation.save(update_fields=["status", "declined_at", "updated_at"])
        await self._release_code_slot(invitation)
        await ProjectAuditService.record(
            invitation.project_id,
            actor_user_id=user.id,
            resource_type="project_invitation",
            resource_id=invitation.id,
            action="project_invitation.declined",
        )
        return self._invitation_response(invitation, invitation.project)

    async def create_invite_code(self, user: User, project_id: UUID, request: CreateInviteCodeRequest) -> InviteCodeResponse:
        project, _ = await self._manager_project(user, project_id)
        if project.status == "archived":
            raise ProjectInvitationConflictError("归档项目不能创建邀请码", code="PROJECT_ARCHIVED")
        plain = f"SA-{secrets.token_urlsafe(12)}"
        code = await ProjectInviteCode.create(project=project, created_by=user, role=request.role, code_hash=self._hash(plain), expires_at=datetime.now(timezone.utc) + timedelta(seconds=request.expires_in), max_uses=request.max_uses)
        await ProjectAuditService.record(
            project.id,
            actor_user_id=user.id,
            resource_type="project_invite_code",
            resource_id=code.id,
            action="project_invite_code.created",
            details={"role": request.role, "max_uses": request.max_uses},
        )
        return self._code_response(code, plain)

    async def redeem_invite_code(self, user: User, plain: str) -> ProjectInvitationResponse:
        async with in_transaction() as connection:
            code = await ProjectInviteCode.filter(code_hash=self._hash(plain)).using_db(connection).select_for_update().select_related("project").first()
            if code is None:
                raise ProjectInvitationNotFoundError("邀请码不存在", code="PROJECT_INVITE_CODE_NOT_FOUND")
            now = datetime.now(timezone.utc)
            if await ProjectMember.filter(project_id=code.project_id, user_id=user.id).using_db(connection).exists():
                raise ProjectInvitationConflictError("用户已经是项目成员", code="PROJECT_MEMBER_EXISTS")
            if code.project.status == "archived":
                raise ProjectInvitationConflictError("归档项目不能加入", code="PROJECT_ARCHIVED")
            if code.status == "revoked":
                raise ProjectInvitationConflictError("邀请码已撤销", code="PROJECT_INVITE_CODE_REVOKED")
            if code.expires_at <= now:
                code.status = "expired"
                await code.save(using_db=connection, update_fields=["status", "updated_at"])
                raise ProjectInvitationConflictError("邀请码已过期", code="PROJECT_INVITE_CODE_EXPIRED")
            existing = await ProjectInvitation.filter(
                project_id=code.project_id,
                target_user_id=user.id,
                invite_code_id=code.id,
                status="pending",
            ).using_db(connection).select_related("project").first()
            if existing is not None:
                return self._invitation_response(existing, code.project)
            if code.used_count >= code.max_uses or code.status == "exhausted":
                raise ProjectInvitationConflictError("邀请码已达到使用上限", code="PROJECT_INVITE_CODE_EXHAUSTED")
            invitation = await ProjectInvitation.create(
                project_id=code.project_id,
                invited_by_id=code.created_by_id,
                target_user_id=user.id,
                invite_code_id=code.id,
                role=code.role,
                expires_at=code.expires_at,
                using_db=connection,
            )
            code.used_count += 1
            if code.used_count >= code.max_uses:
                code.status = "exhausted"
            await code.save(using_db=connection, update_fields=["used_count", "status", "updated_at"])
        await ProjectAuditService.record(
            code.project_id,
            actor_user_id=user.id,
            resource_type="project_invite_code",
            resource_id=code.id,
            action="project_invite_code.claimed",
        )
        return self._invitation_response(invitation, code.project)

    @staticmethod
    def _refresh_status(record: ProjectInvitation) -> bool:
        if record.status == "pending" and record.expires_at <= datetime.now(timezone.utc):
            record.status = "expired"
            return True
        return False

    @staticmethod
    def _refresh_code_status(record: ProjectInviteCode) -> bool:
        if record.status == "active" and record.expires_at <= datetime.now(timezone.utc):
            record.status = "expired"
            return True
        return False

    async def _release_code_slot(self, invitation: ProjectInvitation) -> None:
        if invitation.invite_code_id is None:
            return
        code = await ProjectInviteCode.get_or_none(id=invitation.invite_code_id)
        if code is None or code.used_count <= 0:
            return
        code.used_count -= 1
        code.status = "expired" if code.expires_at <= datetime.now(timezone.utc) else "active"
        await code.save(update_fields=["used_count", "status", "updated_at"])

    async def list_received(self, user: User, *, status: str | None = None, page_size: int = 20, cursor: str | None = None) -> InvitationPage:
        query = ProjectInvitation.filter(target_user_id=user.id)
        if status:
            query = query.filter(status=status)
        total = await query.count()
        offset = decode_cursor(cursor)
        rows = await query.select_related("project").order_by("-created_at").offset(offset).limit(page_size)
        for item in rows:
            if self._refresh_status(item):
                await item.save(update_fields=["status", "updated_at"])
                await self._release_code_slot(item)
        next_offset = offset + len(rows)
        return InvitationPage(items=[self._invitation_response(item, item.project) for item in rows], total=total, next_cursor=encode_cursor(next_offset) if next_offset < total else None)

    async def list_project_invitations(self, user: User, project_id: UUID, query: ProjectInvitationListQuery) -> InvitationPage:
        project, _ = await self._manager_project(user, project_id)
        rows_query = ProjectInvitation.filter(project_id=project.id)
        if query.status:
            rows_query = rows_query.filter(status=query.status)
        offset = decode_cursor(query.cursor)
        rows = await rows_query.select_related("project").order_by("-created_at").offset(offset).limit(query.page_size)
        total = await rows_query.count()
        for item in rows:
            if self._refresh_status(item):
                await item.save(update_fields=["status", "updated_at"])
                await self._release_code_slot(item)
        next_offset = offset + len(rows)
        return InvitationPage(items=[self._invitation_response(item, project) for item in rows], total=total, next_cursor=encode_cursor(next_offset) if next_offset < total else None)

    async def revoke_invitation(self, user: User, project_id: UUID, invitation_id: UUID) -> None:
        await self._manager_project(user, project_id)
        invitation = await ProjectInvitation.get_or_none(id=invitation_id, project_id=project_id)
        if invitation is None:
            raise ProjectInvitationNotFoundError("项目邀请不存在")
        if invitation.status != "pending":
            raise ProjectInvitationConflictError("只有待处理邀请可以撤销")
        invitation.status = "revoked"
        invitation.revoked_at = datetime.now(timezone.utc)
        await invitation.save(update_fields=["status", "revoked_at", "updated_at"])
        await self._release_code_slot(invitation)
        await ProjectAuditService.record(
            project_id,
            actor_user_id=user.id,
            resource_type="project_invitation",
            resource_id=invitation.id,
            action="project_invitation.revoked",
        )

    async def list_invite_codes(self, user: User, project_id: UUID, query: InviteCodeListQuery) -> InviteCodePage:
        await self._manager_project(user, project_id)
        rows_query = ProjectInviteCode.filter(project_id=project_id)
        if query.status:
            rows_query = rows_query.filter(status=query.status)
        offset = decode_cursor(query.cursor)
        rows = await rows_query.order_by("-created_at").offset(offset).limit(query.page_size)
        total = await rows_query.count()
        for row in rows:
            if self._refresh_code_status(row):
                await row.save(update_fields=["status", "updated_at"])
        next_offset = offset + len(rows)
        return InviteCodePage(items=[self._code_response(row) for row in rows], total=total, next_cursor=encode_cursor(next_offset) if next_offset < total else None)

    async def revoke_invite_code(self, user: User, project_id: UUID, invite_code_id: UUID) -> None:
        await self._manager_project(user, project_id)
        code = await ProjectInviteCode.get_or_none(id=invite_code_id, project_id=project_id)
        if code is None:
            raise ProjectInvitationNotFoundError("邀请码不存在", code="PROJECT_INVITE_CODE_NOT_FOUND")
        if code.status != "active":
            raise ProjectInvitationConflictError("只有 active 邀请码可以撤销")
        code.status = "revoked"
        code.revoked_at = datetime.now(timezone.utc)
        await code.save(update_fields=["status", "revoked_at", "updated_at"])
        await ProjectAuditService.record(
            project_id,
            actor_user_id=user.id,
            resource_type="project_invite_code",
            resource_id=code.id,
            action="project_invite_code.revoked",
        )

    @staticmethod
    def _invitation_response(invitation: ProjectInvitation, project: Project) -> ProjectInvitationResponse:
        return ProjectInvitationResponse(id=invitation.id, project_id=project.id, project_name=project.name, invited_by_user_id=invitation.invited_by_id, target_user_id=invitation.target_user_id, role=invitation.role, status=invitation.status, expires_at=invitation.expires_at, accepted_at=invitation.accepted_at, declined_at=invitation.declined_at, revoked_at=invitation.revoked_at, created_at=invitation.created_at)

    @staticmethod
    def _code_response(code: ProjectInviteCode, plain: str | None = None) -> InviteCodeResponse:
        return InviteCodeResponse(id=code.id, project_id=code.project_id, role=code.role, status=code.status, expires_at=code.expires_at, max_uses=code.max_uses, used_count=code.used_count, code=plain, created_at=code.created_at)

    @staticmethod
    def _hash(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    @staticmethod
    def _mask_email(email: str) -> str:
        local, _, domain = email.partition("@")
        return f"{local[:1]}***@{domain}" if domain else "***"


__all__ = ["ProjectInvitationConflictError", "ProjectInvitationError", "ProjectInvitationForbiddenError", "ProjectInvitationNotFoundError", "ProjectInvitationService"]
