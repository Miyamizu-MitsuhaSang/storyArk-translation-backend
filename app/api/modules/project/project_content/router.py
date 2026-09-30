from fastapi import APIRouter

from .context.routes import project_context_router
from .terminology.routes import project_terminology_router
from .worldview.routes import project_worldview_router
from .translation_memory.routes import project_translation_memory_router

project_content_router = APIRouter()
project_content_router.include_router(project_worldview_router, prefix="/worldview", tags=["worldview"])
project_content_router.include_router(project_context_router, prefix="/context", tags=["context"])
project_content_router.include_router(project_terminology_router, tags=["terminology"])
project_content_router.include_router(project_translation_memory_router, tags=["translation-memory"])
