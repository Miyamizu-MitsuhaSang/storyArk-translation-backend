from __future__ import annotations

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from tortoise import Tortoise

from translation_backend.main import app
from translation_backend.app.application.project.document.service import DocumentService
from translation_backend.app.application.project.context.schemas import ContextQuery
from translation_backend.app.application.project.context.service import ContextService
from translation_backend.app.infrastructure.document.storage import LocalDocumentStorage
from translation_backend.app.models import (
    BackgroundJob,
    Document,
    DocumentSegment,
    Project,
    ProjectMember,
    TerminologyBase,
    TerminologyTerm,
    User,
)


def test_documented_audit_and_export_download_routes_are_registered() -> None:
    paths = app.openapi()["paths"]

    assert "/api/v1/projects/{project_id}/audit-events" in paths
    assert "/api/v1/jobs/{job_id}/download" in paths


def test_document_delete_replays_same_job_for_same_idempotency_key() -> None:
    async def scenario() -> None:
        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["translation_backend.app.models"]})
        await Tortoise.generate_schemas()
        try:
            user = await User.create(
                username="idem-owner",
                email="idem-owner@example.com",
                password_hash="hash",
                display_name="Owner",
            )
            project = await Project.create(key=f"idem-{uuid4().hex}", name="Idempotency", created_by=user)
            await ProjectMember.create(project=project, user=user, role="owner")
            document = await Document.create(
                project=project,
                created_by=user,
                name="source",
                file_name="source.txt",
                file_format="txt",
                checksum_sha256="a" * 64,
                source_language="zh-CN",
                target_language="en-US",
                status="ready",
            )
            with TemporaryDirectory() as directory:
                service = DocumentService(storage=LocalDocumentStorage(Path(directory)))
                first = await service.delete(user, project.id, document.id, idempotency_key="delete-1")
                second = await service.delete(user, project.id, document.id, idempotency_key="delete-1")

            assert first.job_id == second.job_id
            assert await BackgroundJob.filter(resource_id=document.id, type="document_purge").count() == 1
        finally:
            await Tortoise.close_connections()

    asyncio.run(scenario())


def test_context_returns_requested_terms_and_neighbor_segments() -> None:
    async def scenario() -> None:
        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["translation_backend.app.models"]})
        await Tortoise.generate_schemas()
        try:
            user = await User.create(
                username="context-user",
                email="context-user@example.com",
                password_hash="hash",
                display_name="Context",
            )
            project = await Project.create(key=f"context-{uuid4().hex}", name="Context", created_by=user)
            await ProjectMember.create(project=project, user=user, role="owner")
            document = await Document.create(
                project=project,
                created_by=user,
                name="chapter",
                file_name="chapter.txt",
                file_format="txt",
                checksum_sha256="c" * 64,
                source_language="zh-CN",
                target_language="en-US",
                status="ready",
            )
            await DocumentSegment.create(
                document=document, segment_no=1, source_text="前文", source_language="zh-CN", target_language="en-US"
            )
            current = await DocumentSegment.create(
                document=document, segment_no=2, source_text="晨曦骑士团", source_language="zh-CN", target_language="en-US"
            )
            await DocumentSegment.create(
                document=document, segment_no=3, source_text="后文", source_language="zh-CN", target_language="en-US"
            )
            base = await TerminologyBase.create(
                project=project,
                name="Terms",
                source_language="zh-CN",
                target_languages=["en-US"],
            )
            await TerminologyTerm.create(
                base=base,
                source_term="晨曦骑士团",
                target_terms={"en-US": "Dawn Knights"},
                term_type="faction",
                status="approved",
            )

            result = await ContextService().get(
                user,
                project.id,
                ContextQuery(segment_id=str(current.id), include="terms,neighbors"),
            )

            assert result.terms[0]["target_term"] == "Dawn Knights"
            assert result.neighbors[0]["source"] == "前文"
            assert result.neighbors[1]["source"] == "后文"
        finally:
            await Tortoise.close_connections()

    asyncio.run(scenario())
