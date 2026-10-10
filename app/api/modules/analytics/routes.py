from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from starlette.responses import JSONResponse

from ....application.analytics.schemas import TranslationReportResponse, UsageAnalyticsQuery, UsageAnalyticsResponse
from ....application.analytics.service import UsageAnalyticsError, UsageAnalyticsService
from ....models import User
from ...shared.dependencies import get_current_user

analytics_router = APIRouter(tags=["analytics"])


async def _handle_analytics_error(request: Request, exc: UsageAnalyticsError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": {"code": exc.code, "message": str(exc), "details": {}, "request_id": getattr(request.state, "request_id", None)}})


def register_analytics_exception_handler(app) -> None:
    app.add_exception_handler(UsageAnalyticsError, _handle_analytics_error)


@analytics_router.get("/auth/me/analytics/usage", response_model=UsageAnalyticsResponse, description="返回当前用户自己的 AI provider 用量统计。")
async def user_usage_analytics(query: UsageAnalyticsQuery = Depends(), user: User = Depends(get_current_user)) -> UsageAnalyticsResponse:
    return await UsageAnalyticsService().for_user(user, query)


@analytics_router.get("/projects/{project_id}/analytics/usage", response_model=UsageAnalyticsResponse, description="返回项目范围内的 AI provider 用量统计。")
async def project_usage_analytics(project_id: UUID, query: UsageAnalyticsQuery = Depends(), user: User = Depends(get_current_user)) -> UsageAnalyticsResponse:
    return await UsageAnalyticsService().for_project(user, project_id, query)


@analytics_router.get("/projects/{project_id}/analytics/translation-report", response_model=TranslationReportResponse, description="返回项目翻译任务的零汇总占位报表。")
async def project_translation_report(project_id: UUID, user: User = Depends(get_current_user), from_: str | None = Query(default=None, alias="from"), to: str | None = Query(default=None), target_language: str | None = Query(default=None), status: str | None = Query(default=None)) -> TranslationReportResponse:
    filters: dict[str, Any] = {"from": from_, "to": to, "target_language": target_language, "status": status}
    return await UsageAnalyticsService().translation_report(user, project_id, filters)


__all__ = ["analytics_router", "register_analytics_exception_handler"]
