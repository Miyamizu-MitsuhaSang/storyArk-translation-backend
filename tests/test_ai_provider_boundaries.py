from __future__ import annotations

import asyncio
from decimal import Decimal
from uuid import uuid4

import pytest
from tortoise import Tortoise

from translation_backend.app.application.ai_translation.service import AiTranslationError, AiTranslationService
from translation_backend.app.domain.ai_translation.contracts import (
    ProviderCapabilities,
    TranslationRequest,
    TranslationResult,
    UsageSnapshot,
)
from translation_backend.app.domain.ai_translation.errors import (
    ModelUnsupportedError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)
from translation_backend.app.infrastructure.ai_provider.fake import FakeModelInvoker
from translation_backend.app.infrastructure.ai_provider.openai_chat import OpenAIChatInvoker
from translation_backend.app.infrastructure.ai_provider.openai_compatible import OpenAICompatibleInvoker
from translation_backend.app.infrastructure.ai_provider.registry import ModelInvokerRegistry, ModelRegistration
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


def test_registry_validates_registered_model_rules_and_exposes_capabilities():
    registry = ModelInvokerRegistry(
        {
            "fake.echo": ModelRegistration(
                provider="custom",
                invoker=FakeModelInvoker(),
                supported_models=frozenset({"echo-v1"}),
                capabilities=ProviderCapabilities(supports_usage=False),
            )
        }
    )

    assert registry.provider_for("fake.echo") == "custom"
    assert registry.capabilities_for("fake.echo").supports_usage is False
    registry.validate_model("fake.echo", "echo-v1")
    with pytest.raises(ModelUnsupportedError):
        registry.validate_model("fake.echo", "echo-v2")


def test_openai_chat_adapter_passes_different_models_through_the_same_adapter():
    class Completions:
        def __init__(self):
            self.models = []

        async def create(self, **kwargs):
            self.models.append(kwargs["model"])
            return type(
                "Response",
                (),
                {
                    "id": "req-1",
                    "choices": [type("Choice", (), {"message": type("Message", (), {"content": "ok"})(), "finish_reason": "stop"})()],
                    "usage": type("Usage", (), {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})(),
                },
            )()

    completions = Completions()
    client = type("Client", (), {"chat": type("Chat", (), {"completions": completions})()})()
    invoker = OpenAIChatInvoker(client_factory=lambda _: client)

    async def scenario():
        for model in ("gpt-4o-mini", "gpt-5.6-luna"):
            await invoker.translate(
                TranslationRequest(
                    text="hello",
                    source_language="en",
                    target_language="zh-CN",
                    model_type="openai.chat",
                    model=model,
                ),
                api_key="secret",
            )

    asyncio.run(scenario())
    assert completions.models == ["gpt-4o-mini", "gpt-5.6-luna"]


def test_provider_errors_expose_retry_boundary_without_provider_response_details():
    assert ProviderTimeoutError("timeout").retryable is True
    assert ProviderRateLimitError("rate limited").retryable is True
    assert ProviderRateLimitError.code == "PROVIDER_RATE_LIMITED"


def test_openai_compatible_invoker_uses_server_configured_endpoint_and_model():
    captured = {}

    class Completions:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return type(
                "Response",
                (),
                {
                    "id": "compatible-1",
                    "choices": [type("Choice", (), {"message": type("Message", (), {"content": "你好"})(), "finish_reason": "stop"})()],
                    "usage": type("Usage", (), {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5})(),
                },
            )()

    client = type("Client", (), {"chat": type("Chat", (), {"completions": Completions()})()})()
    invoker = OpenAICompatibleInvoker(provider="deepseek", base_url="https://api.deepseek.com", client_factory=lambda key, url: (captured.update(api_key=key, base_url=url) or client))

    async def scenario():
        result = await invoker.translate(
            TranslationRequest(
                text="hello",
                source_language="en",
                target_language="zh-CN",
                model_type="deepseek.chat",
                model="deepseek-chat",
            ),
            api_key="deepseek-secret",
        )
        assert result.provider == "deepseek"
        assert result.usage.total_tokens == 5

    asyncio.run(scenario())
    assert captured["api_key"] == "deepseek-secret"
    assert captured["base_url"] == "https://api.deepseek.com"
    assert captured["model"] == "deepseek-chat"


def test_default_registry_registers_enabled_chinese_providers_with_model_allowlists():
    from translation_backend.app.core.config import AppSettings
    from translation_backend.app.infrastructure.ai_provider.registry import default_registry

    settings = AppSettings(
        _env_file=None,
        ai_provider_enabled=True,
        ai_deepseek_enabled=True,
        ai_qwen_enabled=True,
        ai_deepseek_models="deepseek-chat,deepseek-reasoner",
        ai_qwen_models="qwen-plus,qwen-turbo",
    )
    registry = default_registry(settings=settings)
    registry.validate_model("deepseek.chat", "deepseek-reasoner")
    registry.validate_model("qwen.chat", "qwen-plus")
    with pytest.raises(ModelUnsupportedError):
        registry.validate_model("qwen.chat", "qwen-unknown")


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
        assert usage.cost == Decimal("0.00000200")
        assert usage.pricing_version == "test-pricing-v1"
        assert "provider-secret" not in str(usage)
        assert invoker.last_api_key == "provider-secret-1234"

    run_db_test(scenario)
