from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from .....application.project.settings.schemas import ProjectSettingsResponse, ProjectSettingsUpdateRequest
from .....application.project.settings.service import ProjectSettingsError, ProjectSettingsService
from .....application.project.shared import expected_revision
from .....models import User
from ....shared.dependencies import get_current_user
from .dependencies import get_project_settings_service


project_settings_router = APIRouter(tags=["project-settings"])


async def _handle_project_settings_error(request: Request, exc: ProjectSettingsError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": str(exc),
                "details": getattr(exc, "details", {}),
                "request_id": getattr(request.state, "request_id", None)
                or request.headers.get("X-Request-ID"),
            }
        },
    )


def register_project_settings_exception_handler(app) -> None:
    app.add_exception_handler(ProjectSettingsError, _handle_project_settings_error)


@project_settings_router.get(
    "/projects/{project_id}/settings",
    response_model=ProjectSettingsResponse,
    summary="读取项目级设置",
    description="读取当前用户可见项目的协作默认设置。用户级设置和翻译工作区设置不通过此接口修改。",
)
async def get_project_settings(
    project_id: UUID,
    user: User = Depends(get_current_user),
    service: ProjectSettingsService = Depends(get_project_settings_service),
) -> ProjectSettingsResponse:
    return await service.get(user, project_id)


@project_settings_router.patch(
    "/projects/{project_id}/settings",
    response_model=ProjectSettingsResponse,
    summary="更新项目级设置",
    description="部分更新项目级协作默认设置。仅 owner 或 manager 可写；revision 可放在请求体或 If-Match 请求头中。",
)
async def update_project_settings(
    project_id: UUID,
    request_body: ProjectSettingsUpdateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    service: ProjectSettingsService = Depends(get_project_settings_service),
) -> ProjectSettingsResponse:
    return await service.update(
        user,
        project_id,
        request_body,
        expected_revision(request, request_body.revision),
    )


__all__ = [
    "get_project_settings",
    "project_settings_router",
    "register_project_settings_exception_handler",
    "update_project_settings",
]
