from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app import firebase_auth
from app.config import settings
from app.csrf import clear_csrf_cookie, require_csrf, set_csrf_cookie
from app.database import get_db
from app.identity import (
    IdentityPrincipal,
    clear_identity_cookie,
    current_principal,
    issue_identity,
    provisional_principal,
    set_identity_cookie,
)
from app.models import Attempt, PracticeSession
from app.schemas import (
    AuthStatus,
    AuthUser,
    CsrfResponse,
    FirebaseLogout,
    FirebaseSessionCreate,
)
from app.user_state import UserStateError, UserStateRepository
from app.user_state.dependencies import get_user_state_repository


router = APIRouter(prefix="/auth", tags=["Authentication"])


def _claim_text(claims: dict[str, Any], key: str) -> str | None:
    value = claims.get(key)
    return value if isinstance(value, str) and value else None


def _firebase_status(
    identity: firebase_auth.FirebaseIdentity,
) -> AuthStatus:
    claims = identity.claims
    return AuthStatus(
        authenticated=True,
        mode="firebase",
        user_key=identity.user_key,
        user=AuthUser(
            uid=identity.uid,
            display_name=_claim_text(claims, "name"),
            email=_claim_text(claims, "email"),
            photo_url=_claim_text(claims, "picture"),
            email_verified=claims.get("email_verified") is True,
        ),
    )


def _principal_status(principal: IdentityPrincipal) -> AuthStatus:
    if principal.mode == "firebase" and principal.firebase_uid:
        return _firebase_status(
            firebase_auth.FirebaseIdentity(
                uid=principal.firebase_uid,
                user_key=principal.user_key,
                claims=principal.claims,
            )
        )
    return AuthStatus(
        authenticated=False,
        mode="guest",
        user_key=principal.user_key,
        user=None,
    )


async def _claim_guest_progress(
    db: AsyncSession,
    *,
    principal: IdentityPrincipal,
    firebase_user_key: str,
    user_state: UserStateRepository | None,
) -> None:
    if principal.mode != "guest":
        return
    guest_user_key = principal.guest_user_key
    if guest_user_key != principal.user_key:
        return
    if not guest_user_key or not guest_user_key.startswith("anon-"):
        return
    if user_state is not None:
        try:
            await user_state.claim_guest_state(
                guest_user_key,
                firebase_user_key,
            )
        except UserStateError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Progress could not be linked to the signed-in account",
            ) from exc
        return
    try:
        await db.execute(
            update(PracticeSession)
            .where(PracticeSession.user_key == guest_user_key)
            .values(user_key=firebase_user_key)
        )
        await db.execute(
            update(Attempt)
            .where(Attempt.user_key == guest_user_key)
            .values(user_key=firebase_user_key)
        )
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Progress could not be linked to the signed-in account",
        ) from exc


@router.get("/csrf", response_model=CsrfResponse)
async def issue_csrf_token(response: Response) -> CsrfResponse:
    token = secrets.token_urlsafe(32)
    response.headers["Cache-Control"] = "no-store"
    set_csrf_cookie(response, token)
    return CsrfResponse(csrf_token=token)


@router.post("/session", response_model=AuthStatus)
async def create_session(
    payload: FirebaseSessionCreate,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    user_state: UserStateRepository | None = Depends(get_user_state_repository),
) -> AuthStatus:
    response.headers["Cache-Control"] = "no-store"
    require_csrf(request, payload.csrf_token)
    if not settings.firebase_auth_enabled or settings.firebase_configuration_issues:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Firebase authentication is not available",
        )

    try:
        firebase_session = await firebase_auth.create_firebase_session(
            payload.id_token
        )
    except firebase_auth.FirebaseRecentSignInRequired as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Recent Firebase sign-in is required",
        ) from exc
    except firebase_auth.FirebaseTokenInvalid as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Firebase sign-in could not be verified",
        ) from exc
    except firebase_auth.FirebaseAuthUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Firebase authentication is temporarily unavailable",
        ) from exc

    principal = provisional_principal(request)
    if getattr(request.state, "firebase_auth_verification_failure", None) is None:
        await _claim_guest_progress(
            db,
            principal=principal,
            firebase_user_key=firebase_session.identity.user_key,
            user_state=user_state,
        )
    firebase_auth.set_firebase_session_cookie(response, firebase_session.cookie)
    clear_identity_cookie(response)
    clear_csrf_cookie(response)
    request.state.firebase_session_replaced = True
    request.state.suppress_guest_cookie = True
    return _firebase_status(firebase_session.identity)


@router.get("/me", response_model=AuthStatus)
async def auth_status(
    response: Response,
    principal: IdentityPrincipal = Depends(current_principal),
) -> AuthStatus:
    response.headers["Cache-Control"] = "no-store"
    return _principal_status(principal)


@router.post("/logout", response_model=AuthStatus)
async def logout(
    payload: FirebaseLogout,
    request: Request,
    response: Response,
) -> AuthStatus:
    response.headers["Cache-Control"] = "no-store"
    require_csrf(request, payload.csrf_token)
    guest_user_key, guest_token = issue_identity()
    firebase_auth.clear_firebase_session_cookie(response)
    clear_identity_cookie(response)
    set_identity_cookie(response, guest_token)
    clear_csrf_cookie(response)
    request.state.firebase_session_replaced = True
    request.state.suppress_guest_cookie = True
    return AuthStatus(
        authenticated=False,
        mode="guest",
        user_key=guest_user_key,
        user=None,
    )
