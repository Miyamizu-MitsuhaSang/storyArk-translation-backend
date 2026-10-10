from __future__ import annotations

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import pytest
from pydantic import ValidationError
from tortoise import Tortoise

from translation_backend.app.application.project.document.service import DocumentNotFoundError, DocumentService
from translation_backend.app.application.project.version.schemas import VersionCreateRequest, VersionListQuery
from translation_backend.app.application.project.version.service import VersionService
from translation_backend.app.infrastructure.document.storage import LocalDocumentStorage
from translation_backend.app.models import Document, Project, ProjectMember, ProjectVersion, User


def run_db_test(coro):
    async def scenario():
        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["translation_backend.app.models"]})
        await Tortoise.generate_schemas()
        try:
            return await coro()
        finally:
            await Tortoise.close_connections()

    return asyncio.run(scenario())


async def _setup_project():
    owner = await User.create(
        username=f"version-owner-{uuid4().hex}",
        email=f"version-owner-{uuid4().hex}@example.com",
        password_hash="hash",
        display_name="版本 owner",
    )
    manager = await User.create(
        username=f"version-manager-{uuid4().hex}",
        email=f"version-manager-{uuid4().hex}@example.com",
        password_hash="hash",
        display_name="版本 manager",
    )
    viewer = await User.create(
        username=f"version-viewer-{uuid4().hex}",
        email=f"version-viewer-{uuid4().hex}@example.com",
        password_hash="hash",
        display_name="版本 viewer",
    )
    outsider = await User.create(
        username=f"version-outsider-{uuid4().hex}",
        email=f"version-outsider-{uuid4().hex}@example.com",
        password_hash="hash",
        display_name="版本 outsider",
    )
    project = await Project.create(key=f"version-{uuid4().hex}", name="版本项目", created_by=owner)
    other_project = await Project.create(key=f"version-other-{uuid4().hex}", name="其他项目", created_by=owner)
    await ProjectMember.create(project=project, user=owner, role="owner")
    await ProjectMember.create(project=project, user=manager, role="manager")
    await ProjectMember.create(project=project, user=viewer, role="viewer")
    await ProjectMember.create(project=other_project, user=owner, role="owner")
    return owner, manager, viewer, outsider, project, other_project


def test_project_versions_allocate_integer_numbers_and_allow_duplicate_or_empty_names() -> None:
    async def scenario() -> None:
        owner, manager, _, _, project, other_project = await _setup_project()
        service = VersionService()
        try:
            first = await service.create(
                owner,
                project.id,
                VersionCreateRequest(name="客户审核版", description="第一轮交付"),
            )
            duplicate = await service.create(
                manager,
                project.id,
                VersionCreateRequest(name="客户审核版"),
            )
            unnamed = await service.create(owner, project.id, VersionCreateRequest())
            other = await service.create(owner, other_project.id, VersionCreateRequest(name="客户审核版"))

            assert [first.version_number, duplicate.version_number, unnamed.version_number] == [1, 2, 3]
            assert all(isinstance(item.version_number, int) for item in (first, duplicate, unnamed, other))
            assert other.version_number == 1
            assert unnamed.name is None

            with pytest.raises(ValidationError):
                VersionCreateRequest(name="非法覆盖", version_number=99)
        finally:
            await Tortoise.close_connections()

    run_db_test(scenario)


def test_project_versions_list_uses_number_by_default_and_supports_name_search_sort_and_cursor() -> None:
    async def scenario() -> None:
        owner, _, _, _, project, _ = await _setup_project()
        service = VersionService()
        try:
            await service.create(owner, project.id, VersionCreateRequest(name="同名"))
            await service.create(owner, project.id, VersionCreateRequest(name="另一个"))
            await service.create(owner, project.id, VersionCreateRequest(name="同名"))

            default_page = await service.list(owner, project.id, VersionListQuery(page_size=2))
            assert [item.version_number for item in default_page.items] == [3, 2]
            assert default_page.next_cursor

            next_page = await service.list(
                owner,
                project.id,
                VersionListQuery(page_size=2, cursor=default_page.next_cursor),
            )
            assert [item.version_number for item in next_page.items] == [1]

            searched = await service.list(owner, project.id, VersionListQuery(q="同名", sort="name"))
            assert [item.version_number for item in searched.items] == [3, 1]
        finally:
            await Tortoise.close_connections()

    run_db_test(scenario)


def test_project_version_numbers_are_not_reused_after_deletion_or_concurrent_creation() -> None:
    async def scenario() -> None:
        owner, _, _, _, project, _ = await _setup_project()
        service = VersionService()
        try:
            first = await service.create(owner, project.id, VersionCreateRequest(name="first"))
            deleted = await ProjectVersion.get(id=first.id)
            await deleted.delete()
            second = await service.create(owner, project.id, VersionCreateRequest(name="second"))
            assert second.version_number == 2

            results = await asyncio.gather(
                *[
                    service.create(owner, project.id, VersionCreateRequest(name=f"parallel-{index}"))
                    for index in range(4)
                ]
            )
            assert sorted(item.version_number for item in results) == [3, 4, 5, 6]
        finally:
            await Tortoise.close_connections()

    run_db_test(scenario)


