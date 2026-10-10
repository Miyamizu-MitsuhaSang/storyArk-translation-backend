from __future__ import annotations

from time import perf_counter
from typing import Any, Callable

from ...domain.ai_translation.contracts import TranslationRequest, TranslationResult, UsageSnapshot
from ...domain.ai_translation.errors import ProviderCallError


class OpenAIChatInvoker:
    """Lazy OpenAI Chat Completions adapter; SDK errors are normalized."""

    provider = "openai"

    def __init__(self, *, client_factory: Callable[[str], Any] | None = None) -> None:
        self._client_factory = client_factory

    async def translate(self, request: TranslationRequest, *, api_key: str) -> TranslationResult:
        try:
            client = self._client_factory(api_key) if self._client_factory else self._client(api_key)
            started = perf_counter()
            response = await client.chat.completions.create(
                model=request.model,
                messages=[
                    {"role": "system", "content": f"Translate from {request.source_language} to {request.target_language}."},
                    {"role": "user", "content": request.text},
                ],
                temperature=request.temperature,
                **({"max_tokens": request.max_tokens} if request.max_tokens is not None else {}),
            )
            choices = getattr(response, "choices", None) or []
            if not choices or not getattr(choices[0], "message", None):
                raise ProviderCallError("provider 返回空结果", code="PROVIDER_EMPTY_RESPONSE")
            text = getattr(choices[0].message, "content", None)
            if not isinstance(text, str) or not text.strip():
                raise ProviderCallError("provider 返回空译文", code="PROVIDER_EMPTY_RESPONSE")
            usage = getattr(response, "usage", None)
            prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
            completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
            total_tokens = int(getattr(usage, "total_tokens", prompt_tokens + completion_tokens) or 0)
            return TranslationResult(
                text=text.strip(),
                provider=self.provider,
                model_type=request.model_type,
                model=request.model,
                provider_request_id=getattr(response, "id", None),
                usage=UsageSnapshot(
                    input_tokens=max(0, prompt_tokens),
                    output_tokens=max(0, completion_tokens),
                    total_tokens=max(0, total_tokens),
                ),
                latency_ms=max(0, int((perf_counter() - started) * 1000)),
                finish_reason=getattr(choices[0], "finish_reason", None),
            )
        except ProviderCallError:
            raise
        except Exception as exc:
            raise ProviderCallError("OpenAI provider 调用失败", code="PROVIDER_CALL_FAILED") from None

    @staticmethod
    def _client(api_key: str) -> Any:
        from openai import AsyncOpenAI

        return AsyncOpenAI(api_key=api_key)


__all__ = ["OpenAIChatInvoker"]
