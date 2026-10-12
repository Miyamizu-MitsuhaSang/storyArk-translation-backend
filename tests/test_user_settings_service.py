from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from tortoise import Tortoise

from translation_backend.app.application.auth.settings.schemas import UserSettingsUpdateRequest
from translation_backend.app.application.auth.settings.service import (
    UserSettingsConflictError,
    UserSettingsService,
    UnsupportedLocaleError,
)
from translation_backend.app.models import User


def run_db_test(coro):
    async def scenario():
        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["translation_backend.app.models"]})
        await Tortoise.generate_schemas()
        try:
            return await coro()
        finally:
            await Tortoise.close_connections()

    return asyncio.run(scenario())


async def create_user() -> User:
    return await User.create(
        username=f"settings-{uuid4().hex}",
        email=f"settings-{uuid4().hex}@example.com",
        password_hash="hash",
        display_name="Settings user",
    )


def test_user_settings_get_creates_defaults_and_patch_is_partial() -> None:
    async def scenario() -> None:
        user = await create_user()
        service = UserSettingsService()

        initial = await service.get(user)
        assert initial.appearance.theme == "system"
        assert initial.preferences.locale == "zh-CN"
        assert initial.preferences.allow_member_search is False
        assert initial.appearance.revision == 1

        updated = await service.update(
            user,
            UserSettingsUpdateRequest(preferences={"locale": "en-US", "revision": 1}),
        )
        assert updated.preferences.locale == "en-US"
        assert updated.preferences.allow_member_search is False
        assert updated.preferences.revision == 2
        assert updated.appearance.theme == "system"
        assert updated.appearance.revision == 1

    run_db_test(scenario)


def test_user_can_update_member_search_privacy() -> None:
    async def scenario() -> None:
        user = await create_user()
        service = UserSettingsService()
        await service.get(user)
        updated = await service.update(
            user,
            UserSettingsUpdateRequest(preferences={"allow_member_search": True, "revision": 1}),
        )
        assert updated.preferences.allow_member_search is True
        assert updated.preferences.revision == 2

    run_db_test(scenario)


def test_user_settings_reject_invalid_locale_and_stale_revision() -> None:
    async def scenario() -> None:
        user = await create_user()
        service = UserSettingsService()
        await service.get(user)

        with pytest.raises(UnsupportedLocaleError):
            await service.update(user, UserSettingsUpdateRequest(preferences={"locale": "fr-FR"}))

        with pytest.raises(UserSettingsConflictError):
            await service.update(user, UserSettingsUpdateRequest(appearance={"theme": "dark", "revision": 2}))

    run_db_test(scenario)
