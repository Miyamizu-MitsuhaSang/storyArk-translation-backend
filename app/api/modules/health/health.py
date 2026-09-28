from fastapi import APIRouter

from ....core.config import app_settings
from ....core.schemas import HealthResponse

health_router = APIRouter(tags=["health"])


@health_router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service=app_settings.app_name)
