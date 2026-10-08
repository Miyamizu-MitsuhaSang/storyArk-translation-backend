from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from starlette.requests import Request

from translation_backend.app.api.shared.dependencies import (
    get_project_manager,
    get_project_member,
    get_project_report_reader,
)
from translation_backend.app.api.shared.errors import register_shared_exception_handlers
from translation_backend.app.api.modules.project.routes import _handle_project_error
from translation_backend.app.application.idempotency import (
    IdempotencyConflictError,
    execute_idempotently,
)
from translation_backend.app.application.project.shared import (
    InvalidCursorError,
    ProjectForbiddenError,
    ProjectNotFoundError,
    ProjectValidationError,
    RevisionConflictError,
    decode_cursor,
    encode_cursor,
    expected_revision,
    require_project_member,
    require_project_role,
)
from translation_backend.app.core.schemas import (
    ApiErrorBody,
    ApiErrorResponse,
    CursorPage,
    VersionConflictDetails,
)
from translation_backend.app.models import Project, ProjectMember, User


def _request(headers: dict[str, str] | None = None) -> Request:
    raw_headers = [(key.lower().encode(), value.encode()) for key, value in (headers or {}).items()]
    return Request({"type": "http", "method": "PATCH", "path": "/test", "headers": raw_headers})


def test_cursor_round_trip_uses_an_opaque_non_negative_offset() -> None:
    cursor = encode_cursor(27)

    assert cursor != "27"
    assert decode_cursor(cursor) == 27
    assert decode_cursor(None) == 0


def test_shared_core_schemas_cover_pagination_and_error_details() -> None:
    page = CursorPage[Any](items=[{"id": "item-1"}], next_cursor="opaque", total=1)
    error = ApiErrorResponse(
        error=ApiErrorBody(
            code="VERSION_CONFLICT",
            message="版本冲突",
            details=VersionConflictDetails(current_revision=4).model_dump(),
            request_id="request-1",
        )
    )

    assert page.model_dump() == {"items": [{"id": "item-1"}], "next_cursor": "opaque", "total": 1}
    assert error.error.details == {"current_revision": 4}


def test_invalid_cursor_is_a_422_validation_error() -> None:
    with pytest.raises(InvalidCursorError) as raised:
        decode_cursor("not-a-valid-cursor")

    assert raised.value.status_code == 422
    assert raised.value.code == "INVALID_CURSOR"


def test_expected_revision_accepts_header_or_body_and_rejects_disagreement() -> None:
    assert expected_revision(_request({"If-Match": "12"}), None) == 12
    assert expected_revision(_request(), 12) == 12

    with pytest.raises(ProjectValidationError) as raised:
        expected_revision(_request({"If-Match": "bad"}), None)
    assert raised.value.code == "INVALID_REVISION"

    with pytest.raises(ProjectValidationError) as raised:
        expected_revision(_request({"If-Match": "12"}), 13)
    assert raised.value.code == "REVISION_MISMATCH"


def test_revision_conflict_exposes_current_revision_without_changing_status_contract() -> None:
    error = RevisionConflictError(current_revision=19)

    assert error.status_code == 409
    assert error.code == "VERSION_CONFLICT"
    assert error.details == {"current_revision": 19}


