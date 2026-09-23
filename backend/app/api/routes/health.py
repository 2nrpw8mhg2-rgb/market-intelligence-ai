from fastapi import APIRouter

from app import __version__
from app.core.config import get_settings
from app.schemas.health import HealthResponse

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        service="market-intelligence-api",
        version=__version__,
        environment=settings.environment,
    )
