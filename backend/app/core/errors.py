"""Typed application errors and the handlers that render them.

Every failure the client can provoke maps to an ``AppError`` subclass carrying a
stable machine-readable ``code``, so the frontend can branch on the failure kind
instead of pattern-matching English prose.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.logging_config import request_id_var

LOG = logging.getLogger(__name__)


class AppError(Exception):
    """Base class for all deliberately-raised application failures."""

    code = "internal_error"
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    message = "An unexpected error occurred."

    def __init__(self, message: str | None = None, **details: Any) -> None:
        self.message = message or self.message
        self.details = details
        super().__init__(self.message)

    def to_payload(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
                "request_id": request_id_var.get(),
            }
        }


class InvalidCSVError(AppError):
    code = "invalid_csv"
    status_code = status.HTTP_400_BAD_REQUEST
    message = "The uploaded file could not be parsed as CSV."


class SchemaError(AppError):
    code = "schema_error"
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    message = "The dataset is missing required columns."


class ProductNotFoundError(AppError):
    code = "product_not_found"
    status_code = status.HTTP_404_NOT_FOUND
    message = "No rows found for the requested product."


class InsufficientDataError(AppError):
    """Raised instead of padding a short series with invented history."""

    code = "insufficient_data"
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    message = "The series is too short to support an honest forecast."


class DatasetNotFoundError(AppError):
    code = "dataset_not_found"
    status_code = status.HTTP_404_NOT_FOUND
    message = "The requested dataset does not exist."


class ModelUnavailableError(AppError):
    code = "model_unavailable"
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    message = "The requested forecasting model could not be loaded."


class JobNotFoundError(AppError):
    code = "job_not_found"
    status_code = status.HTTP_404_NOT_FOUND
    message = "The requested job does not exist."


class UploadTooLargeError(AppError):
    code = "upload_too_large"
    status_code = status.HTTP_413_CONTENT_TOO_LARGE
    message = "The uploaded file exceeds the maximum permitted size."


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        # Client mistakes are expected traffic, not incidents: log them quietly.
        log = LOG.warning if exc.status_code < 500 else LOG.exception
        log("%s: %s", exc.code, exc.message, extra={"details": exc.details})
        return JSONResponse(status_code=exc.status_code, content=exc.to_payload())

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Request parameters failed validation.",
                    "details": {"errors": exc.errors()},
                    "request_id": request_id_var.get(),
                }
            },
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        LOG.exception("Unhandled exception: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=AppError(
                "An unexpected internal error occurred. Check the server logs."
            ).to_payload(),
        )
