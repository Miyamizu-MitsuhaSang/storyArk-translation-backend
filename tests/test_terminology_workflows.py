from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from tortoise import Tortoise

from translation_backend.app.application.project.terminology.schemas import (
    TerminologyBulkActionRequest,
    TerminologyClearRequest,
    TerminologyExportRequest,
    TerminologyExtractRequest,
    TerminologyImportRequest,
    TerminologyMineRequest,
)
from translation_backend.app.application.project.terminology.workflows import (
    TerminologyWorkflowService,
)
from translation_backend.app.models import (
    BackgroundJob,
    Document,
    DocumentSegment,
    Project,
    ProjectMember,
    TerminologyBase,
    TerminologyTerm,
    TranslationMemoryEntry,
    TranslationMemoryLibrary,
    User,
)


async def _setup():
    await Tortoise.init(
        db_url="sqlite://:memory:",
        modules={"models": ["translation_backend.app.models"]},
    )
    await Tortoise.generate_schemas()
    owner = await User.create(
        username=f"workflow-owner-{uuid4().hex}",
        email=f"workflow-owner-{uuid4().hex}@example.com",
        password_hash="hash",
        display_name="Owner",
    )
    other = await User.create(
        username=f"workflow-other-{uuid4().hex}",
        email=f"workflow-other-{uuid4().hex}@example.com",
        password_hash="hash",
        display_name="Other",
    )
    project = await Project.create(key=f"workflow-{uuid4().hex}", name="Workflow", created_by=owner)
    other_project = await Project.create(key=f"workflow-other-{uuid4().hex}", name="Other", created_by=other)
    await ProjectMember.create(project=project, user=owner, role="owner")
    await ProjectMember.create(project=other_project, user=other, role="owner")
    base = await TerminologyBase.create(
        project=project,
        name="Main",
        source_language="zh-CN",
        target_languages=["en"],
    )
    existing = await TerminologyTerm.create(
        base=base,
        source_term="星门",
        target_terms={"en": "Star Gate"},
        term_type="general",
        status="approved",
        created_by_id=owner.id,
    )
    document = await Document.create(
        project=project,
        created_by=owner,
        name="Source",
        file_name="source.txt",
        file_format="txt",
        checksum_sha256="a" * 64,
        source_language="zh-CN",
        target_language="en",
        status="ready",
    )
    await DocumentSegment.create(
        document=document,
        segment_no=1,
        source_text="星门开启",
        target_text="Star Gate opens",
        source_language="zh-CN",
        target_language="en",
    )
    tm = await TranslationMemoryLibrary.create(scope="user", owner_user=owner, name="TM", status="active")
    await TranslationMemoryEntry.create(
        library=tm,
        source_language="zh-CN",
        target_language="en",
        source_text="星门",
        target_text="Star Gate",
        source_hash="source",
        target_hash="target",
        origin="manual",
    )
    return owner, other, project, other_project, base, existing, document, tm


def test_import_export_bulk_and_clear_preserve_conflicts_and_rows():
    async def scenario() -> None:
        owner, _, project, _, base, existing, _, _ = await _setup()
        try:
            service = TerminologyWorkflowService()
            imported = await service.import_terms(
                owner,
                project.id,
                base.id,
                TerminologyImportRequest(
                    format="csv",
                    content="source_term,en\n星门,Stargate\n新词,New Term\n,Missing",
                    on_conflict="update",
                ),
                idempotency_key="import-1",
            )
            assert imported.created == 1
            assert imported.updated == 1
            assert imported.invalid_rows
            assert (await TerminologyTerm.get(id=existing.id)).target_terms == {"en": "Stargate"}

            replay = await service.import_terms(
                owner,
                project.id,
                base.id,
                TerminologyImportRequest(
                    format="csv",
                    content="source_term,en\n星门,Stargate\n新词,New Term\n,Missing",
                    on_conflict="update",
                ),
                idempotency_key="import-1",
            )
            assert replay.model_dump() == imported.model_dump()

            export = await service.export_terms(
                owner,
                project.id,
                base.id,
                TerminologyExportRequest(format="csv"),
                idempotency_key="export-1",
            )
            assert export.filename == "Main-terms.csv"
            assert b"source_term" in export.content
            assert b"Stargate" in export.content

            term = await TerminologyTerm.filter(base_id=base.id, source_term="新词").first()
            assert term is not None
            bulk = await service.bulk_action(
                owner,
                project.id,
                base.id,
                TerminologyBulkActionRequest(
                    action="add_disabled_translation",
                    term_ids=[term.id],
                    value="Bad Term",
                    expected_revisions={str(term.id): term.version},
                ),
                idempotency_key="bulk-1",
            )
            assert bulk.affected == 1
            assert "Bad Term" in (await TerminologyTerm.get(id=term.id)).forbidden_translations

            with pytest.raises(Exception) as raised:
                await service.clear(
                    owner,
                    project.id,
                    base.id,
                    TerminologyClearRequest(confirm=True, expected_count=999),
                    idempotency_key="clear-1",
                )
            assert getattr(raised.value, "code", None) == "COUNT_MISMATCH"
        finally:
            await Tortoise.close_connections()

    asyncio.run(scenario())


def test_extract_and_mine_validate_scope_and_create_project_visible_jobs():
    async def scenario() -> None:
        owner, other, project, other_project, base, _, document, tm = await _setup()
        try:
            service = TerminologyWorkflowService()
            with pytest.raises(Exception) as raised:
                await service.extract(
                    owner,
                    project.id,
                    TerminologyExtractRequest(
                        file_ids=[uuid4()],
                        source_language="zh-CN",
                        target_languages=["en"],
                        terminology_base_id=base.id,
                    ),
                    idempotency_key="extract-invalid-1",
                )
            assert getattr(raised.value, "status_code", None) == 404

            extracted = await service.extract(
                owner,
                project.id,
                TerminologyExtractRequest(
                    file_ids=[document.id],
                    source_language="zh-CN",
                    target_languages=["en"],
                    terminology_base_id=base.id,
                ),
                idempotency_key="extract-1",
            )
            assert extracted.type == "terminology_extract"
            assert await BackgroundJob.filter(id=extracted.job_id, resource_id=project.id).exists()

            mined = await service.mine(
                owner,
                project.id,
                TerminologyMineRequest(
                    tm_base_ids=[tm.id],
                    source_language="zh-CN",
                    target_languages=["en"],
                    min_occurrences=1,
                    terminology_base_id=base.id,
                ),
                idempotency_key="mine-1",
            )
            assert mined.type == "terminology_mine"
            assert await BackgroundJob.filter(id=mined.job_id, resource_id=project.id).exists()
        finally:
            await Tortoise.close_connections()

    asyncio.run(scenario())
