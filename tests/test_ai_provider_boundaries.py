from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from tortoise import Tortoise

from translation_backend.app.application.ai_translation.service import AiTranslationError, AiTranslationService
from translation_backend.app.domain.ai_translation.contracts import TranslationRequest, TranslationResult, UsageSnapshot
from translation_backend.app.infrastructure.ai_provider.fake import FakeModelInvoker
from translation_backend.app.infrastructure.ai_provider.registry import ModelInvokerRegistry
from translation_backend.app.models import AIProviderCredential, AIUsageRecord, Project, ProjectMember, User
from translation_backend.app.application.auth.api_key.service import ApiKeyService
from translation_backend.app.application.auth.api_key.schemas import CreateApiKeyRequest


def run_db_test(coro):
    async def scenario():
        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["translation_backend.app.models"]})
        await Tortoise.generate_schemas()
        try:
            return await coro()
        finally:
            await Tortoise.close_connections()

    return asyncio.run(scenario())


def test_registry_rejects_unknown_model_type():
    registry = ModelInvokerRegistry({"fake.echo": ("custom", FakeModelInvoker())})
    with pytest.raises(AiTranslationError) as raised:
        registry.resolve("user.callable")
    assert raised.value.code == "MODEL_TYPE_UNSUPPORTED"


def test_translation_request_rejects_secret_like_context():
    with pytest.raises(ValueError):
        TranslationRequest(
            text="hello",
            source_language="en",
            target_language="zh-CN",
            model_type="fake.echo",
            model="fake",
            context={"api_key": "secret"},
        )


def test_ai_translation_service_decrypts_owned_key_and_records_usage_without_secret():
    async def scenario():
        user = await User.create(
            username=f"provider-{uuid4().hex}",
            email=f"provider-{uuid4().hex}@example.com",
            password_hash="hash",
            display_name="Provider user",
        )
        project = await Project.create(key=f"provider-{uuid4().hex}", name="Provider project", created_by=user)
        await ProjectMember.create(project=project, user=user, role="owner")
        key = await ApiKeyService(
            encryption_key=b"0123456789abcdef0123456789abcdef", key_version="test-v1"
        ).create(user, CreateApiKeyRequest(provider="custom", secret="provider-secret-1234"))
        invoker = FakeModelInvoker(
            result=TranslationResult(
                text="你好",
                provider="custom",
                model_type="fake.echo",
                model="fake",
                usage=UsageSnapshot(input_tokens=1, output_tokens=1, total_tokens=2),
            )
        )
        service = AiTranslationService(
            registry=ModelInvokerRegistry({"fake.echo": ("custom", invoker)}),
            api_key_service=ApiKeyService(
                encryption_key=b"0123456789abcdef0123456789abcdef", key_version="test-v1"
            ),
        )
        result = await service.translate(
            user,
            project.id,
            key.id,
            TranslationRequest(
                text="hello",
                source_language="en",
                target_language="zh-CN",
                model_type="fake.echo",
                model="fake",
            ),
        )
        assert result.text == "你好"
        assert await AIUsageRecord.filter(user_id=user.id, project_id=project.id).count() == 1
        usage = await AIUsageRecord.filter(user_id=user.id, project_id=project.id).first()
        assert usage is not None
        assert "provider-secret" not in str(usage)
        assert invoker.last_api_key == "provider-secret-1234"

    run_db_test(scenario)
