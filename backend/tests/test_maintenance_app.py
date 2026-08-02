from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

import app.maintenance_main as maintenance
from app.config import Settings, settings
from app.user_state.dependencies import (
    get_user_state_repository,
    reset_user_state_repository_cache,
)
from app.user_state.repository import UserStateUnavailable
from scripts import migrate_user_state_to_firestore as migration


PATH = "/internal/maintenance/user-state-migration"
MIGRATION_SECRET = "migration-secret-" + "x" * 48
WRONG_SECRET = "wrong-migration-secret-" + "y" * 48
SOURCE_DIGEST = "a" * 64


@pytest.fixture
def maintenance_client() -> TestClient:
    client = TestClient(maintenance.app, raise_server_exceptions=False)
    try:
        yield client
    finally:
        client.close()


def _enable_maintenance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "user_state_maintenance", True)
    monkeypatch.setattr(settings, "user_state_migration_enabled", True)
    monkeypatch.setattr(
        settings,
        "user_state_migration_secret",
        SecretStr(MIGRATION_SECRET),
    )
    monkeypatch.setattr(settings, "user_state_backend", "postgres")


def _headers(token: str = MIGRATION_SECRET) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _report(mode: migration.MigrationMode) -> migration.MigrationReport:
    plan = migration.MigrationPlan(
        missing_sessions=2,
        resumable_sessions=0,
        matching_sessions=1,
        missing_attempts=1,
        matching_attempts=1,
        progress_rebuilds=1,
        matching_progress=0,
    )
    return migration.MigrationReport(
        mode=mode,
        source=migration.SourceSummary(
            sessions=3,
            attempts=2,
            responses=4,
            owners=2,
        ),
        source_digest=SOURCE_DIGEST,
        plan=plan,
        applied=(
            migration.ApplySummary(
                created_sessions=2,
                submitted_attempts=1,
                rebuilt_progress=1,
            )
            if mode == "apply"
            else None
        ),
        verified=mode in {"apply", "verify-only"},
    )


def test_maintenance_settings_default_to_disabled_and_secretless() -> None:
    fields = Settings.model_fields

    assert fields["user_state_maintenance"].default is False
    assert fields["user_state_migration_enabled"].default is False
    assert fields["user_state_migration_secret"].default is None

    secret = "must-not-appear-in-settings-repr-" + "z" * 40
    configured = Settings(user_state_migration_secret=SecretStr(secret))
    assert secret not in repr(configured)


def test_disabled_get_and_post_are_hidden(
    maintenance_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "user_state_maintenance", True)
    monkeypatch.setattr(settings, "user_state_migration_enabled", False)
    monkeypatch.setattr(
        settings,
        "user_state_migration_secret",
        SecretStr(MIGRATION_SECRET),
    )
    runner = AsyncMock()
    monkeypatch.setattr(maintenance, "_execute_with_advisory_lock", runner)

    get_response = maintenance_client.get(PATH)
    post_response = maintenance_client.post(
        PATH,
        headers=_headers(),
        json={"mode": "dry-run"},
    )

    for response in (get_response, post_response):
        assert response.status_code == 404
        assert response.json() == {"status": "error", "code": "NOT_FOUND"}
        assert response.headers["cache-control"] == "no-store"
        assert MIGRATION_SECRET not in response.text
    runner.assert_not_awaited()


