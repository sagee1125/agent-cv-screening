# Defines stable candidate matching API errors and their JSON responses.
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse

from app.config import settings


class MatchingAPIError(Exception):
    """Carry a stable matching error code and HTTP response metadata."""

    # Initialize one machine-readable candidate matching API error.
    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        status_code: int,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable
        self.details = details or {}


# Render candidate matching failures with the PRD error envelope.
async def matching_api_error_handler(request: Request, exc: MatchingAPIError) -> JSONResponse:
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "version": settings.app_version,
            "schema_version": settings.matching_schema_version,
            "error_code": exc.error_code,
            "message": exc.message,
            "module": "candidate_matching",
            "retryable": exc.retryable,
            "request_id": request_id,
            "details": exc.details,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )
