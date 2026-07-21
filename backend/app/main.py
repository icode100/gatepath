from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.api import router as api_router
from app.config import settings
from app.database import AsyncSessionFactory, close_database, create_database_schema
from app.schemas import HealthResponse
from app.seed import seed_database


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if settings.auto_create_db:
        await create_database_schema()
    if settings.seed_data:
        async with AsyncSessionFactory() as session:
            await seed_database(session)
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
async def health() -> HealthResponse:
    database_status = "ok"
    try:
        async with AsyncSessionFactory() as session:
            await session.execute(select(1))
    except Exception:
        database_status = "unavailable"
    return HealthResponse(
        status="ok" if database_status == "ok" else "degraded",
        service=settings.app_name,
        version=settings.app_version,
        database=database_status,
    )
