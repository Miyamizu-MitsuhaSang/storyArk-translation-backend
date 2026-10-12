from __future__ import annotations

import asyncio
from uuid import uuid4

from tortoise import Tortoise

from translation_backend.app.application.project.cat.schemas import BulkActionRequest
from translation_backend.app.application.project.cat.workflow.service import CatWorkflowService
from translation_backend.app.models import BackgroundJob, Project, ProjectMember, User


def run_db_test(coro):
    async def scenario():
        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["translation_backend.app.models"]})
        await Tortoise.generate_schemas()
        try:
            return await coro()
        finally:
            await Tortoise.close_connections()

    return asyncio.run(scenario())


def test_cat_async_bulk_action_is_idempotent() -> None:
    async def scenario():
        user = await User.create(
            username=f"producer-{uuid4().hex}", email=f"producer-{uuid4().hex}@example.com", password_hash="hash", display_name="生产方",
        )
        project = await Project.create(key=f"producer-{uuid4().hex}", name="生产项目", created_by=user)
        await ProjectMember.create(project=project, user=user, role="owner")
        request = BulkActionRequest(
            action="qa",
            segment_ids=[uuid4() for _ in range(101)],
            expected_versions={},
        )
        service = CatWorkflowService()
        first = await service.bulk_action(user, project.id, request, idempotency_key="cat-job-1")
        second = await service.bulk_action(user, project.id, request, idempotency_key="cat-job-1")
        assert first.job_id == second.job_id
        assert await BackgroundJob.filter(type="cat_bulk_action", resource_id=project.id).count() == 1

    run_db_test(scenario)
