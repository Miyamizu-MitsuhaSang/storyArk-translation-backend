"""Shared project-scoped authorization and request parsing helpers."""

from __future__ import annotations

import base64
import binascii
import json
import re
from typing import TYPE_CHECKING
from uuid import UUID

from ...domain.project.policies import ProjectPolicy
from ...domain.shared.errors import DomainError
from ...models import ProjectMember, User
from ...repositories import ProjectRepository
from .service import ProjectConflictError, ProjectForbiddenError, ProjectNotFoundError, ProjectError

if TYPE_CHECKING:
    from starlette.requests import Request


class ProjectValidationError(ProjectError):
    status_code = 422
    code = "PROJECT_INVALID"


class InvalidCursorError(ProjectValidationError):
    code = "INVALID_CURSOR"


class InvalidRevisionError(ProjectValidationError):
    code = "INVALID_REVISION"


class RevisionMismatchError(ProjectValidationError):
    code = "REVISION_MISMATCH"


class RevisionConflictError(ProjectConflictError):
    code = "VERSION_CONFLICT"

    def __init__(self, current_revision: int) -> None:
        super().__init__(
            "资源版本已变化，请重新读取后再试",
            details={"current_revision": current_revision},
        )


async def require_project_member(
    user: User,
    project_id: UUID,
    *,
    projects: ProjectRepository | None = None,
) -> ProjectMember:
    repository = projects or ProjectRepository()
    membership = await repository.find_membership(project_id, user.id, with_project=True)
    if membership is None:
        raise ProjectNotFoundError("项目不存在或当前用户不可见")
    return membership


async def require_project_role(
    user: User,
    project_id: UUID,
    roles: frozenset[str],
    *,
    projects: ProjectRepository | None = None,
) -> ProjectMember:
    membership = await require_project_member(user, project_id, projects=projects)
    if roles == frozenset({"owner", "manager"}):
        try:
            ProjectPolicy.ensure_manager(membership.role)
        except DomainError as exc:
            raise ProjectForbiddenError(str(exc)) from exc
    elif membership.role not in roles:
        raise ProjectForbiddenError("当前角色没有此项目操作权限")
    return membership


async def get_project_member(project_id: UUID, user: User) -> ProjectMember:
    """FastAPI dependency for any visible project member."""
    return await require_project_member(user, project_id)


async def get_project_manager(project_id: UUID, user: User) -> ProjectMember:
    """FastAPI dependency for owner/manager operations."""
    return await require_project_role(user, project_id, frozenset({"owner", "manager"}))


async def get_project_owner(project_id: UUID, user: User) -> ProjectMember:
    """FastAPI dependency for owner-only destructive operations."""
    return await require_project_role(user, project_id, frozenset({"owner"}))


async def get_project_report_reader(project_id: UUID, user: User) -> ProjectMember:
    """Return membership for roles allowed to inspect project reports."""
    return await require_project_role(
        user,
        project_id,
        frozenset({"owner", "manager", "reviewer"}),
    )


def encode_cursor(offset: int) -> str:
    if offset < 0:
        raise ValueError("cursor offset must be non-negative")
    payload = json.dumps({"offset": offset}, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_cursor(cursor: str | None) -> int:
    if cursor is None or cursor == "":
        return 0
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        decoded = base64.b64decode(padded, altchars=b"-_", validate=True)
        payload = json.loads(decoded.decode("utf-8"))
        offset = payload["offset"]
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("invalid offset")
    except (ValueError, TypeError, KeyError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error) as exc:
        raise InvalidCursorError("分页游标无效") from exc
    return offset


_REVISION_PATTERN = re.compile(r'^(?:"([1-9][0-9]*)"|([1-9][0-9]*))$')


def expected_revision(request: Request, body_revision: int | None) -> int | None:
    """Resolve the optimistic-lock revision from If-Match or a request body."""
    header = request.headers.get("If-Match")
    header_revision: int | None = None
    if header is not None:
        match = _REVISION_PATTERN.fullmatch(header.strip())
        if match is None:
            raise InvalidRevisionError("If-Match 必须是正整数 revision")
        header_revision = int(match.group(1) or match.group(2))

    if body_revision is not None and body_revision < 1:
        raise InvalidRevisionError("revision 必须为正整数")
    if header_revision is not None and body_revision is not None and header_revision != body_revision:
        raise RevisionMismatchError("If-Match 与请求体 revision 不一致", details={
            "header_revision": header_revision,
            "body_revision": body_revision,
        })
    return header_revision if header_revision is not None else body_revision


def ensure_revision_matches(expected: int | None, current: int) -> None:
    if expected is not None and expected != current:
        raise RevisionConflictError(current)


__all__ = [
    "InvalidCursorError",
    "InvalidRevisionError",
    "ProjectForbiddenError",
    "ProjectNotFoundError",
    "ProjectValidationError",
    "RevisionConflictError",
    "RevisionMismatchError",
    "decode_cursor",
    "encode_cursor",
    "ensure_revision_matches",
    "expected_revision",
    "get_project_manager",
    "get_project_member",
    "get_project_owner",
    "get_project_report_reader",
    "require_project_member",
    "require_project_role",
]
