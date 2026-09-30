"""Persistence operations for authentication aggregates."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from tortoise.expressions import Q

from ..models import ProjectMember, RefreshToken, User


class UserRepository:
    async def create(self, **values) -> User:
        return await User.create(**values)

    async def find_by_login(self, login: str, *, active_only: bool = False) -> User | None:
        query = User.filter(Q(username=login) | Q(email=login))
        if active_only:
            query = query.filter(is_active=True)
        return await query.first()

    async def find_active(self, user_id: UUID | str) -> User | None:
        return await User.get_or_none(id=user_id, is_active=True)

    async def save(self, user: User, *, update_fields: list[str] | None = None) -> User:
        fields = list(dict.fromkeys([*(update_fields or []), "updated_at"]))
        await user.save(update_fields=fields)
        return user


class RefreshTokenRepository:
    async def create(self, **values) -> RefreshToken:
        return await RefreshToken.create(**values)

    async def find_by_hash(self, token_hash: str, *, with_user: bool = False) -> RefreshToken | None:
        query = RefreshToken.filter(token_hash=token_hash)
        if with_user:
            query = query.select_related("user")
        return await query.first()

    async def revoke(self, token: RefreshToken, *, revoked_at: datetime | None = None) -> RefreshToken:
        token.revoked_at = revoked_at or datetime.now(timezone.utc)
        await token.save(update_fields=["revoked_at", "updated_at"])
        return token

    async def revoke_active_for_user(self, user: User, *, revoked_at: datetime) -> int:
        return await RefreshToken.filter(user=user, revoked_at=None).update(revoked_at=revoked_at)


class MembershipRepository:
    async def find(self, project_id: UUID | str, user_id: UUID | str, *, with_project: bool = False) -> ProjectMember | None:
        query = ProjectMember.filter(project_id=project_id, user_id=user_id)
        if with_project:
            query = query.select_related("project")
        return await query.first()

    async def list_for_user(self, user: User, *, with_project: bool = False) -> list[ProjectMember]:
        query = ProjectMember.filter(user=user)
        if with_project:
            query = query.select_related("project")
        return await query
