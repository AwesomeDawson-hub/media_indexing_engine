"""Standardized error response handling."""

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

# Map status codes to error codes
_STATUS_TO_CODE = {
    400: "VALIDATION_ERROR",
    401: "AUTH_REQUIRED",
    404: "NOT_FOUND",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
}


def register_error_handlers(app: FastAPI) -> None:
    """Register global exception handlers for standardized error responses."""

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        error_code = _STATUS_TO_CODE.get(exc.status_code, "ERROR")
        content: dict[str, object] = {}

        # Allow routes to override error_code via detail dict
        detail = exc.detail
        if isinstance(detail, dict):
            error_code = detail.get("error_code", error_code)
            content = {
                key: value
                for key, value in detail.items()
                if key not in {"message", "error_code"}
            }
            detail = detail.get("message", str(detail))

        content.update({"detail": detail, "error_code": error_code})

        return JSONResponse(
            status_code=exc.status_code,
            content=content,
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "detail": "Invalid request data",
                "error_code": "VALIDATION_ERROR",
                "errors": exc.errors(),
            },
        )
