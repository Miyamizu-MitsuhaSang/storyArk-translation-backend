from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from ....models import ProjectLanguagePair, ProjectSettings, User
from ....repositories import ProjectRepository
from ..service import ProjectError
from ..shared import ensure_revision_matches, require_project_member, require_project_role
from .schemas import ProjectSettingsResponse, ProjectSettingsUpdateRequest


class ProjectSettingsError(ProjectError):
    code = "PROJECT_SETTINGS_ERROR"


class ProjectSettingsValidationError(ProjectSettingsError):
    status_code = 422
    code = "PROJECT_SETTINGS_INVALID"


class ProjectSettingsService:
    def __init__(self, *, projects: ProjectRepository | None = None) -> None:
        self._projects = projects or ProjectRepository()

    async def get(self, user: User, project_id: UUID) -> ProjectSettingsResponse:
        await require_project_member(user, project_id, projects=self._projects)
        settings, _ = await ProjectSettings.get_or_create(project_id=project_id)
        return self._response(settings)

    async def update(
        self,
        user: User,
        project_id: UUID,
        request: ProjectSettingsUpdateRequest,
        expected_revision: int | None = None,
    ) -> ProjectSettingsResponse:
        await require_project_role(
            user,
            project_id,
            frozenset({"owner", "manager"}),
            projects=self._projects,
        )
        settings, _ = await ProjectSettings.get_or_create(project_id=project_id)
        expected = expected_revision if expected_revision is not None else request.revision
        ensure_revision_matches(expected, settings.revision)

        changes = request.model_dump(exclude_unset=True, exclude={"revision"})
        await self._validate_language_changes(settings, changes)
        if not changes:
            return self._response(settings)

        for field, value in changes.items():
            setattr(settings, field, value)
        settings.revision += 1
        await settings.save(update_fields=[*changes.keys(), "revision", "updated_at"])
        return self._response(settings)

    @staticmethod
    async def _validate_language_changes(settings: ProjectSettings, changes: dict[str, object]) -> None:
        language_fields = {"default_source_language", "default_target_language"}
        if not language_fields.intersection(changes):
            return

        source = changes.get("default_source_language", settings.default_source_language)
        target = changes.get("default_target_language", settings.default_target_language)
        if (source is None) != (target is None):
            raise ProjectSettingsValidationError("默认源语言和目标语言必须同时设置或同时清空")
        if source is None and target is None:
            return

        # Validate the pair against active project language configuration.
        pair_exists = await ProjectLanguagePair.filter(
            project_id=settings.project_id,
            source_language=source,
            target_language=target,
            is_active=True,
        ).exists()
        if not pair_exists:
            raise ProjectSettingsValidationError("默认语言对必须属于项目已配置的启用语言对")

    @staticmethod
    def _response(settings: ProjectSettings) -> ProjectSettingsResponse:
        return ProjectSettingsResponse(
            project_id=settings.project_id,
            default_source_language=settings.default_source_language,
            default_target_language=settings.default_target_language,
            terminology_enabled=settings.terminology_enabled,
            translation_memory_enabled=settings.translation_memory_enabled,
            default_model=settings.default_model,
            quality_threshold=float(Decimal(settings.quality_threshold)),
            revision=settings.revision,
            updated_at=settings.updated_at,
        )
