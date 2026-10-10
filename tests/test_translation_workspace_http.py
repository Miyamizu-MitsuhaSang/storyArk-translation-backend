from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from tortoise import Tortoise

from translation_backend.main import app
from translation_backend.app.application.auth.service import AuthService
from translation_backend.app.models import Project, ProjectMember, User


@pytest.mark.anyio
async def test_http_login_project_version_api_key_and_analytics_scope():
    await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["translation_backend.app.models"]})
    await Tortoise.generate_schemas()
    try:
        auth = AuthService()
        user = await User.create(
            username=f"http-owner-{uuid4().hex}",
            email=f"http-owner-{uuid4().hex}@example.com",
            password_hash=auth.hash_password("Strong-pass-123"),
            display_name="HTTP owner",
        )
        outsider = await User.create(
            username=f"http-outsider-{uuid4().hex}",
            email=f"http-outsider-{uuid4().hex}@example.com",
            password_hash=auth.hash_password("Strong-pass-123"),
            display_name="HTTP outsider",
        )
        project = await Project.create(key=f"http-{uuid4().hex}", name="HTTP project", created_by=user)
        other_project = await Project.create(key=f"http-other-{uuid4().hex}", name="Other HTTP project", created_by=outsider)
        await ProjectMember.create(project=project, user=user, role="owner")
        await ProjectMember.create(project=other_project, user=outsider, role="owner")

        async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
            login = await client.post(
                "/api/v1/auth/login",
                json={"login": user.email, "password": "Strong-pass-123", "remember_me": False},
            )
            assert login.status_code == 200
            token = login.json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}

            me = await client.get("/api/v1/auth/me", headers=headers)
            assert me.status_code == 200
            assert me.json()["user"]["id"] == str(user.id)

            created_version = await client.post(
                f"/api/v1/projects/{project.id}/versions",
                headers=headers,
                json={"name": "HTTP review", "target_languages": ["en"]},
            )
            assert created_version.status_code == 201
            version = created_version.json()
            assert version["version_number"] == 1

            versions = await client.get(f"/api/v1/projects/{project.id}/versions", headers=headers)
            assert versions.status_code == 200
            assert versions.json()["items"][0]["id"] == version["id"]

            key_transport = await client.post(
                "/api/v1/auth/me/api-keys",
                headers=headers,
                json={"provider": "custom", "label": "HTTP key", "secret": "http-secret-value"},
            )
            assert key_transport.status_code == 201
            assert "http-secret-value" not in key_transport.text

            usage = await client.get(f"/api/v1/projects/{project.id}/analytics/usage", headers=headers)
            assert usage.status_code == 200
            assert usage.json()["totals"]["call_count"] == 0

            report = await client.get(f"/api/v1/projects/{project.id}/analytics/translation-report", headers=headers)
            assert report.status_code == 200
            assert report.json()["summary"] == {"task_count": 0, "translated_words": 0}

            cross_project = await client.get(f"/api/v1/projects/{other_project.id}/analytics/usage", headers=headers)
            assert cross_project.status_code == 404
    finally:
        await Tortoise.close_connections()
