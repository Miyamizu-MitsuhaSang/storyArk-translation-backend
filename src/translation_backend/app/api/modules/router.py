from fastapi import APIRouter

from translation_backend.app.api.modules.auth.routes import auth_router
from translation_backend.app.core.config import app_settings
from translation_backend.app.api.modules.health import health
from translation_backend.app.api.modules.rag import routes as rag

api_router = APIRouter()
api_router.include_router(auth_router, prefix=f"{app_settings.api_prefix}/auth", tags=["auth"])
api_router.include_router(health.router)
api_router.include_router(rag.router)
