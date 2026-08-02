from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass
from datetime import timedelta
from importlib import import_module
from typing import Any, Mapping

from fastapi import Response
from starlette.concurrency import run_in_threadpool

from app.config import settings


FIREBASE_SESSION_MAX_AGE_MIN_SECONDS = 5 * 60
FIREBASE_SESSION_MAX_AGE_MAX_SECONDS = 60 * 60 * 24 * 14
_ADMIN_APP_NAME = "gatepath"
_ADMIN_APP: Any | None = None
_ADMIN_APP_CONFIGURATION_KEY: tuple[str, str] | None = None
_ADMIN_APP_LOCK = threading.Lock()


class FirebaseAuthError(Exception):
    """Base class for safe, user-facing Firebase failure categories."""


class FirebaseAuthUnavailable(FirebaseAuthError):
    """The Firebase Admin service cannot currently process a request."""


class FirebaseTokenInvalid(FirebaseAuthError):
    """A Firebase ID token or session cookie is invalid or no longer valid."""


class FirebaseRecentSignInRequired(FirebaseTokenInvalid):
    """The ID token was not minted recently enough for cookie exchange."""


@dataclass(frozen=True)
class FirebaseIdentity:
    uid: str
    user_key: str
    claims: dict[str, Any]


@dataclass(frozen=True)
class FirebaseSession:
    cookie: str
    identity: FirebaseIdentity


def firebase_owner_key(uid: str, project_id: str | None = None) -> str:
    """Build the stable, project-scoped owner key stored in progress rows."""

    normalized_uid = uid.strip()
    normalized_project = (project_id or settings.firebase_project_id).strip()
    if not normalized_uid or not normalized_project:
        raise ValueError("Firebase UID and project ID are required")
    digest = hashlib.sha256(
        f"{normalized_project}\0{normalized_uid}".encode("utf-8")
    ).hexdigest()
    return f"fb-v1-{digest}"


def _configuration_key() -> tuple[str, str]:
    credential_source = settings.firebase_service_account_json or "adc"
    credential_fingerprint = hashlib.sha256(
        credential_source.encode("utf-8")
    ).hexdigest()
    return settings.firebase_project_id.strip(), credential_fingerprint


def _firebase_modules() -> tuple[Any, Any, Any]:
    try:
        firebase_admin = import_module("firebase_admin")
        auth = import_module("firebase_admin.auth")
        credentials = import_module("firebase_admin.credentials")
    except (ImportError, ModuleNotFoundError) as exc:
        raise FirebaseAuthUnavailable("Firebase Admin is unavailable") from exc
    return firebase_admin, auth, credentials


def _admin_app() -> tuple[Any, Any]:
    global _ADMIN_APP, _ADMIN_APP_CONFIGURATION_KEY

    issues = settings.firebase_configuration_issues
    if not settings.firebase_auth_enabled or issues:
        raise FirebaseAuthUnavailable("Firebase authentication is not configured")

    configuration_key = _configuration_key()
    if _ADMIN_APP is not None:
        if _ADMIN_APP_CONFIGURATION_KEY != configuration_key:
            raise FirebaseAuthUnavailable("Firebase configuration changed at runtime")
        _, auth, _ = _firebase_modules()
        return _ADMIN_APP, auth

    with _ADMIN_APP_LOCK:
        if _ADMIN_APP is not None:
            if _ADMIN_APP_CONFIGURATION_KEY != configuration_key:
                raise FirebaseAuthUnavailable(
                    "Firebase configuration changed at runtime"
                )
            _, auth, _ = _firebase_modules()
            return _ADMIN_APP, auth

        firebase_admin, auth, credentials = _firebase_modules()
        try:
            if settings.firebase_service_account_json:
                service_account = json.loads(settings.firebase_service_account_json)
                if not isinstance(service_account, dict):
                    raise ValueError("Service account must be a JSON object")
                credential_project = str(service_account.get("project_id", "")).strip()
                if (
                    credential_project
                    and credential_project != settings.firebase_project_id.strip()
                ):
                    raise ValueError("Service account project does not match")
                credential = credentials.Certificate(service_account)
            else:
                credential = credentials.ApplicationDefault()

            try:
                app = firebase_admin.get_app(_ADMIN_APP_NAME)
            except ValueError:
                app = firebase_admin.initialize_app(
                    credential,
                    {"projectId": settings.firebase_project_id.strip()},
                    name=_ADMIN_APP_NAME,
                )
        except Exception as exc:
            raise FirebaseAuthUnavailable(
                "Firebase Admin could not be initialized"
            ) from exc

        _ADMIN_APP = app
        _ADMIN_APP_CONFIGURATION_KEY = configuration_key
        return app, auth


