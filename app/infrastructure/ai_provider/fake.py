from __future__ import annotations

from ...domain.ai_translation.contracts import TranslationRequest, TranslationResult


class FakeModelInvoker:
    def __init__(self, result: TranslationResult | None = None) -> None:
        self._result = result
        self.last_api_key: str | None = None

    async def translate(self, request: TranslationRequest, *, api_key: str) -> TranslationResult:
        self.last_api_key = api_key
        return self._result or TranslationResult(
            text=request.text,
            provider="custom",
            model_type=request.model_type,
            model=request.model,
        )


__all__ = ["FakeModelInvoker"]
