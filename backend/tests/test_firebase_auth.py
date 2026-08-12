from __future__ import annotations

import json
from collections.abc import Iterator
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import Response
from fastapi.testclient import TestClient

from app import firebase_auth
from app.config import settings


@pytest.fixture
def auth_client(client: TestClient) -> Iterator[TestClient]:
    client.cookies.clear()
    yield client
    client.cookies.clear()


def _enable_firebase(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "firebase_auth_enabled", True)
    monkeypatch.setattr(settings, "firebase_project_id", "gatepath-test-project")
    monkeypatch.setattr(
        settings,
        "firebase_service_account_json",
        json.dumps(
            {
                "project_id": "gatepath-test-project",
                "client_email": "firebase-admin@example.test",
                "private_key": "-----BEGIN PRIVATE KEY-----\nTEST\n-----END PRIVATE KEY-----\n",
            }
        ),
    )


def _firebase_identity(uid: str = "firebase-user-1") -> firebase_auth.FirebaseIdentity:
    return firebase_auth.FirebaseIdentity(
        uid=uid,
        user_key=firebase_auth.firebase_owner_key(uid, "gatepath-test-project"),
        claims={
            "uid": uid,
            "name": "Gate Learner",
            "email": "learner@example.com",
            "picture": "https://example.com/avatar.png",
            "email_verified": True,
        },
    )


def test_firebase_owner_key_is_stable_project_scoped_and_opaque() -> None:
    first = firebase_auth.firebase_owner_key("raw-firebase-uid", "project-a")
    second = firebase_auth.firebase_owner_key("raw-firebase-uid", "project-a")
    other_project = firebase_auth.firebase_owner_key(
        "raw-firebase-uid", "project-b"
    )

    assert first == second
    assert first != other_project
    assert first.startswith("fb-v1-")
    assert len(first) == 70
    assert "raw-firebase-uid" not in first


@pytest.mark.asyncio
async def test_session_verification_uses_configured_revocation_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_auth = Mock()
    fake_auth.verify_session_cookie.return_value = {
        "uid": "revocation-policy-user"
    }
    fake_app = object()
    monkeypatch.setattr(firebase_auth, "_admin_app", lambda: (fake_app, fake_auth))
    monkeypatch.setattr(settings, "firebase_project_id", "gatepath-test-project")
    monkeypatch.setattr(settings, "firebase_check_revoked", False)

    identity = await firebase_auth.verify_firebase_session_cookie(
        "signed-session-cookie"
    )

    assert identity.uid == "revocation-policy-user"
    fake_auth.verify_session_cookie.assert_called_once_with(
        "signed-session-cookie",
        check_revoked=False,
        app=fake_app,
    )


def test_firebase_session_cookie_uses_hosted_security_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "identity_cookie_secure", True)
    response = Response()

    firebase_auth.set_firebase_session_cookie(response, "signed-cookie")

    header = response.headers["set-cookie"].lower()
    assert "httponly" in header
    assert "secure" in header
    assert "samesite=lax" in header
    assert "path=/" in header


def test_auth_me_preserves_zero_configuration_guest_mode(
    auth_client: TestClient,
) -> None:
    response = auth_client.get("/api/v1/auth/me")

    assert response.status_code == 200
    assert response.json() == {
        "authenticated": False,
        "mode": "guest",
        "user_key": response.json()["user_key"],
        "user": None,
    }
    assert response.json()["user_key"].startswith("anon-")
    assert response.headers["cache-control"] == "private, no-store"
    assert {"cookie", "authorization"}.issubset(
        {
            value.strip().casefold()
            for value in response.headers["vary"].split(",")
        }
    )
    assert "httponly" in response.headers["set-cookie"].lower()


