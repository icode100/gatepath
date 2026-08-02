from __future__ import annotations

import asyncio
import secrets
from contextlib import asynccontextmanager
from typing import AsyncIterator, Literal

from fastapi import FastAPI, Header, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import text

from app.config import settings
from app.database import AsyncSessionFactory, close_database
from app.user_state import UserStateError
from scripts.migrate_user_state_to_firestore import (
    MigrationError,
    MigrationReport,
    execute_migration,
)


MIGRATION_CONFIRMATION = "MIGRATE_POSTGRES_USER_STATE_TO_FIRESTORE"
MIGRATION_LOCK_ID = 0x4741544550415448
MIGRATION_TIMEOUT_SECONDS = 240


class MigrationRequest(BaseModel):
    mode: Literal["dry-run", "apply", "verify-only"]
    confirmation: str | None = Field(default=None, max_length=128)
    source_digest: str | None = Field(default=None, max_length=64)


class MigrationBusy(RuntimeError):
    """Another production migration invocation owns the database lock."""


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await close_database()


app = FastAPI(
    title="Gatepath User-State Migration",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)


@app.middleware("http")
async def secure_maintenance_responses(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; connect-src 'self'; form-action 'self'; "
        "frame-ancestors 'none'; script-src 'unsafe-inline'; "
        "style-src 'unsafe-inline'; base-uri 'none'"
    )
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response


def _configured_secret() -> str | None:
    if not settings.user_state_migration_enabled:
        return None
    if settings.user_state_migration_configuration_issues:
        return None
    if settings.user_state_migration_secret is None:
        return None
    return settings.user_state_migration_secret.get_secret_value()


def _safe_error(status_code: int, code: str) -> JSONResponse:
    headers = {"Cache-Control": "no-store"}
    if status_code == status.HTTP_401_UNAUTHORIZED:
        headers["WWW-Authenticate"] = "Bearer"
    return JSONResponse(
        status_code=status_code,
        headers=headers,
        content={"status": "error", "code": code},
    )


def _authorize(authorization: str | None) -> JSONResponse | None:
    expected = _configured_secret()
    if expected is None:
        return _safe_error(status.HTTP_404_NOT_FOUND, "NOT_FOUND")
    scheme, separator, candidate = (authorization or "").partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not candidate:
        return _safe_error(status.HTTP_401_UNAUTHORIZED, "UNAUTHORIZED")
    if not secrets.compare_digest(candidate.encode(), expected.encode()):
        return _safe_error(status.HTTP_401_UNAUTHORIZED, "UNAUTHORIZED")
    return None


async def _execute_with_advisory_lock(
    payload: MigrationRequest,
) -> MigrationReport:
    async with AsyncSessionFactory() as lock_session:
        async with lock_session.begin():
            acquired = await lock_session.scalar(
                text("SELECT pg_try_advisory_xact_lock(:lock_id)"),
                {"lock_id": MIGRATION_LOCK_ID},
            )
            if not acquired:
                raise MigrationBusy
            async with asyncio.timeout(MIGRATION_TIMEOUT_SECONDS):
                return await execute_migration(
                    payload.mode,
                    expected_source_digest=(
                        payload.source_digest if payload.mode == "apply" else None
                    ),
                )


