from __future__ import annotations

from collections.abc import Mapping

from ...domain.ai_translation.errors import ModelTypeUnsupportedError
from .protocol import ModelInvoker


class ModelInvokerRegistry:
    """Immutable allowlist; user input can select a key but cannot import code."""

    def __init__(self, entries: Mapping[str, tuple[str, ModelInvoker]]) -> None:
        self._entries = dict(entries)

    def resolve(self, model_type: str) -> ModelInvoker:
        try:
            return self._entries[model_type][1]
        except KeyError as exc:
            raise ModelTypeUnsupportedError("不支持的 model_type", code="MODEL_TYPE_UNSUPPORTED") from exc

    def provider_for(self, model_type: str) -> str:
        try:
            return self._entries[model_type][0]
        except KeyError as exc:
            raise ModelTypeUnsupportedError("不支持的 model_type", code="MODEL_TYPE_UNSUPPORTED") from exc


def default_registry() -> ModelInvokerRegistry:
    from .openai_chat import OpenAIChatInvoker

    return ModelInvokerRegistry({"openai.chat": ("openai", OpenAIChatInvoker())})


__all__ = ["ModelInvokerRegistry", "default_registry"]