def test_version_files_are_project_scoped_and_allow_same_name_in_different_versions() -> None:
    async def scenario() -> None:
        owner, _, viewer, _, project, other_project = await _setup_project()
        service = VersionService()
        try:
            first = await service.create(owner, project.id, VersionCreateRequest(name="v1"))
            second = await service.create(owner, project.id, VersionCreateRequest(name="v2"))
            other = await service.create(owner, other_project.id, VersionCreateRequest(name="v1"))

            first_document = await Document.create(
                project_id=project.id,
                project_version_id=first.id,
                created_by=owner,
                name="dialog",
                file_name="dialog.json",
                file_format="json",
                checksum_sha256="a" * 64,
                source_language="en-US",
                target_language="zh-CN",
                file_size=10,
            )
            second_document = await Document.create(
                project_id=project.id,
                project_version_id=second.id,
                created_by=owner,
                name="dialog",
                file_name="dialog.json",
                file_format="json",
                checksum_sha256="b" * 64,
                source_language="en-US",
                target_language="zh-CN",
                file_size=20,
            )
            await Document.create(
                project_id=other_project.id,
                version_id=other.id,
                created_by=owner,
                name="dialog",
                file_name="dialog.json",
                file_format="json",
                checksum_sha256="c" * 64,
                source_language="en-US",
                target_language="zh-CN",
                file_size=30,
            )

            files = await service.list_files(viewer, project.id, first.id, page_size=20, cursor=None)
            assert [item.id for item in files.items] == [first_document.id]
            assert files.items[0].name == "dialog"
            assert files.items[0].size_bytes == 10
            assert set(files.items[0].__class__.model_fields) == {
                "id",
                "name",
                "source_language",
                "format",
                "updated_at",
                "size_bytes",
            }
            assert second_document.id not in [item.id for item in files.items]

            with pytest.raises(Exception) as raised:
                await service.list_files(viewer, project.id, other.id, page_size=20, cursor=None)
            assert getattr(raised.value, "status_code", None) == 404
        finally:
            await Tortoise.close_connections()

    run_db_test(scenario)


def test_document_upload_validates_version_project_and_keeps_optional_version_compatibility() -> None:
    async def scenario() -> None:
        owner, _, _, _, project, other_project = await _setup_project()
        version_service = VersionService()
        version = await version_service.create(owner, project.id, VersionCreateRequest(name="v1"))
        other_version = await version_service.create(owner, other_project.id, VersionCreateRequest(name="other"))
        try:
            with TemporaryDirectory() as directory:
                service = DocumentService(storage=LocalDocumentStorage(Path(directory)))
                unversioned = await service.upload(
                    owner,
                    project.id,
                    filename="unversioned.txt",
                    content_type="text/plain",
                    content=b"unversioned",
                    name=None,
                    source_language="en-US",
                    target_language="zh-CN",
                )
                versioned = await service.upload(
                    owner,
                    project.id,
                    filename="versioned.txt",
                    content_type="text/plain",
                    content=b"versioned",
                    name=None,
                    source_language="en-US",
                    target_language="zh-CN",
                    version_id=version.id,
                )
                assert unversioned.document.version_id is None
                assert versioned.document.version_id == version.id

                with pytest.raises(DocumentNotFoundError):
                    await service.upload(
                        owner,
                        project.id,
                        filename="wrong-project.txt",
                        content_type="text/plain",
                        content=b"wrong",
                        name=None,
                        source_language="en-US",
                        target_language="zh-CN",
                        version_id=other_version.id,
                    )
        finally:
            await Tortoise.close_connections()

    run_db_test(scenario)


def test_project_version_router_exposes_only_task_four_paths_and_contract_fields() -> None:
    from fastapi import FastAPI

    from translation_backend.app.api.modules.project.version.routes import project_version_router

    app = FastAPI()
    app.include_router(project_version_router, prefix="/api/v1/projects/{project_id}/versions")
    paths = app.openapi()["paths"]
    assert "/api/v1/projects/{project_id}/versions" in paths
    assert "/api/v1/projects/{project_id}/versions/{version_id}/files" in paths
    assert set(paths["/api/v1/projects/{project_id}/versions"]) == {"get", "post"}
    assert set(paths["/api/v1/projects/{project_id}/versions/{version_id}/files"]) == {"get"}
    response_ref = paths["/api/v1/projects/{project_id}/versions"]["post"]["responses"]["201"]["content"]["application/json"]["schema"]["$ref"]
    response_schema = app.openapi()["components"]["schemas"][response_ref.rsplit("/", 1)[-1]]
    assert "version_number" in response_schema["properties"]
