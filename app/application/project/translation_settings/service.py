from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from tortoise.exceptions import IntegrityError

from ....application.idempotency import execute_idempotently
from ....domain.project.policies import ProjectPolicy
from ....domain.shared.errors import DomainError
from ....models import CultureRule, Project, ProjectMember, TranslationRole, TranslationRule, User, Worldview
from ....repositories import ProjectRepository
from ..audit import ProjectAuditService
from ..service import ProjectConflictError, ProjectError, ProjectForbiddenError, ProjectNotFoundError
from ...project.shared import decode_cursor, encode_cursor, ensure_revision_matches
from .repository import TranslationSettingsRepository
from .templates import TEMPLATES
from .schemas import (
    CultureRuleCreateRequest,
    CultureRulePage,
    CultureRuleResponse,
    CultureRuleUpdateRequest,
    RuleCreateRequest,
    RoleCreateRequest,
    SettingsUpdateRequest,
    TranslationRolePage,
    TranslationRoleResponse,
    TranslationRoleUpdateRequest,
    TranslationRulePage,
    TranslationRuleResponse,
    TranslationSettingsResponse,
    TranslationTemplatePage,
)


class TranslationSettingsError(ProjectError):
    code = "TRANSLATION_SETTINGS_ERROR"


class TranslationSettingsNotFoundError(TranslationSettingsError):
    status_code = 404
    code = "TRANSLATION_SETTINGS_NOT_FOUND"


class TranslationSettingsConflictError(ProjectConflictError):
    code = "TRANSLATION_SETTINGS_CONFLICT"


class ConfirmationRequiredError(TranslationSettingsError):
    status_code = 422
    code = "CONFIRMATION_REQUIRED"


class TranslationTemplateNotFoundError(TranslationSettingsError):
    status_code = 404
    code = "TRANSLATION_TEMPLATE_NOT_FOUND"


