from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from tortoise import Tortoise

from translation_backend.app.application.jobs.schemas import JobListQuery
from translation_backend.app.application.jobs.service import JobsService
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
        username=f"jobs-list-{uuid4().hex}",
        email=f"jobs-list-{uuid4().hex}@example.com",
        password_hash="hash",
        display_name="列表用户",
    )
    project = await Project.create(key=f"jobs-list-{uuid4().hex}", name="列表项目", created_by=user)
    await ProjectMember.create(project=project, user=user, role="owner")
    return user, project


def test_jobs_list_returns_project_projection_and_opaque_cursor() -> None:
    async def scenario():
        user, project = await make_project_user()
        document = await Document.create(
            project=project,
            created_by=user,
            name="列表文档",
            file_name="list.txt",
            file_format="txt",
            checksum_sha256="a" * 64,
            source_language="zh-CN",
            target_language="en-US",
        )
        first = await BackgroundJob.create(
            type="document_parse",
            resource_type="document",
            resource_id=document.id,
            requested_version=2,
            status="queued",
        )
        second = await BackgroundJob.create(
            type="cat_bulk_action",
            resource_type="project",
            resource_id=project.id,
            requested_version=3,
            status="running",
        )
        page = await JobsService().list(user, JobListQuery(page_size=1))
        assert len(page.items) == 1
        assert page.items[0].id == second.id
        assert page.items[0].project_id == project.id
        assert page.next_cursor
        assert "/" not in page.next_cursor
        next_page = await JobsService().list(user, JobListQuery(page_size=1, cursor=page.next_cursor))
        assert [item.id for item in next_page.items] == [first.id]
        assert next_page.items[0].project_id == project.id

    run_db_test(scenario)


def test_jobs_list_filters_active_status_and_date_range() -> None:
    async def scenario():
        user, project = await make_project_user()
        now = datetime.now(timezone.utc)
        await BackgroundJob.create(
            type="old_job",
            resource_type="project",
            resource_id=project.id,
            requested_version=1,
            status="succeeded",
            created_at=now - timedelta(days=2),
        )
        active = await BackgroundJob.create(
            type="active_job",
            resource_type="project",
            resource_id=project.id,
            requested_version=1,
            status="running",
        )
        page = await JobsService().list(
            user,
            JobListQuery(
                active_only=True,
                status="running",
                created_after=now - timedelta(minutes=1),
                type="active_job",
            ),
        )
        assert [item.id for item in page.items] == [active.id]

    run_db_test(scenario)
