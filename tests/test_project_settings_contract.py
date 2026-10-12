from __future__ import annotations

from translation_backend.main import app


def test_project_settings_paths_are_exposed_under_dedicated_tag() -> None:
    document = app.openapi()
    paths = document["paths"]

    assert "/api/v1/projects/{project_id}/settings" in paths
    operations = paths["/api/v1/projects/{project_id}/settings"]
    assert "project-settings" in operations["get"]["tags"]
    assert "project-settings" in operations["patch"]["tags"]


def test_project_settings_routes_are_separate_from_user_and_translation_settings() -> None:
    document = app.openapi()
    paths = document["paths"]

    assert "/api/v1/auth/me/settings" in paths
    assert "/api/v1/projects/{project_id}/translation-settings" in paths
    project_settings_paths = {
        path
        for path, item in paths.items()
        if any("project-settings" in operation.get("tags", []) for operation in item.values())
    }
    assert project_settings_paths == {"/api/v1/projects/{project_id}/settings"}
