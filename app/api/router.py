"""Root HTTP API router assembly."""

from fastapi import APIRouter

from .modules.auth.routes import auth_router
from .modules.project.routes import project_router
from .modules.rag.routes import router as rag_router
from .modules.jobs.routes import jobs_router
from .modules.project.translation_settings.routes import translation_settings_router
from .modules.analytics.routes import analytics_router
from ..core.config import app_settings


api_router = APIRouter(prefix=app_settings.api_prefix)
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(rag_router)
api_router.include_router(project_router)
api_router.include_router(jobs_router)
api_router.include_router(translation_settings_router)
api_router.include_router(analytics_router)

__all__ = ["api_router"]
