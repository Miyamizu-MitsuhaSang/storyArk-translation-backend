from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from translation_backend.app.api.modules.project.translation_settings.routes import translation_settings_router


def test_translation_settings_router_exposes_all_documented_paths():
    app = FastAPI()
    app.include_router(translation_settings_router, prefix="/api/v1")
    paths = set(app.openapi()["paths"])
    assert "/api/v1/translation-templates" in paths
    assert "/api/v1/projects/{project_id}/translation-settings" in paths
    assert "/api/v1/projects/{project_id}/translation-settings/roles/{role_id}" in paths
    assert "/api/v1/projects/{project_id}/translation-settings/rules/{rule_id}" in paths
    assert "/api/v1/projects/{project_id}/translation-settings/culture-rules/{rule_id}" in paths
