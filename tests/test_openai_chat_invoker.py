from __future__ import annotations

from types import SimpleNamespace

import asyncio

from translation_backend.app.domain.ai_translation.contracts import TranslationRequest
from translation_backend.app.infrastructure.ai_provider.openai_chat import OpenAIChatInvoker


def test_openai_chat_invoker_maps_request_response_and_usage():
    captured = {}

    class Completions:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                id="req-123",
                choices=[SimpleNamespace(message=SimpleNamespace(content="  你好  "), finish_reason="stop")],
                usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2, total_tokens=5),
            )

    class Client:
        chat = SimpleNamespace(completions=Completions())

    async def scenario():
        invoker = OpenAIChatInvoker(client_factory=lambda api_key: (captured.update(api_key=api_key) or Client()))
        result = await invoker.translate(
            TranslationRequest(
                text="hello",
                source_language="en",
                target_language="zh-CN",
                model_type="openai.chat",
                model="gpt-test",
                temperature=0.4,
                max_tokens=40,
            ),
            api_key="provider-secret",
        )
        assert result.text == "你好"
        assert result.provider_request_id == "req-123"
        assert result.usage.total_tokens == 5
        assert captured["api_key"] == "provider-secret"
        assert captured["model"] == "gpt-test"
        assert captured["temperature"] == 0.4
        assert captured["max_tokens"] == 40
        assert captured["messages"][1]["content"] == "hello"

    asyncio.run(scenario())
