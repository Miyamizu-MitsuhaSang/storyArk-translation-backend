from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from tortoise import Tortoise

from translation_backend.main import app
from translation_backend.app.application.translation_memory.schemas import (
    TranslationMemoryReindexResponse,
    TranslationMemoryTaskStatusResponse,
)
from translation_backend.app.application.translation_memory.service import (
    TranslationMemoryIndexUnavailableError,
    TranslationMemoryService,
)
from translation_backend.app.models import BackgroundJob, TranslationMemoryLibrary, User


def test_reindex_http_contract_exposes_202_and_task_status_fields() -> None:
    operation = app.openapi()["paths"][
        "/api/v1/projects/{project_id}/translation-memories/reindex"
    ]["post"]

    assert operation["responses"]["202"]
    item_ref = operation["responses"]["202"]["content"]["application/json"]["schema"]["items"]["$ref"]
    item_schema = app.openapi()["components"]["schemas"][item_ref.rsplit("/", 1)[-1]]
    assert {"job_id", "status", "requested_version", "type"} <= set(item_schema["required"])
    assert item_schema["properties"]["type"]["const"] == "tm_index_rebuild"

    job_schema = app.openapi()["components"]["schemas"]["TranslationMemoryTaskStatusResponse"]
    assert {"job_id", "status", "requested_version", "attempts", "type"} <= set(job_schema["required"])
    assert "storage_uri" not in job_schema["properties"]
    assert "source_text" not in job_schema["properties"]
    assert "/api/v1/jobs/{job_id}" in app.openapi()["paths"]


def test_reindex_returns_503_contract_when_dispatcher_is_unavailable():
    class Service:
        async def reindex(self, user, project_id):
            raise TranslationMemoryIndexUnavailableError("broker unavailable")

    async def scenario():
        from translation_backend.app.api.modules.project.project_content.translation_memory.routes import (
            reindex_translation_memories,
        )

        with pytest.raises(TranslationMemoryIndexUnavailableError) as raised:
            await reindex_translation_memories(uuid4(), object(), Service())
        assert raised.value.status_code == 503
        assert raised.value.code == "INDEX_NOT_AVAILABLE"

    asyncio.run(scenario())


def test_job_status_is_scoped_and_redacts_artifact_details():
    async def scenario():
        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["translation_backend.app.models"]})
        await Tortoise.generate_schemas()
        try:
            user = await User.create(username="job-status", email="job-status@example.com", password_hash="x", display_name="Job")
            library = await TranslationMemoryLibrary.create(scope="user", owner_user=user, name="TM")
            job = await BackgroundJob.create(
                type="tm_index_rebuild",
                resource_type="translation_memory_library",
                resource_id=library.id,
                requested_version=library.content_version,
                status="succeeded",
                attempts=1,
                result={"status": "active", "artifact_id": str(uuid4()), "storage_uri": "sha256/secret"},
                error_message="api_key=secret-value",
            )

            response = await TranslationMemoryService().get_job_status(user, job.id)

            assert isinstance(response, TranslationMemoryTaskStatusResponse)
            assert response.job_id == job.id
            assert response.result == {"status": "active", "artifact_id": response.result["artifact_id"]}
            assert "storage_uri" not in response.model_dump_json()
            assert "secret-value" not in response.model_dump_json()
        finally:
            await Tortoise.close_connections()

    asyncio.run(scenario())
