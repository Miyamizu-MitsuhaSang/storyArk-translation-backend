import asyncio
from uuid import uuid4

import pytest
from pydantic import ValidationError
from tortoise import Tortoise
from tortoise.exceptions import IntegrityError

from translation_backend.app.models import Project, ProjectSettings
from translation_backend.app.application.project.settings.schemas import ProjectSettingsUpdateRequest
from translation_backend.app.application.project.settings.service import ProjectSettingsService
from translation_backend.app.application.project.shared import RevisionConflictError
from translation_backend.app.models import ProjectLanguagePair, ProjectMember, User


async def _service_setup():
    await Tortoise.init(
        db_url="sqlite://:memory:",
        modules={"models": ["translation_backend.app.models"]},
    )
    await Tortoise.generate_schemas()
    owner = await User.create(
        username=f"project-settings-owner-{uuid4().hex}",
        email=f"project-settings-owner-{uuid4().hex}@example.com",
        password_hash="hash",
        display_name="Owner",
    )
    viewer = await User.create(
        username=f"project-settings-viewer-{uuid4().hex}",
        email=f"project-settings-viewer-{uuid4().hex}@example.com",
        password_hash="hash",
        display_name="Viewer",
    )
    project = await Project.create(
        key=f"project-settings-service-{uuid4().hex}",
        name="Project settings service",
        created_by=owner,
    )
    await ProjectMember.create(project=project, user=owner, role="owner")
    await ProjectMember.create(project=project, user=viewer, role="viewer")
    await ProjectLanguagePair.create(
        project=project,
        source_language="zh-CN",
        target_language="en-US",
        is_default=True,
    )
    return owner, viewer, project


def test_project_settings_service_reads_defaults_and_updates_partial_fields():
    async def scenario() -> None:
        owner, viewer, project = await _service_setup()
        try:
            service = ProjectSettingsService()
            initial = await service.get(viewer, project.id)
            assert initial.project_id == project.id
            assert initial.quality_threshold == 0.7
            assert initial.revision == 1

            updated = await service.update(
                owner,
                project.id,
                ProjectSettingsUpdateRequest(quality_threshold=0.85),
                expected_revision=1,
            )
            assert updated.quality_threshold == 0.85
            assert updated.terminology_enabled is True
            assert updated.translation_memory_enabled is True
            assert updated.revision == 2
        finally:
            await Tortoise.close_connections()

    asyncio.run(scenario())


def test_project_settings_service_rejects_forbidden_invalid_language_and_stale_revision():
    async def scenario() -> None:
        owner, viewer, project = await _service_setup()
        try:
            service = ProjectSettingsService()
            with pytest.raises(Exception) as raised:
                await service.update(
                    viewer,
                    project.id,
                    ProjectSettingsUpdateRequest(quality_threshold=0.8),
                    expected_revision=1,
                )
            assert raised.value.status_code == 403

            with pytest.raises(Exception) as raised:
                await service.update(
                    owner,
                    project.id,
                    ProjectSettingsUpdateRequest(
                        default_source_language="ja-JP",
                        default_target_language="en-US",
                    ),
                    expected_revision=1,
                )
            assert raised.value.status_code == 422

            await service.update(
                owner,
                project.id,
                ProjectSettingsUpdateRequest(quality_threshold=0.8),
                expected_revision=1,
            )
            with pytest.raises(RevisionConflictError) as raised:
                await service.update(
                    owner,
                    project.id,
                    ProjectSettingsUpdateRequest(default_model="gpt-test"),
                    expected_revision=1,
                )
            assert raised.value.details == {"current_revision": 2}
        finally:
            await Tortoise.close_connections()

    asyncio.run(scenario())


def test_project_settings_service_requires_language_pair_fields_together():
    async def scenario() -> None:
        owner, _, project = await _service_setup()
        try:
            service = ProjectSettingsService()
            with pytest.raises(Exception) as raised:
                await service.update(
                    owner,
                    project.id,
                    ProjectSettingsUpdateRequest(default_source_language="zh-CN"),
                    expected_revision=1,
                )
            assert raised.value.status_code == 422
        finally:
            await Tortoise.close_connections()

    asyncio.run(scenario())


def test_project_settings_service_rejects_empty_default_model():
    async def scenario() -> None:
        owner, _, project = await _service_setup()
        try:
            service = ProjectSettingsService()
            with pytest.raises(ValidationError):
                ProjectSettingsUpdateRequest(default_model="")
        finally:
            await Tortoise.close_connections()

    asyncio.run(scenario())


def test_project_settings_model_has_defaults_and_one_to_one() -> None:
    async def scenario() -> None:
        await Tortoise.init(
            db_url="sqlite://:memory:",
            modules={"models": ["translation_backend.app.models"]},
        )
        await Tortoise.generate_schemas()
        try:
            project = await Project.create(
                key=f"project-settings-{uuid4().hex}",
                name="Project settings",
            )
            settings = await ProjectSettings.create(project=project)
            assert settings.terminology_enabled is True
            assert settings.translation_memory_enabled is True
            assert float(settings.quality_threshold) == pytest.approx(0.7)
            assert settings.revision == 1

            with pytest.raises(IntegrityError):
                await ProjectSettings.create(project=project)
        finally:
            await Tortoise.close_connections()

    asyncio.run(scenario())
