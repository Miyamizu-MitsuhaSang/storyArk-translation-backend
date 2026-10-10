from __future__ import annotations

import asyncio
from uuid import uuid4

from tortoise import Tortoise

from translation_backend.app.application.auth.api_key.schemas import CreateApiKeyRequest
from translation_backend.app.application.auth.api_key.service import ApiKeyService
from translation_backend.app.application.project.translation_task.schemas import TableColumn, TranslationTaskCreateRequest
from translation_backend.app.application.project.translation_task.service import TranslationTaskService
from translation_backend.app.core.config import app_settings
from translation_backend.app.infrastructure.document.storage import LocalDocumentStorage
from translation_backend.app.models import BackgroundJob, Document, DocumentSegment, Project, ProjectMember, TranslationTask, User
from translation_backend.app.tasks.translation_tasks import _run_translation_task


def run_db_test(coro):
    async def scenario():
        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["translation_backend.app.models"]})
        await Tortoise.generate_schemas()
        try:
            return await coro()
        finally:
            await Tortoise.close_connections()

    return asyncio.run(scenario())


async def _setup_task(*, status: str = "queued") -> TranslationTask:
    owner = await User.create(
        username=f"worker-owner-{uuid4().hex}",
        email=f"worker-owner-{uuid4().hex}@example.com",
        password_hash="hash",
        display_name="Worker owner",
    )
    project = await Project.create(key=f"worker-{uuid4().hex}", name="Worker project", created_by=owner)
    return await TranslationTask.create(
        project=project,
        created_by=owner,
        name="worker task",
        source_language="zh-CN",
        target_languages=["en"],
        status=status,
        progress=0 if status == "queued" else 100,
    )


def test_worker_claims_queued_task_and_fails_without_provider_configuration():
    async def scenario():
        task = await _setup_task()
        result = await _run_translation_task(task.id, worker_id="test-worker")
        await task.refresh_from_db()
        assert result == {"status": "failed", "error_code": "PROVIDER_NOT_CONFIGURED"}
        assert task.status == "failed"
        assert task.progress == 1
        assert task.error_code == "PROVIDER_NOT_CONFIGURED"

    run_db_test(scenario)


def test_worker_does_not_reexecute_completed_or_cancelled_tasks():
    async def scenario():
        completed = await _setup_task(status="completed")
        cancelled = await _setup_task(status="cancelled")
        completed_result = await _run_translation_task(completed.id, worker_id="test-worker")
        cancelled_result = await _run_translation_task(cancelled.id, worker_id="test-worker")
        assert completed_result == {"status": "not_claimed", "task_status": "completed"}
        assert cancelled_result == {"status": "not_claimed", "task_status": "cancelled"}

    run_db_test(scenario)


def test_worker_translates_csv_and_stops_at_review_without_auto_approval(tmp_path, monkeypatch):
    async def scenario():
        owner = await User.create(
            username=f"batch-owner-{uuid4().hex}",
            email=f"batch-owner-{uuid4().hex}@example.com",
            password_hash="hash",
            display_name="Batch owner",
        )
        project = await Project.create(key=f"batch-{uuid4().hex}", name="Batch project", created_by=owner)
        await ProjectMember.create(project=project, user=owner, role="owner")
        document = await Document.create(
            project=project,
            created_by=owner,
            name="batch",
            file_name="batch.csv",
            file_format="csv",
            checksum_sha256="a" * 64,
            source_language="zh-CN",
            target_language="en",
            status="ready",
            storage_uri=f"projects/{project.id}/documents/source.csv",
        )
        storage = LocalDocumentStorage(tmp_path)
        storage.put(
            storage_key=document.storage_uri,
            content="source,en\n你好,\n再见,\n".encode(),
        )
        key = await ApiKeyService(
            encryption_key=b"0123456789abcdef0123456789abcdef", key_version="test-v1"
        ).create(owner, CreateApiKeyRequest(provider="openai", secret="batch-secret-1234"))
        task = await TranslationTaskService().create(
            owner,
            project.id,
            TranslationTaskCreateRequest(
                name="CSV batch",
                source_language="zh-CN",
                target_languages=["en"],
                file_ids=[document.id],
                api_key_id=key.id,
                model_type="fake.echo",
                model="fake",
                source_column="source",
                target_columns=[TableColumn(language="en", column="en")],
                overwrite=True,
            ),
        )
        async def invoker(text, source, target, model_type, model):
            return f"{text}-{target}"

        result = await _run_translation_task(task.id, worker_id="batch-worker", invoker=invoker, storage=storage)
        stored = await TranslationTask.get(id=task.id)
        job = await BackgroundJob.get(id=task.job_id)
        assert result == {"status": "review", "translated_cells": 2}
        assert stored.status == "review"
        assert stored.progress == 100
        assert stored.output_storage_key
        assert job.status == "succeeded"
        assert storage.exists(storage_key=stored.output_storage_key)
        assert storage.open(storage_key=stored.output_storage_key).read() == b"source,en\n\xe4\xbd\xa0\xe5\xa5\xbd,\xe4\xbd\xa0\xe5\xa5\xbd-en\n\xe5\x86\x8d\xe8\xa7\x81,\xe5\x86\x8d\xe8\xa7\x81-en\n"
        segment = await DocumentSegment.get(document_id=document.id, segment_no=1)
        assert segment.target_text == "你好-en"
        assert segment.status == "translated"
        assert segment.workflow_state == "draft"

    monkeypatch.setattr(app_settings, "document_storage_dir", tmp_path)
    run_db_test(scenario)


