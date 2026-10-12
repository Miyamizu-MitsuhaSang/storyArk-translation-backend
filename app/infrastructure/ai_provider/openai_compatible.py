from __future__ import annotations

from time import perf_counter
from typing import Any, Callable

from ...domain.ai_translation.contracts import ProviderCapabilities, TranslationRequest, TranslationResult, UsageSnapshot
from ...domain.ai_translation.errors import ProviderAuthenticationError, ProviderCallError, ProviderRateLimitError, ProviderTimeoutError


class OpenAICompatibleInvoker:
    """Adapter for providers exposing the OpenAI Chat Completions protocol."""

    capabilities = ProviderCapabilities(supports_usage=True, supports_context=True)

    def __init__(
        self,
        *,
        provider: str,
        base_url: str,
        client_factory: Callable[[str, str], Any] | None = None,
    ) -> None:
        self.provider = provider
        self.base_url = base_url
        self._client_factory = client_factory

    async def translate(self, request: TranslationRequest, *, api_key: str) -> TranslationResult:
        try:
            client = self._client_factory(api_key, self.base_url) if self._client_factory else self._client(api_key, self.base_url)
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
            input_tokens = int(getattr(usage, "prompt_tokens", getattr(usage, "input_tokens", 0)) or 0)
            output_tokens = int(getattr(usage, "completion_tokens", getattr(usage, "output_tokens", 0)) or 0)
            total_tokens = int(getattr(usage, "total_tokens", input_tokens + output_tokens) or 0)
            return TranslationResult(
                text=text.strip(),
                provider=self.provider,
                model_type=request.model_type,
                model=request.model,
                provider_request_id=getattr(response, "id", None),
                usage=UsageSnapshot(
                    input_tokens=max(0, input_tokens),
                    output_tokens=max(0, output_tokens),
                    total_tokens=max(0, total_tokens),
                ),
                latency_ms=max(0, int((perf_counter() - started) * 1000)),
                finish_reason=getattr(choices[0], "finish_reason", None),
            )
        except ProviderCallError:
            raise
        except Exception as exc:
            name = type(exc).__name__.casefold()
            if "timeout" in name:
                raise ProviderTimeoutError("provider 请求超时", code="PROVIDER_TIMEOUT") from None
            if "ratelimit" in name or "rate_limit" in name:
                raise ProviderRateLimitError("provider 请求受限", code="PROVIDER_RATE_LIMITED") from None
            if "authentication" in name or "permission" in name:
                raise ProviderAuthenticationError("provider 凭据无效", code="PROVIDER_AUTH_FAILED") from None
            raise ProviderCallError("兼容协议 provider 调用失败", code="PROVIDER_CALL_FAILED") from None

    @staticmethod
    def _client(api_key: str, base_url: str) -> Any:
        from openai import AsyncOpenAI

        return AsyncOpenAI(api_key=api_key, base_url=base_url)


__all__ = ["OpenAICompatibleInvoker"]