def test_project_dependencies_enforce_visibility_and_roles() -> None:
    async def scenario() -> None:
        from tortoise import Tortoise

        await Tortoise.init(
            db_url="sqlite://:memory:",
            modules={"models": ["translation_backend.app.models"]},
        )
        await Tortoise.generate_schemas()
        try:
            owner = await User.create(
                username="workspace-owner",
                email="workspace-owner@example.com",
                password_hash="hash",
                display_name="Owner",
            )
            translator = await User.create(
                username="workspace-translator",
                email="workspace-translator@example.com",
                password_hash="hash",
                display_name="Translator",
            )
            viewer = await User.create(
                username="workspace-viewer",
                email="workspace-viewer@example.com",
                password_hash="hash",
                display_name="Viewer",
            )
            outsider = await User.create(
                username="workspace-outsider",
                email="workspace-outsider@example.com",
                password_hash="hash",
                display_name="Outsider",
            )
            project = await Project.create(
                key=f"workspace-{uuid4().hex}",
                name="Workspace",
                created_by=owner,
            )
            await ProjectMember.create(project=project, user=owner, role="owner")
            translator_membership = await ProjectMember.create(
                project=project,
                user=translator,
                role="translator",
            )
            await ProjectMember.create(project=project, user=viewer, role="viewer")

            assert (await require_project_member(owner, project.id)).role == "owner"
            assert (await get_project_member(project.id, owner)).role == "owner"
            assert (await get_project_member(project.id, viewer)).role == "viewer"
            assert (await get_project_report_reader(project.id, owner)).role == "owner"

            with pytest.raises(ProjectForbiddenError) as raised:
                await require_project_role(translator, project.id, frozenset({"owner", "manager"}))
            assert raised.value.status_code == 403
            assert raised.value.code == "PROJECT_FORBIDDEN"

            with pytest.raises(ProjectForbiddenError) as raised:
                await get_project_manager(project.id, translator)
            assert raised.value.status_code == 403
            assert raised.value.code == "PROJECT_FORBIDDEN"

            assert translator_membership.role == "translator"
            with pytest.raises(ProjectNotFoundError):
                await require_project_member(outsider, project.id)
        finally:
            await Tortoise.close_connections()

    asyncio.run(scenario())


def test_idempotency_conflict_is_a_409_with_stable_error_code() -> None:
    async def scenario() -> None:
        from pydantic import BaseModel
        from tortoise import Tortoise

        class Result(BaseModel):
            value: str

        await Tortoise.init(
            db_url="sqlite://:memory:",
            modules={"models": ["translation_backend.app.models"]},
        )
        await Tortoise.generate_schemas()
        try:
            user = await User.create(
                username="workspace-idempotency",
                email="workspace-idempotency@example.com",
                password_hash="hash",
                display_name="Idempotency",
            )

            async def callback() -> Result:
                return Result(value="created")

            await execute_idempotently(
                user,
                operation="workspace.create",
                scope="project:test",
                key="workspace-key",
                payload={"name": "first"},
                response_type=Result,
                callback=callback,
            )

            with pytest.raises(IdempotencyConflictError) as raised:
                await execute_idempotently(
                    user,
                    operation="workspace.create",
                    scope="project:test",
                    key="workspace-key",
                    payload={"name": "different"},
                    response_type=Result,
                    callback=callback,
                )

            assert raised.value.status_code == 409
            assert raised.value.code == "IDEMPOTENCY_CONFLICT"
        finally:
            await Tortoise.close_connections()

    asyncio.run(scenario())


def test_idempotency_exception_handler_returns_the_unified_error_shape() -> None:
    async def scenario() -> None:
        app = FastAPI()
        register_shared_exception_handlers(app)
        handler = app.exception_handlers[IdempotencyConflictError]
        response = await handler(
            _request({"X-Request-ID": "request-123"}),
            IdempotencyConflictError("same key used for a different request"),
        )

        assert response.status_code == 409
        payload = json.loads(response.body)
        assert payload == {
            "error": {
                "code": "IDEMPOTENCY_CONFLICT",
                "message": "same key used for a different request",
                "details": {},
                "request_id": "request-123",
            }
        }

    asyncio.run(scenario())


def test_project_error_handler_preserves_revision_details_and_request_id() -> None:
    async def scenario() -> None:
        response = await _handle_project_error(
            _request({"X-Request-ID": "request-456"}),
            RevisionConflictError(current_revision=8),
        )
        payload = json.loads(response.body)

        assert response.status_code == 409
        assert payload["error"] == {
            "code": "VERSION_CONFLICT",
            "message": "资源版本已变化，请重新读取后再试",
            "details": {"current_revision": 8},
            "request_id": "request-456",
        }

    asyncio.run(scenario())
