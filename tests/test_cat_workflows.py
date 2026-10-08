import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from tortoise import Tortoise

from translation_backend.app.application.project.cat.schemas import (
    BulkActionRequest,
    SegmentLockRequest,
    SegmentUpdateRequest,
    QARequest,
    WorkflowApproveRequest,
    WorkflowConfirmRequest,
    WorkflowSubmitReviewRequest,
    WorkflowUnconfirmRequest,
)
from translation_backend.app.application.project.cat.workbench.service import CatWorkbenchService
from translation_backend.app.application.project.cat.workflow.service import CatWorkflowService
from translation_backend.app.models import (
    Document,
    DocumentSegment,
    BackgroundJob,
    Project,
    ProjectMember,
    TranslationMemoryEntry,
    TranslationMemoryEntrySource,
    User,
)


def run_db_test(coro):
    async def scenario():
        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["translation_backend.app.models"]})
        await Tortoise.generate_schemas()
        try:
            return await coro()
        finally:
            await Tortoise.close_connections()

    return asyncio.run(scenario())


async def make_segment(*, target: str | None = None):
    user = await User.create(
        username=f"cat-{uuid4().hex}",
        email=f"cat-{uuid4().hex}@example.com",
        password_hash="hash",
        display_name="CAT 用户",
    )
    project = await Project.create(key=f"cat-{uuid4().hex}", name="CAT 项目", created_by=user)
    await ProjectMember.create(project=project, user=user, role="owner")
    document = await Document.create(
        project=project,
        created_by=user,
        name="CAT 文档",
        file_name="source.txt",
        file_format="txt",
        checksum_sha256="a" * 64,
        source_language="zh-CN",
        target_language="en-US",
        status="ready",
    )
    segment = await DocumentSegment.create(
        document=document,
        segment_no=1,
        source_text="HP 100",
        target_text=target,
        source_language="zh-CN",
        target_language="en-US",
        status="translated" if target else "untranslated",
    )
    return user, project, document, segment


def test_workbench_lock_save_and_detail() -> None:
    async def scenario():
        user, project, document, segment = await make_segment()
        service = CatWorkbenchService()

        locked = await service.lock(user, project.id, segment.id, SegmentLockRequest())
        updated = await service.update(
            user,
            project.id,
            segment.id,
            SegmentUpdateRequest(
                target="HP 100",
                translator_note="保留数值",
                version=1,
                lock_token=locked.lock_token,
                save_as="draft",
            ),
        )
        detail = await service.get(user, project.id, segment.id)

        assert updated.target == "HP 100"
        assert updated.version == 2
        assert detail.segment.id == segment.id
        assert detail.lock is not None
        assert detail.lock.lock_token == locked.lock_token
        assert detail.recent_changes

    run_db_test(scenario)


def test_workflow_transitions_and_confirm_are_idempotent() -> None:
    async def scenario():
        user, project, document, segment = await make_segment(target="Health 100")
        workbench = CatWorkbenchService()
        workflow = CatWorkflowService()
        locked = await workbench.lock(user, project.id, segment.id, SegmentLockRequest())
        submitted = await workflow.submit_review(
            user,
            project.id,
            segment.id,
            WorkflowSubmitReviewRequest(version=1, lock_token=locked.lock_token),
        )
        approved = await workflow.approve(
            user,
            project.id,
            segment.id,
            WorkflowApproveRequest(version=submitted.version),
        )
        first = await workflow.confirm(
            user,
            project.id,
            segment.id,
            WorkflowConfirmRequest(version=approved.version),
        )
        second = await workflow.confirm(
            user,
            project.id,
            segment.id,
            WorkflowConfirmRequest(version=first.version),
        )

        assert submitted.workflow_state == "in_review"
        assert approved.status == "approved"
        assert first.status == "confirmed"
        assert second.status == "confirmed"
        assert await TranslationMemoryEntry.filter(origin="confirmed_segment").count() == 1

        unconfirmed = await workflow.unconfirm(
            user,
            project.id,
            segment.id,
            WorkflowUnconfirmRequest(version=second.version),
        )
        entry = await TranslationMemoryEntry.get(origin="confirmed_segment")
        source = await TranslationMemoryEntrySource.get(entry=entry, segment_id=segment.id)
        assert unconfirmed.status == "approved"
        assert source.invalidated_at is not None
        assert entry.status == "deprecated"

    run_db_test(scenario)


def test_workbench_qa_detects_placeholder_and_number_mismatch() -> None:
    async def scenario():
        user, project, document, segment = await make_segment(target="HP {value}")
        service = CatWorkbenchService()
        result = await service.qa(user, project.id, segment.id, QARequest(checks=["placeholders", "numbers"], save_results=True))

        assert result.summary["error"] == 2
        assert {issue.rule for issue in result.issues} == {"placeholders", "numbers"}

    run_db_test(scenario)


def test_large_bulk_action_creates_async_job() -> None:
    async def scenario():
        user, project, document, segment = await make_segment()
        service = CatWorkflowService()
        request = BulkActionRequest(
            segment_ids=[uuid4() for _ in range(101)],
            action="qa",
            expected_versions={},
        )

        result = await service.bulk_action(user, project.id, request)

        job = await BackgroundJob.get(id=result.job_id)
        assert result.job_id is not None
        assert result.items == []
        assert job.type == "cat_bulk_action"
        assert job.status == "queued"

    run_db_test(scenario)
