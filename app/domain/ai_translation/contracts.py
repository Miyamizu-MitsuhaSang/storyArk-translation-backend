from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID


def _validate_context(value: dict[str, Any]) -> dict[str, Any]:
    blocked = {"api_key", "apikey", "secret", "token", "password", "credential"}
    if any(str(key).casefold() in blocked for key in value):
        raise ValueError("context 不能包含凭据字段")
    return dict(value)


@dataclass(frozen=True, slots=True)
class TranslationRequest:
    text: str
    source_language: str
    target_language: str
    model_type: str
    model: str
    context: dict[str, Any] = field(default_factory=dict)
    temperature: float = 0.2
    max_tokens: int | None = None
    request_id: UUID | None = None

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("text 不能为空")
        if not self.source_language.strip() or not self.target_language.strip():
            raise ValueError("语言不能为空")
        if self.source_language.casefold() == self.target_language.casefold():
            raise ValueError("源语言和目标语言不能相同")
        if not self.model_type.strip() or not self.model.strip():
            raise ValueError("model_type 和 model 不能为空")
        if not 0 <= self.temperature <= 2:
            raise ValueError("temperature 必须在 0 到 2 之间")
        if self.max_tokens is not None and self.max_tokens < 1:
            raise ValueError("max_tokens 必须为正数")
        _validate_context(self.context)


@dataclass(frozen=True, slots=True)
class UsageSnapshot:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0

    def __post_init__(self) -> None:
        if any(value < 0 for value in (
            self.input_tokens,
            self.output_tokens,
            self.cached_input_tokens,
            self.reasoning_tokens,
            self.total_tokens,
        )):
            raise ValueError("usage token 不能为负数")


@dataclass(frozen=True, slots=True)
class TranslationResult:
    text: str
    provider: str
    model_type: str
    model: str
    provider_request_id: str | None = None
    usage: UsageSnapshot = field(default_factory=UsageSnapshot)
    latency_ms: int | None = None
    finish_reason: str | None = None
    warnings: tuple[str, ...] = ()


__all__ = ["TranslationRequest", "TranslationResult", "UsageSnapshot"]