CONTROL_PAGE = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Gatepath user-state migration</title>
  <style>
    body {{ color:#e8f0eb; background:#0d1712; font:16px system-ui; margin:0; }}
    main {{ max-width:760px; margin:5vh auto; padding:24px; }}
    form {{ display:grid; gap:14px; padding:22px; border:1px solid #365344; border-radius:14px; }}
    label {{ display:grid; gap:6px; }}
    input,select,button {{ font:inherit; padding:10px; border-radius:8px; border:1px solid #4d705e; }}
    input,select {{ color:#e8f0eb; background:#12241b; }}
    button {{ color:#07110c; background:#80d6aa; cursor:pointer; font-weight:700; }}
    pre {{ white-space:pre-wrap; overflow-wrap:anywhere; padding:18px; background:#08100c; border-radius:10px; }}
  </style>
</head>
<body><main>
  <h1>Gatepath user-state migration</h1>
  <p>Run dry-run, copy its source digest into Apply, then run verify-only.</p>
  <form id="migration-form">
    <label>One-time bearer secret<input id="token" type="password" autocomplete="off" required></label>
    <label>Mode<select id="mode">
      <option value="dry-run">dry-run</option>
      <option value="apply">apply</option>
      <option value="verify-only">verify-only</option>
    </select></label>
    <label>Reviewed source digest<input id="digest" maxlength="64" autocomplete="off"></label>
    <label>Apply confirmation<input id="confirmation" maxlength="128" autocomplete="off" placeholder="{MIGRATION_CONFIRMATION}"></label>
    <button type="submit">Run migration operation</button>
  </form>
  <pre id="result" aria-live="polite">Ready.</pre>
  <script>
    const form = document.getElementById('migration-form');
    form.addEventListener('submit', async (event) => {{
      event.preventDefault();
      const token = document.getElementById('token');
      const result = document.getElementById('result');
      result.textContent = 'Running...';
      try {{
        const response = await fetch(location.pathname, {{
          method: 'POST',
          headers: {{
            'Authorization': 'Bearer ' + token.value,
            'Content-Type': 'application/json'
          }},
          body: JSON.stringify({{
            mode: document.getElementById('mode').value,
            source_digest: document.getElementById('digest').value || null,
            confirmation: document.getElementById('confirmation').value || null
          }})
        }});
        const body = await response.json();
        result.textContent = JSON.stringify(body, null, 2);
      }} catch (_) {{
        result.textContent = JSON.stringify({{status:'error',code:'REQUEST_FAILED'}}, null, 2);
      }} finally {{ token.value = ''; }}
    }});
  </script>
</main></body></html>"""


@app.get(
    "/internal/maintenance/user-state-migration",
    include_in_schema=False,
)
async def migration_control_page() -> Response:
    if _configured_secret() is None:
        return _safe_error(status.HTTP_404_NOT_FOUND, "NOT_FOUND")
    return HTMLResponse(CONTROL_PAGE, headers={"Cache-Control": "no-store"})


@app.post(
    "/internal/maintenance/user-state-migration",
    include_in_schema=False,
)
async def run_user_state_migration(
    request: Request,
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    authorization_error = _authorize(authorization)
    if authorization_error is not None:
        return authorization_error
    try:
        payload = MigrationRequest.model_validate(await request.json())
    except (TypeError, ValueError, ValidationError):
        return _safe_error(status.HTTP_400_BAD_REQUEST, "INVALID_REQUEST")
    if payload.mode == "apply":
        if settings.user_state_backend != "postgres":
            return _safe_error(
                status.HTTP_409_CONFLICT,
                "APPLY_REQUIRES_POSTGRES_SOURCE",
            )
        if payload.confirmation != MIGRATION_CONFIRMATION:
            return _safe_error(
                status.HTTP_400_BAD_REQUEST,
                "APPLY_CONFIRMATION_REQUIRED",
            )
        digest = (payload.source_digest or "").lower()
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            return _safe_error(
                status.HTTP_400_BAD_REQUEST,
                "REVIEWED_SOURCE_DIGEST_REQUIRED",
            )
    try:
        report = await _execute_with_advisory_lock(payload)
    except MigrationBusy:
        return _safe_error(status.HTTP_409_CONFLICT, "MIGRATION_ALREADY_RUNNING")
    except TimeoutError:
        return _safe_error(status.HTTP_503_SERVICE_UNAVAILABLE, "MIGRATION_TIMED_OUT")
    except MigrationError:
        return _safe_error(status.HTTP_409_CONFLICT, "MIGRATION_PRECONDITION_FAILED")
    except UserStateError:
        return _safe_error(status.HTTP_503_SERVICE_UNAVAILABLE, "USER_STATE_UNAVAILABLE")
    except Exception:
        return _safe_error(status.HTTP_503_SERVICE_UNAVAILABLE, "MIGRATION_FAILED")
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        headers={"Cache-Control": "no-store"},
        content={"status": "ok", "report": report.public_dict()},
    )
