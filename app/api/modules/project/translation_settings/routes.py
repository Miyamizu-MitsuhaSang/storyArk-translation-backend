from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from starlette.responses import Response

from .....application.project.shared import expected_revision
from .....application.project.translation_settings.schemas import (
    CultureRuleCreateRequest,
    CultureRulePage,
    CultureRuleResponse,
    CultureRuleUpdateRequest,
    RuleCreateRequest,
    RoleCreateRequest,
    SettingsInitializeRequest,
    SettingsUpdateRequest,
    TranslationRolePage,
    TranslationRoleResponse,
    TranslationRoleUpdateRequest,
    TranslationRulePage,
    TranslationRuleResponse,
    TranslationRuleUpdateRequest,
    TranslationSettingsResponse,
    TranslationTemplatePage,
)
from .....application.project.translation_settings.service import TranslationSettingsError, TranslationSettingsService
from .....models import User
from ....shared.dependencies import get_current_user
from .dependencies import get_translation_settings_service


translation_settings_router = APIRouter(tags=["translation-settings"])


async def _handle_translation_settings_error(request: Request, exc: TranslationSettingsError):
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": str(exc),
                "details": getattr(exc, "details", {}),
                "request_id": getattr(request.state, "request_id", None) or request.headers.get("X-Request-ID"),
            }
        },
    )


def register_translation_settings_exception_handler(app) -> None:
    app.add_exception_handler(TranslationSettingsError, _handle_translation_settings_error)


@translation_settings_router.get("/translation-templates", response_model=TranslationTemplatePage)
async def list_translation_templates(
    service: TranslationSettingsService = Depends(get_translation_settings_service),
) -> TranslationTemplatePage:
    return await service.templates()


@translation_settings_router.get(
    "/projects/{project_id}/translation-settings",
    response_model=TranslationSettingsResponse,
)
async def get_translation_settings(
    project_id: UUID,
    user: User = Depends(get_current_user),
    service: TranslationSettingsService = Depends(get_translation_settings_service),
) -> TranslationSettingsResponse:
    return await service.get(user, project_id)


@translation_settings_router.patch(
    "/projects/{project_id}/translation-settings",
    response_model=TranslationSettingsResponse,
)
async def update_translation_settings(
    project_id: UUID,
    request_body: SettingsUpdateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    service: TranslationSettingsService = Depends(get_translation_settings_service),
) -> TranslationSettingsResponse:
    return await service.update(
        user,
        project_id,
        request_body,
        expected_revision(request, request_body.revision),
    )


@translation_settings_router.get(
    "/projects/{project_id}/translation-settings/roles",
    response_model=TranslationRolePage,
)
async def list_translation_roles(
    project_id: UUID,
    q: str | None = Query(default=None),
    page_size: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    service: TranslationSettingsService = Depends(get_translation_settings_service),
) -> TranslationRolePage:
    return await service.list_roles(user, project_id, q=q, page_size=page_size, cursor=cursor)


@translation_settings_router.post(
    "/projects/{project_id}/translation-settings/roles",
    response_model=TranslationRoleResponse,
    status_code=201,
)
async def create_translation_role(
    project_id: UUID,
    request_body: RoleCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user: User = Depends(get_current_user),
    service: TranslationSettingsService = Depends(get_translation_settings_service),
) -> TranslationRoleResponse:
    return await service.create_role(user, project_id, request_body, idempotency_key=idempotency_key)


@translation_settings_router.get(
    "/projects/{project_id}/translation-settings/roles/{role_id}",
    response_model=TranslationRoleResponse,
)
async def get_translation_role(
    project_id: UUID,
    role_id: UUID,
    user: User = Depends(get_current_user),
    service: TranslationSettingsService = Depends(get_translation_settings_service),
) -> TranslationRoleResponse:
    return await service.get_role(user, project_id, role_id)


@translation_settings_router.patch(
    "/projects/{project_id}/translation-settings/roles/{role_id}",
    response_model=TranslationRoleResponse,
)
async def update_translation_role(
    project_id: UUID,
    role_id: UUID,
    request_body: TranslationRoleUpdateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    service: TranslationSettingsService = Depends(get_translation_settings_service),
) -> TranslationRoleResponse:
    return await service.update_role(
        user,
        project_id,
        role_id,
        request_body,
        expected_revision(request, request_body.revision),
    )


@translation_settings_router.delete(
    "/projects/{project_id}/translation-settings/roles/{role_id}",
    status_code=204,
)
async def delete_translation_role(
    project_id: UUID,
    role_id: UUID,
    request: Request,
    user: User = Depends(get_current_user),
    service: TranslationSettingsService = Depends(get_translation_settings_service),
) -> Response:
    await service.delete_role(user, project_id, role_id, expected_revision(request, None))
    return Response(status_code=204)


@translation_settings_router.get(
    "/projects/{project_id}/translation-settings/rules",
    response_model=TranslationRulePage,
)
async def list_translation_rules(
    project_id: UUID,
    type: str | None = Query(default=None, pattern="^(general|category)$"),
    category: str | None = Query(default=None),
    q: str | None = Query(default=None),
    page_size: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    service: TranslationSettingsService = Depends(get_translation_settings_service),
) -> TranslationRulePage:
    return await service.list_rules(
        user,
        project_id,
        rule_type=type,
        category=category,
        q=q,
        page_size=page_size,
        cursor=cursor,
    )


