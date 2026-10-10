"""Persistence operations for user and project API keys."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from ..models import AIProviderCredential, Project, ProjectApiKeyBinding, TranslationTask, User


class ApiKeyRepository:
    async def list_for_user(self, user: User, *, offset: int = 0, limit: int | None = None) -> tuple[list[AIProviderCredential], int]:
        query = AIProviderCredential.filter(user=user).order_by("-created_at")
        total = await query.count()
        query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)
        return await query, total

    async def find_owned(self, user_id: UUID | str, key_id: UUID | str) -> AIProviderCredential | None:
        return await AIProviderCredential.filter(user_id=user_id, id=key_id).first()

    async def find_active_owned(self, user_id: UUID | str, key_id: UUID | str) -> AIProviderCredential | None:
        return await AIProviderCredential.filter(user_id=user_id, id=key_id, is_active=True).first()

    async def create(self, **values: Any) -> AIProviderCredential:
        return await AIProviderCredential.create(**values)

    async def save(self, credential: AIProviderCredential, *, update_fields: list[str]) -> AIProviderCredential:
        await credential.save(update_fields=list(dict.fromkeys([*update_fields, "updated_at"])))
        return credential

    async def delete(self, credential: AIProviderCredential) -> None:
        await credential.delete()

    async def has_project_bindings(self, credential_id: UUID | str) -> bool:
        return await ProjectApiKeyBinding.filter(api_key_id=credential_id).exists()

    async def has_active_translation_tasks(self, credential_id: UUID | str) -> bool:
        return await TranslationTask.filter(
            api_key_id=credential_id,
            status__in=["queued", "translating"],
        ).exists()


class ProjectApiKeyRepository:
    async def list_for_project(self, project: Project, *, offset: int = 0, limit: int | None = None) -> tuple[list[ProjectApiKeyBinding], int]:
        query = ProjectApiKeyBinding.filter(project=project).select_related("api_key").order_by("-created_at")
        total = await query.count()
        query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)
        return await query, total

    async def find(self, project: Project, binding_id: UUID | str, *, with_key: bool = False) -> ProjectApiKeyBinding | None:
        query = ProjectApiKeyBinding.filter(id=binding_id, project=project)
        if with_key:
            query = query.select_related("api_key")
        return await query.first()

    async def find_for_key(self, project: Project, api_key: AIProviderCredential) -> ProjectApiKeyBinding | None:
        return await ProjectApiKeyBinding.filter(project=project, api_key=api_key).select_related("api_key").first()

    async def create(self, **values: Any) -> ProjectApiKeyBinding:
        binding = await ProjectApiKeyBinding.create(**values)
        await binding.fetch_related("api_key")
        return binding

    async def clear_default(self, project: Project) -> int:
        return await ProjectApiKeyBinding.filter(project=project, is_default=True).update(is_default=False)

    async def save(self, binding: ProjectApiKeyBinding, *, update_fields: list[str]) -> ProjectApiKeyBinding:
        await binding.save(update_fields=list(dict.fromkeys([*update_fields, "updated_at"])))
        return binding

    async def delete(self, binding: ProjectApiKeyBinding) -> None:
        await binding.delete()


__all__ = ["ApiKeyRepository", "ProjectApiKeyRepository"]
