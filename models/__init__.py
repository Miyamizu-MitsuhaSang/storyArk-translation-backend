"""Compatibility exports for the canonical ``app.models`` package.

The backend source now owns ORM models under ``app/models``. This module keeps
the historical ``translation_backend.models`` import path working for callers
and existing migrations while avoiding a second model definition.
"""

try:
    from ..app.models import (
        AIProviderCredential,
        AIUsageRecord,
        Project,
        ProjectApiKeyBinding,
        ProjectLanguagePair,
        ProjectMember,
        RefreshToken,
        TimestampedModel,
        User,
        Worldview,
        WorldviewEntry,
    )
except ImportError:
    from app.models import (
        AIProviderCredential,
        AIUsageRecord,
        Project,
        ProjectApiKeyBinding,
        ProjectLanguagePair,
        ProjectMember,
        RefreshToken,
        TimestampedModel,
        User,
        Worldview,
        WorldviewEntry,
    )

__all__ = [
    "AIProviderCredential",
    "AIUsageRecord",
    "Project",
    "ProjectApiKeyBinding",
    "ProjectLanguagePair",
    "ProjectMember",
    "RefreshToken",
    "TimestampedModel",
    "User",
    "Worldview",
    "WorldviewEntry",
]
