from __future__ import annotations

import base64
import hashlib
import hmac
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from fastapi import HTTPException, Request, Response

from app.config import settings


ANONYMOUS_IDENTITY_MAX_AGE_SECONDS = 60 * 60 * 24 * 365


@dataclass(frozen=True)
class IdentityPrincipal:
    user_key: str
    mode: Literal["guest", "firebase"]
    guest_user_key: str | None = None
    firebase_uid: str | None = None
    claims: dict[str, Any] = field(default_factory=dict)


def _signature(identity: str) -> str:
    digest = hmac.new(
        settings.anonymous_identity_secret.encode("utf-8"),
        identity.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def issue_identity() -> tuple[str, str]:
    identity = f"anon-{uuid.uuid4().hex}"
    return identity, f"v1.{identity}.{_signature(identity)}"


def verify_identity(token: str | None) -> str | None:
    if not token:
        return None
    try:
        version, identity, signature = token.split(".", 2)
    except ValueError:
        return None
    if version != "v1" or not identity.startswith("anon-") or len(identity) != 37:
        return None
    if not hmac.compare_digest(signature, _signature(identity)):
        return None
    return identity


def set_identity_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.identity_cookie_name,
        value=token,
        httponly=True,
        secure=settings.secure_identity_cookie,
        samesite="lax",
        max_age=ANONYMOUS_IDENTITY_MAX_AGE_SECONDS,
        path="/",
    )


def clear_identity_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.identity_cookie_name,
        httponly=True,
        secure=settings.secure_identity_cookie,
        samesite="lax",
        path="/",
    )


def current_principal(request: Request) -> IdentityPrincipal:
    verification_failure = getattr(
        request.state, "firebase_auth_verification_failure", None
    )
    if verification_failure == "invalid":
        raise HTTPException(
            status_code=401,
            detail="Firebase session is invalid or expired",
        )
    if verification_failure == "unavailable":
        raise HTTPException(
            status_code=503,
            detail="Firebase authentication is temporarily unavailable",
        )
    principal = getattr(request.state, "principal", None)
    if not isinstance(principal, IdentityPrincipal):
        raise HTTPException(status_code=500, detail="Identity is unavailable")
    return principal


def provisional_principal(request: Request) -> IdentityPrincipal:
    """Return middleware identity without accepting it for owned operations.

    Session exchange and logout need to recover from an invalid or temporarily
    unverifiable Firebase cookie. Callers using this helper must not authorize
    access with the returned guest fallback while a verification failure is set.
    """

    principal = getattr(request.state, "principal", None)
    if not isinstance(principal, IdentityPrincipal):
        raise HTTPException(status_code=500, detail="Identity is unavailable")
    return principal


def current_user_key(request: Request) -> str:
    return current_principal(request).user_key
