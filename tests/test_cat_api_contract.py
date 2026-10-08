from translation_backend.main import app


def test_cat_workbench_and_workflow_routes_are_mounted_with_descriptions() -> None:
    paths = app.openapi()["paths"]
    expected = {
        "/api/v1/projects/{project_id}/segments/{segment_id}": {"get", "patch"},
        "/api/v1/projects/{project_id}/segments/{segment_id}/lock": {"post", "delete"},
        "/api/v1/projects/{project_id}/segments/{segment_id}/lock/renew": {"post"},
        "/api/v1/projects/{project_id}/segments/{segment_id}/suggestions": {"post"},
        "/api/v1/projects/{project_id}/segments/{segment_id}/qa": {"post"},
        "/api/v1/projects/{project_id}/segments/{segment_id}/submit-review": {"post"},
        "/api/v1/projects/{project_id}/segments/{segment_id}/approve": {"post"},
        "/api/v1/projects/{project_id}/segments/{segment_id}/reject": {"post"},
        "/api/v1/projects/{project_id}/segments/{segment_id}/confirm": {"post"},
        "/api/v1/projects/{project_id}/segments/{segment_id}/unconfirm": {"post"},
        "/api/v1/projects/{project_id}/segments/bulk-action": {"post"},
    }
    for path, methods in expected.items():
        assert path in paths
        for method in methods:
            assert method in paths[path]
            assert paths[path][method]["description"]


def test_provider_backed_sources_are_explicitly_not_implemented() -> None:
    schema = app.openapi()["components"]["schemas"]["SuggestionsResponse"]
    assert "warnings" in schema["properties"]
