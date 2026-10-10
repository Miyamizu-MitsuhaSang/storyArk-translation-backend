from __future__ import annotations

import base64
import json
from uuid import UUID

from tortoise import transactions
from tortoise.exceptions import IntegrityError

from ....domain.api_key.policies import ApiKeyPolicy
from ....domain.shared.errors import DomainError
from .schemas import (
    CreateProjectApiKeyRequest,
    ProjectApiKeyPage,
    ProjectApiKeyResponse,
    UpdateProjectApiKeyRequest,
)
from ....models import AIProviderCredential, Project, ProjectApiKeyBinding, ProjectMember, User
from ....repositories import ApiKeyRepository, ProjectApiKeyRepository, ProjectRepository


class ProjectApiKeyError(Exception):
    status_code = 400
    code = "PROJECT_API_KEY_ERROR"


class ProjectApiKeyNotFoundError(ProjectApiKeyError):
    status_code = 404
    code = "PROJECT_API_KEY_NOT_FOUND"


class ProjectApiKeyForbiddenError(ProjectApiKeyError):
    status_code = 403
    code = "PROJECT_API_KEY_FORBIDDEN"


class ProjectApiKeyConflictError(ProjectApiKeyError):
    status_code = 409
    code = "PROJECT_API_KEY_CONFLICT"


class ProjectApiKeyInUseError(ProjectApiKeyError):
    status_code = 409
    code = "API_KEY_IN_USE"


class ProjectApiKeyService:
    def __init__(self, *, projects: ProjectRepository | None = None, api_keys: ApiKeyRepository | None = None, bindings: ProjectApiKeyRepository | None = None) -> None:
        self._projects = projects or ProjectRepository()
        self._api_keys = api_keys or ApiKeyRepository()
        self._bindings = bindings or ProjectApiKeyRepository()

    async def list(self, user: User, project_id: UUID, *, page_size: int, cursor: str | None) -> ProjectApiKeyPage:
        project, _ = await self._authorized_project(user, project_id, require_manager=False)
        offset = self._decode_cursor(cursor)
        rows, total = await self._bindings.list_for_project(project, offset=offset, limit=page_size)
        items = [self._response(binding) for binding in rows]
        next_offset = offset + len(items)
        return ProjectApiKeyPage(
            items=items,
            next_cursor=self._encode_cursor(next_offset) if next_offset < total else None,
            total=total,
        )

    async def create(
        self,
        user: User,
        project_id: UUID,
        request: CreateProjectApiKeyRequest,
    ) -> ProjectApiKeyResponse:
        project, _ = await self._authorized_project(user, project_id, require_manager=True)
        api_key = await self._api_keys.find_active_owned(user.id, request.api_key_id)
        try:
            ApiKeyPolicy.ensure_bindable(is_owned=api_key is not None, is_active=api_key is not None and api_key.is_active)
        except DomainError as exc:
            raise ProjectApiKeyNotFoundError(str(exc)) from exc

        if api_key is None:
            raise ProjectApiKeyNotFoundError("API key 不存在或不可用")
        async with transactions.in_transaction() as connection:
            locked_project = (
                await Project.filter(id=project.id)
                .using_db(connection)
                .select_for_update()
                .first()
            )
            if locked_project is None:
                raise ProjectApiKeyNotFoundError("项目不存在或当前用户不可见")
            locked_key = await AIProviderCredential.filter(
                id=api_key.id,
                user_id=user.id,
                is_active=True,
            ).using_db(connection).first()
            if locked_key is None:
                raise ProjectApiKeyNotFoundError("API key 不存在或不可用")
            binding = (
                await ProjectApiKeyBinding.filter(project_id=project.id, api_key_id=api_key.id)
                .using_db(connection)
                .select_related("api_key")
                .first()
            )
            if binding is not None:
                if request.is_default and not binding.is_default:
                    await ProjectApiKeyBinding.filter(
                        project_id=project.id,
                        is_default=True,
                    ).using_db(connection).update(is_default=False)
                    binding.is_default = True
                    await binding.save(using_db=connection, update_fields=["is_default", "updated_at"])
                return self._response(binding)
            if request.is_default:
                await ProjectApiKeyBinding.filter(
                    project_id=project.id,
                    is_default=True,
                ).using_db(connection).update(is_default=False)
            try:
                created = await ProjectApiKeyBinding.create(
                    project_id=project.id,
                    api_key_id=api_key.id,
                    is_default=request.is_default,
                    using_db=connection,
                )
            except IntegrityError as exc:
                raise ProjectApiKeyConflictError("API key 已绑定到项目") from exc
            binding = await (
                ProjectApiKeyBinding.filter(id=created.id)
                .using_db(connection)
                .select_related("api_key")
                .first()
            )
        if binding is None:
            raise ProjectApiKeyConflictError("API key 绑定创建失败")
        return self._response(binding)

    async def update(
        self,
        user: User,
        project_id: UUID,
        binding_id: UUID,
        request: UpdateProjectApiKeyRequest,
    ) -> ProjectApiKeyResponse:
        project, _ = await self._authorized_project(user, project_id, require_manager=True)
        binding = await self._bindings.find(project, binding_id, with_key=True)
        if binding is None:
            raise ProjectApiKeyNotFoundError("项目 API key 绑定不存在")
        changes = request.model_dump(exclude_unset=True)
        if changes.get("status") == "active":
            credential = await self._api_keys.find_owned(binding.api_key.user_id, binding.api_key.id)
            if credential is None or not credential.is_active:
                raise ProjectApiKeyNotFoundError("用户级 API key 不存在或不可用")
        if changes.get("is_default"):
            await self._bindings.clear_default(project)
        for field, value in changes.items():
            setattr(binding, field, value)
        if changes:
            await self._bindings.save(binding, update_fields=list(changes.keys()))
        return self._response(binding)

    async def delete(self, user: User, project_id: UUID, binding_id: UUID) -> None:
        project, _ = await self._authorized_project(user, project_id, require_manager=True)
        binding = await self._bindings.find(project, binding_id)
        if binding is None:
            raise ProjectApiKeyNotFoundError("项目 API key 绑定不存在")
        # Translation-task references will be checked here when that model is added.
        await self._bindings.delete(binding)

    async def _authorized_project(
        self,
        user: User,
        project_id: UUID,
        *,
        require_manager: bool,
    ) -> tuple[Project, ProjectMember]:
        membership = await self._projects.find_membership(project_id, user.id, with_project=True)
        if membership is None:
            raise ProjectApiKeyNotFoundError("项目不存在或当前用户不可见")
        if require_manager:
            try:
                ApiKeyPolicy.ensure_manager(membership.role)
            except DomainError as exc:
                raise ProjectApiKeyForbiddenError(str(exc)) from exc
        return membership.project, membership

    @staticmethod
    def _response(binding: ProjectApiKeyBinding) -> ProjectApiKeyResponse:
        credential = binding.api_key
        return ProjectApiKeyResponse(
            id=binding.id,
            api_key_id=credential.id,
            provider=credential.provider,
            label=credential.label,
            masked_secret=f"{credential.key_prefix or ''}{'•' * 8}{credential.key_hint or ''}",
            status=binding.status,
            is_default=binding.is_default,
            created_at=binding.created_at,
        )

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
            raise ProjectApiKeyConflictError("分页游标无效") from exc
        if offset < 0:
            raise ProjectApiKeyConflictError("分页游标无效")
        return offset
