"""Persistence operations for projects, members, and language pairs."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from tortoise import transactions
from tortoise.exceptions import IntegrityError
from tortoise.expressions import Q

from ..models import Project, ProjectLanguagePair, ProjectMember, User


class ProjectRepository:
    async def create_with_owner(
        self,
        *,
        key: str,
        name: str,
        description: str | None,
        user: User,
        language_pairs: list[tuple[str, str]],
    ) -> Project:
        async with transactions.in_transaction():
            project = await Project.create(key=key, name=name, description=description, created_by=user)
            await ProjectMember.create(project=project, user=user, role="owner")
            await ProjectLanguagePair.bulk_create(
                [
                    ProjectLanguagePair(
                        project=project,
                        source_language=source,
                        target_language=target,
                        is_default=index == 0,
                    )
                    for index, (source, target) in enumerate(language_pairs)
                ]
            )
        return project

    async def find(self, project_id: UUID | str) -> Project | None:
        return await Project.get_or_none(id=project_id)

    async def find_membership(
        self,
        project_id: UUID | str,
        user_id: UUID | str,
        *,
        with_project: bool = False,
    ) -> ProjectMember | None:
        query = ProjectMember.filter(project_id=project_id, user_id=user_id)
        if with_project:
            query = query.select_related("project")
        return await query.first()

    async def list_project_ids_for_user(self, user: User) -> list[UUID]:
        return await ProjectMember.filter(user=user).values_list("project_id", flat=True)

    async def list_for_user(
        self,
        project_ids: list[UUID],
        *,
        status: str | None = None,
        search: str | None = None,
        order_by: str = "-updated_at",
        offset: int = 0,
        limit: int | None = None,
    ) -> tuple[list[Project], int]:
        query = Project.filter(id__in=project_ids)
        if status:
            query = query.filter(status=status)
        if search:
            query = query.filter(Q(name__icontains=search) | Q(key__icontains=search))
        total = await query.count()
        query = query.order_by(order_by).offset(offset)
        if limit is not None:
            query = query.limit(limit)
        return await query, total

    async def roles_for_user(self, user: User, project_ids: list[UUID]) -> dict[str, str]:
        return {
            str(item["project_id"]): item["role"]
            for item in await ProjectMember.filter(user=user, project_id__in=project_ids).values("project_id", "role")
        }

    async def save(self, project: Project, *, update_fields: list[str]) -> Project:
        await project.save(update_fields=list(dict.fromkeys([*update_fields, "updated_at"])))
        return project

    async def list_members(
        self,
        project: Project,
        *,
        role: str | None = None,
        search: str | None = None,
        order_by: str = "-created_at",
        offset: int = 0,
        limit: int | None = None,
    ) -> tuple[list[ProjectMember], int]:
        query = ProjectMember.filter(project=project).select_related("user")
        if role:
            query = query.filter(role=role)
        if search:
            query = query.filter(
                Q(user__username__icontains=search)
                | Q(user__email__icontains=search)
                | Q(user__display_name__icontains=search)
            )
        total = await query.count()
        query = query.order_by(order_by).offset(offset)
        if limit is not None:
            query = query.limit(limit)
        return await query, total

    async def find_member(self, project: Project, user_id: UUID | str, *, with_user: bool = False) -> ProjectMember | None:
        query = ProjectMember.filter(project=project, user_id=user_id)
        if with_user:
            query = query.select_related("user")
        return await query.first()

    async def member_exists(self, project: Project, user_id: UUID | str) -> bool:
        return await ProjectMember.filter(project=project, user_id=user_id).exists()

    async def create_member(self, project: Project, user: User, *, role: str) -> ProjectMember:
        member = await ProjectMember.create(project=project, user=user, role=role)
        await member.fetch_related("user")
        return member

    async def count_owners(self, project: Project) -> int:
        return await ProjectMember.filter(project=project, role="owner").count()

    async def delete_member(self, member: ProjectMember) -> None:
        await member.delete()

    async def save_member(self, member: ProjectMember, *, update_fields: list[str]) -> ProjectMember:
        await member.save(update_fields=list(dict.fromkeys([*update_fields, "updated_at"])))
        return member

    async def count_members(self, project: Project) -> int:
        return await ProjectMember.filter(project=project).count()

    async def list_language_pairs(
        self,
        project: Project,
        *,
        offset: int = 0,
        limit: int | None = None,
    ) -> tuple[list[ProjectLanguagePair], int]:
        query = ProjectLanguagePair.filter(project=project)
        total = await query.count()
        query = query.order_by("-is_default", "created_at").offset(offset)
        if limit is not None:
            query = query.limit(limit)
        return await query, total

    async def find_language_pair(
        self,
        project: Project,
        source_language: str,
        target_language: str,
    ) -> ProjectLanguagePair | None:
        return await ProjectLanguagePair.filter(
            project=project,
            source_language=source_language,
            target_language=target_language,
        ).first()

    async def language_pair_exists(self, project: Project) -> bool:
        return await ProjectLanguagePair.filter(project=project).exists()

    async def clear_default_language_pairs(self, project: Project) -> int:
        return await ProjectLanguagePair.filter(project=project).update(is_default=False)

    async def save_language_pair(self, pair: ProjectLanguagePair, *, update_fields: list[str]) -> ProjectLanguagePair:
        await pair.save(update_fields=list(dict.fromkeys([*update_fields, "updated_at"])))
        return pair

    async def create_language_pair(self, project: Project, **values: Any) -> ProjectLanguagePair:
        return await ProjectLanguagePair.create(project=project, **values)


__all__ = ["ProjectRepository"]
