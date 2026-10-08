from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from tortoise import Tortoise

from translation_backend.app.application.jobs.service import (
    JobConflictError,
    JobNotFoundError,
    JobsService,
)
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


async def make_project_user():
    user = await User.create(
        username=f"jobs-{uuid4().hex}",
        email=f"jobs-{uuid4().hex}@example.com",
        password_hash="hash",
        display_name="任务用户",
    )
    project = await Project.create(key=f"jobs-{uuid4().hex}", name="任务项目", created_by=user)
    await ProjectMember.create(project=project, user=user, role="owner")
    return user, project


def test_project_job_can_be_read_and_cancelled() -> None:
    async def scenario():
        user, project = await make_project_user()
        job = await BackgroundJob.create(
            type="cat_bulk_action",
            resource_type="project",
            resource_id=project.id,
            requested_version=1,
            status="running",
            worker_id="cat-worker",
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )

        service = JobsService()
        response = await service.get_status(user, job.id)
        assert response.id == job.id
        assert response.type == "cat_bulk_action"
        assert response.status == "running"

        cancelled = await service.cancel(user, job.id, reason="用户主动取消")
        assert cancelled.status == "cancelled"
        stored = await BackgroundJob.get(id=job.id)
        assert stored.worker_id is None
        assert stored.lease_expires_at is None
        assert stored.error_code == "JOB_CANCELLED"

    run_db_test(scenario)


def test_non_member_cannot_see_project_job() -> None:
    async def scenario():
        owner, project = await make_project_user()
        outsider = await User.create(
            username=f"outsider-{uuid4().hex}",
            email=f"outsider-{uuid4().hex}@example.com",
            password_hash="hash",
            display_name="外部用户",
        )
        job = await BackgroundJob.create(
            type="cat_bulk_action",
            resource_type="project",
            resource_id=project.id,
            requested_version=1,
        )
        with pytest.raises(JobNotFoundError):
            await JobsService().get_status(outsider, job.id)
        with pytest.raises(JobNotFoundError):
            await JobsService().cancel(outsider, job.id)

    run_db_test(scenario)


def test_terminal_job_cannot_be_cancelled() -> None:
    async def scenario():
        user, project = await make_project_user()
        job = await BackgroundJob.create(
            type="cat_bulk_action",
            resource_type="project",
            resource_id=project.id,
            requested_version=1,
            status="succeeded",
        )
        with pytest.raises(JobConflictError):
            await JobsService().cancel(user, job.id)

    run_db_test(scenario)
