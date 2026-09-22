from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.responses import Response

from app.api import (
    admin,
    auth,
    demo,
    evidence,
    health,
    notifications,
    opportunities,
    performance,
    watchlists,
)
from app.api.company_profiles import router as company_profiles_router
from app.api.evaluation import router as evaluation_router
from app.config import get_settings
from app.observability import REQUEST_ID_HEADER, configure_json_logging

settings = get_settings()
configure_json_logging()
logger = logging.getLogger("procure_delta.http")

app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
    allow_headers=["Content-Type", "X-CSRF-Token"],
)
app.include_router(company_profiles_router)
app.include_router(evaluation_router)
for router in (
    auth.router,
    demo.router,
    evidence.router,
    health.router,
    opportunities.router,
    performance.router,
    watchlists.router,
    notifications.router,
    admin.router,
):
    app.include_router(router)


def _request_id(request: Request) -> str:
    request_id = getattr(request.state, "request_id", None)
    if isinstance(request_id, str) and request_id:
        return request_id
    request_id = uuid4().hex
    request.state.request_id = request_id
    return request_id


@app.middleware("http")
async def observe_request(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    request_id = _request_id(request)
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:
        logger.error(
            "http_request_failed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": 500,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                "error_type": type(exc).__name__,
            },
        )
        raise

    response.headers[REQUEST_ID_HEADER] = request_id
    logger.info(
        "http_request_completed",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        },
    )
    return response


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Never echo rejected credentials, URLs, or untrusted values in API errors.
    return JSONResponse(
        status_code=422,
        content={
            "detail": [
                {"loc": error["loc"], "type": error["type"], "msg": "Invalid request value"}
                for error in exc.errors()
            ]
        },
    )


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    # The middleware records only the exception class, never its message or request payload.
    return JSONResponse(
        status_code=500,
        content={"detail": "Request could not be completed"},
        headers={REQUEST_ID_HEADER: _request_id(request)},
    )


@app.get("/health/live", tags=["health"])
async def health_live() -> dict[str, str]:
    return {"status": "ok"}
