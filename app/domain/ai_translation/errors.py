from __future__ import annotations


class AiTranslationError(Exception):
    """Stable application error that never carries provider response bodies or secrets."""

    status_code = 422
    code = "AI_TRANSLATION_ERROR"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class ModelTypeUnsupportedError(AiTranslationError):
    code = "MODEL_TYPE_UNSUPPORTED"


class ProviderMismatchError(AiTranslationError):
    code = "PROVIDER_MISMATCH"


class ProviderCallError(AiTranslationError):
    code = "PROVIDER_CALL_FAILED"


__all__ = [
    "AiTranslationError",
    "ModelTypeUnsupportedError",
    "ProviderCallError",
    "ProviderMismatchError",
]
