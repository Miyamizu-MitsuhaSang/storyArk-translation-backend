from __future__ import annotations

import base64
import os
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from .schemas import (
    ApiKeyPage,
    ApiKeyResponse,
    CreateApiKeyRequest,
    UpdateApiKeyRequest,
)
from .....models import AIProviderCredential, User


class ApiKeyError(Exception):
    status_code = 400
    code = "API_KEY_ERROR"


class ApiKeyEncryptionUnavailableError(ApiKeyError):
    status_code = 503
    code = "API_KEY_ENCRYPTION_UNAVAILABLE"


class ApiKeyNotFoundError(ApiKeyError):
    status_code = 404
    code = "API_KEY_NOT_FOUND"


class ApiKeyInUseError(ApiKeyError):
    status_code = 409
    code = "API_KEY_IN_USE"


class ApiKeyService:
    def __init__(self, *, encryption_key: bytes | None = None, key_version: str | None = None) -> None:
        self._encryption_key = encryption_key or self._load_key_from_settings()
        if len(self._encryption_key) != 32:
            raise ApiKeyEncryptionUnavailableError("API key 加密配置不可用")
        self._key_version = key_version or self._load_key_version()

    async def list(self, user: User, *, page_size: int, cursor: str | None) -> ApiKeyPage:
        query = AIProviderCredential.filter(user=user).order_by("-created_at")
        total = await query.count()
        offset = self._decode_cursor(cursor)
        rows = await query.offset(offset).limit(page_size)
        items = [self._response(item) for item in rows]
        next_offset = offset + len(items)
        return ApiKeyPage(
            items=items,
            next_cursor=self._encode_cursor(next_offset) if next_offset < total else None,
            total=total,
        )

    async def get(self, user: User, key_id: UUID) -> ApiKeyResponse:
        credential = await self._owned(user, key_id)
        return self._response(credential)

    async def create(self, user: User, request: CreateApiKeyRequest) -> ApiKeyResponse:
        secret = request.secret.strip()
        if not secret:
            raise ApiKeyError("secret 不能为空")
        nonce = os.urandom(12)
        ciphertext = AESGCM(self._encryption_key).encrypt(nonce, secret.encode(), None)
        credential = await AIProviderCredential.create(
            user=user,
            provider=request.provider,
            label=request.label.strip() if request.label else None,
            api_key_ciphertext=base64.urlsafe_b64encode(ciphertext).decode("ascii"),
            encryption_nonce=base64.urlsafe_b64encode(nonce).decode("ascii"),
            encryption_key_version=self._key_version,
            key_hint=secret[-4:],
            key_prefix=secret[: min(8, max(0, len(secret) - 4))],
        )
        return self._response(credential)

    async def update(self, user: User, key_id: UUID, request: UpdateApiKeyRequest) -> ApiKeyResponse:
        credential = await self._owned(user, key_id)
        changes = request.model_dump(exclude_unset=True)
        if "label" in changes and changes["label"]:
            changes["label"] = changes["label"].strip()
        update_fields: list[str] = []
        for field, value in changes.items():
            model_field = "is_active" if field == "status" else field
            setattr(credential, model_field, value == "active" if field == "status" else value)
            update_fields.append(model_field)
        if changes:
            await credential.save(update_fields=[*update_fields, "updated_at"])
        return self._response(credential)

    async def delete(self, user: User, key_id: UUID) -> None:
        credential = await self._owned(user, key_id)
        # Project key bindings will supply this check when their model is added.
        await credential.delete()

    async def decrypt(self, credential: AIProviderCredential) -> str:
        nonce = base64.urlsafe_b64decode(credential.encryption_nonce)
        ciphertext = base64.urlsafe_b64decode(credential.api_key_ciphertext)
        return AESGCM(self._encryption_key).decrypt(nonce, ciphertext, None).decode()

    async def _owned(self, user: User, key_id: UUID) -> AIProviderCredential:
        credential = await AIProviderCredential.filter(user=user, id=key_id).first()
        if credential is None:
            raise ApiKeyNotFoundError("API key 不存在")
        return credential

    @staticmethod
    def _response(credential: AIProviderCredential) -> ApiKeyResponse:
        suffix = credential.key_hint or ""
        return ApiKeyResponse(
            id=credential.id,
            provider=credential.provider,
            label=credential.label,
            masked_secret=f"{credential.key_prefix or ''}{'•' * 8}{suffix}",
            last_four=suffix,
            status="active" if credential.is_active else "inactive",
            created_at=credential.created_at,
            last_used_at=getattr(credential, "last_used_at", None),
        )

    @staticmethod
    def _encode_cursor(offset: int) -> str:
        return base64.urlsafe_b64encode(str(offset).encode()).decode().rstrip("=")

    @staticmethod
    def _decode_cursor(cursor: str | None) -> int:
        if not cursor:
            return 0
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            offset = int(base64.urlsafe_b64decode(padded).decode())
        except (ValueError, UnicodeDecodeError, base64.binascii.Error) as exc:
            raise ApiKeyError("分页游标无效") from exc
        if offset < 0:
            raise ApiKeyError("分页游标无效")
        return offset

    @staticmethod
    def _load_key_from_settings() -> bytes:
        from .....core.config import security_settings

        raw = security_settings.auth_api_key_encryption_key
        if not raw:
            raise ApiKeyEncryptionUnavailableError("API key 加密配置不可用")
        try:
            key = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        except (ValueError, base64.binascii.Error) as exc:
            raise ApiKeyEncryptionUnavailableError("API key 加密配置不可用") from exc
        if len(key) != 32:
            raise ApiKeyEncryptionUnavailableError("API key 加密配置不可用")
        return key

    @staticmethod
    def _load_key_version() -> str:
        from .....core.config import security_settings

        return security_settings.auth_api_key_encryption_key_version
