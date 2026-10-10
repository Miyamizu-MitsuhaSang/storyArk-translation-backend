from translation_backend.main import app


def test_usage_analytics_routes_are_registered():
    paths = app.openapi()["paths"]
    assert "/api/v1/auth/me/analytics/usage" in paths
    assert "/api/v1/projects/{project_id}/analytics/usage" in paths
    assert "/api/v1/projects/{project_id}/analytics/translation-report" in paths
