from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from tortoise import Tortoise

from translation_backend.main import app
from translation_backend.app.application.auth.service import AuthService
from translation_backend.app.models import User


@pytest.mark.anyio
async def test_user_settings_http_contract() -> None:
    await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["translation_backend.app.models"]})
    await Tortoise.generate_schemas()
    try:
        auth = AuthService()
        user = await User.create(
            username=f"settings-http-{uuid4().hex}",
            email=f"settings-http-{uuid4().hex}@example.com",
            password_hash=auth.hash_password("Strong-pass-123"),
            display_name="Settings HTTP",
        )
        async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
            unauthenticated = await client.get("/api/v1/auth/me/settings")
            assert unauthenticated.status_code == 401

            login = await client.post(
                "/api/v1/auth/login",
                json={"login": user.email, "password": "Strong-pass-123"},
            )
            assert login.status_code == 200
            headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

            current = await client.get("/api/v1/auth/me/settings", headers=headers)
            assert current.status_code == 200
            assert current.json()["appearance"]["theme"] == "system"
            assert current.json()["preferences"]["locale"] == "zh-CN"
            assert current.json()["preferences"]["allow_member_search"] is False

            updated = await client.patch(
                "/api/v1/auth/me/settings",
                headers=headers,
                json={"appearance": {"theme": "dark", "revision": 1}},
            )
            assert updated.status_code == 200
            assert updated.json()["appearance"]["theme"] == "dark"
            assert updated.json()["preferences"]["locale"] == "zh-CN"

            privacy = await client.patch(
                "/api/v1/auth/me/settings",
                headers=headers,
                json={"preferences": {"allow_member_search": True, "revision": 1}},
            )
            assert privacy.status_code == 200
            assert privacy.json()["preferences"]["allow_member_search"] is True

            stale = await client.patch(
                "/api/v1/auth/me/settings",
                headers=headers,
                json={"appearance": {"theme": "light", "revision": 1}},
            )
            assert stale.status_code == 409
            assert stale.json()["error"]["code"] == "SETTINGS_REVISION_CONFLICT"
    finally:
        await Tortoise.close_connections()


@pytest.mark.anyio
async def test_user_profile_http_contract() -> None:
    await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["translation_backend.app.models"]})
    await Tortoise.generate_schemas()
    try:
        auth = AuthService()
        user = await User.create(
            username=f"profile-http-{uuid4().hex}",
            email=f"profile-http-{uuid4().hex}@example.com",
            password_hash=auth.hash_password("Strong-pass-123"),
            display_name="Profile HTTP",
        )
        async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
            login = await client.post("/api/v1/auth/login", json={"login": user.email, "password": "Strong-pass-123"})
            headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

            current = await client.get("/api/v1/auth/me/profile", headers=headers)
            assert current.status_code == 200
            assert current.json() == {"id": str(user.id), "username": user.username, "email": user.email, "display_name": "Profile HTTP"}

            updated = await client.patch("/api/v1/auth/me/profile", headers=headers, json={"display_name": "Profile Updated"})
            assert updated.status_code == 200
            assert updated.json()["display_name"] == "Profile Updated"
            assert await User.get(id=user.id).values_list("display_name", flat=True) == "Profile Updated"

            immutable = await client.patch("/api/v1/auth/me/profile", headers=headers, json={"email": "changed@example.com"})
            assert immutable.status_code == 422

            blank = await client.patch("/api/v1/auth/me/profile", headers=headers, json={"display_name": "   "})
            assert blank.status_code == 422
            assert blank.json()["error"]["code"] == "INVALID_DISPLAY_NAME"
    finally:
        await Tortoise.close_connections()
