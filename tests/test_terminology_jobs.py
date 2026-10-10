from __future__ import annotations

import asyncio
from uuid import uuid4

from tortoise import Tortoise

from translation_backend.app.models import BackgroundJob, Document, DocumentSegment, Project, ProjectMember, User
from translation_backend.app.tasks.terminology import process_terminology_job


def test_terminology_extract_job_claims_completes_and_keeps_candidate_provenance():
    async def scenario() -> None:
        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["translation_backend.app.models"]})
        await Tortoise.generate_schemas()
        try:
            user = await User.create(
                username=f"job-user-{uuid4().hex}",
                email=f"job-user-{uuid4().hex}@example.com",
                password_hash="hash",
                display_name="Job User",
            )
            project = await Project.create(key=f"job-{uuid4().hex}", name="Jobs", created_by=user)
            await ProjectMember.create(project=project, user=user, role="owner")
            document = await Document.create(
                project=project,
                created_by=user,
                name="Source",
                file_name="source.txt",
                file_format="txt",
                checksum_sha256="b" * 64,
                source_language="zh-CN",
                target_language="en",
                status="ready",
            )
            segment = await DocumentSegment.create(
                document=document,
                segment_no=1,
                source_text="星门开启",
                target_text="Star Gate opens",
                source_language="zh-CN",
                target_language="en",
            )
            job = await BackgroundJob.create(
                type="terminology_extract",
                resource_type="project",
                resource_id=project.id,
                requested_version=1,
                result={"workflow_payload": {"file_ids": [str(document.id),], "min_occurrences": 1}},
            )
            result = await process_terminology_job(job.id, worker_id="test-worker")
            assert result["status"] == "succeeded"
            assert any(item["source_file_id"] == str(document.id) for item in result["candidates"])
            assert str(segment.id) in result["candidates"][0]["segment_ids"]
            stored = await BackgroundJob.get(id=job.id)
            assert stored.status == "succeeded"
            assert "secret" not in str(stored.result).casefold()
        finally:
            await Tortoise.close_connections()

    asyncio.run(scenario())
