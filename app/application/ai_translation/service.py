from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from ...domain.ai_translation.contracts import TranslationRequest, TranslationResult
from ...domain.ai_translation.errors import AiTranslationError, ProviderCallError, ProviderMismatchError
from ...models import AIProviderCredential, ProjectMember, User
from ...repositories.usage import AIUsageRepository
from ...infrastructure.ai_provider.registry import ModelInvokerRegistry
from ..auth.api_key.service import ApiKeyService


class AiTranslationService:
    def __init__(
        self,
        *,
        registry: ModelInvokerRegistry,
        api_key_service: ApiKeyService,
        usage_repository: AIUsageRepository | None = None,
    ) -> None:
        self._registry = registry
        self._api_keys = api_key_service
        self._usage = usage_repository or AIUsageRepository()

    async def translate(
        self,
        user: User,
        project_id: UUID,
        api_key_id: UUID,
        request: TranslationRequest,
    ) -> TranslationResult:
        if not await ProjectMember.filter(project_id=project_id, user_id=user.id).exists():
            raise AiTranslationError("项目不存在或当前用户不可见", code="AI_TRANSLATION_NOT_FOUND")
        credential = await AIProviderCredential.filter(id=api_key_id, user_id=user.id, is_active=True).first()
        if credential is None:
            raise AiTranslationError("API key 不存在或不可用", code="API_KEY_NOT_FOUND")
        expected_provider = self._registry.provider_for(request.model_type)
        if expected_provider != credential.provider:
            raise ProviderMismatchError("API key provider 与 model_type 不匹配", code="PROVIDER_MISMATCH")
        invoker = self._registry.resolve(request.model_type)
        secret = await self._api_keys.decrypt(credential)
        started = datetime.now(timezone.utc)
        try:
            result = await invoker.translate(request, api_key=secret)
        except Exception as exc:
            completed = datetime.now(timezone.utc)
            await self._record_usage(user, project_id, credential, request, status="failed", started=started, completed=completed, error_code="PROVIDER_CALL_FAILED")
            if isinstance(exc, AiTranslationError):
                raise
            raise ProviderCallError("翻译 provider 调用失败", code="PROVIDER_CALL_FAILED") from None
        completed = datetime.now(timezone.utc)
        await self._record_usage(user, project_id, credential, request, status="succeeded", started=started, completed=completed, result=result)
        return result

    async def _record_usage(self, user, project_id, credential, request, *, status, started, completed, result=None, error_code=None):
        usage = result.usage if result is not None else None
        await self._usage.create(
            user_id=user.id,
            project_id=project_id,
            api_key_id=credential.id,
            provider=credential.provider,
            model=request.model,
            provider_request_id=result.provider_request_id if result is not None else None,
            status=status,
            input_tokens=usage.input_tokens if usage else 0,
            output_tokens=usage.output_tokens if usage else 0,
            cached_input_tokens=usage.cached_input_tokens if usage else 0,
            reasoning_tokens=usage.reasoning_tokens if usage else 0,
            total_tokens=usage.total_tokens if usage else 0,
            started_at=started,
            completed_at=completed,
            latency_ms=max(0, int((completed - started).total_seconds() * 1000)),
            error_code=error_code,
        )


__all__ = ["AiTranslationService", "AiTranslationError"]
