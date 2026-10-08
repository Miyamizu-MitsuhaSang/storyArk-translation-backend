from __future__ import annotations

import base64
import json
from uuid import UUID, uuid4

from tortoise.exceptions import IntegrityError

from ...domain.project.policies import LanguagePairPolicy, OwnerPolicy, ProjectPolicy
from ...domain.shared.errors import DomainError
from .schemas import (
    AddMemberRequest,
    CreateProjectRequest,
    LanguagePairPage,
    LanguagePairListQuery,
    LanguagePairRequest,
    LanguagePairRef,
    LanguagePairResponse,
    MemberListQuery,
    MemberPage,
    ProjectListItem,
    ProjectListQuery,
    ProjectMemberResponse,
    ProjectPage,
    ProjectResponse,
    UpdateMemberRequest,
    UpdateProjectRequest,
    UserSummary,
)
from ...models import Project, ProjectLanguagePair, ProjectMember, User
from ...repositories import ProjectRepository, UserRepository


class ProjectError(Exception):
    status_code = 400
    code = "PROJECT_ERROR"

    def __init__(self, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


class ProjectNotFoundError(ProjectError):
    status_code = 404
    code = "PROJECT_NOT_FOUND"


class ProjectForbiddenError(ProjectError):
    status_code = 403
    code = "PROJECT_FORBIDDEN"


class ProjectConflictError(ProjectError):
    status_code = 409
    code = "PROJECT_CONFLICT"


class ProjectService:
    def __init__(self, *, projects: ProjectRepository | None = None, users: UserRepository | None = None) -> None:
        self._projects = projects or ProjectRepository()
        self._users = users or UserRepository()

    @staticmethod
    def _apply_policy(policy_call) -> None:
        try:
            policy_call()
        except DomainError as exc:
            if exc.code == "PROJECT_FORBIDDEN":
                raise ProjectForbiddenError(str(exc)) from exc
            raise ProjectConflictError(str(exc)) from exc

    async def create_project(self, user: User, request: CreateProjectRequest) -> ProjectResponse:
        pairs = [
            (source, target)
            for source in request.source_languages
            for target in request.target_languages
        ]
        project = await self._projects.create_with_owner(
            key=self._new_project_key(),
            name=request.name.strip(),
            description=request.description,
            user=user,
            language_pairs=pairs,
        )
        return await self._project_response(project, user)

    async def list_projects(self, user: User, query: ProjectListQuery) -> ProjectPage:
        memberships = await self._projects.list_project_ids_for_user(user)
        offset = self._decode_cursor(query.cursor)
        rows, total = await self._projects.list_for_user(
            memberships,
            status=query.status,
            search=query.q,
            order_by=self._order_clause(query.sort),
            offset=offset,
            limit=query.page_size,
        )
        role_map = await self._projects.roles_for_user(user, memberships)
        items = [
            ProjectListItem(
                id=project.id,
                key=project.key,
                name=project.name,
                description=project.description,
                status=project.status,
                role=role_map[str(project.id)],
                updated_at=project.updated_at,
            )
            for project in rows
        ]
        next_offset = offset + len(items)
        return ProjectPage(
            items=items,
            next_cursor=self._encode_cursor(next_offset) if next_offset < total else None,
            total=total,
        )

    async def get_project(self, user: User, project_id: UUID) -> ProjectResponse:
        project = await self._authorized_project(user, project_id)
        return await self._project_response(project, user)

    async def update_project(
        self,
        user: User,
        project_id: UUID,
        request: UpdateProjectRequest,
    ) -> ProjectResponse:
        project, membership = await self._authorized_project_with_membership(user, project_id)
        self._require_manager(membership)
        default_pair = None
        if request.default_language_pair is not None:
            default_pair = await self._projects.find_language_pair(
                project,
                request.default_language_pair.source,
                request.default_language_pair.target,
            )
            self._apply_policy(lambda: LanguagePairPolicy.ensure_default_pair_exists(default_pair is not None))
        changes = request.model_dump(exclude_unset=True, exclude={"default_language_pair"})
        if "name" in changes:
            changes["name"] = changes["name"].strip()
        for field, value in changes.items():
            setattr(project, field, value)
        await self._projects.save(project, update_fields=list(changes.keys()))
        if default_pair is not None:
            await self._projects.clear_default_language_pairs(project)
            default_pair.is_default = True
            await self._projects.save_language_pair(default_pair, update_fields=["is_default"])
        return await self._project_response(project, user)

    async def list_members(self, user: User, project_id: UUID, query: MemberListQuery) -> MemberPage:
        project = await self._authorized_project(user, project_id)
        memberships, total = await self._projects.list_members(
            project,
            role=query.role,
            search=query.q,
            order_by=self._member_order_clause(query.sort),
            offset=self._decode_cursor(query.cursor),
            limit=query.page_size,
        )
        offset = self._decode_cursor(query.cursor)
        items = [self._member_response(item) for item in memberships]
        next_offset = offset + len(items)
        return MemberPage(
            items=items,
            next_cursor=self._encode_cursor(next_offset) if next_offset < total else None,
            total=total,
        )

    async def add_member(self, user: User, project_id: UUID, request: AddMemberRequest) -> ProjectMemberResponse:
        project, membership = await self._authorized_project_with_membership(user, project_id)
        self._require_manager(membership)
        target = await self._users.find_active(request.user_id)
        if target is None:
            raise ProjectNotFoundError("用户不存在")
        if await self._projects.member_exists(project, target.id):
            raise ProjectConflictError("用户已经是项目成员")
        member = await self._projects.create_member(project, target, role=request.role)
        return self._member_response(member)

    async def update_member(
        self,
        user: User,
        project_id: UUID,
        target_user_id: UUID,
        request: UpdateMemberRequest,
    ) -> ProjectMemberResponse:
        project, membership = await self._authorized_project_with_membership(user, project_id)
        self._require_manager(membership)
        target = await self._projects.find_member(project, target_user_id, with_user=True)
        if target is None:
            raise ProjectNotFoundError("项目成员不存在")
        if target.role == "owner" and request.role != "owner":
            owners = await self._projects.count_owners(project)
            self._apply_policy(lambda: OwnerPolicy.ensure_not_last_owner(target.role, request.role, owners))
        target.role = request.role
        await self._projects.save_member(target, update_fields=["role"])
        return self._member_response(target)

    async def remove_member(self, user: User, project_id: UUID, target_user_id: UUID) -> None:
        project, membership = await self._authorized_project_with_membership(user, project_id)
        self._require_manager(membership)
        target = await self._projects.find_member(project, target_user_id)
        if target is None:
            raise ProjectNotFoundError("项目成员不存在")
        owners = await self._projects.count_owners(project)
        self._apply_policy(lambda: OwnerPolicy.ensure_not_last_owner(target.role, None, owners))
        await self._projects.delete_member(target)

    async def list_language_pairs(self, user: User, project_id: UUID, query: LanguagePairListQuery | None = None) -> LanguagePairPage:
        project = await self._authorized_project(user, project_id)
        query = query or LanguagePairListQuery()
        offset = self._decode_cursor(query.cursor)
        rows, total = await self._projects.list_language_pairs(project, offset=offset, limit=query.page_size)
        items = [self._language_pair_response(pair) for pair in rows]
        next_offset = offset + len(items)
        return LanguagePairPage(
            items=items,
            next_cursor=self._encode_cursor(next_offset) if next_offset < total else None,
            total=total,
        )

    async def add_language_pair(
        self,
        user: User,
        project_id: UUID,
        request: LanguagePairRequest,
    ) -> LanguagePairResponse:
        project, membership = await self._authorized_project_with_membership(user, project_id)
        self._require_manager(membership)
        if await self._projects.find_language_pair(project, request.source_language, request.target_language):
            raise ProjectConflictError("语言对已经存在")
        if request.is_default:
            await self._projects.clear_default_language_pairs(project)
        elif not await self._projects.language_pair_exists(project):
            request.is_default = True
        try:
            pair = await self._projects.create_language_pair(project, **request.model_dump())
        except IntegrityError as exc:
            raise ProjectConflictError("语言对已经存在") from exc
        return self._language_pair_response(pair)

    async def _authorized_project(self, user: User, project_id: UUID) -> Project:
        project, _ = await self._authorized_project_with_membership(user, project_id)
        return project

    async def _authorized_project_with_membership(self, user: User, project_id: UUID) -> tuple[Project, ProjectMember]:
        membership = await self._projects.find_membership(project_id, user.id, with_project=True)
        if membership is None:
            raise ProjectNotFoundError("项目不存在或当前用户不可见")
        return membership.project, membership

    @staticmethod
    def _require_manager(membership: ProjectMember) -> None:
        try:
            ProjectPolicy.ensure_manager(membership.role)
        except DomainError as exc:
            raise ProjectForbiddenError(str(exc)) from exc

    async def _project_response(self, project: Project, user: User) -> ProjectResponse:
        membership = await self._projects.find_membership(project.id, user.id)
        pairs, _ = await self._projects.list_language_pairs(project)
        return ProjectResponse(
            id=project.id,
            key=project.key,
            name=project.name,
            description=project.description,
            status=project.status,
            role=membership.role,
            updated_at=project.updated_at,
            source_languages=list(dict.fromkeys(pair.source_language for pair in pairs)),
            target_languages=list(dict.fromkeys(pair.target_language for pair in pairs)),
            default_language_pair=next(
                (
                    LanguagePairRef(source=pair.source_language, target=pair.target_language)
                    for pair in pairs
                    if pair.is_default
                ),
                None,
            ),
            member_count=await self._projects.count_members(project),
            language_pairs=[self._language_pair_response(pair) for pair in pairs],
        )

    @staticmethod
    def _member_response(member: ProjectMember) -> ProjectMemberResponse:
        return ProjectMemberResponse(
            user=UserSummary.model_validate(member.user),
            role=member.role,
            created_at=member.created_at,
        )

    @staticmethod
    def _language_pair_response(pair: ProjectLanguagePair) -> LanguagePairResponse:
        return LanguagePairResponse(
            id=pair.id,
            source_language=pair.source_language,
            target_language=pair.target_language,
            is_default=pair.is_default,
            is_active=pair.is_active,
            created_at=pair.created_at,
        )

    @staticmethod
    def _new_project_key() -> str:
        return f"project-{uuid4().hex[:24]}"

    @staticmethod
    def _encode_cursor(offset: int) -> str:
        return base64.urlsafe_b64encode(json.dumps({"offset": offset}).encode()).decode().rstrip("=")

    @staticmethod
    def _decode_cursor(cursor: str | None) -> int:
        if not cursor:
            return 0
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            offset = int(json.loads(base64.urlsafe_b64decode(padded).decode())["offset"])
        except (ValueError, KeyError, TypeError, json.JSONDecodeError, base64.binascii.Error) as exc:
            raise ProjectConflictError("分页游标无效") from exc
        if offset < 0:
            raise ProjectConflictError("分页游标无效")
        return offset

    @staticmethod
    def _order_clause(sort: str) -> str:
        return "name" if sort == "name" else f"-{sort}"

    @staticmethod
    def _member_order_clause(sort: str) -> str:
        return "user__username" if sort == "username" else f"-{sort}"