def test_invalid_firebase_cookie_blocks_owned_identity_and_is_cleared(
    auth_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_firebase(monkeypatch)
    auth_client.cookies.set(settings.firebase_session_cookie_name, "invalid-cookie")
    verify = AsyncMock(side_effect=firebase_auth.FirebaseTokenInvalid())
    monkeypatch.setattr(firebase_auth, "verify_firebase_session_cookie", verify)

    response = auth_client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.json()["detail"] == "Firebase session is invalid or expired"
    cookie_headers = "; ".join(response.headers.get_list("set-cookie")).lower()
    assert f"{settings.firebase_session_cookie_name}=" in cookie_headers
    assert "max-age=0" in cookie_headers
    verify.assert_awaited_once_with("invalid-cookie")


def test_firebase_outage_keeps_public_api_available_but_blocks_owned_routes(
    auth_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_firebase(monkeypatch)
    auth_client.cookies.set(settings.firebase_session_cookie_name, "retry-later")
    monkeypatch.setattr(
        firebase_auth,
        "verify_firebase_session_cookie",
        AsyncMock(side_effect=firebase_auth.FirebaseAuthUnavailable()),
    )

    public_response = auth_client.get("/api/v1/subjects")
    owned_response = auth_client.post(
        "/api/v1/practice-sessions",
        json={
            "subject_slug": "engineering-mathematics",
            "count": 1,
            "seed": 908,
        },
    )
    me_response = auth_client.get("/api/v1/auth/me")

    assert public_response.status_code == 200
    assert owned_response.status_code == 503
    assert owned_response.json()["detail"] == (
        "Firebase authentication is temporarily unavailable"
    )
    assert me_response.status_code == 503
    assert auth_client.cookies.get(settings.firebase_session_cookie_name) == "retry-later"


def test_session_exchange_requires_matching_double_submit_csrf(
    auth_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_firebase(monkeypatch)
    csrf_response = auth_client.get("/api/v1/auth/csrf")
    assert csrf_response.status_code == 200
    exchange = AsyncMock()
    monkeypatch.setattr(firebase_auth, "create_firebase_session", exchange)
    secret_token = "secret-id-token-must-not-leak"

    response = auth_client.post(
        "/api/v1/auth/session",
        json={"id_token": secret_token, "csrf_token": "x" * 32},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "CSRF validation failed"
    assert secret_token not in response.text
    exchange.assert_not_awaited()


def test_login_claims_guest_sessions_and_attempts_for_firebase_account(
    auth_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_firebase(monkeypatch)
    csrf_response = auth_client.get("/api/v1/auth/csrf")
    csrf_token = csrf_response.json()["csrf_token"]
    practice_response = auth_client.post(
        "/api/v1/practice-sessions",
        json={
            "subject_slug": "engineering-mathematics",
            "count": 1,
            "seed": 909,
        },
    )
    assert practice_response.status_code == 201, practice_response.text
    practice = practice_response.json()
    guest_user_key = practice["user_key"]
    attempt_response = auth_client.post(
        "/api/v1/attempts",
        json={"session_id": practice["id"], "answers": []},
    )
    assert attempt_response.status_code == 201, attempt_response.text
    attempt = attempt_response.json()
    assert attempt["user_key"] == guest_user_key

    identity = _firebase_identity()
    monkeypatch.setattr(
        firebase_auth,
        "create_firebase_session",
        AsyncMock(
            return_value=firebase_auth.FirebaseSession(
                cookie="verified-session-cookie",
                identity=identity,
            )
        ),
    )
    monkeypatch.setattr(
        firebase_auth,
        "verify_firebase_session_cookie",
        AsyncMock(return_value=identity),
    )

    login_response = auth_client.post(
        "/api/v1/auth/session",
        json={"id_token": "verified-id-token", "csrf_token": csrf_token},
    )

    assert login_response.status_code == 200, login_response.text
    assert login_response.json()["authenticated"] is True
    assert login_response.json()["user_key"] == identity.user_key
    assert login_response.json()["user"]["uid"] == identity.uid
    assert guest_user_key != identity.user_key
    login_cookies = "; ".join(
        login_response.headers.get_list("set-cookie")
    ).lower()
    assert f"{settings.firebase_session_cookie_name}=" in login_cookies
    assert "httponly" in login_cookies
    assert "samesite=lax" in login_cookies

    claimed_session = auth_client.get(f"/api/v1/sessions/{practice['id']}")
    claimed_attempt = auth_client.get(f"/api/v1/attempts/{attempt['id']}")
    dashboard = auth_client.get("/api/v1/progress/dashboard")
    assert claimed_session.status_code == 200
    assert claimed_session.json()["user_key"] == identity.user_key
    assert claimed_attempt.status_code == 200
    assert claimed_attempt.json()["user_key"] == identity.user_key
    assert dashboard.status_code == 200
    assert dashboard.json()["user_key"] == identity.user_key
    assert dashboard.json()["total_attempts"] == 1


def test_recent_sign_in_failure_is_safe_and_does_not_echo_token(
    auth_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_firebase(monkeypatch)
    csrf_token = auth_client.get("/api/v1/auth/csrf").json()["csrf_token"]
    monkeypatch.setattr(
        firebase_auth,
        "create_firebase_session",
        AsyncMock(side_effect=firebase_auth.FirebaseRecentSignInRequired()),
    )
    id_token = "stale-secret-id-token"

    response = auth_client.post(
        "/api/v1/auth/session",
        json={"id_token": id_token, "csrf_token": csrf_token},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Recent Firebase sign-in is required"
    assert id_token not in response.text


def test_account_switch_never_reassigns_existing_firebase_progress(
    auth_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_firebase(monkeypatch)
    first_identity = _firebase_identity("account-a")
    second_identity = _firebase_identity("account-b")
    verify = AsyncMock(return_value=first_identity)
    monkeypatch.setattr(firebase_auth, "verify_firebase_session_cookie", verify)
    auth_client.cookies.set(
        settings.firebase_session_cookie_name,
        "account-a-cookie",
        domain="testserver.local",
        path="/",
    )
    csrf_token = auth_client.get("/api/v1/auth/csrf").json()["csrf_token"]
    practice_response = auth_client.post(
        "/api/v1/practice-sessions",
        json={
            "subject_slug": "operating-systems",
            "count": 1,
            "seed": 910,
        },
    )
    assert practice_response.status_code == 201, practice_response.text
    practice = practice_response.json()
    assert practice["user_key"] == first_identity.user_key

    monkeypatch.setattr(
        firebase_auth,
        "create_firebase_session",
        AsyncMock(
            return_value=firebase_auth.FirebaseSession(
                cookie="account-b-cookie",
                identity=second_identity,
            )
        ),
    )
    switch_response = auth_client.post(
        "/api/v1/auth/session",
        json={"id_token": "account-b-token", "csrf_token": csrf_token},
    )
    assert switch_response.status_code == 200, switch_response.text

    verify.return_value = second_identity
    assert auth_client.get(f"/api/v1/sessions/{practice['id']}").status_code == 404
    verify.return_value = first_identity
    original_owner_response = auth_client.get(
        f"/api/v1/sessions/{practice['id']}"
    )
    assert original_owner_response.status_code == 200
    assert original_owner_response.json()["user_key"] == first_identity.user_key


def test_account_switch_never_claims_coexisting_guest_progress(
    auth_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_firebase(monkeypatch)
    guest_practice_response = auth_client.post(
        "/api/v1/practice-sessions",
        json={
            "subject_slug": "algorithms",
            "count": 1,
            "seed": 911,
        },
    )
    assert guest_practice_response.status_code == 201
    guest_practice = guest_practice_response.json()
    guest_cookie = auth_client.cookies.get(settings.identity_cookie_name)
    assert guest_cookie

    first_identity = _firebase_identity("account-a-with-guest")
    second_identity = _firebase_identity("account-b-with-guest")
    verify = AsyncMock(return_value=first_identity)
    monkeypatch.setattr(firebase_auth, "verify_firebase_session_cookie", verify)
    auth_client.cookies.set(
        settings.firebase_session_cookie_name,
        "account-a-cookie",
        domain="testserver.local",
        path="/",
    )
    csrf_token = auth_client.get("/api/v1/auth/csrf").json()["csrf_token"]
    monkeypatch.setattr(
        firebase_auth,
        "create_firebase_session",
        AsyncMock(
            return_value=firebase_auth.FirebaseSession(
                cookie="account-b-cookie",
                identity=second_identity,
            )
        ),
    )

    switch_response = auth_client.post(
        "/api/v1/auth/session",
        json={"id_token": "account-b-token", "csrf_token": csrf_token},
    )

    assert switch_response.status_code == 200
    verify.return_value = second_identity
    assert (
        auth_client.get(f"/api/v1/sessions/{guest_practice['id']}").status_code
        == 404
    )

    auth_client.cookies.delete(settings.firebase_session_cookie_name)
    auth_client.cookies.set(
        settings.identity_cookie_name,
        guest_cookie,
        domain="testserver.local",
        path="/",
    )
    original_guest_response = auth_client.get(
        f"/api/v1/sessions/{guest_practice['id']}"
    )
    assert original_guest_response.status_code == 200
    assert original_guest_response.json()["user_key"].startswith("anon-")


def test_health_reports_invalid_enabled_firebase_configuration(
    auth_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "firebase_auth_enabled", True)
    monkeypatch.setattr(settings, "firebase_project_id", "gatepath-test-project")
    monkeypatch.setattr(settings, "firebase_service_account_json", "{")

    response = auth_client.get("/health")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["authentication"] == "invalid"
    assert response.json()["authentication_issues"] == [
        "FIREBASE_SERVICE_ACCOUNT_JSON_MALFORMED"
    ]


def test_logout_clears_firebase_cookie_and_rotates_to_isolated_guest(
    auth_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_firebase(monkeypatch)
    identity = _firebase_identity("signed-in-user")
    verify = AsyncMock(return_value=identity)
    monkeypatch.setattr(firebase_auth, "verify_firebase_session_cookie", verify)
    auth_client.cookies.set(
        settings.firebase_session_cookie_name,
        "active-session-cookie",
        domain="testserver.local",
        path="/",
    )
    csrf_response = auth_client.get("/api/v1/auth/csrf")
    csrf_token = csrf_response.json()["csrf_token"]

    response = auth_client.post(
        "/api/v1/auth/logout",
        json={"csrf_token": csrf_token},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["authenticated"] is False
    assert body["mode"] == "guest"
    assert body["user_key"].startswith("anon-")
    assert body["user_key"] != identity.user_key
    cookie_headers = "; ".join(response.headers.get_list("set-cookie")).lower()
    assert f"{settings.firebase_session_cookie_name}=" in cookie_headers
    assert "max-age=0" in cookie_headers
    assert f"{settings.identity_cookie_name}=" in cookie_headers

    me_response = auth_client.get("/api/v1/auth/me")
    assert me_response.status_code == 200
    assert me_response.json()["user_key"] == body["user_key"]
    assert me_response.json()["mode"] == "guest"
