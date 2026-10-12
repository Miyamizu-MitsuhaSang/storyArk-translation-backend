from __future__ import annotations


class AiTranslationError(Exception):
    """Stable application error that never carries provider response bodies or secrets."""

    status_code = 422
    code = "AI_TRANSLATION_ERROR"
    retryable = False

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


class ProviderTimeoutError(ProviderCallError):
    code = "PROVIDER_TIMEOUT"
    retryable = True


class ProviderRateLimitError(ProviderCallError):
    code = "PROVIDER_RATE_LIMITED"
    retryable = True


class ProviderAuthenticationError(ProviderCallError):
    code = "PROVIDER_AUTH_FAILED"
    retryable = False


class ModelUnsupportedError(AiTranslationError):
    code = "MODEL_UNSUPPORTED"
    retryable = False


__all__ = [
    "AiTranslationError",
    "ModelTypeUnsupportedError",
    "ProviderCallError",
    "ProviderAuthenticationError",
    "ProviderMismatchError",
    "ProviderRateLimitError",
    "ProviderTimeoutError",
    "ModelUnsupportedError",
]