@translation_settings_router.post(
    "/projects/{project_id}/translation-settings/rules",
    response_model=TranslationRuleResponse,
    status_code=201,
)
async def create_translation_rule(
    project_id: UUID,
    request_body: RuleCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user: User = Depends(get_current_user),
    service: TranslationSettingsService = Depends(get_translation_settings_service),
) -> TranslationRuleResponse:
    return await service.create_rule(user, project_id, request_body, idempotency_key=idempotency_key)


@translation_settings_router.get(
    "/projects/{project_id}/translation-settings/rules/{rule_id}",
    response_model=TranslationRuleResponse,
)
async def get_translation_rule(
    project_id: UUID,
    rule_id: UUID,
    user: User = Depends(get_current_user),
    service: TranslationSettingsService = Depends(get_translation_settings_service),
) -> TranslationRuleResponse:
    return await service.get_rule(user, project_id, rule_id)


@translation_settings_router.patch(
    "/projects/{project_id}/translation-settings/rules/{rule_id}",
    response_model=TranslationRuleResponse,
)
async def update_translation_rule(
    project_id: UUID,
    rule_id: UUID,
    request_body: TranslationRuleUpdateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    service: TranslationSettingsService = Depends(get_translation_settings_service),
) -> TranslationRuleResponse:
    return await service.update_rule(
        user,
        project_id,
        rule_id,
        request_body,
        expected_revision(request, request_body.revision),
    )


@translation_settings_router.delete(
    "/projects/{project_id}/translation-settings/rules/{rule_id}",
    status_code=204,
)
async def delete_translation_rule(
    project_id: UUID,
    rule_id: UUID,
    request: Request,
    user: User = Depends(get_current_user),
    service: TranslationSettingsService = Depends(get_translation_settings_service),
) -> Response:
    await service.delete_rule(user, project_id, rule_id, expected_revision(request, None))
    return Response(status_code=204)


@translation_settings_router.get(
    "/projects/{project_id}/translation-settings/culture-rules",
    response_model=CultureRulePage,
)
async def list_culture_rules(
    project_id: UUID,
    language: str | None = Query(default=None),
    q: str | None = Query(default=None),
    page_size: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    service: TranslationSettingsService = Depends(get_translation_settings_service),
) -> CultureRulePage:
    return await service.list_culture_rules(user, project_id, language=language, q=q, page_size=page_size, cursor=cursor)


@translation_settings_router.post(
    "/projects/{project_id}/translation-settings/culture-rules",
    response_model=CultureRuleResponse,
    status_code=201,
)
async def create_culture_rule(
    project_id: UUID,
    request_body: CultureRuleCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user: User = Depends(get_current_user),
    service: TranslationSettingsService = Depends(get_translation_settings_service),
) -> CultureRuleResponse:
    return await service.create_culture_rule(user, project_id, request_body, idempotency_key=idempotency_key)


@translation_settings_router.get(
    "/projects/{project_id}/translation-settings/culture-rules/{rule_id}",
    response_model=CultureRuleResponse,
)
async def get_culture_rule(
    project_id: UUID,
    rule_id: UUID,
    user: User = Depends(get_current_user),
    service: TranslationSettingsService = Depends(get_translation_settings_service),
) -> CultureRuleResponse:
    return await service.get_culture_rule(user, project_id, rule_id)


@translation_settings_router.patch(
    "/projects/{project_id}/translation-settings/culture-rules/{rule_id}",
    response_model=CultureRuleResponse,
)
async def update_culture_rule(
    project_id: UUID,
    rule_id: UUID,
    request_body: CultureRuleUpdateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    service: TranslationSettingsService = Depends(get_translation_settings_service),
) -> CultureRuleResponse:
    return await service.update_culture_rule(user, project_id, rule_id, request_body, expected_revision(request, request_body.revision))


@translation_settings_router.delete(
    "/projects/{project_id}/translation-settings/culture-rules/{rule_id}",
    status_code=204,
)
async def delete_culture_rule(
    project_id: UUID,
    rule_id: UUID,
    request: Request,
    user: User = Depends(get_current_user),
    service: TranslationSettingsService = Depends(get_translation_settings_service),
) -> Response:
    await service.delete_culture_rule(user, project_id, rule_id, expected_revision(request, None))
    return Response(status_code=204)


@translation_settings_router.post(
    "/projects/{project_id}/translation-settings/initialize",
    response_model=TranslationSettingsResponse,
)
async def initialize_translation_settings(
    project_id: UUID,
    request_body: SettingsInitializeRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user: User = Depends(get_current_user),
    service: TranslationSettingsService = Depends(get_translation_settings_service),
) -> TranslationSettingsResponse:
    return await service.initialize(
        user,
        project_id,
        template_id=request_body.template_id,
        expected_revision=expected_revision(request, request_body.expected_revision),
        confirm_replace=request_body.confirm_replace,
        idempotency_key=idempotency_key,
    )


__all__ = ["translation_settings_router"]