_INVALID_TOKEN_ERROR_NAMES = {
    "ExpiredIdTokenError",
    "ExpiredSessionCookieError",
    "InvalidIdTokenError",
    "InvalidSessionCookieError",
    "RevokedIdTokenError",
    "RevokedSessionCookieError",
    "UserDisabledError",
}


def _is_invalid_token_error(exc: Exception) -> bool:
    return any(
        exception_type.__name__ in _INVALID_TOKEN_ERROR_NAMES
        for exception_type in type(exc).__mro__
    )


def _identity_from_claims(claims: Mapping[str, Any]) -> FirebaseIdentity:
    raw_uid = claims.get("uid") or claims.get("sub")
    uid = raw_uid.strip() if isinstance(raw_uid, str) else ""
    if not uid:
        raise FirebaseTokenInvalid("Firebase token has no subject")
    return FirebaseIdentity(
        uid=uid,
        user_key=firebase_owner_key(uid),
        claims=dict(claims),
    )


def _verify_session_cookie_sync(session_cookie: str) -> FirebaseIdentity:
    app, auth = _admin_app()
    try:
        claims = auth.verify_session_cookie(
            session_cookie,
            check_revoked=settings.firebase_check_revoked,
            app=app,
        )
    except Exception as exc:
        if isinstance(exc, ValueError) or _is_invalid_token_error(exc):
            raise FirebaseTokenInvalid("Firebase session cookie is invalid") from exc
        raise FirebaseAuthUnavailable(
            "Firebase session verification is unavailable"
        ) from exc
    if not isinstance(claims, Mapping):
        raise FirebaseTokenInvalid("Firebase session claims are invalid")
    return _identity_from_claims(claims)


async def verify_firebase_session_cookie(
    session_cookie: str,
) -> FirebaseIdentity:
    if not session_cookie:
        raise FirebaseTokenInvalid("Firebase session cookie is missing")
    return await run_in_threadpool(_verify_session_cookie_sync, session_cookie)


def _create_session_cookie_sync(id_token: str) -> FirebaseSession:
    app, auth = _admin_app()
    normalized_token = id_token.strip()
    if not normalized_token:
        raise FirebaseTokenInvalid("Firebase ID token is missing")
    try:
        claims = auth.verify_id_token(
            normalized_token,
            check_revoked=True,
            app=app,
        )
    except Exception as exc:
        if isinstance(exc, ValueError) or _is_invalid_token_error(exc):
            raise FirebaseTokenInvalid("Firebase ID token is invalid") from exc
        raise FirebaseAuthUnavailable(
            "Firebase ID token verification is unavailable"
        ) from exc
    if not isinstance(claims, Mapping):
        raise FirebaseTokenInvalid("Firebase ID token claims are invalid")

    identity = _identity_from_claims(claims)
    auth_time = claims.get("auth_time")
    if isinstance(auth_time, bool) or not isinstance(auth_time, (int, float)):
        raise FirebaseRecentSignInRequired("Recent Firebase sign-in is required")
    token_age = time.time() - float(auth_time)
    if token_age < -60 or token_age > settings.firebase_recent_auth_seconds:
        raise FirebaseRecentSignInRequired("Recent Firebase sign-in is required")

    max_age = settings.firebase_session_max_age_seconds
    if not FIREBASE_SESSION_MAX_AGE_MIN_SECONDS <= max_age <= FIREBASE_SESSION_MAX_AGE_MAX_SECONDS:
        raise FirebaseAuthUnavailable("Firebase session duration is invalid")
    try:
        cookie = auth.create_session_cookie(
            normalized_token,
            expires_in=timedelta(seconds=max_age),
            app=app,
        )
    except Exception as exc:
        if isinstance(exc, ValueError) or _is_invalid_token_error(exc):
            raise FirebaseTokenInvalid("Firebase ID token is invalid") from exc
        raise FirebaseAuthUnavailable(
            "Firebase session creation is unavailable"
        ) from exc
    if isinstance(cookie, bytes):
        cookie = cookie.decode("utf-8")
    if not isinstance(cookie, str) or not cookie:
        raise FirebaseAuthUnavailable("Firebase returned an invalid session cookie")
    return FirebaseSession(cookie=cookie, identity=identity)


async def create_firebase_session(id_token: str) -> FirebaseSession:
    return await run_in_threadpool(_create_session_cookie_sync, id_token)


def set_firebase_session_cookie(response: Response, cookie: str) -> None:
    response.set_cookie(
        key=settings.firebase_session_cookie_name,
        value=cookie,
        httponly=True,
        secure=settings.secure_identity_cookie,
        samesite="lax",
        max_age=settings.firebase_session_max_age_seconds,
        path="/",
    )


def clear_firebase_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.firebase_session_cookie_name,
        httponly=True,
        secure=settings.secure_identity_cookie,
        samesite="lax",
        path="/",
    )
