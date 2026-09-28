"""Root HTTP API router assembly."""

from fastapi import APIRouter

from translation_backend.app.api.modules.auth.routes import auth_router
from translation_backend.app.api.modules.project.routes import project_router
from translation_backend.app.api.modules.rag.routes import router as rag_router
from translation_backend.app.core.config import app_settings


api_router = APIRouter(prefix=app_settings.api_prefix)
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(rag_router)
api_router.include_router(project_router)

__all__ = ["api_router"]
