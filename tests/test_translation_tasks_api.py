from translation_backend.main import app


def test_translation_task_routes_are_registered_with_expected_methods_and_models():
    paths = app.openapi()["paths"]
    assert "/api/v1/projects/{project_id}/api-keys" not in paths
    assert set(paths["/api/v1/projects/{project_id}/translation-tasks"]) == {"get", "post"}
    assert set(paths["/api/v1/projects/{project_id}/translation-tasks/{task_id}"]) == {"get"}
    assert set(paths["/api/v1/projects/{project_id}/translation-tasks/{task_id}/cancel"]) == {"post"}
    assert set(paths["/api/v1/projects/{project_id}/translation-tasks/{task_id}/output"]) == {"get"}
    post = paths["/api/v1/projects/{project_id}/translation-tasks"]["post"]
    assert "Idempotency-Key" in str(post)
    assert "201" in post["responses"]
