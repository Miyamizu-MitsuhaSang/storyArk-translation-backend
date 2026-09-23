from fastapi import APIRouter

from app.core.config import app_settings
from app.core.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service=app_settings.app_name)
