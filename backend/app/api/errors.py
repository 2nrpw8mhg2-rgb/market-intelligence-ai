from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.logging import get_logger

logger = get_logger(__name__)


class ApplicationError(Exception):
    def __init__(self, message: str, *, code: str, status_code: int = 400) -> None:
        self.message = message
        self.code = code
        self.status_code = status_code
        super().__init__(message)


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApplicationError)
    async def handle_application_error(
        _: Request, exc: ApplicationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_exception", extra={"error_type": type(exc).__name__})
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "An unexpected error occurred.",
                }
            },
        )
