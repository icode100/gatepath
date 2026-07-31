from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.api import router as api_router
from app.bootstrap import initialize_local_development_database
from app.config import DEFAULT_ANONYMOUS_IDENTITY_SECRET, settings
from app.database import AsyncSessionFactory, close_database
from app.identity import issue_identity, verify_identity
from app.schemas import HealthResponse


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    hosted = settings.is_production or settings.is_serverless_runtime
    if (
        hosted
        and settings.anonymous_identity_secret == DEFAULT_ANONYMOUS_IDENTITY_SECRET
    ):
        raise RuntimeError(
            "ANONYMOUS_IDENTITY_SECRET must be changed in hosted environments"
        )
    if hosted and settings.async_database_url.startswith("sqlite"):
        raise RuntimeError(
            "DATABASE_URL must point to PostgreSQL in hosted environments; "
            "SQLite is not persistent on Vercel"
        )
    if settings.should_bootstrap_on_startup:
        await initialize_local_development_database()
    yield
    await close_database()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "Syllabus-bounded question bank, revision notes, practice sessions, "
        "mock tests and progress tracking for GATE CSE 2027."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def bind_anonymous_identity(request: Request, call_next):
    if not request.url.path.startswith(settings.api_v1_prefix):
        return await call_next(request)
    identity = verify_identity(request.cookies.get(settings.identity_cookie_name))
    new_token: str | None = None
    if identity is None:
        identity, new_token = issue_identity()
    request.state.user_key = identity
    response = await call_next(request)
    if new_token is not None:
        response.set_cookie(
            key=settings.identity_cookie_name,
            value=new_token,
            httponly=True,
            secure=settings.secure_identity_cookie,
            samesite="lax",
            max_age=60 * 60 * 24 * 365,
            path="/",
        )
    return response


app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {
        "service": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health", response_model=HealthResponse, tags=["Operations"])
async def health(response: Response) -> HealthResponse:
    database_status = "ok"
    try:
        async with AsyncSessionFactory() as session:
            await session.execute(select(1))
    except Exception:
        database_status = "unavailable"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(
        status="ok" if database_status == "ok" else "degraded",
        service=settings.app_name,
        version=settings.app_version,
        database=database_status,
    )
