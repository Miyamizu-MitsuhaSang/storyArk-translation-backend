from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from tortoise.transactions import in_transaction

from ....models import CultureRule, Project, TranslationRole, TranslationRule, Worldview


class TranslationSettingsRepository:
    async def get_worldview(self, project_id: UUID) -> Worldview | None:
        return await Worldview.filter(project_id=project_id).first()

    async def get_or_create_worldview(self, project: Project) -> Worldview:
        worldview = await self.get_worldview(project.id)
        if worldview is None:
            worldview = await Worldview.create(project=project, name=f"{project.name} Worldview")
        return worldview

    async def save_worldview(self, worldview: Worldview, fields: list[str]) -> Worldview:
        await worldview.save(update_fields=list(dict.fromkeys([*fields, "updated_at"])))
        return worldview

    async def list_roles(self, project_id: UUID) -> list[TranslationRole]:
        return await TranslationRole.filter(project_id=project_id, deleted_at=None).order_by("sort_order", "name")

    async def get_role(self, project_id: UUID, role_id: UUID) -> TranslationRole | None:
        return await TranslationRole.filter(project_id=project_id, id=role_id, deleted_at=None).first()

    async def get_role_any(self, project_id: UUID, name: str) -> TranslationRole | None:
        return await TranslationRole.filter(project_id=project_id, name=name).first()

    async def create_role(self, project: Project, **values: Any) -> TranslationRole:
        return await TranslationRole.create(project=project, **values)

    async def save_role(self, role: TranslationRole, fields: list[str]) -> TranslationRole:
        await role.save(update_fields=list(dict.fromkeys([*fields, "updated_at"])))
        return role

    async def list_rules(self, project_id: UUID) -> list[TranslationRule]:
        return await TranslationRule.filter(project_id=project_id, deleted_at=None).order_by("name", "category")

    async def get_rule(self, project_id: UUID, rule_id: UUID) -> TranslationRule | None:
        return await TranslationRule.filter(project_id=project_id, id=rule_id, deleted_at=None).first()

    async def create_rule(self, project: Project, **values: Any) -> TranslationRule:
        return await TranslationRule.create(project=project, **values)

    async def save_rule(self, rule: TranslationRule, fields: list[str]) -> TranslationRule:
        await rule.save(update_fields=list(dict.fromkeys([*fields, "updated_at"])))
        return rule

    async def list_culture_rules(self, project_id: UUID) -> list[CultureRule]:
        return await CultureRule.filter(project_id=project_id, deleted_at=None).order_by("language", "name", "category")

    async def get_culture_rule(self, project_id: UUID, rule_id: UUID) -> CultureRule | None:
        return await CultureRule.filter(project_id=project_id, id=rule_id, deleted_at=None).first()

    async def create_culture_rule(self, project: Project, **values: Any) -> CultureRule:
        return await CultureRule.create(project=project, **values)

    async def save_culture_rule(self, rule: CultureRule, fields: list[str]) -> CultureRule:
        await rule.save(update_fields=list(dict.fromkeys([*fields, "updated_at"])))
        return rule

    async def soft_delete(self, model: Any) -> None:
        model.deleted_at = model.updated_at
        await model.save(update_fields=["deleted_at", "updated_at"])

    async def replace_template_children(self, project_id: UUID) -> None:
        async with in_transaction():
            deleted_at = datetime.now(timezone.utc)
            await TranslationRole.filter(project_id=project_id, deleted_at=None).update(deleted_at=deleted_at)
            await TranslationRule.filter(project_id=project_id, deleted_at=None).update(deleted_at=deleted_at)
            await CultureRule.filter(project_id=project_id, deleted_at=None).update(deleted_at=deleted_at)


__all__ = ["TranslationSettingsRepository"]
