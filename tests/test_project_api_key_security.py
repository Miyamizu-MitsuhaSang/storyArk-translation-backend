from __future__ import annotations

import asyncio
import base64
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from tortoise import Tortoise

from translation_backend.app.application.auth.api_key.schemas import (
    CreateApiKeyRequest,
    UpdateApiKeyRequest,
)
from translation_backend.app.application.auth.api_key.service import ApiKeyInUseError, ApiKeyService
from translation_backend.app.application.project.api_key.schemas import (
    CreateProjectApiKeyRequest,
    UpdateProjectApiKeyRequest,
)
from translation_backend.app.application.project.api_key.service import (
    ProjectApiKeyNotFoundError,
    ProjectApiKeyService,
)
from translation_backend.app.core.security import is_secure_api_key_transport
from translation_backend.app.models import AIProviderCredential, Project, ProjectApiKeyBinding, ProjectMember, User


TEST_ENCRYPTION_KEY = b"0123456789abcdef0123456789abcdef"


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
        username=f"key-owner-{uuid4().hex}",
        email=f"key-owner-{uuid4().hex}@example.com",
        password_hash="hash",
        display_name="Key owner",
    )
    other = await User.create(
        username=f"key-other-{uuid4().hex}",
        email=f"key-other-{uuid4().hex}@example.com",
        password_hash="hash",
        display_name="Key other",
    )
    viewer = await User.create(
        username=f"key-viewer-{uuid4().hex}",
        email=f"key-viewer-{uuid4().hex}@example.com",
        password_hash="hash",
        display_name="Key viewer",
    )
    project = await Project.create(key=f"key-{uuid4().hex}", name="Key project", created_by=owner)
    await ProjectMember.create(project=project, user=owner, role="owner")
    await ProjectMember.create(project=project, user=viewer, role="viewer")
    return owner, other, viewer, project


def test_user_api_key_uses_aes_256_gcm_storage_and_never_returns_secret() -> None:
    async def scenario() -> None:
        owner, _, _, _ = await _setup()
        service = ApiKeyService(encryption_key=TEST_ENCRYPTION_KEY, key_version="test-v1")
        try:
            created = await service.create(
                owner,
                CreateApiKeyRequest(provider="openai", label="main", secret="sk-live-super-secret-1234"),
            )
            credential = await AIProviderCredential.get(id=created.id)
            assert credential.api_key_ciphertext != "sk-live-super-secret-1234"
            assert credential.encryption_key_version == "test-v1"
            assert len(base64.urlsafe_b64decode(credential.encryption_nonce)) == 12
            assert await service.decrypt(credential) == "sk-live-super-secret-1234"
            assert "super-secret" not in created.model_dump_json()
            assert created.masked_secret.endswith("1234")
        finally:
            await Tortoise.close_connections()

    run_db_test(scenario)


def test_user_key_delete_is_blocked_while_project_binding_exists() -> None:
    async def scenario() -> None:
        owner, _, _, project = await _setup()
        user_service = ApiKeyService(encryption_key=TEST_ENCRYPTION_KEY, key_version="test-v1")
        project_service = ProjectApiKeyService()
        try:
            key = await user_service.create(
                owner,
                CreateApiKeyRequest(provider="openai", secret="bound-secret"),
            )
            await project_service.create(
                owner,
                project.id,
                CreateProjectApiKeyRequest(api_key_id=key.id),
            )
            with pytest.raises(ApiKeyInUseError):
                await user_service.delete(owner, key.id)
            assert await AIProviderCredential.filter(id=key.id).exists()
        finally:
            await Tortoise.close_connections()

    run_db_test(scenario)


def test_project_binding_cannot_be_reactivated_when_user_key_is_inactive() -> None:
    async def scenario() -> None:
        owner, _, _, project = await _setup()
        user_service = ApiKeyService(encryption_key=TEST_ENCRYPTION_KEY, key_version="test-v1")
        project_service = ProjectApiKeyService()
        try:
            key = await user_service.create(
                owner,
                CreateApiKeyRequest(provider="openai", secret="inactive-bound-secret"),
            )
            binding = await project_service.create(
                owner,
                project.id,
                CreateProjectApiKeyRequest(api_key_id=key.id),
            )
            await user_service.update(
                owner,
                key.id,
                UpdateApiKeyRequest(status="inactive"),
            )
            with pytest.raises(ProjectApiKeyNotFoundError):
                await project_service.update(
                    owner,
                    project.id,
                    binding.id,
                    UpdateProjectApiKeyRequest(status="active"),
                )
        finally:
            await Tortoise.close_connections()

    run_db_test(scenario)


