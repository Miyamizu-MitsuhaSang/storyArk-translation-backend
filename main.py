from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

try:
    from .app.api.modules.auth.routes import register_auth_exception_handler
    from .app.api.modules.auth.api_key.routes import register_api_key_exception_handler
    from .app.api.modules.health import health
    from .app.api.modules.project.routes import register_project_exception_handler
    from .app.api.modules.project.document.routes import register_document_exception_handler
    from .app.api.modules.project.translation_settings.routes import register_translation_settings_exception_handler
    from .app.api.modules.project.translation_task.routes import register_translation_task_exception_handler
    from .app.api.modules.analytics.routes import register_analytics_exception_handler
    from .app.api.shared.errors import register_shared_exception_handlers
    from .app.api.router import api_router
    from .app.core.config import app_settings
    from .app.core.database import TORTOISE_ORM
    from .app.core.logging import configure_logging, install_request_logging
    from .app.core.security import install_api_key_transport_guard
except ImportError:
    from app.api.modules.auth.routes import register_auth_exception_handler
    from app.api.modules.auth.api_key.routes import register_api_key_exception_handler
    from app.api.modules.health import health
    from app.api.modules.project.routes import register_project_exception_handler
    from app.api.modules.project.document.routes import register_document_exception_handler
    from app.api.modules.project.translation_settings.routes import register_translation_settings_exception_handler
    from app.api.modules.project.translation_task.routes import register_translation_task_exception_handler
    from app.api.modules.analytics.routes import register_analytics_exception_handler
    from app.api.shared.errors import register_shared_exception_handlers
    from app.api.router import api_router
    from app.core.config import app_settings
    from app.core.database import TORTOISE_ORM
    from app.core.logging import configure_logging, install_request_logging
    from app.core.security import install_api_key_transport_guard
from tortoise import Tortoise


@asynccontextmanager
async def lifespan(app: FastAPI):
    await Tortoise.init(config=TORTOISE_ORM, _enable_global_fallback=True)
    if (
        app_settings.redis_enabled
        and (app_settings.tm_cache_enabled or app_settings.idempotency_redis_enabled)
    ):
        try:
            from .app.core.redis import close_redis, init_redis
        except ImportError:
            from app.core.redis import close_redis, init_redis

        app.state.redis = await init_redis()
    else:
        app.state.redis = None
    try:
        yield
    finally:
        if app.state.redis is not None:
            await close_redis()
        await Tortoise.close_connections()


configure_logging(app_settings.log_level, app_settings.log_file_path)

app = FastAPI(
    title=app_settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)
install_api_key_transport_guard(app, path=f"{app_settings.api_prefix}/auth/me/api-keys")
install_request_logging(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # frontend
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, tags=["API Starter"])
app.include_router(health.health_router)

# 注册认证模块异常处理器，将 AuthError 转换为统一的认证错误响应。
register_auth_exception_handler(app)
register_api_key_exception_handler(app)
# 注册项目模块异常处理器，将 ProjectError 转换为统一的项目错误响应。
register_project_exception_handler(app)
register_document_exception_handler(app)
register_shared_exception_handlers(app)
register_translation_settings_exception_handler(app)
register_translation_task_exception_handler(app)
register_analytics_exception_handler(app)

if __name__ == '__main__':
    uvicorn.run(app, host="127.0.0.1", port=8000, workers=2, reload=True)
