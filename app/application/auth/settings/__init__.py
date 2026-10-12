"""Application use cases for authenticated user settings."""

from .schemas import (
    AppearanceSettingsResponse,
    AppearanceSettingsUpdate,
    UserPreferencesResponse,
    UserPreferencesUpdate,
    UserSettingsResponse,
    UserSettingsUpdateRequest,
)
from .service import (
    UnsupportedLocaleError,
    UserSettingsConflictError,
    UserSettingsService,
)

__all__ = [
    "AppearanceSettingsResponse",
    "AppearanceSettingsUpdate",
    "UnsupportedLocaleError",
    "UserPreferencesResponse",
    "UserPreferencesUpdate",
    "UserSettingsConflictError",
    "UserSettingsResponse",
    "UserSettingsService",
    "UserSettingsUpdateRequest",
]
