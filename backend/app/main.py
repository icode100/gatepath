from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app import firebase_auth
from app.api import router as api_router
from app.auth_api import router as auth_router
from app.bootstrap import initialize_local_development_database
from app.config import settings
from app.database import AsyncSessionFactory, close_database
from app.identity import (
    IdentityPrincipal,
    issue_identity,
    set_identity_cookie,
    verify_identity,
)
from app.schemas import HealthResponse
from app.user_state import (
    UserStateAlreadySubmitted,
    UserStateError,
    UserStateNotFound,
    UserStatePayloadTooLarge,
    UserStateUnavailable,
)
from app.user_state.dependencies import get_user_state_repository


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
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


@app.exception_handler(UserStateError)
async def handle_user_state_error(
    _: Request,
    exc: UserStateError,
) -> JSONResponse:
    """Fail user-owned routes safely without leaking provider diagnostics."""

    if isinstance(exc, UserStateNotFound):
        status_code = status.HTTP_404_NOT_FOUND
        detail = "Session or attempt not found"
    elif isinstance(exc, UserStateAlreadySubmitted):
        status_code = status.HTTP_409_CONFLICT
        detail = "Session has already been submitted"
    elif isinstance(exc, UserStatePayloadTooLarge):
        status_code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
        detail = "The study record is too large to store safely"
    else:
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        detail = "User progress storage is temporarily unavailable"
    return JSONResponse(
        status_code=status_code,
        headers={"Cache-Control": "no-store"},
        content={"detail": detail},
    )


@app.middleware("http")
async def bind_anonymous_identity(request: Request, call_next):
    is_api_request = (
        request.url.path == settings.api_v1_prefix
        or request.url.path.startswith(f"{settings.api_v1_prefix}/")
    )
    if not is_api_request:
        return await call_next(request)
    configuration_issues = settings.hosted_configuration_issues
    if configuration_issues:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            headers={"Cache-Control": "no-store"},
            content={
                "detail": "Backend deployment configuration is incomplete",
                "configuration_issues": configuration_issues,
            },
        )
    guest_identity = verify_identity(
        request.cookies.get(settings.identity_cookie_name)
    )
    new_guest_token: str | None = None
    clear_firebase_cookie = False
    firebase_auth_verification_failure: str | None = None
    principal: IdentityPrincipal | None = None
    firebase_cookie = request.cookies.get(settings.firebase_session_cookie_name)
    if firebase_cookie:
        if not settings.firebase_auth_enabled:
            firebase_auth_verification_failure = "unavailable"
        elif settings.firebase_configuration_issues:
            firebase_auth_verification_failure = "unavailable"
        else:
            try:
                firebase_identity = (
                    await firebase_auth.verify_firebase_session_cookie(
                        firebase_cookie
                    )
                )
            except firebase_auth.FirebaseTokenInvalid:
                clear_firebase_cookie = True
                firebase_auth_verification_failure = "invalid"
            except firebase_auth.FirebaseAuthUnavailable:
                # Public curriculum remains readable, but dependencies guarding
                # owned data will return 503 instead of writing as a guest.
                firebase_auth_verification_failure = "unavailable"
            else:
                principal = IdentityPrincipal(
                    user_key=firebase_identity.user_key,
                    mode="firebase",
                    guest_user_key=guest_identity,
                    firebase_uid=firebase_identity.uid,
                    claims=firebase_identity.claims,
                )
    if principal is None:
        if guest_identity is None:
            guest_identity, new_guest_token = issue_identity()
        principal = IdentityPrincipal(
            user_key=guest_identity,
            mode="guest",
            guest_user_key=guest_identity,
        )
    request.state.principal = principal
    request.state.user_key = principal.user_key
    request.state.guest_user_key = principal.guest_user_key
    request.state.firebase_uid = principal.firebase_uid
    request.state.firebase_auth_verification_failure = (
        firebase_auth_verification_failure
    )
    response = await call_next(request)
    if new_guest_token is not None and not getattr(
        request.state, "suppress_guest_cookie", False
    ):
        set_identity_cookie(response, new_guest_token)
    if clear_firebase_cookie and not getattr(
        request.state, "firebase_session_replaced", False
    ):
        firebase_auth.clear_firebase_session_cookie(response)
    return response


app.include_router(api_router, prefix=settings.api_v1_prefix)
app.include_router(auth_router, prefix=settings.api_v1_prefix)


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
    response.headers["Cache-Control"] = "no-store"
    configuration_issues = settings.hosted_configuration_issues
    firebase_issues = settings.firebase_configuration_issues
    user_state_issues = list(
        dict.fromkeys(
            [
                *settings.user_state_configuration_issues,
                *settings.user_state_migration_configuration_issues,
            ]
        )
    )
    authentication_status = (
        "guest_only"
        if not settings.firebase_auth_enabled
        else "invalid"
        if firebase_issues
        else "enabled"
    )
    if configuration_issues:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(
            status="degraded",
            service=settings.app_name,
            version=settings.app_version,
            database="not_checked",
            configuration="invalid",
            configuration_issues=configuration_issues,
            authentication=authentication_status,
            authentication_issues=firebase_issues,
            user_state_backend=settings.user_state_backend,
            user_state="not_checked",
            user_state_issues=user_state_issues,
        )
    database_status = "ok"
    try:
        async with AsyncSessionFactory() as session:
            await session.execute(select(1))
    except Exception:
        database_status = "unavailable"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    user_state_status = "postgres"
    if settings.user_state_maintenance:
        user_state_status = "maintenance"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    elif settings.user_state_backend == "firestore":
        if user_state_issues:
            user_state_status = "invalid"
        else:
            try:
                repository = get_user_state_repository()
                if repository is None:  # Defensive: the selected backend is Firestore.
                    raise UserStateUnavailable("Firestore user state is unavailable")
                await repository.healthcheck()
            except UserStateError:
                user_state_status = "unavailable"
            else:
                user_state_status = "ok"

    if firebase_issues or user_state_issues or user_state_status == "unavailable":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(
        status=(
            "ok"
            if (
                database_status == "ok"
                and not firebase_issues
                and not user_state_issues
                and user_state_status in {"postgres", "ok"}
            )
            else "degraded"
        ),
        service=settings.app_name,
        version=settings.app_version,
        database=database_status,
        authentication=authentication_status,
        authentication_issues=firebase_issues,
        user_state_backend=settings.user_state_backend,
        user_state=user_state_status,
        user_state_issues=user_state_issues,
    )
