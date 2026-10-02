from __future__ import annotations

from translation_backend.main import app
from translation_backend.app.application.translation_memory.schemas import JobReference, TranslationMemoryImportResult
from translation_backend.app.api.modules.auth.translation_memory.routes import import_translation_memory_entries


def test_translation_memory_routes_are_documented_and_mounted() -> None:
    paths = app.openapi()["paths"]
    expected = {
        "/api/v1/auth/me/translation-memories",
        "/api/v1/auth/me/translation-memories/{memory_id}",
        "/api/v1/auth/me/translation-memories/{memory_id}/entries",
        "/api/v1/auth/me/translation-memories/{memory_id}/entries/{entry_id}",
        "/api/v1/auth/me/translation-memories/{memory_id}/imports",
        "/api/v1/projects/{project_id}/translation-memories",
        "/api/v1/projects/{project_id}/tm/search",
        "/api/v1/projects/{project_id}/translation-memories/reindex",
    }

    assert expected <= paths.keys()
    for path in expected:
        for operation in paths[path].values():
            assert operation.get("description"), f"missing description for {path}"


def test_reindex_route_declares_async_response() -> None:
    operation = app.openapi()["paths"][
        "/api/v1/projects/{project_id}/translation-memories/reindex"
    ]["post"]

    assert "202" in operation["responses"]
    response_schema = operation["responses"]["202"]["content"]["application/json"]["schema"]
    assert response_schema["type"] == "array"
    item_schema = app.openapi()["components"]["schemas"][response_schema["items"]["$ref"].rsplit("/", 1)[-1]]
    assert {"job_id", "status", "requested_version", "type"} <= set(item_schema["required"])
    assert item_schema["properties"]["type"]["const"] == "tm_index_rebuild"


def test_large_import_returns_202_for_queued_job() -> None:
    class Service:
        async def import_entries(self, user, memory_id, rows, idempotency_key):
            return TranslationMemoryImportResult(
                job=JobReference(
                    job_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    status="queued",
                )
            )

    import asyncio

    response = asyncio.run(
        import_translation_memory_entries(
            memory_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            rows=[],
            idempotency_key="import-1",
            user=object(),
            service=Service(),
        )
    )

    assert response.status_code == 202
