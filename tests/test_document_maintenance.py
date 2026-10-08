from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from tortoise import Tortoise

from translation_backend.app.core.config import app_settings
from translation_backend.app.models import BackgroundJob, Document, Project, ProjectMember, User
from translation_backend.app.tasks import documents as document_tasks
from translation_backend.app.tasks.documents import cleanup_due_documents
from translation_backend.app.tasks.celery_app import celery_app


def run_db_test(coro):
    async def scenario():
        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["translation_backend.app.models"]})
        await Tortoise.generate_schemas()
        try:
            return await coro()
        finally:
            await Tortoise.close_connections()

    return asyncio.run(scenario())


async def _make_document(*, status: str, purge_after: datetime, storage_key: str | None = None):
    user = await User.create(
        username=f"document-maintenance-{uuid4().hex}",
        email=f"document-maintenance-{uuid4().hex}@example.com",
        password_hash="hash",
        display_name="清理用户",
    )
    project = await Project.create(key=f"document-maintenance-{uuid4().hex}", name="清理项目", created_by=user)
    await ProjectMember.create(project=project, user=user, role="owner")
    document = await Document.create(
        project=project,
        created_by=user,
        name="待清理文档",
        file_name="source.txt",
        file_format="txt",
        storage_uri=storage_key,
        file_size=5,
        checksum_sha256="a" * 64,
        source_language="zh-CN",
        target_language="en-US",
        status=status,
        purge_after=purge_after,
    )
    return user, project, document


def test_cleanup_due_documents_purges_file_and_keeps_database_record(tmp_path, monkeypatch) -> None:
    async def scenario():
        monkeypatch.setattr(app_settings, "document_storage_dir", tmp_path)
        storage_key = "projects/p1/documents/d1/source.txt"
        path = tmp_path / storage_key
        path.parent.mkdir(parents=True)
        path.write_bytes(b"hello")
        _, _, document = await _make_document(
            status="deletion_pending",
            purge_after=datetime.now(timezone.utc) - timedelta(seconds=1),
            storage_key=storage_key,
        )

        result = await cleanup_due_documents(now=datetime.now(timezone.utc))

        await document.refresh_from_db()
        job = await BackgroundJob.filter(resource_type="document", resource_id=document.id, type="document_purge").first()
        assert result == {"scanned": 1, "purged": 1, "skipped": 0, "failed": 0}
        assert document.status == "purged"
        assert document.purged_at is not None
        assert not path.exists()
        assert job is not None and job.status == "succeeded"

    run_db_test(scenario)


def test_cleanup_skips_document_with_active_processing_job(tmp_path, monkeypatch) -> None:
    async def scenario():
        monkeypatch.setattr(app_settings, "document_storage_dir", tmp_path)
        _, _, document = await _make_document(
            status="deletion_pending",
            purge_after=datetime.now(timezone.utc) - timedelta(seconds=1),
            storage_key="projects/p1/documents/d2/source.txt",
        )
        await BackgroundJob.create(
            type="document_parse",
            status="running",
            resource_type="document",
            resource_id=document.id,
            requested_version=document.version,
            worker_id="parser-worker",
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )

        result = await cleanup_due_documents(now=datetime.now(timezone.utc))

        await document.refresh_from_db()
        assert result == {"scanned": 1, "purged": 0, "skipped": 1, "failed": 0}
        assert document.status == "deletion_pending"
        assert not await BackgroundJob.filter(resource_type="document", resource_id=document.id, type="document_purge").exists()

    run_db_test(scenario)


def test_cleanup_does_not_process_before_grace_period(tmp_path, monkeypatch) -> None:
    async def scenario():
        monkeypatch.setattr(app_settings, "document_storage_dir", tmp_path)
        _, _, document = await _make_document(
            status="deletion_pending",
            purge_after=datetime.now(timezone.utc) + timedelta(minutes=5),
            storage_key="projects/p1/documents/d3/source.txt",
        )

        result = await cleanup_due_documents(now=datetime.now(timezone.utc))

        assert result == {"scanned": 0, "purged": 0, "skipped": 0, "failed": 0}
        await document.refresh_from_db()
        assert document.status == "deletion_pending"

    run_db_test(scenario)


def test_cleanup_does_not_recreate_terminal_failed_purge_job(tmp_path, monkeypatch) -> None:
    async def scenario():
        monkeypatch.setattr(app_settings, "document_storage_dir", tmp_path)
        _, _, document = await _make_document(
            status="deletion_pending",
            purge_after=datetime.now(timezone.utc) - timedelta(seconds=1),
            storage_key="projects/p1/documents/d4/source.txt",
        )
        await BackgroundJob.create(
            type="document_purge",
            status="failed",
            resource_type="document",
            resource_id=document.id,
            requested_version=document.version,
            attempts=3,
            max_attempts=3,
            error_code="DOCUMENT_JOB_FAILED",
            error_message="清理失败",
        )

        result = await cleanup_due_documents(now=datetime.now(timezone.utc))

        assert result == {"scanned": 1, "purged": 0, "skipped": 0, "failed": 1}
        assert await BackgroundJob.filter(
            resource_type="document", resource_id=document.id, type="document_purge"
        ).count() == 1

    run_db_test(scenario)


def test_document_cleanup_is_registered_in_celery_beat() -> None:
    schedule = celery_app.conf.beat_schedule["cleanup-due-documents"]

    assert schedule["task"] == "documents.cleanup_due"
    assert schedule["schedule"] == 3600.0
