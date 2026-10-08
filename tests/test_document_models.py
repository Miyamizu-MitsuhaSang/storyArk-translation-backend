import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from tortoise import Tortoise
from tortoise.exceptions import IntegrityError

from translation_backend.app.models import (
    Document,
    DocumentSegment,
    Project,
    ProjectLanguagePair,
    SegmentLock,
    User,
)


def run_db_test(coro):
    async def scenario():
        await Tortoise.init(
            db_url="sqlite://:memory:",
            modules={"models": ["translation_backend.app.models"]},
        )
        await Tortoise.generate_schemas()
        try:
            return await coro()
        finally:
            await Tortoise.close_connections()

    return asyncio.run(scenario())


def test_document_segments_and_locks_preserve_project_relationships() -> None:
    async def scenario():
        user = await User.create(
            username="document-owner",
            email="document-owner@example.com",
            password_hash="argon2$hash",
            display_name="文档创建者",
        )
        project = await Project.create(key="document-project", name="文档项目", created_by=user)
        await ProjectLanguagePair.create(
            project=project,
            source_language="zh-CN",
            target_language="en-US",
            is_default=True,
        )
        document = await Document.create(
            project=project,
            created_by=user,
            name="第一章",
            file_name="chapter-1.xliff",
            file_format="xliff",
            mime_type="application/xliff+xml",
            storage_uri="s3://translation-platform/documents/chapter-1.xliff",
            file_size=2048,
            checksum_sha256="a" * 64,
            source_language="zh-CN",
            target_language="en-US",
        )
        segment = await DocumentSegment.create(
            document=document,
            segment_no=1,
            source_text="欢迎来到晨曦大陆。",
            target_text="Welcome to the Dawn Continent.",
            source_language="zh-CN",
            target_language="en-US",
            status="translated",
            workflow_state="in_review",
            assigned_to=user,
            context={"previous": "序章"},
        )
        lock = await SegmentLock.create(
            segment=segment,
            user=user,
            lock_token="lock-document-segment-1",
            locked_until=datetime.now(timezone.utc) + timedelta(minutes=15),
        )

        assert await document.project == project
        assert await document.created_by == user
        assert await document.segments.all().count() == 1
        assert await segment.document == document
        assert await segment.assigned_to == user
        assert await segment.lock == lock
        assert await lock.user == user

    run_db_test(scenario)


def test_document_segment_number_and_lock_token_are_unique() -> None:
    async def scenario():
        user = await User.create(
            username="document-unique",
            email="document-unique@example.com",
            password_hash="argon2$hash",
            display_name="文档唯一性测试",
        )
        project = await Project.create(key="document-unique-project", name="文档唯一性项目")
        document = await Document.create(
            project=project,
            name="唯一性测试",
            file_name="unique.txt",
            file_format="txt",
            checksum_sha256="b" * 64,
            source_language="zh-CN",
            target_language="en-US",
        )
        first = await DocumentSegment.create(
            document=document,
            segment_no=1,
            source_text="相同编号",
            source_language="zh-CN",
            target_language="en-US",
        )
        with pytest.raises(IntegrityError):
            await DocumentSegment.create(
                document=document,
                segment_no=1,
                source_text="重复编号",
                source_language="zh-CN",
                target_language="en-US",
            )

        await SegmentLock.create(
            segment=first,
            user=user,
            lock_token="unique-lock-token",
            locked_until=datetime.now(timezone.utc) + timedelta(minutes=15),
        )
        second = await DocumentSegment.create(
            document=document,
            segment_no=2,
            source_text="第二段",
            source_language="zh-CN",
            target_language="en-US",
        )
        with pytest.raises(IntegrityError):
            await SegmentLock.create(
                segment=second,
                user=user,
                lock_token="unique-lock-token",
                locked_until=datetime.now(timezone.utc) + timedelta(minutes=15),
            )

    run_db_test(scenario)


def test_document_models_have_retention_fields_and_descriptions() -> None:
    models = (Document, DocumentSegment, SegmentLock)
    for model in models:
        missing = [
            name
            for name, field in model._meta.fields_map.items()
            if field.has_db_field and not field.description
        ]
        assert missing == []

    assert "deleted_at" in Document._meta.fields_map
    assert "purge_after" in Document._meta.fields_map
    assert "deleted_at" in DocumentSegment._meta.fields_map
    assert "purge_after" in DocumentSegment._meta.fields_map
    assert "locked_until" in SegmentLock._meta.fields_map
