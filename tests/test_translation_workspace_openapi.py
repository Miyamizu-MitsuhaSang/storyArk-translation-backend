from __future__ import annotations

from translation_backend.main import app


def _response_refs(operation: dict) -> set[str]:
    refs: set[str] = set()
    for response in operation.get("responses", {}).values():
        schema = response.get("content", {}).get("application/json", {}).get("schema", {})
        if "$ref" in schema:
            refs.add(schema["$ref"].rsplit("/", 1)[-1])
        for item in schema.get("anyOf", []):
            if "$ref" in item:
                refs.add(item["$ref"].rsplit("/", 1)[-1])
    return refs


def test_translation_workspace_chapter_15_paths_and_methods_are_registered():
    paths = app.openapi()["paths"]
    expected = {
        "/api/v1/translation-templates": {"get"},
        "/api/v1/projects/{project_id}/translation-settings": {"get", "patch"},
        "/api/v1/projects/{project_id}/translation-settings/roles": {"get", "post"},
        "/api/v1/projects/{project_id}/translation-settings/roles/{role_id}": {"get", "patch", "delete"},
        "/api/v1/projects/{project_id}/translation-settings/rules": {"get", "post"},
        "/api/v1/projects/{project_id}/translation-settings/rules/{rule_id}": {"get", "patch", "delete"},
        "/api/v1/projects/{project_id}/translation-settings/culture-rules": {"get", "post"},
        "/api/v1/projects/{project_id}/translation-settings/culture-rules/{rule_id}": {"get", "patch", "delete"},
        "/api/v1/projects/{project_id}/terminology-bases": {"get", "post"},
        "/api/v1/projects/{project_id}/terminology-bases/{base_id}/terms": {"get", "post"},
        "/api/v1/projects/{project_id}/terminology-bases/{base_id}/terms/{term_id}": {"get", "patch", "delete"},
        "/api/v1/projects/{project_id}/terminology-bases/{base_id}/terms/import": {"post"},
        "/api/v1/projects/{project_id}/terminology-bases/{base_id}/terms/export": {"post"},
        "/api/v1/projects/{project_id}/terminology-bases/{base_id}/terms/bulk-action": {"post"},
        "/api/v1/projects/{project_id}/terminology-bases/{base_id}/terms/clear": {"post"},
        "/api/v1/projects/{project_id}/terminology/extract": {"post"},
        "/api/v1/projects/{project_id}/terminology/mine": {"post"},
        "/api/v1/projects/{project_id}/versions": {"get", "post"},
        "/api/v1/projects/{project_id}/versions/{version_id}/files": {"get"},
        "/api/v1/projects/{project_id}/translation-tasks": {"get", "post"},
        "/api/v1/projects/{project_id}/translation-tasks/{task_id}": {"get"},
        "/api/v1/projects/{project_id}/translation-tasks/{task_id}/cancel": {"post"},
        "/api/v1/projects/{project_id}/translation-tasks/{task_id}/output": {"get"},
        "/api/v1/auth/me/analytics/usage": {"get"},
        "/api/v1/projects/{project_id}/analytics/usage": {"get"},
        "/api/v1/projects/{project_id}/analytics/translation-report": {"get"},
    }
    for path, methods in expected.items():
        assert path in paths, path
        assert set(paths[path]) == methods, path
        for method in methods:
            assert paths[path][method].get("description") or paths[path][method].get("summary"), f"missing operation text: {method} {path}"

    assert "/api/v1/projects/{project_id}/api-keys" not in paths


def test_translation_workspace_openapi_contracts_include_headers_responses_and_security():
    schema = app.openapi()
    paths = schema["paths"]
    create_task = paths["/api/v1/projects/{project_id}/translation-tasks"]["post"]
    parameter_names = {item.get("name") for item in create_task.get("parameters", [])}
    assert "Idempotency-Key" in parameter_names
    assert "201" in create_task["responses"]
    assert "TranslationTaskResponse" in _response_refs(create_task)

    create_key = paths["/api/v1/auth/me/api-keys"]["post"]
    assert "201" in create_key["responses"]
    assert "CreatedApiKeyResponse" in _response_refs(create_key)
    assert create_key.get("security"), "API key creation must require authentication"

    templates = paths["/api/v1/translation-templates"]["get"]
    assert not templates.get("security"), "translation-templates is the public template catalog"

    usage = paths["/api/v1/projects/{project_id}/analytics/usage"]["get"]
    assert "UsageAnalyticsResponse" in _response_refs(usage)
    assert usage.get("security"), "project analytics must require authentication"

    output_schema = schema["components"]["schemas"]["TranslationTaskOutputResponse"]["properties"]
    assert "storage_key" not in output_schema
