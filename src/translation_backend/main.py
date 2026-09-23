from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from translation_backend.app.api.modules.auth.routes import register_auth_exception_handler
from translation_backend.app.api.modules.router import api_router
from translation_backend.app.core.config import app_settings, database_settings
from translation_backend.app.core.database import TORTOISE_ORM
from translation_backend.app.core.logging import configure_logging, install_request_logging
from tortoise import Tortoise


@asynccontextmanager
async def lifespan(app: FastAPI):
    await Tortoise.init(config=TORTOISE_ORM)
    if database_settings.redis_launch is True:
        from translation_backend.app.core.redis import close_redis, init_redis

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
install_request_logging(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # frontend
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, tags=["API Starter"])
register_auth_exception_handler(app)

if __name__ == '__main__':
    uvicorn.run(app, host="127.0.0.1", port=8000, workers=2, reload=True)