def test_worker_marks_background_job_failed_when_provider_is_not_configured(tmp_path, monkeypatch):
    async def scenario():
        owner = await User.create(
            username=f"missing-provider-owner-{uuid4().hex}",
            email=f"missing-provider-owner-{uuid4().hex}@example.com",
            password_hash="hash",
            display_name="Missing provider owner",
        )
        project = await Project.create(key=f"missing-provider-{uuid4().hex}", name="Missing provider", created_by=owner)
        await ProjectMember.create(project=project, user=owner, role="owner")
        document = await Document.create(
            project=project,
            created_by=owner,
            name="batch",
            file_name="batch.csv",
            file_format="csv",
            checksum_sha256="b" * 64,
            source_language="zh-CN",
            target_language="en",
            status="ready",
            storage_uri=f"projects/{project.id}/documents/source.csv",
        )
        storage = LocalDocumentStorage(tmp_path)
        storage.put(storage_key=document.storage_uri, content="source,en\n你好,\n".encode())
        key = await ApiKeyService(
            encryption_key=b"0123456789abcdef0123456789abcdef", key_version="test-v1"
        ).create(owner, CreateApiKeyRequest(provider="openai", secret="missing-provider-secret-1234"))
        task = await TranslationTaskService().create(
            owner,
            project.id,
            TranslationTaskCreateRequest(
                name="Missing provider",
                source_language="zh-CN",
                target_languages=["en"],
                file_ids=[document.id],
                api_key_id=key.id,
                model_type="openai.chat",
                model="gpt-test",
                source_column="source",
                target_columns=[TableColumn(language="en", column="en")],
            ),
        )

        result = await _run_translation_task(task.id, worker_id="missing-provider-worker", storage=storage)
        stored_task = await TranslationTask.get(id=task.id)
        stored_job = await BackgroundJob.get(id=task.job_id)
        assert result == {"status": "failed", "error_code": "PROVIDER_NOT_CONFIGURED"}
        assert stored_task.status == "failed"
        assert stored_job.status == "failed"
        assert stored_job.error_code == "PROVIDER_NOT_CONFIGURED"

    monkeypatch.setattr(app_settings, "document_storage_dir", tmp_path)
    run_db_test(scenario)


def test_worker_normalizes_provider_configuration_errors_to_terminal_failure(tmp_path, monkeypatch):
    async def scenario():
        owner = await User.create(
            username=f"config-provider-owner-{uuid4().hex}",
            email=f"config-provider-owner-{uuid4().hex}@example.com",
            password_hash="hash",
            display_name="Config provider owner",
        )
        project = await Project.create(key=f"config-provider-{uuid4().hex}", name="Config provider", created_by=owner)
        await ProjectMember.create(project=project, user=owner, role="owner")
        document = await Document.create(
            project=project,
            created_by=owner,
            name="batch",
            file_name="batch.csv",
            file_format="csv",
            checksum_sha256="c" * 64,
            source_language="zh-CN",
            target_language="en",
            status="ready",
            storage_uri=f"projects/{project.id}/documents/source.csv",
        )
        storage = LocalDocumentStorage(tmp_path)
        storage.put(storage_key=document.storage_uri, content="source,en\n你好,\n".encode())
        key = await ApiKeyService(
            encryption_key=b"0123456789abcdef0123456789abcdef", key_version="test-v1"
        ).create(owner, CreateApiKeyRequest(provider="openai", secret="config-provider-secret-1234"))
        task = await TranslationTaskService().create(
            owner,
            project.id,
            TranslationTaskCreateRequest(
                name="Config provider",
                source_language="zh-CN",
                target_languages=["en"],
                file_ids=[document.id],
                api_key_id=key.id,
                model_type="openai.chat",
                model="gpt-test",
                source_column="source",
                target_columns=[TableColumn(language="en", column="en")],
            ),
        )
        monkeypatch.setattr(app_settings, "ai_provider_enabled", True)
        async def unavailable(_task):
            raise RuntimeError("provider encryption key unavailable")
        monkeypatch.setattr("translation_backend.app.tasks.translation_tasks._configured_invoker", unavailable)
        result = await _run_translation_task(task.id, worker_id="config-provider-worker", storage=storage)
        stored_task = await TranslationTask.get(id=task.id)
        stored_job = await BackgroundJob.get(id=task.job_id)
        assert result == {"status": "failed", "error_code": "PROVIDER_NOT_CONFIGURED"}
        assert stored_task.status == "failed"
        assert stored_job.status == "failed"
        assert stored_job.error_code == "PROVIDER_NOT_CONFIGURED"

    monkeypatch.setattr(app_settings, "document_storage_dir", tmp_path)
    run_db_test(scenario)
