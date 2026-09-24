from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI

from app import __version__
from app.api.errors import install_exception_handlers
from app.api.routes import backtests, features, health, research, scanner
from app.core.logging import configure_logging, get_logger


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    logger = get_logger(__name__)
    logger.info("application_started", extra={"version": __version__})
    yield
    logger.info("application_stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Market Intelligence AI API",
        version=__version__,
        description="Quantitative research API. It does not provide investment advice.",
        lifespan=lifespan,
    )
    install_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(features.router)
    app.include_router(scanner.router)
    app.include_router(backtests.router)
    app.include_router(research.router)
    return app


app = create_app()
