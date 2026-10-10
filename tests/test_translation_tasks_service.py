from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from pydantic import ValidationError
from tortoise import Tortoise

from translation_backend.app.application.auth.api_key.schemas import CreateApiKeyRequest, UpdateApiKeyRequest
from translation_backend.app.application.auth.api_key.service import ApiKeyInUseError, ApiKeyService
from translation_backend.app.application.project.translation_task.schemas import TranslationTaskCreateRequest
from translation_backend.app.application.project.translation_task.service import (
    TranslationTaskConflictError,
    TranslationTaskForbiddenError,
    TranslationTaskNotFoundError,
    TranslationTaskService,
)
from translation_backend.app.models import (
    AIProviderCredential,
    Document,
    Project,
    ProjectMember,
    ProjectVersion,
    TranslationTask,
    User,
)


def run_db_test(coro):
    async def scenario():
        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["translation_backend.app.models"]})
        await Tortoise.generate_schemas()
        try:
            return await coro()
        finally:
            await Tortoise.close_connections()

    return asyncio.run(scenario())


async def _setup():
    owner = await User.create(
        username=f"task-owner-{uuid4().hex}",
        email=f"task-owner-{uuid4().hex}@example.com",
        password_hash="hash",
        display_name="Task owner",
    )
    translator = await User.create(
        username=f"task-translator-{uuid4().hex}",
        email=f"task-translator-{uuid4().hex}@example.com",
        password_hash="hash",
        display_name="Task translator",
    )
    viewer = await User.create(
        username=f"task-viewer-{uuid4().hex}",
        email=f"task-viewer-{uuid4().hex}@example.com",
        password_hash="hash",
        display_name="Task viewer",
    )
    other = await User.create(
        username=f"task-other-{uuid4().hex}",
        email=f"task-other-{uuid4().hex}@example.com",
        password_hash="hash",
        display_name="Task other",
    )
    project = await Project.create(key=f"task-{uuid4().hex}", name="Translation tasks", created_by=owner)
    other_project = await Project.create(key=f"task-other-{uuid4().hex}", name="Other project", created_by=owner)
    await ProjectMember.create(project=project, user=owner, role="owner")
    await ProjectMember.create(project=project, user=translator, role="translator")
    await ProjectMember.create(project=project, user=viewer, role="viewer")
    await ProjectMember.create(project=other_project, user=owner, role="owner")
    document = await Document.create(
        project=project,
        created_by=owner,
        name="dialog",
        file_name="dialog.json",
        file_format="json",
        checksum_sha256="a" * 64,
        source_language="zh-CN",
        target_language="en",
        status="ready",
    )
    other_document = await Document.create(
        project=other_project,
        created_by=owner,
        name="other",
        file_name="other.json",
        file_format="json",
        checksum_sha256="b" * 64,
        source_language="zh-CN",
        target_language="en",
        status="ready",
    )
    version = await ProjectVersion.create(project=project, version_number=1, name="v1", created_by=owner)
    return owner, translator, viewer, other, project, other_project, document, other_document, version


async def _create_api_key(user: User, *, secret: str = "task-provider-secret-1234"):
    service = ApiKeyService(encryption_key=b"0123456789abcdef0123456789abcdef", key_version="test-v1")
    return await service.create(user, CreateApiKeyRequest(provider="openai", label="Shared key", secret=secret))


def test_translation_task_request_rejects_empty_duplicate_or_source_target_languages():
    with pytest.raises(ValidationError):
        TranslationTaskCreateRequest(
            name="task", source_language="zh-CN", target_languages=[], file_ids=[uuid4()], api_key_id=uuid4()
        )
    with pytest.raises(ValidationError):
        TranslationTaskCreateRequest(
            name="task", source_language="zh-CN", target_languages=["en", "en"], file_ids=[uuid4()], api_key_id=uuid4()
        )
    with pytest.raises(ValidationError):
        TranslationTaskCreateRequest(
            name="task", source_language="zh-CN", target_languages=["zh-CN"], file_ids=[uuid4()], api_key_id=uuid4()
        )


def test_translation_task_create_uses_owned_user_key_across_projects_and_is_idempotent():
    async def scenario():
        owner, translator, _, _, project, other_project, document, _, version = await _setup()
        translator_key = await _create_api_key(translator, secret="translator-task-secret-1234")
        owner_key = await _create_api_key(owner, secret="owner-task-secret-5678")
        service = TranslationTaskService()
        request = TranslationTaskCreateRequest(
            name="Localized release",
            source_language="zh-CN",
            target_languages=["en", "ko"],
            file_ids=[document.id],
            version_id=version.id,
            api_key_id=translator_key.id,
        )
        first = await service.create(translator, project.id, request, idempotency_key="task-create-1")
        replay = await service.create(translator, project.id, request, idempotency_key="task-create-1")
        assert replay.id == first.id
        assert first.status == "queued"
        assert first.progress == 0
        assert first.api_key.id == translator_key.id
        assert first.api_key.provider == "openai"
        assert "task-provider-secret" not in first.model_dump_json()
        assert await TranslationTask.filter(project_id=project.id).count() == 1

        # The same user credential is valid in another project without a project binding.
        other_document = await Document.create(
            project=other_project,
            created_by=owner,
            name="other2",
            file_name="other2.json",
            file_format="json",
            checksum_sha256="c" * 64,
            source_language="zh-CN",
            target_language="en",
            status="ready",
        )
        other_task = await service.create(
            owner,
            other_project.id,
            request.model_copy(update={"file_ids": [other_document.id], "version_id": None, "api_key_id": owner_key.id}),
            idempotency_key="task-create-other-project",
        )
        assert other_task.api_key.id == owner_key.id

    run_db_test(scenario)


