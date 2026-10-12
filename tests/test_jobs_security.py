from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from tortoise import Tortoise

from translation_backend.app.application.jobs.service import JobConflictError, JobNotFoundError, JobsService
from translation_backend.app.core.config import app_settings
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


async def make_user_project():
    user = await User.create(
        username=f"jobs-security-{uuid4().hex}",
        email=f"jobs-security-{uuid4().hex}@example.com",
        password_hash="hash",
        display_name="下载用户",
    )
    project = await Project.create(key=f"jobs-security-{uuid4().hex}", name="下载项目", created_by=user)
    await ProjectMember.create(project=project, user=user, role="owner")
    return user, project


def test_download_distinguishes_not_ready_from_invalid_signature() -> None:
    async def scenario():
        user, project = await make_user_project()
        queued = await BackgroundJob.create(
            type="document_export",
            resource_type="project",
            resource_id=project.id,
            requested_version=1,
            status="running",
        )
        with pytest.raises(JobConflictError) as not_ready:
            await JobsService().download_export(user, queued.id, expires=int(datetime.now(timezone.utc).timestamp()) + 60, signature="x" * 64)
        assert not_ready.value.code == "JOB_DOWNLOAD_NOT_READY"

        done = await BackgroundJob.create(
            type="document_export",
            resource_type="project",
            resource_id=project.id,
            requested_version=1,
            status="succeeded",
            result={"storage_key": "exports/missing.txt"},
        )
        with pytest.raises(JobNotFoundError) as invalid:
            await JobsService().download_export(user, done.id, expires=int(datetime.now(timezone.utc).timestamp()) + 60, signature="x" * 64)
        assert invalid.value.code == "JOB_DOWNLOAD_INVALID_SIGNATURE"

    run_db_test(scenario)
