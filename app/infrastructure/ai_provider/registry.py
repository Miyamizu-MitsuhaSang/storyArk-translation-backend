from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
from typing import TYPE_CHECKING

from ...domain.ai_translation.contracts import ProviderCapabilities
from ...domain.ai_translation.errors import ModelTypeUnsupportedError, ModelUnsupportedError
from .protocol import ModelInvoker

if TYPE_CHECKING:
    from ...core.config import AppSettings


@dataclass(frozen=True, slots=True)
class ModelRegistration:
    provider: str
    invoker: ModelInvoker
    supported_models: frozenset[str] | None = None
    capabilities: ProviderCapabilities = ProviderCapabilities()

    def supports_model(self, model: str) -> bool:
        return self.supported_models is None or model in self.supported_models


class ModelInvokerRegistry:
    """Immutable allowlist; user input can select a key but cannot import code."""

    def __init__(self, entries: Mapping[str, tuple[str, ModelInvoker] | ModelRegistration]) -> None:
        self._entries: dict[str, ModelRegistration] = {
            model_type: entry if isinstance(entry, ModelRegistration) else ModelRegistration(provider=entry[0], invoker=entry[1], capabilities=getattr(entry[1], "capabilities", ProviderCapabilities()))
            for model_type, entry in entries.items()
        }

    def resolve(self, model_type: str) -> ModelInvoker:
        try:
            return self._entries[model_type].invoker
        except KeyError as exc:
            raise ModelTypeUnsupportedError("不支持的 model_type", code="MODEL_TYPE_UNSUPPORTED") from exc

    def provider_for(self, model_type: str) -> str:
        try:
            return self._entries[model_type].provider
        except KeyError as exc:
            raise ModelTypeUnsupportedError("不支持的 model_type", code="MODEL_TYPE_UNSUPPORTED") from exc

    def capabilities_for(self, model_type: str) -> ProviderCapabilities:
        try:
            return self._entries[model_type].capabilities
        except KeyError as exc:
            raise ModelTypeUnsupportedError("不支持的 model_type", code="MODEL_TYPE_UNSUPPORTED") from exc

    def validate_model(self, model_type: str, model: str) -> None:
        try:
            registration = self._entries[model_type]
        except KeyError as exc:
            raise ModelTypeUnsupportedError("不支持的 model_type", code="MODEL_TYPE_UNSUPPORTED") from exc
        if not registration.supports_model(model):
            raise ModelUnsupportedError("当前 model_type 不支持该模型", code="MODEL_UNSUPPORTED")


def _model_allowlist(value: str) -> frozenset[str]:
    return frozenset(item.strip() for item in value.split(",") if item.strip())


def default_registry(*, settings: AppSettings | None = None) -> ModelInvokerRegistry:
    from ...core.config import app_settings
    from .openai_chat import OpenAIChatInvoker
    from .openai_compatible import OpenAICompatibleInvoker

    settings = settings or app_settings
    invoker = OpenAIChatInvoker()
    entries: dict[str, ModelRegistration] = {
        "openai.chat": ModelRegistration(provider="openai", invoker=invoker, capabilities=invoker.capabilities),
    }
    if settings.ai_provider_enabled and settings.ai_deepseek_enabled:
        deepseek = OpenAICompatibleInvoker(provider="deepseek", base_url=settings.ai_deepseek_base_url)
        entries["deepseek.chat"] = ModelRegistration(
            provider="deepseek",
            invoker=deepseek,
            supported_models=_model_allowlist(settings.ai_deepseek_models),
            capabilities=deepseek.capabilities,
        )
    if settings.ai_provider_enabled and settings.ai_qwen_enabled:
        qwen = OpenAICompatibleInvoker(provider="qwen", base_url=settings.ai_qwen_base_url)
        entries["qwen.chat"] = ModelRegistration(
            provider="qwen",
            invoker=qwen,
            supported_models=_model_allowlist(settings.ai_qwen_models),
            capabilities=qwen.capabilities,
        )
    return ModelInvokerRegistry(entries)


__all__ = ["ModelInvokerRegistry", "ModelRegistration", "default_registry"]