def test_translation_task_key_cannot_be_deleted_or_disabled_while_active_task_references_it():
    async def scenario():
        owner, _, _, _, project, _, document, _, _ = await _setup()
        key = await _create_api_key(owner, secret="active-task-secret-1234")
        task_service = TranslationTaskService()
        request = TranslationTaskCreateRequest(
            name="task", source_language="zh-CN", target_languages=["en"],
            file_ids=[document.id], api_key_id=key.id,
        )
        await task_service.create(owner, project.id, request)
        key_service = ApiKeyService(encryption_key=b"0123456789abcdef0123456789abcdef", key_version="test-v1")
        with pytest.raises(ApiKeyInUseError):
            await key_service.delete(owner, key.id)
        with pytest.raises(ApiKeyInUseError):
            await key_service.update(owner, key.id, UpdateApiKeyRequest(status="inactive"))

    run_db_test(scenario)


def test_translation_task_validates_file_version_and_key_ownership_and_status():
    async def scenario():
        owner, _, _, other, project, other_project, document, other_document, version = await _setup()
        own_key = await _create_api_key(owner)
        other_key = await _create_api_key(other, secret="foreign-secret-9876")
        service = TranslationTaskService()

        def request(**overrides):
            values = {
                "name": "task",
                "source_language": "zh-CN",
                "target_languages": ["en"],
                "file_ids": [document.id],
                "version_id": version.id,
                "api_key_id": own_key.id,
            }
            values.update(overrides)
            return TranslationTaskCreateRequest(**values)

        with pytest.raises(TranslationTaskNotFoundError):
            await service.create(owner, project.id, request(file_ids=[other_document.id]))
        foreign_version = await ProjectVersion.create(project=other_project, version_number=1, created_by=owner)
        with pytest.raises(TranslationTaskNotFoundError):
            await service.create(owner, project.id, request(version_id=foreign_version.id))
        with pytest.raises(TranslationTaskNotFoundError):
            await service.create(owner, project.id, request(api_key_id=other_key.id))
        await AIProviderCredential.filter(id=own_key.id).update(is_active=False)
        with pytest.raises(TranslationTaskNotFoundError):
            await service.create(owner, project.id, request())

    run_db_test(scenario)


def test_translation_task_permissions_and_list_visibility():
    async def scenario():
        owner, translator, viewer, other, project, _, document, _, _ = await _setup()
        key = await _create_api_key(translator, secret="translator-permission-secret-1234")
        service = TranslationTaskService()
        request = TranslationTaskCreateRequest(
            name="task", source_language="zh-CN", target_languages=["en"],
            file_ids=[document.id], api_key_id=key.id,
        )
        created = await service.create(translator, project.id, request)
        with pytest.raises(TranslationTaskForbiddenError):
            await service.create(viewer, project.id, request)
        with pytest.raises(TranslationTaskNotFoundError):
            await service.get(other, project.id, created.id)
        page = await service.list(viewer, project.id)
        assert [item.id for item in page.items] == [created.id]
        assert page.total == 1

    run_db_test(scenario)


def test_translation_task_list_supports_project_scoped_filters():
    async def scenario():
        owner, _, _, _, project, _, document, _, version = await _setup()
        key = await _create_api_key(owner, secret="filter-task-secret-1234")
        service = TranslationTaskService()
        await service.create(
            owner,
            project.id,
            TranslationTaskCreateRequest(
                name="English release", source_language="zh-CN", target_languages=["en"],
                file_ids=[document.id], version_id=version.id, api_key_id=key.id,
            ),
        )
        await service.create(
            owner,
            project.id,
            TranslationTaskCreateRequest(
                name="Korean release", source_language="zh-CN", target_languages=["ko"],
                file_ids=[document.id], api_key_id=key.id,
            ),
        )
        page = await service.list(owner, project.id, target_language="ko", q="Korean")
        assert page.total == 1
        assert page.items[0].name == "Korean release"

    run_db_test(scenario)


def test_translation_task_can_be_cancelled_and_cannot_be_cancelled_after_review():
    async def scenario():
        owner, _, _, _, project, _, document, _, _ = await _setup()
        key = await _create_api_key(owner, secret="cancel-task-secret-1234")
        service = TranslationTaskService()
        request = TranslationTaskCreateRequest(
            name="cancel me", source_language="zh-CN", target_languages=["en"],
            file_ids=[document.id], api_key_id=key.id,
        )
        created = await service.create(owner, project.id, request)
        cancelled = await service.cancel(owner, project.id, created.id)
        assert cancelled.status == "cancelled"
        assert (await TranslationTask.get(id=created.id)).status == "cancelled"

        await TranslationTask.filter(id=created.id).update(status="review")
        with pytest.raises(TranslationTaskConflictError):
            await service.cancel(owner, project.id, created.id)

    run_db_test(scenario)
