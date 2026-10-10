from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from tortoise import Tortoise

from translation_backend.app.application.project.shared import RevisionConflictError
from translation_backend.app.application.project.translation_settings.schemas import (
    CultureRuleCreateRequest,
    RuleCreateRequest,
    RoleCreateRequest,
    SettingsUpdateRequest,
)
from translation_backend.app.application.project.translation_settings.service import (
    ConfirmationRequiredError,
    TranslationSettingsService,
)
from translation_backend.app.models import Project, ProjectMember, User


async def _setup():
    await Tortoise.init(
        db_url="sqlite://:memory:",
        modules={"models": ["translation_backend.app.models"]},
    )
    await Tortoise.generate_schemas()
    owner = await User.create(
        username=f"settings-owner-{uuid4().hex}",
        email=f"settings-owner-{uuid4().hex}@example.com",
        password_hash="hash",
        display_name="Owner",
    )
    translator = await User.create(
        username=f"settings-translator-{uuid4().hex}",
        email=f"settings-translator-{uuid4().hex}@example.com",
        password_hash="hash",
        display_name="Translator",
    )
    viewer = await User.create(
        username=f"settings-viewer-{uuid4().hex}",
        email=f"settings-viewer-{uuid4().hex}@example.com",
        password_hash="hash",
        display_name="Viewer",
    )
    outsider = await User.create(
        username=f"settings-outsider-{uuid4().hex}",
        email=f"settings-outsider-{uuid4().hex}@example.com",
        password_hash="hash",
        display_name="Outsider",
    )
    project = await Project.create(
        key=f"settings-{uuid4().hex}",
        name="Settings project",
        created_by=owner,
    )
    await ProjectMember.create(project=project, user=owner, role="owner")
    await ProjectMember.create(project=project, user=translator, role="translator")
    await ProjectMember.create(project=project, user=viewer, role="viewer")
    return owner, translator, viewer, outsider, project


def test_translation_settings_crud_and_revision_guards():
    async def scenario() -> None:
        owner, translator, viewer, outsider, project = await _setup()
        try:
            service = TranslationSettingsService()
            initial = await service.get(translator, project.id)
            assert initial.project_id == project.id
            assert initial.revision == 1
            assert initial.worldview is None

            updated = await service.update(
                owner,
                project.id,
                SettingsUpdateRequest(revision=1, worldview="科幻世界", tone="克制"),
                expected_revision=1,
            )
            assert updated.revision == 2
            assert updated.worldview == "科幻世界"
            with pytest.raises(Exception) as raised:
                await service.get(viewer, project.id)
            assert getattr(raised.value, "status_code", None) == 403

            with pytest.raises(RevisionConflictError) as raised:
                await service.update(
                    owner,
                    project.id,
                    SettingsUpdateRequest(revision=1, tone="冲突"),
                    expected_revision=1,
                )
            assert raised.value.details == {"current_revision": 2}

            with pytest.raises(Exception) as raised:
                await service.get(outsider, project.id)
            assert getattr(raised.value, "status_code", None) == 404
        finally:
            await Tortoise.close_connections()

    asyncio.run(scenario())


def test_translation_settings_child_resources_validate_and_initialize_idempotently():
    async def scenario() -> None:
        owner, _, _, _, project = await _setup()
        try:
            service = TranslationSettingsService()
            role = await service.create_role(
                owner,
                project.id,
                RoleCreateRequest(name="Narrator", description="主叙事", detailed_injection="保持节奏", sort_order=1),
                idempotency_key="role-1",
            )
            replay = await service.create_role(
                owner,
                project.id,
                RoleCreateRequest(name="Narrator", description="主叙事", detailed_injection="保持节奏", sort_order=1),
                idempotency_key="role-1",
            )
            assert replay.id == role.id

            with pytest.raises(ValueError):
                await service.create_rule(
                    owner,
                    project.id,
                    RuleCreateRequest(type="category", name="Combat", text="战斗规则"),
                )
            rule = await service.create_rule(
                owner,
                project.id,
                RuleCreateRequest(type="category", name="Combat", text="战斗规则", category="combat"),
            )
            culture = await service.create_culture_rule(
                owner,
                project.id,
                CultureRuleCreateRequest(language="en-US", name="Punctuation", text="Use ASCII punctuation"),
            )
            assert rule.revision == culture.revision == 1

            with pytest.raises(ConfirmationRequiredError):
                await service.initialize(owner, project.id, template_id="rpg", expected_revision=1, confirm_replace=False)
            initialized = await service.initialize(
                owner,
                project.id,
                template_id="rpg",
                expected_revision=1,
                confirm_replace=True,
                idempotency_key="init-1",
            )
            assert initialized.revision == 2
            assert initialized.worldview
            assert initialized.tone
        finally:
            await Tortoise.close_connections()

    asyncio.run(scenario())
