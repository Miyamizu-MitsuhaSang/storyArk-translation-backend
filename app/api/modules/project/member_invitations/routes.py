from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from starlette.responses import Response

from .....application.idempotency import execute_idempotently
from .....application.project.invitations.schemas import (
    CreateInviteCodeRequest,
    CreateProjectInvitationRequest,
    InviteCodeListQuery,
    InviteCodePage,
    InviteCodeResponse,
    InvitationPage,
    ProjectInvitationListQuery,
    ProjectInvitationResponse,
    RedeemInviteCodeRequest,
    ReceivedInvitationQuery,
    UserCandidatePage,
)
from .....application.project.invitations.service import ProjectInvitationService
from .....application.project.schemas import ProjectMemberResponse
from .....models import User
from ....shared.dependencies import get_current_user
from .dependencies import get_project_invitation_service

project_member_invitation_router = APIRouter(tags=["project-member-invitations"])
user_project_invitation_router = APIRouter(tags=["project-member-invitations"])


@project_member_invitation_router.get(
    "/{project_id}/member-candidates",
    response_model=UserCandidatePage,
    description="搜索项目外的已注册用户；只有明确允许被搜索的 active 用户才会返回，搜索结果不泄露隐私设置。",
)
async def list_member_candidates(
    project_id: UUID,
    q: str = Query(..., min_length=2, max_length=160, description="用户名、邮箱或显示名称关键词。"),
    user: User = Depends(get_current_user),
    service: ProjectInvitationService = Depends(get_project_invitation_service),
) -> UserCandidatePage:
    return await service.list_candidates(user, project_id, q=q)


@project_member_invitation_router.post(
    "/{project_id}/invitations",
    response_model=ProjectInvitationResponse,
    status_code=201,
    description="创建发给指定已注册用户的项目邀请；需要 owner 或 manager，创建不会立即加入项目。",
)
async def create_invitation(
    project_id: UUID,
    request: CreateProjectInvitationRequest,
    user: User = Depends(get_current_user),
    service: ProjectInvitationService = Depends(get_project_invitation_service),
) -> ProjectInvitationResponse:
    return await service.create_invitation(user, project_id, request)


@project_member_invitation_router.get(
    "/{project_id}/invitations",
    response_model=InvitationPage,
    description="查询项目发出的定向邀请；需要 owner 或 manager，支持状态和游标参数。",
)
async def list_invitations(
    project_id: UUID,
    query: ProjectInvitationListQuery = Depends(),
    user: User = Depends(get_current_user),
    service: ProjectInvitationService = Depends(get_project_invitation_service),
) -> InvitationPage:
    return await service.list_project_invitations(user, project_id, query)


@project_member_invitation_router.delete(
    "/{project_id}/invitations/{invitation_id}",
    status_code=204,
    description="撤销尚未处理的定向邀请；需要 owner 或 manager。",
)
async def revoke_invitation(
    project_id: UUID,
    invitation_id: UUID,
    user: User = Depends(get_current_user),
    service: ProjectInvitationService = Depends(get_project_invitation_service),
) -> Response:
    await service.revoke_invitation(user, project_id, invitation_id)
    return Response(status_code=204)


@project_member_invitation_router.post(
    "/{project_id}/invite-codes",
    response_model=InviteCodeResponse,
    status_code=201,
    description="生成项目邀请码；需要 owner 或 manager，明文只在创建响应中返回一次。",
)
async def create_invite_code(
    project_id: UUID,
    request: CreateInviteCodeRequest,
    user: User = Depends(get_current_user),
    service: ProjectInvitationService = Depends(get_project_invitation_service),
) -> InviteCodeResponse:
    return await service.create_invite_code(user, project_id, request)


@project_member_invitation_router.get(
    "/{project_id}/invite-codes",
    response_model=InviteCodePage,
    description="查询项目邀请码摘要，不返回邀请码明文；需要 owner 或 manager。",
)
async def list_invite_codes(
    project_id: UUID,
    query: InviteCodeListQuery = Depends(),
    user: User = Depends(get_current_user),
    service: ProjectInvitationService = Depends(get_project_invitation_service),
) -> InviteCodePage:
    return await service.list_invite_codes(user, project_id, query)


@project_member_invitation_router.delete(
    "/{project_id}/invite-codes/{invite_code_id}",
    status_code=204,
    description="撤销仍可使用的邀请码；需要 owner 或 manager。",
)
async def revoke_invite_code(
    project_id: UUID,
    invite_code_id: UUID,
    user: User = Depends(get_current_user),
    service: ProjectInvitationService = Depends(get_project_invitation_service),
) -> Response:
    await service.revoke_invite_code(user, project_id, invite_code_id)
    return Response(status_code=204)


@user_project_invitation_router.get(
    "/me/project-invitations",
    response_model=InvitationPage,
    description="返回当前已登录用户收到的定向项目邀请。",
)
async def list_received_invitations(
    query: ReceivedInvitationQuery = Depends(),
    user: User = Depends(get_current_user),
    service: ProjectInvitationService = Depends(get_project_invitation_service),
) -> InvitationPage:
    return await service.list_received(user, status=query.status, page_size=query.page_size, cursor=query.cursor)


@user_project_invitation_router.post(
    "/me/project-invitations/{invitation_id}/accept",
    response_model=ProjectMemberResponse,
    description="接受发给当前用户的定向邀请并在事务内创建项目成员；支持 Idempotency-Key。",
)
async def accept_invitation(
    invitation_id: UUID,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user: User = Depends(get_current_user),
    service: ProjectInvitationService = Depends(get_project_invitation_service),
) -> ProjectMemberResponse:
    return await execute_idempotently(
        user,
        operation="project.invitation.accept",
        scope=str(invitation_id),
        key=idempotency_key,
        payload={"invitation_id": str(invitation_id)},
        response_type=ProjectMemberResponse,
        callback=lambda: service.accept_invitation(user, invitation_id),
    )


@user_project_invitation_router.post(
    "/me/project-invitations/{invitation_id}/decline",
    response_model=ProjectInvitationResponse,
    description="拒绝发给当前用户的定向邀请。",
)
async def decline_invitation(
    invitation_id: UUID,
    user: User = Depends(get_current_user),
    service: ProjectInvitationService = Depends(get_project_invitation_service),
) -> ProjectInvitationResponse:
    return await service.decline_invitation(user, invitation_id)


@user_project_invitation_router.post(
    "/me/project-invite-codes/redeem",
    response_model=ProjectInvitationResponse,
    description="由已登录用户兑换邀请码并生成待确认邀请；不会立即加入项目，需随后明确接受邀请，支持 Idempotency-Key。",
)
async def redeem_invite_code(
    request: RedeemInviteCodeRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user: User = Depends(get_current_user),
    service: ProjectInvitationService = Depends(get_project_invitation_service),
) -> ProjectInvitationResponse:
    return await execute_idempotently(
        user,
        operation="project.invite_code.redeem",
        scope=service._hash(request.code),
        key=idempotency_key,
        payload={"code": request.code},
        response_type=ProjectInvitationResponse,
        callback=lambda: service.redeem_invite_code(user, request.code),
    )


__all__ = ["project_member_invitation_router", "user_project_invitation_router"]
