from __future__ import annotations

import secrets

from fastapi import HTTPException, Request, Response, status

from app.config import settings


CSRF_COOKIE_MAX_AGE_SECONDS = 60 * 60


def set_csrf_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.firebase_csrf_cookie_name,
        value=token,
        httponly=False,
        secure=settings.secure_identity_cookie,
        samesite="strict",
        max_age=CSRF_COOKIE_MAX_AGE_SECONDS,
        path="/",
    )


def clear_csrf_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.firebase_csrf_cookie_name,
        httponly=False,
        secure=settings.secure_identity_cookie,
        samesite="strict",
        path="/",
    )


def require_csrf(request: Request, submitted_token: str) -> None:
    cookie_token = request.cookies.get(settings.firebase_csrf_cookie_name)
    if (
        not cookie_token
        or not submitted_token
        or not secrets.compare_digest(cookie_token, submitted_token)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF validation failed",
        )
