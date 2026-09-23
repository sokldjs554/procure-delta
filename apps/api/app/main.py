from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import (
    admin,
    auth,
    contract_process,
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

settings = get_settings()
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
    contract_process.router,
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