class TranslationSettingsService:
    def __init__(
        self,
        *,
        projects: ProjectRepository | None = None,
        repository: TranslationSettingsRepository | None = None,
    ) -> None:
        self._projects = projects or ProjectRepository()
        self._repository = repository or TranslationSettingsRepository()

    async def get(self, user: User, project_id: UUID) -> TranslationSettingsResponse:
        project, _ = await self._authorized_reader(user, project_id)
        worldview = await self._repository.get_or_create_worldview(project)
        return self._settings_response(worldview)

    async def update(
        self,
        user: User,
        project_id: UUID,
        request: SettingsUpdateRequest,
        expected_revision: int | None = None,
    ) -> TranslationSettingsResponse:
        project, membership = await self._authorized_project(user, project_id)
        self._require_manager(membership)
        worldview = await self._repository.get_or_create_worldview(project)
        expected = expected_revision if expected_revision is not None else request.revision
        ensure_revision_matches(expected, worldview.version)
        changes = request.model_dump(exclude_unset=True, exclude={"revision"})
        field_map = {"worldview": "style_guide", "tone": "default_tone"}
        for field, value in changes.items():
            setattr(worldview, field_map[field], value)
        if changes:
            worldview.version += 1
            await self._repository.save_worldview(
                worldview,
                [*{field_map[field] for field in changes}, "version"],
            )
            await ProjectAuditService.record(
                project_id,
                actor_user_id=user.id,
                resource_type="translation_settings",
                resource_id=worldview.id,
                action="translation_settings.updated",
            )
        return self._settings_response(worldview)

    async def list_roles(
        self,
        user: User,
        project_id: UUID,
        *,
        q: str | None = None,
        page_size: int = 20,
        cursor: str | None = None,
    ) -> TranslationRolePage:
        await self._authorized_reader(user, project_id)
        query = q.strip().casefold() if q else None
        rows = await self._repository.list_roles(project_id)
        if query:
            rows = [row for row in rows if query in f"{row.name} {row.description or ''} {row.detailed_injection or ''}".casefold()]
        offset = decode_cursor(cursor)
        page = rows[offset : offset + page_size]
        return TranslationRolePage(
            items=[self._role_response(row) for row in page],
            next_cursor=encode_cursor(offset + len(page)) if offset + len(page) < len(rows) else None,
            total=len(rows),
        )

    async def get_role(self, user: User, project_id: UUID, role_id: UUID) -> TranslationRoleResponse:
        await self._authorized_reader(user, project_id)
        row = await self._repository.get_role(project_id, role_id)
        if row is None:
            raise TranslationSettingsNotFoundError("翻译角色不存在")
        return self._role_response(row)

    async def create_role(
        self,
        user: User,
        project_id: UUID,
        request: RoleCreateRequest,
        *,
        idempotency_key: str | None = None,
    ) -> TranslationRoleResponse:
        project, membership = await self._authorized_project(user, project_id)
        self._require_manager(membership)

        async def callback() -> TranslationRoleResponse:
            existing = await self._repository.get_role_any(project_id, request.name)
            if existing is not None and existing.deleted_at is None:
                raise TranslationSettingsConflictError("同名翻译角色已存在")
            try:
                row = await self._repository.create_role(project, **request.model_dump())
            except IntegrityError as exc:
                raise TranslationSettingsConflictError("同名翻译角色已存在") from exc
            await ProjectAuditService.record(
                project_id,
                actor_user_id=user.id,
                resource_type="translation_role",
                resource_id=row.id,
                action="translation_role.created",
            )
            return self._role_response(row)

        return await execute_idempotently(
            user,
            operation="translation_settings.role.create",
            scope=f"project:{project_id}",
            key=idempotency_key,
            payload=request.model_dump(mode="json"),
            response_type=TranslationRoleResponse,
            callback=callback,
        )

    async def update_role(
        self,
        user: User,
        project_id: UUID,
        role_id: UUID,
        request: TranslationRoleUpdateRequest,
        expected_revision: int | None = None,
    ) -> TranslationRoleResponse:
        await self._authorized_manager(user, project_id)
        row = await self._repository.get_role(project_id, role_id)
        if row is None:
            raise TranslationSettingsNotFoundError("翻译角色不存在")
        ensure_revision_matches(expected_revision if expected_revision is not None else request.revision, row.revision)
        changes = request.model_dump(exclude_unset=True, exclude={"revision"})
        if changes:
            for field, value in changes.items():
                setattr(row, field, value)
            row.revision += 1
            await self._repository.save_role(row, [*changes, "revision"])
            await ProjectAuditService.record(
                project_id,
                actor_user_id=user.id,
                resource_type="translation_role",
                resource_id=row.id,
                action="translation_role.updated",
            )
        return self._role_response(row)

    async def delete_role(self, user: User, project_id: UUID, role_id: UUID, expected_revision: int | None = None) -> None:
        await self._authorized_manager(user, project_id)
        row = await self._repository.get_role(project_id, role_id)
        if row is None:
            raise TranslationSettingsNotFoundError("翻译角色不存在")
        ensure_revision_matches(expected_revision, row.revision)
        row.deleted_at = datetime.now(timezone.utc)
        row.revision += 1
        await self._repository.save_role(row, ["deleted_at", "revision"])
        await ProjectAuditService.record(
            project_id,
            actor_user_id=user.id,
            resource_type="translation_role",
            resource_id=row.id,
            action="translation_role.deleted",
        )

    async def list_rules(
        self,
        user: User,
        project_id: UUID,
        *,
        rule_type: str | None = None,
        category: str | None = None,
        q: str | None = None,
        page_size: int = 20,
        cursor: str | None = None,
    ) -> TranslationRulePage:
        await self._authorized_reader(user, project_id)
        query = q.strip().casefold() if q else None
        rows = await self._repository.list_rules(project_id)
        rows = [
            row for row in rows
            if (rule_type is None or row.type == rule_type)
            and (category is None or row.category == category)
            and (query is None or query in f"{row.name} {row.text} {row.category or ''}".casefold())
        ]
        offset = decode_cursor(cursor)
        page = rows[offset : offset + page_size]
        return TranslationRulePage(
            items=[self._rule_response(row) for row in page],
            next_cursor=encode_cursor(offset + len(page)) if offset + len(page) < len(rows) else None,
            total=len(rows),
        )

    async def get_rule(self, user: User, project_id: UUID, rule_id: UUID) -> TranslationRuleResponse:
        await self._authorized_reader(user, project_id)
        row = await self._repository.get_rule(project_id, rule_id)
        if row is None:
            raise TranslationSettingsNotFoundError("翻译规则不存在")
        return self._rule_response(row)

    async def create_rule(
        self,
        user: User,
        project_id: UUID,
        request: RuleCreateRequest,
        *,
        idempotency_key: str | None = None,
    ) -> TranslationRuleResponse:
        project, membership = await self._authorized_project(user, project_id)
        self._require_manager(membership)

        async def callback() -> TranslationRuleResponse:
            existing = await self._repository.list_rules(project_id)
            if any(
                row.type == request.type and row.name == request.name and row.category == request.category
                for row in existing
            ):
                raise TranslationSettingsConflictError("相同翻译规则已存在")
            try:
                row = await self._repository.create_rule(project, **request.model_dump())
            except IntegrityError as exc:
                raise TranslationSettingsConflictError("相同翻译规则已存在") from exc
            await ProjectAuditService.record(
                project_id,
                actor_user_id=user.id,
                resource_type="translation_rule",
                resource_id=row.id,
                action="translation_rule.created",
            )
            return self._rule_response(row)

        return await execute_idempotently(
            user,
            operation="translation_settings.rule.create",
            scope=f"project:{project_id}",
            key=idempotency_key,
            payload=request.model_dump(mode="json"),
            response_type=TranslationRuleResponse,
            callback=callback,
        )

    async def update_rule(
        self,
        user: User,
        project_id: UUID,
        rule_id: UUID,
        request: TranslationRuleUpdateRequest,
        expected_revision: int | None = None,
    ) -> TranslationRuleResponse:
        await self._authorized_manager(user, project_id)
        row = await self._repository.get_rule(project_id, rule_id)
        if row is None:
            raise TranslationSettingsNotFoundError("翻译规则不存在")
        ensure_revision_matches(expected_revision if expected_revision is not None else request.revision, row.revision)
        changes = request.model_dump(exclude_unset=True, exclude={"revision"})
        resulting_type = changes.get("type", row.type)
        resulting_category = changes.get("category", row.category)
        if resulting_type == "category" and not resulting_category:
            raise ValueError("category 类型规则必须提供 category")
        if resulting_type == "general":
            changes["category"] = None
        if changes:
            for field, value in changes.items():
                setattr(row, field, value)
            row.revision += 1
            await self._repository.save_rule(row, [*changes, "revision"])
            await ProjectAuditService.record(
                project_id,
                actor_user_id=user.id,
                resource_type="translation_rule",
                resource_id=row.id,
                action="translation_rule.updated",
            )
        return self._rule_response(row)

    async def delete_rule(self, user: User, project_id: UUID, rule_id: UUID, expected_revision: int | None = None) -> None:
        await self._authorized_manager(user, project_id)
        row = await self._repository.get_rule(project_id, rule_id)
        if row is None:
            raise TranslationSettingsNotFoundError("翻译规则不存在")
        ensure_revision_matches(expected_revision, row.revision)
        row.deleted_at = datetime.now(timezone.utc)
        row.revision += 1
        await self._repository.save_rule(row, ["deleted_at", "revision"])
        await ProjectAuditService.record(
            project_id,
            actor_user_id=user.id,
            resource_type="translation_rule",
            resource_id=row.id,
            action="translation_rule.deleted",
        )

    async def list_culture_rules(
        self,
        user: User,
        project_id: UUID,
        *,
        language: str | None = None,
        q: str | None = None,
        page_size: int = 20,
        cursor: str | None = None,
    ) -> CultureRulePage:
        await self._authorized_reader(user, project_id)
        query = q.strip().casefold() if q else None
        rows = await self._repository.list_culture_rules(project_id)
        rows = [
            row for row in rows
            if (language is None or row.language == language)
            and (query is None or query in f"{row.name} {row.text} {row.category or ''}".casefold())
        ]
        offset = decode_cursor(cursor)
        page = rows[offset : offset + page_size]
        return CultureRulePage(
            items=[self._culture_response(row) for row in page],
            next_cursor=encode_cursor(offset + len(page)) if offset + len(page) < len(rows) else None,
            total=len(rows),
        )

    async def get_culture_rule(self, user: User, project_id: UUID, rule_id: UUID) -> CultureRuleResponse:
        await self._authorized_reader(user, project_id)
        row = await self._repository.get_culture_rule(project_id, rule_id)
        if row is None:
            raise TranslationSettingsNotFoundError("文化规则不存在")
        return self._culture_response(row)

    async def create_culture_rule(
        self,
        user: User,
        project_id: UUID,
        request: CultureRuleCreateRequest,
        *,
        idempotency_key: str | None = None,
    ) -> CultureRuleResponse:
        project, membership = await self._authorized_project(user, project_id)
        self._require_manager(membership)

        async def callback() -> CultureRuleResponse:
            existing = await self._repository.list_culture_rules(project_id)
            if any(
                row.language == request.language and row.name == request.name and row.category == request.category
                for row in existing
            ):
                raise TranslationSettingsConflictError("相同文化规则已存在")
            try:
                row = await self._repository.create_culture_rule(project, **request.model_dump())
            except IntegrityError as exc:
                raise TranslationSettingsConflictError("相同文化规则已存在") from exc
            await ProjectAuditService.record(
                project_id,
                actor_user_id=user.id,
                resource_type="culture_rule",
                resource_id=row.id,
                action="culture_rule.created",
            )
            return self._culture_response(row)

        return await execute_idempotently(
            user,
            operation="translation_settings.culture_rule.create",
            scope=f"project:{project_id}",
            key=idempotency_key,
            payload=request.model_dump(mode="json"),
            response_type=CultureRuleResponse,
            callback=callback,
        )

    async def update_culture_rule(
        self,
        user: User,
        project_id: UUID,
        rule_id: UUID,
        request: CultureRuleUpdateRequest,
        expected_revision: int | None = None,
    ) -> CultureRuleResponse:
        await self._authorized_manager(user, project_id)
        row = await self._repository.get_culture_rule(project_id, rule_id)
        if row is None:
            raise TranslationSettingsNotFoundError("文化规则不存在")
        ensure_revision_matches(expected_revision if expected_revision is not None else request.revision, row.revision)
        changes = request.model_dump(exclude_unset=True, exclude={"revision"})
        if changes:
            for field, value in changes.items():
                setattr(row, field, value)
            row.revision += 1
            await self._repository.save_culture_rule(row, [*changes, "revision"])
            await ProjectAuditService.record(
                project_id,
                actor_user_id=user.id,
                resource_type="culture_rule",
                resource_id=row.id,
                action="culture_rule.updated",
            )
        return self._culture_response(row)

    async def delete_culture_rule(self, user: User, project_id: UUID, rule_id: UUID, expected_revision: int | None = None) -> None:
        await self._authorized_manager(user, project_id)
        row = await self._repository.get_culture_rule(project_id, rule_id)
        if row is None:
            raise TranslationSettingsNotFoundError("文化规则不存在")
        ensure_revision_matches(expected_revision, row.revision)
        row.deleted_at = datetime.now(timezone.utc)
        row.revision += 1
        await self._repository.save_culture_rule(row, ["deleted_at", "revision"])
        await ProjectAuditService.record(
            project_id,
            actor_user_id=user.id,
            resource_type="culture_rule",
            resource_id=row.id,
            action="culture_rule.deleted",
        )

    async def templates(self) -> TranslationTemplatePage:
        return TranslationTemplatePage(items=list(TEMPLATES.values()))

    async def initialize(
        self,
        user: User,
        project_id: UUID,
        *,
        template_id: str,
        expected_revision: int | None,
        confirm_replace: bool,
        idempotency_key: str | None = None,
    ) -> TranslationSettingsResponse:
        project, membership = await self._authorized_project(user, project_id)
        self._require_manager(membership)
        if not confirm_replace:
            raise ConfirmationRequiredError("整体初始化必须确认替换现有设置")
        if template_id not in TEMPLATES:
            raise TranslationTemplateNotFoundError("翻译设置模板不存在")

        async def callback() -> TranslationSettingsResponse:
            worldview = await self._repository.get_or_create_worldview(project)
            ensure_revision_matches(expected_revision, worldview.version)
            worldview.style_guide = "保留世界观专有名词的官方写法，保持叙事一致性。"
            worldview.default_tone = "自然、清晰、符合角色身份"
            worldview.version += 1
            await self._repository.save_worldview(worldview, ["style_guide", "default_tone", "version"])
            await self._repository.replace_template_children(project_id)
            for values in (
                {
                    "name": "RPG Narrator",
                    "description": "旁白和系统文本",
                    "detailed_injection": "保持信息清晰，避免过度口语化。",
                    "sort_order": 1,
                },
                {
                    "name": "RPG Character",
                    "description": "角色对白",
                    "detailed_injection": "根据角色身份保持稳定语气。",
                    "sort_order": 2,
                },
            ):
                existing = await self._repository.get_role_any(project_id, values["name"])
                if existing is None:
                    await self._repository.create_role(project, **values)
                else:
                    for field, value in values.items():
                        setattr(existing, field, value)
                    existing.deleted_at = None
                    existing.revision += 1
                    await self._repository.save_role(existing, [*values, "deleted_at", "revision"])
            await ProjectAuditService.record(
                project_id,
                actor_user_id=user.id,
                resource_type="translation_settings",
                resource_id=worldview.id,
                action="translation_settings.initialized",
                details={"template_id": template_id, "confirm_replace": True},
            )
            return self._settings_response(worldview)

        return await execute_idempotently(
            user,
            operation="translation_settings.initialize",
            scope=f"project:{project_id}",
            key=idempotency_key,
            payload={
                "template_id": template_id,
                "expected_revision": expected_revision,
                "confirm_replace": confirm_replace,
            },
            response_type=TranslationSettingsResponse,
            callback=callback,
        )

    async def _authorized_project(self, user: User, project_id: UUID) -> tuple[Project, ProjectMember]:
        membership = await self._projects.find_membership(project_id, user.id, with_project=True)
        if membership is None:
            raise ProjectNotFoundError("项目不存在或当前用户不可见")
        return membership.project, membership

    async def _authorized_manager(self, user: User, project_id: UUID) -> tuple[Project, ProjectMember]:
        project, membership = await self._authorized_project(user, project_id)
        self._require_manager(membership)
        return project, membership

    async def _authorized_reader(self, user: User, project_id: UUID) -> tuple[Project, ProjectMember]:
        project, membership = await self._authorized_project(user, project_id)
        if membership.role not in {"owner", "manager", "translator"}:
            raise ProjectForbiddenError("当前角色没有翻译设置读取权限")
        return project, membership

    @staticmethod
    def _require_manager(membership: ProjectMember) -> None:
        try:
            ProjectPolicy.ensure_manager(membership.role)
        except DomainError as exc:
            raise ProjectForbiddenError(str(exc)) from exc

    @staticmethod
    def _settings_response(worldview: Worldview) -> TranslationSettingsResponse:
        return TranslationSettingsResponse(
            project_id=worldview.project_id,
            revision=worldview.version,
            worldview=worldview.style_guide,
            tone=worldview.default_tone,
            updated_at=worldview.updated_at,
        )

    @staticmethod
    def _role_response(row: TranslationRole) -> TranslationRoleResponse:
        return TranslationRoleResponse.model_validate(row, from_attributes=True)

    @staticmethod
    def _rule_response(row: TranslationRule) -> TranslationRuleResponse:
        return TranslationRuleResponse.model_validate(row, from_attributes=True)

    @staticmethod
    def _culture_response(row: CultureRule) -> CultureRuleResponse:
        return CultureRuleResponse.model_validate(row, from_attributes=True)


__all__ = [
    "ConfirmationRequiredError",
    "TEMPLATES",
    "TranslationSettingsConflictError",
    "TranslationSettingsError",
    "TranslationSettingsNotFoundError",
    "TranslationSettingsService",
    "TranslationTemplateNotFoundError",
]
