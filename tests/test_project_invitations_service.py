from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from tortoise import Tortoise

from translation_backend.app.application.auth.settings.service import UserSettingsService
from translation_backend.app.application.project.invitations.schemas import (
    CreateInviteCodeRequest,
    CreateProjectInvitationRequest,
)
from translation_backend.app.application.project.invitations.service import (
    ProjectInvitationConflictError,
    ProjectInvitationNotFoundError,
    ProjectInvitationService,
)
from translation_backend.app.models import Project, ProjectInvitation, ProjectInviteCode, ProjectMember, User


def run_db_test(coro):
    async def scenario():
        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["translation_backend.app.models"]})
        await Tortoise.generate_schemas()
        try:
            return await coro()
        finally:
            await Tortoise.close_connections()

    return asyncio.run(scenario())


async def make_users():
    owner = await User.create(username=f"owner-{uuid4().hex}", email=f"owner-{uuid4().hex}@example.com", password_hash="hash", display_name="Owner")
    candidate = await User.create(username=f"candidate-{uuid4().hex}", email=f"candidate-{uuid4().hex}@example.com", password_hash="hash", display_name="Candidate")
    hidden = await User.create(username=f"hidden-{uuid4().hex}", email=f"hidden-{uuid4().hex}@example.com", password_hash="hash", display_name="Hidden")
    project = await Project.create(key=f"invite-{uuid4().hex}", name="邀请项目", created_by=owner)
    await ProjectMember.create(project=project, user=owner, role="owner")
    await UserSettingsService().update(candidate, __import__("translation_backend.app.application.auth.settings.schemas", fromlist=["UserSettingsUpdateRequest"]).UserSettingsUpdateRequest(preferences={"allow_member_search": True}))
    return owner, candidate, hidden, project


def test_candidates_only_include_registered_users_who_allow_search() -> None:
    async def scenario():
        owner, candidate, hidden, project = await make_users()
        service = ProjectInvitationService()
        candidates = await service.list_candidates(owner, project.id, q="candidate")
        assert [item.id for item in candidates.items] == [candidate.id]
        hidden_candidates = await service.list_candidates(owner, project.id, q="hidden")
        assert hidden_candidates.items == []

    run_db_test(scenario)


def test_direct_invitation_accepts_once_and_creates_member() -> None:
    async def scenario():
        owner, candidate, _, project = await make_users()
        service = ProjectInvitationService()
        invitation = await service.create_invitation(owner, project.id, CreateProjectInvitationRequest(user_id=candidate.id, role="translator"))
        accepted = await service.accept_invitation(candidate, invitation.id)
        assert accepted.user.id == candidate.id
        assert accepted.role == "translator"
        assert await ProjectMember.filter(project_id=project.id, user_id=candidate.id).count() == 1
        with pytest.raises(ProjectInvitationConflictError) as exc:
            await service.accept_invitation(candidate, invitation.id)
        assert exc.value.code == "PROJECT_MEMBER_EXISTS"

    run_db_test(scenario)


def test_invite_code_redeem_requires_explicit_acceptance() -> None:
    async def scenario():
        owner, candidate, _, project = await make_users()
        service = ProjectInvitationService()
        created = await service.create_invite_code(owner, project.id, CreateInviteCodeRequest(role="reviewer"))
        assert created.code
        redeemed = await service.redeem_invite_code(candidate, created.code)
        assert redeemed.status == "pending"
        assert await ProjectMember.filter(project_id=project.id, user_id=candidate.id).count() == 0

        accepted = await service.accept_invitation(candidate, redeemed.id)
        assert accepted.role == "reviewer"
        assert await ProjectMember.filter(project_id=project.id, user_id=candidate.id).count() == 1

        code = await ProjectInviteCode.get(id=created.id)
        assert code.used_count == 1
        assert code.status == "exhausted"
        with pytest.raises(ProjectInvitationConflictError) as exc:
            await service.redeem_invite_code(candidate, created.code)
        assert exc.value.code == "PROJECT_MEMBER_EXISTS"

    run_db_test(scenario)


def test_expired_invitation_is_not_accepted() -> None:
    async def scenario():
        owner, candidate, _, project = await make_users()
        service = ProjectInvitationService()
        response = await service.create_invitation(owner, project.id, CreateProjectInvitationRequest(user_id=candidate.id, role="viewer", expires_in=3600))
        invitation = await ProjectInvitation.get(id=response.id)
        await invitation.refresh_from_db()
        invitation.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await invitation.save(update_fields=["expires_at", "updated_at"])
        with pytest.raises(ProjectInvitationConflictError) as exc:
            await service.accept_invitation(candidate, invitation.id)
        assert exc.value.code == "PROJECT_INVITATION_EXPIRED"

    run_db_test(scenario)