def test_project_binding_rejects_non_owner_key_and_inactive_key_without_leaking_existence() -> None:
    async def scenario() -> None:
        owner, other, _, project = await _setup()
        user_service = ApiKeyService(encryption_key=TEST_ENCRYPTION_KEY, key_version="test-v1")
        project_service = ProjectApiKeyService()
        try:
            other_key = await user_service.create(
                other,
                CreateApiKeyRequest(provider="openai", secret="other-secret"),
            )
            with pytest.raises(ProjectApiKeyNotFoundError) as raised:
                await project_service.create(
                    owner,
                    project.id,
                    CreateProjectApiKeyRequest(api_key_id=other_key.id),
                )
            assert raised.value.status_code == 404
            assert "other-secret" not in str(raised.value)

            inactive = await user_service.create(
                owner,
                CreateApiKeyRequest(provider="openai", secret="inactive-secret"),
            )
            await user_service.update(owner, inactive.id, UpdateApiKeyRequest(status="inactive"))
            with pytest.raises(ProjectApiKeyNotFoundError):
                await project_service.create(
                    owner,
                    project.id,
                    CreateProjectApiKeyRequest(api_key_id=inactive.id),
                )
        finally:
            await Tortoise.close_connections()

    run_db_test(scenario)


def test_project_binding_is_idempotent_and_keeps_one_default_without_deleting_user_key() -> None:
    async def scenario() -> None:
        owner, _, _, project = await _setup()
        user_service = ApiKeyService(encryption_key=TEST_ENCRYPTION_KEY, key_version="test-v1")
        project_service = ProjectApiKeyService()
        try:
            first_key = await user_service.create(
                owner,
                CreateApiKeyRequest(provider="openai", secret="first-secret"),
            )
            second_key = await user_service.create(
                owner,
                CreateApiKeyRequest(provider="openai", secret="second-secret"),
            )
            first = await project_service.create(
                owner,
                project.id,
                CreateProjectApiKeyRequest(api_key_id=first_key.id, is_default=True),
            )
            replay = await project_service.create(
                owner,
                project.id,
                CreateProjectApiKeyRequest(api_key_id=first_key.id, is_default=True),
            )
            assert replay.id == first.id

            second = await project_service.create(
                owner,
                project.id,
                CreateProjectApiKeyRequest(api_key_id=second_key.id, is_default=True),
            )
            defaults = await ProjectApiKeyBinding.filter(project_id=project.id, is_default=True).count()
            assert defaults == 1
            assert second.is_default is True

            await project_service.delete(owner, project.id, first.id)
            assert await AIProviderCredential.filter(id=first_key.id).exists()
            assert not await ProjectApiKeyBinding.filter(id=first.id).exists()
        finally:
            await Tortoise.close_connections()

    run_db_test(scenario)


def test_project_binding_response_and_user_key_response_never_contain_raw_secret() -> None:
    async def scenario() -> None:
        owner, _, viewer, project = await _setup()
        user_service = ApiKeyService(encryption_key=TEST_ENCRYPTION_KEY, key_version="test-v1")
        project_service = ProjectApiKeyService()
        try:
            key = await user_service.create(
                owner,
                CreateApiKeyRequest(provider="openai", secret="sk-project-secret-9999"),
            )
            binding = await project_service.create(
                owner,
                project.id,
                CreateProjectApiKeyRequest(api_key_id=key.id, is_default=True),
            )
            listed = await project_service.list(viewer, project.id, page_size=20, cursor=None)
            assert "project-secret" not in listed.model_dump_json()
            assert "project-secret" not in binding.model_dump_json()
            assert "project-secret" not in (await user_service.get(owner, key.id)).model_dump_json()
        finally:
            await Tortoise.close_connections()

    run_db_test(scenario)


def test_api_key_transport_requires_tls_or_explicitly_trusted_https_proxy() -> None:
    def request(*, scheme: str, forwarded_proto: str | None = None):
        headers = {}
        if forwarded_proto is not None:
            headers["x-forwarded-proto"] = forwarded_proto
        return type(
            "RequestLike",
            (),
            {"url": type("URL", (), {"scheme": scheme})(), "headers": dict(headers)},
        )()

    assert is_secure_api_key_transport(request(scheme="https"), trust_forwarded_proto=False)
    assert not is_secure_api_key_transport(
        request(scheme="http", forwarded_proto="https"),
        trust_forwarded_proto=False,
    )
    assert is_secure_api_key_transport(
        request(scheme="http", forwarded_proto="https"),
        trust_forwarded_proto=True,
    )


def test_http_api_key_creation_is_rejected_before_request_body_parsing() -> None:
    async def scenario() -> None:
        from translation_backend.main import app

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.post(
                "/api/v1/auth/me/api-keys",
                content=b"not-json-and-must-not-be-parsed",
            )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "API_KEY_HTTPS_REQUIRED"

    asyncio.run(scenario())