def test_weak_configured_secret_keeps_endpoint_hidden(
    maintenance_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    weak_secret = "too-short"
    monkeypatch.setattr(settings, "user_state_maintenance", True)
    monkeypatch.setattr(settings, "user_state_migration_enabled", True)
    monkeypatch.setattr(
        settings,
        "user_state_migration_secret",
        SecretStr(weak_secret),
    )
    runner = AsyncMock()
    monkeypatch.setattr(maintenance, "_execute_with_advisory_lock", runner)

    get_response = maintenance_client.get(PATH)
    post_response = maintenance_client.post(
        PATH,
        headers=_headers(weak_secret),
        json={"mode": "dry-run"},
    )

    assert get_response.status_code == 404
    assert post_response.status_code == 404
    assert get_response.json() == post_response.json() == {
        "status": "error",
        "code": "NOT_FOUND",
    }
    assert weak_secret not in get_response.text
    assert weak_secret not in post_response.text
    runner.assert_not_awaited()


@pytest.mark.parametrize(
    "authorization",
    [
        None,
        "Basic malformed",
        "Bearer",
        f"Bearer {WRONG_SECRET}",
    ],
)
def test_missing_malformed_and_wrong_bearer_are_generic_and_secret_safe(
    maintenance_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    authorization: str | None,
) -> None:
    _enable_maintenance(monkeypatch)
    runner = AsyncMock()
    monkeypatch.setattr(maintenance, "_execute_with_advisory_lock", runner)
    headers = {"Authorization": authorization} if authorization is not None else {}

    response = maintenance_client.post(
        PATH,
        headers=headers,
        json={"mode": "dry-run"},
    )

    assert response.status_code == 401
    assert response.json() == {"status": "error", "code": "UNAUTHORIZED"}
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.headers["cache-control"] == "no-store"
    assert MIGRATION_SECRET not in response.text
    assert WRONG_SECRET not in response.text
    runner.assert_not_awaited()


def test_wrong_bearer_is_compared_in_constant_time(
    maintenance_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_maintenance(monkeypatch)
    compare_digest = Mock(wraps=maintenance.secrets.compare_digest)
    monkeypatch.setattr(maintenance.secrets, "compare_digest", compare_digest)

    response = maintenance_client.post(
        PATH,
        headers=_headers(WRONG_SECRET),
        json={"mode": "dry-run"},
    )

    assert response.status_code == 401
    compare_digest.assert_called_once_with(
        WRONG_SECRET.encode(),
        MIGRATION_SECRET.encode(),
    )


def test_authorization_precedes_privileged_body_parsing(
    maintenance_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "user_state_maintenance", True)
    monkeypatch.setattr(settings, "user_state_migration_enabled", False)
    disabled = maintenance_client.post(
        PATH,
        content="not-json",
        headers={"Content-Type": "application/json"},
    )
    assert disabled.status_code == 404

    _enable_maintenance(monkeypatch)
    unauthenticated = maintenance_client.post(
        PATH,
        content="not-json",
        headers={"Content-Type": "application/json"},
    )
    authenticated = maintenance_client.post(
        PATH,
        content="not-json",
        headers={
            **_headers(),
            "Content-Type": "application/json",
        },
    )

    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["code"] == "UNAUTHORIZED"
    assert authenticated.status_code == 400
    assert authenticated.json()["code"] == "INVALID_REQUEST"


def test_authorized_dry_run_invokes_structured_runner(
    maintenance_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_maintenance(monkeypatch)
    report = _report("dry-run")
    runner = AsyncMock(return_value=report)
    monkeypatch.setattr(maintenance, "_execute_with_advisory_lock", runner)

    response = maintenance_client.post(
        PATH,
        headers=_headers(),
        json={"mode": "dry-run"},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"status": "ok", "report": report.public_dict()}
    assert response.headers["cache-control"] == "no-store"
    assert MIGRATION_SECRET not in response.text
    runner.assert_awaited_once()
    payload = runner.await_args.args[0]
    assert isinstance(payload, maintenance.MigrationRequest)
    assert payload.mode == "dry-run"
    assert payload.confirmation is None
    assert payload.source_digest is None


def test_apply_requires_confirmation_reviewed_digest_and_matching_plan(
    maintenance_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_maintenance(monkeypatch)
    report = _report("apply")

    async def enforce_reviewed_plan(
        payload: maintenance.MigrationRequest,
    ) -> migration.MigrationReport:
        if payload.source_digest != SOURCE_DIGEST:
            raise migration.MigrationError("reviewed source digest does not match")
        return report

    runner = AsyncMock(side_effect=enforce_reviewed_plan)
    monkeypatch.setattr(maintenance, "_execute_with_advisory_lock", runner)

    missing_confirmation = maintenance_client.post(
        PATH,
        headers=_headers(),
        json={"mode": "apply", "source_digest": SOURCE_DIGEST},
    )
    missing_digest = maintenance_client.post(
        PATH,
        headers=_headers(),
        json={
            "mode": "apply",
            "confirmation": maintenance.MIGRATION_CONFIRMATION,
        },
    )
    stale_plan = maintenance_client.post(
        PATH,
        headers=_headers(),
        json={
            "mode": "apply",
            "confirmation": maintenance.MIGRATION_CONFIRMATION,
            "source_digest": "b" * 64,
        },
    )
    applied = maintenance_client.post(
        PATH,
        headers=_headers(),
        json={
            "mode": "apply",
            "confirmation": maintenance.MIGRATION_CONFIRMATION,
            "source_digest": SOURCE_DIGEST,
        },
    )

    assert missing_confirmation.status_code == 400
    assert missing_confirmation.json()["code"] == "APPLY_CONFIRMATION_REQUIRED"
    assert missing_digest.status_code == 400
    assert missing_digest.json()["code"] == "REVIEWED_SOURCE_DIGEST_REQUIRED"
    assert stale_plan.status_code == 409
    assert stale_plan.json()["code"] == "MIGRATION_PRECONDITION_FAILED"
    assert applied.status_code == 200, applied.text
    assert applied.json() == {"status": "ok", "report": report.public_dict()}
    assert runner.await_count == 2


def test_apply_is_rejected_after_firestore_becomes_active(
    maintenance_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_maintenance(monkeypatch)
    monkeypatch.setattr(settings, "user_state_backend", "firestore")
    runner = AsyncMock()
    monkeypatch.setattr(maintenance, "_execute_with_advisory_lock", runner)

    response = maintenance_client.post(
        PATH,
        headers=_headers(),
        json={
            "mode": "apply",
            "confirmation": maintenance.MIGRATION_CONFIRMATION,
            "source_digest": SOURCE_DIGEST,
        },
    )

    assert response.status_code == 409
    assert response.json() == {
        "status": "error",
        "code": "APPLY_REQUIRES_POSTGRES_SOURCE",
    }
    runner.assert_not_awaited()


@pytest.mark.parametrize(
    ("failure", "status_code", "code"),
    [
        (maintenance.MigrationBusy(), 409, "MIGRATION_ALREADY_RUNNING"),
        (TimeoutError("sensitive timeout detail"), 503, "MIGRATION_TIMED_OUT"),
        (
            migration.MigrationError(f"provider failed with {MIGRATION_SECRET}"),
            409,
            "MIGRATION_PRECONDITION_FAILED",
        ),
        (
            UserStateUnavailable(f"firebase failed with {MIGRATION_SECRET}"),
            503,
            "USER_STATE_UNAVAILABLE",
        ),
        (RuntimeError(f"unexpected {MIGRATION_SECRET}"), 503, "MIGRATION_FAILED"),
    ],
)
def test_failures_are_sanitized_and_never_cached(
    maintenance_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    status_code: int,
    code: str,
) -> None:
    _enable_maintenance(monkeypatch)
    monkeypatch.setattr(
        maintenance,
        "_execute_with_advisory_lock",
        AsyncMock(side_effect=failure),
    )

    response = maintenance_client.post(
        PATH,
        headers=_headers(),
        json={"mode": "dry-run"},
    )

    assert response.status_code == status_code
    assert response.json() == {"status": "error", "code": code}
    assert response.headers["cache-control"] == "no-store"
    assert MIGRATION_SECRET not in response.text
    assert "provider" not in response.text
    assert "firebase" not in response.text
    assert "unexpected" not in response.text


def test_get_renders_control_form_but_cannot_execute_migration(
    maintenance_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_maintenance(monkeypatch)
    runner = AsyncMock()
    monkeypatch.setattr(maintenance, "_execute_with_advisory_lock", runner)

    response = maintenance_client.get(
        PATH,
        params={"mode": "apply", "source_digest": SOURCE_DIGEST},
    )

    assert response.status_code == 200
    assert "<form" in response.text
    assert 'type="password"' in response.text
    assert maintenance.MIGRATION_CONFIRMATION in response.text
    assert MIGRATION_SECRET not in response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-security-policy"].startswith("default-src 'none'")
    runner.assert_not_awaited()


def test_maintenance_dependency_blocks_learner_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "user_state_maintenance", True)
    reset_user_state_repository_cache()
    try:
        with pytest.raises(UserStateUnavailable, match="maintenance window"):
            get_user_state_repository()
    finally:
        reset_user_state_repository_cache()


def test_normal_app_exposes_no_migration_route(client: TestClient) -> None:
    get_response = client.get(PATH)
    post_response = client.post(PATH, json={"mode": "dry-run"})

    assert get_response.status_code == 404
    assert post_response.status_code == 404
    assert not any(
        getattr(route, "path", None) == PATH
        for route in client.app.routes
    )


def test_health_surfaces_safe_migration_configuration_issues(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "user_state_maintenance", False)
    monkeypatch.setattr(settings, "user_state_migration_enabled", True)
    monkeypatch.setattr(
        settings,
        "user_state_migration_secret",
        SecretStr("weak"),
    )

    response = client.get("/health")

    assert response.status_code == 503
    body = response.json()
    assert "USER_STATE_MAINTENANCE_REQUIRED" in body["user_state_issues"]
    assert (
        "USER_STATE_MIGRATION_SECRET_MISSING_OR_WEAK"
        in body["user_state_issues"]
    )
    assert "weak" not in response.text


@pytest.mark.asyncio
async def test_structured_runner_rejects_a_stale_reviewed_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = migration.SourceSnapshot(records=())

    class EmptyStore:
        async def connect(self) -> None:
            return None

    monkeypatch.setattr(migration, "_validate_configuration", lambda: None)
    monkeypatch.setattr(
        migration,
        "load_source_snapshot",
        AsyncMock(return_value=source),
    )
    store = EmptyStore()

    with pytest.raises(migration.MigrationError, match="changed after"):
        await migration.execute_migration(
            "apply",
            expected_source_digest="f" * 64,
            store=store,
        )

    report = await migration.execute_migration(
        "apply",
        expected_source_digest=source.digest,
        store=store,
    )
    assert report.source_digest == source.digest
    assert report.verified is True
