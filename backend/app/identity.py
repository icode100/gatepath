from __future__ import annotations

import base64
import hashlib
import hmac
import uuid

from fastapi import HTTPException, Request

from app.config import settings


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


def current_user_key(request: Request) -> str:
    identity = getattr(request.state, "user_key", None)
    if not identity:
        raise HTTPException(status_code=500, detail="Anonymous identity is unavailable")
    return str(identity)
