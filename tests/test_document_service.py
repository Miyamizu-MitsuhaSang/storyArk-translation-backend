from __future__ import annotations

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import pytest
from tortoise import Tortoise

from translation_backend.app.application.project.document.schemas import DocumentParseRequest
from translation_backend.app.application.project.document.service import (
    DocumentConflictError,
    DocumentService,
)
from translation_backend.app.infrastructure.document.storage import LocalDocumentStorage
from translation_backend.app.models import BackgroundJob, Document, Project, ProjectMember, User


def run_db_test(coro):
    async def scenario():
        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["translation_backend.app.models"]})
        await Tortoise.generate_schemas()
        try:
            return await coro()
        finally:
            await Tortoise.close_connections()

    return asyncio.run(scenario())


def test_upload_stores_file_and_creates_import_job() -> None:
    async def scenario():
        user = await User.create(
            username="document-service-owner",
            email="document-service-owner@example.com",
            password_hash="hash",
            display_name="文档服务用户",
        )
        project = await Project.create(key=f"document-{uuid4().hex}", name="文档服务项目", created_by=user)
        await ProjectMember.create(project=project, user=user, role="owner")
        with TemporaryDirectory() as directory:
            service = DocumentService(storage=LocalDocumentStorage(Path(directory)))
            result = await service.upload(
                user,
                project.id,
                filename="chapter.xliff",
                content_type="application/xliff+xml",
                content=b"<xliff>hello</xliff>",
                name=None,
                source_language="zh-CN",
                target_language="en-US",
            )
            document = await Document.get(id=result.document.id)
            job = await BackgroundJob.get(id=result.job_id)
            assert document.storage_uri == f"projects/{project.id}/documents/{document.id}/source.xliff"
            assert Path(directory, document.storage_uri).read_bytes() == b"<xliff>hello</xliff>"
            assert job.type == "document_import"
            assert result.document.status == "uploaded"

    run_db_test(scenario)

def test_delete_rejects_document_with_active_import_job() -> None:
    async def scenario():
        user = await User.create(
            username="document-delete-owner",
            email="document-delete-owner@example.com",
            password_hash="hash",
            display_name="删除用户",
        )
        project = await Project.create(key=f"document-{uuid4().hex}", name="删除项目", created_by=user)
        await ProjectMember.create(project=project, user=user, role="owner")
        document = await Document.create(
            project=project,
            created_by=user,
            name="待删除",
            file_name="delete.txt",
            file_format="txt",
            checksum_sha256="a" * 64,
            source_language="zh-CN",
            target_language="en-US",
            status="uploaded",
        )
        await BackgroundJob.create(
            type="document_import",
            resource_type="document",
            resource_id=document.id,
            requested_version=document.version,
            status="queued",
        )
        service = DocumentService(storage=LocalDocumentStorage(Path("/tmp")))
        with pytest.raises(DocumentConflictError):
            await service.delete(user, project.id, document.id)

    run_db_test(scenario)


def test_parse_requires_explicit_preserve_translations() -> None:
    async def scenario():
        user = await User.create(
            username="document-parse-owner",
            email="document-parse-owner@example.com",
            password_hash="hash",
            display_name="解析用户",
        )
        project = await Project.create(key=f"document-{uuid4().hex}", name="解析项目", created_by=user)
        await ProjectMember.create(project=project, user=user, role="owner")
        document = await Document.create(
            project=project,
            created_by=user,
            name="有译文",
            file_name="translated.txt",
            file_format="txt",
            checksum_sha256="b" * 64,
            source_language="zh-CN",
            target_language="en-US",
            status="ready",
            translated_segment_count=1,
        )
        service = DocumentService(storage=LocalDocumentStorage(Path("/tmp")))
        with pytest.raises(Exception, match="preserve_translations"):
            await service.parse(user, project.id, document.id, DocumentParseRequest())

    run_db_test(scenario)
