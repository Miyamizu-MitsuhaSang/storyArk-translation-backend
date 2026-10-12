from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from tortoise import Tortoise

from translation_backend.app.application.auth.service import AuthService
from translation_backend.app.models import Project, ProjectLanguagePair, ProjectMember, User
from translation_backend.main import app


@pytest.mark.anyio
async def test_project_settings_http_permissions_revision_and_validation() -> None:
    await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["translation_backend.app.models"]})
    await Tortoise.generate_schemas()
    try:
        auth = AuthService()

        async def create_user(label: str) -> User:
            token = uuid4().hex
            return await User.create(
                username=f"project-settings-{label}-{token}",
                email=f"project-settings-{label}-{token}@example.com",
                password_hash=auth.hash_password("Strong-pass-123"),
                display_name=label,
            )

        owner, viewer, outsider = [await create_user(label) for label in ("owner", "viewer", "outsider")]
        project = await Project.create(
            key=f"project-settings-api-{uuid4().hex}",
            name="Project settings API",
            created_by=owner,
        )
        await ProjectMember.create(project=project, user=owner, role="owner")
        await ProjectMember.create(project=project, user=viewer, role="viewer")
        await ProjectLanguagePair.create(
            project=project,
            source_language="zh-CN",
            target_language="en-US",
            is_default=True,
        )

        async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as client:
            path = f"/api/v1/projects/{project.id}/settings"
            assert (await client.get(path)).status_code == 401

            async def login(user: User, label: str) -> dict[str, str]:
                response = await client.post(
                    "/api/v1/auth/login",
                    json={"login": user.username, "password": "Strong-pass-123"},
                )
                assert response.status_code == 200
                return {"Authorization": f"Bearer {response.json()['access_token']}"}

            owner_headers = await login(owner, "owner")
            viewer_headers = await login(viewer, "viewer")
            outsider_headers = await login(outsider, "outsider")

            owner_get = await client.get(path, headers=owner_headers)
            assert owner_get.status_code == 200
            assert owner_get.json()["revision"] == 1
            assert (await client.get(path, headers=viewer_headers)).status_code == 200

            updated = await client.patch(
                path,
                headers={**owner_headers, "If-Match": '"1"'},
                json={"quality_threshold": 0.85},
            )
            assert updated.status_code == 200
            assert updated.json()["revision"] == 2
            assert updated.json()["quality_threshold"] == pytest.approx(0.85)

            assert (await client.patch(path, headers=viewer_headers, json={"quality_threshold": 0.8})).status_code == 403
            assert (await client.get(path, headers=outsider_headers)).status_code == 404

            stale = await client.patch(
                path,
                headers=owner_headers,
                json={"quality_threshold": 0.8, "revision": 1},
            )
            assert stale.status_code == 409

            invalid = await client.patch(
                path,
                headers=owner_headers,
                json={"quality_threshold": 1.1},
            )
            assert invalid.status_code == 422
    finally:
        await Tortoise.close_connections()
