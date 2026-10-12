from __future__ import annotations

from typing import Any

from tortoise.transactions import in_transaction

from ....models import AppearanceSettings, User, UserPreferences
from ...auth.service import AuthError
from .schemas import (
    AppearanceSettingsResponse,
    UserPreferencesResponse,
    UserSettingsResponse,
    UserSettingsUpdateRequest,
)


SUPPORTED_LOCALES = frozenset({"zh-CN", "en-US"})


class UserSettingsError(AuthError):
    def __init__(self, code: str, message: str, *, status_code: int = 422, details: dict[str, Any] | None = None):
        super().__init__(code, message, status_code=status_code, details=details)


class UserSettingsConflictError(UserSettingsError):
    def __init__(self, message: str = "设置版本已变化，请刷新后重试"):
        super().__init__("SETTINGS_REVISION_CONFLICT", message, status_code=409)


class UnsupportedLocaleError(UserSettingsError):
    def __init__(self, locale: str):
        super().__init__(
            "UNSUPPORTED_LOCALE",
            "不支持的界面语言",
            details={"locale": locale, "supported_locales": sorted(SUPPORTED_LOCALES)},
        )


class UserSettingsService:
    async def get(self, user: User) -> UserSettingsResponse:
        appearance, preferences = await self._ensure_settings(user)
        return self._response(appearance, preferences)

    async def update(self, user: User, request: UserSettingsUpdateRequest) -> UserSettingsResponse:
        async with in_transaction():
            appearance, preferences = await self._ensure_settings(user)

            if request.appearance is not None:
                update = request.appearance
                self._check_revision(update.revision, appearance.revision)
                if update.theme is not None:
                    appearance.theme = update.theme
                if update.theme is not None:
                    appearance.revision += 1
                    await appearance.save(update_fields=["theme", "revision", "updated_at"])

            if request.preferences is not None:
                update = request.preferences
                self._check_revision(update.revision, preferences.revision)
                if update.locale is not None:
                    if update.locale not in SUPPORTED_LOCALES:
                        raise UnsupportedLocaleError(update.locale)
                    preferences.locale = update.locale
                changed = update.locale is not None or update.allow_member_search is not None
                if update.allow_member_search is not None:
                    preferences.allow_member_search = update.allow_member_search
                if changed:
                    preferences.revision += 1
                    await preferences.save(update_fields=["locale", "allow_member_search", "revision", "updated_at"])

        await appearance.refresh_from_db()
        await preferences.refresh_from_db()
        return self._response(appearance, preferences)

    async def _ensure_settings(self, user: User) -> tuple[AppearanceSettings, UserPreferences]:
        appearance, _ = await AppearanceSettings.get_or_create(user_id=user.id, defaults={"user": user})
        preferences, _ = await UserPreferences.get_or_create(user_id=user.id, defaults={"user": user})
        return appearance, preferences

    @staticmethod
    def _check_revision(expected: int | None, current: int) -> None:
        if expected is not None and expected != current:
            raise UserSettingsConflictError()

    @staticmethod
    def _response(appearance: AppearanceSettings, preferences: UserPreferences) -> UserSettingsResponse:
        return UserSettingsResponse(
            appearance=AppearanceSettingsResponse.model_validate(appearance),
            preferences=UserPreferencesResponse.model_validate(preferences),
        )


__all__ = [
    "SUPPORTED_LOCALES",
    "UnsupportedLocaleError",
    "UserSettingsConflictError",
    "UserSettingsError",
    "UserSettingsService",
]
