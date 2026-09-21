import logging
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

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
from app.observability import configure_json_logging

logger = logging.getLogger("procure_delta.api")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_json_logging()
    yield


settings = get_settings()
app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
    allow_headers=["Content-Type", "X-CSRF-Token"],
)


@app.middleware("http")
async def request_observability(request: Request, call_next):
    request_id = uuid4().hex
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.error(
            "api_request",
            extra={
                "request_id": request_id,
                "stage": "http",
                "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                "result": "exception",
                "status": 500,
            },
        )
        raise
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "api_request",
        extra={
            "request_id": request_id,
            "stage": "http",
            "duration_ms": round((time.perf_counter() - started) * 1000, 3),
            "result": "success" if response.status_code < 400 else "error",
            "status": response.status_code,
        },
    )
    return response
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
    return JSONResponse(status_code=500, content={"detail": "Request could not be completed"})


@app.get("/health/live", tags=["health"])
async def health_live() -> dict[str, str]:
    return {"status": "ok"}
