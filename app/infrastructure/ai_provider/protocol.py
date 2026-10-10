from __future__ import annotations

from typing import Protocol

from ...domain.ai_translation.contracts import TranslationRequest, TranslationResult


class ModelInvoker(Protocol):
    async def translate(self, request: TranslationRequest, *, api_key: str) -> TranslationResult:
        ...


__all__ = ["ModelInvoker"]
