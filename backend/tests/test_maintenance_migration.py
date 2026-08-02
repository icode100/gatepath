from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app import maintenance_main as maintenance
from app.config import Settings, settings
from app.main import app as main_app
from app.user_state import UserStateUnavailable
from app.user_state.dependencies import get_user_state_repository
from scripts.migrate_user_state_to_firestore import (
    MigrationError,
    MigrationPlan,
    MigrationReport,
    SourceSummary,
)


STRONG_SECRET = "s" * 43
AUTHORIZATION = {"Authorization": f"Bearer {STRONG_SECRET}"}


def _report(mode: str = "dry-run") -> MigrationReport:
    return MigrationReport(
        mode=mode,  # type: ignore[arg-type]
        source=SourceSummary(sessions=2, attempts=1, responses=3, owners=1),
        source_digest="a" * 64,
        plan=(
            MigrationPlan(
                missing_sessions=2,
                resumable_sessions=0,
                matching_sessions=0,
                missing_attempts=1,
                matching_attempts=0,
                progress_rebuilds=1,
                matching_progress=0,
            )
            if mode != "verify-only"
            else None
        ),
        verified=mode != "dry-run",
    )


@pytest.fixture
def migration_client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "user_state_maintenance", True)
    monkeypatch.setattr(settings, "user_state_migration_enabled", True)
    monkeypatch.setattr(
        settings,
        "user_state_migration_secret",
        SecretStr(STRONG_SECRET),
    )
    monkeypatch.setattr(settings, "user_state_backend", "postgres")
    monkeypatch.setattr(maintenance, "close_database", AsyncMock())
    with TestClient(maintenance.app) as client:
        yield client


def test_migration_settings_are_disabled_and_secretless_by_default() -> None:
    isolated = Settings(_env_file=None)

    assert isolated.user_state_maintenance is False
    assert isolated.user_state_migration_enabled is False
    assert isolated.user_state_migration_secret is None


def test_disabled_or_weak_migration_surface_is_hidden(
    migration_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = AsyncMock(return_value=_report())
    monkeypatch.setattr(maintenance, "_execute_with_advisory_lock", runner)
    monkeypatch.setattr(settings, "user_state_migration_enabled", False)

    get_response = migration_client.get(
        "/internal/maintenance/user-state-migration"
    )
    post_response = migration_client.post(
        "/internal/maintenance/user-state-migration",
        headers=AUTHORIZATION,
        json={"mode": "dry-run"},
    )

    assert get_response.status_code == 404
    assert post_response.status_code == 404
    assert get_response.json() == {"status": "error", "code": "NOT_FOUND"}
    assert post_response.headers["cache-control"] == "no-store"
    runner.assert_not_awaited()

    monkeypatch.setattr(settings, "user_state_migration_enabled", True)
    monkeypatch.setattr(
        settings,
        "user_state_migration_secret",
        SecretStr("too-short"),
    )
    assert (
        migration_client.get("/internal/maintenance/user-state-migration").status_code
        == 404
    )


@pytest.mark.parametrize(
    "authorization",
    [None, "Basic abc", "Bearer ", "Bearer definitely-wrong"],
)
def test_migration_authentication_failures_are_identical_and_sanitized(
    migration_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    authorization: str | None,
) -> None:
    runner = AsyncMock(return_value=_report())
    monkeypatch.setattr(maintenance, "_execute_with_advisory_lock", runner)
    headers = {"Authorization": authorization} if authorization is not None else {}

    response = migration_client.post(
        "/internal/maintenance/user-state-migration",
        headers=headers,
        json={"mode": "dry-run"},
    )

    assert response.status_code == 401
    assert response.json() == {"status": "error", "code": "UNAUTHORIZED"}
    assert response.headers["cache-control"] == "no-store"
    assert STRONG_SECRET not in response.text
    if authorization:
        assert authorization not in response.text
    runner.assert_not_awaited()


def test_authorized_dry_run_returns_only_structured_report(
    migration_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _report()
    runner = AsyncMock(return_value=report)
    monkeypatch.setattr(maintenance, "_execute_with_advisory_lock", runner)

    response = migration_client.post(
        "/internal/maintenance/user-state-migration",
        headers=AUTHORIZATION,
        json={"mode": "dry-run"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "report": report.public_dict()}
    assert STRONG_SECRET not in response.text
    assert response.headers["cache-control"] == "no-store"
    runner.assert_awaited_once()


def test_apply_requires_confirmation_digest_and_postgres_source(
    migration_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = AsyncMock(return_value=_report("apply"))
    monkeypatch.setattr(maintenance, "_execute_with_advisory_lock", runner)
    base = {"mode": "apply", "source_digest": "a" * 64}

    missing_confirmation = migration_client.post(
        "/internal/maintenance/user-state-migration",
        headers=AUTHORIZATION,
        json=base,
    )
    missing_digest = migration_client.post(
        "/internal/maintenance/user-state-migration",
        headers=AUTHORIZATION,
        json={
            "mode": "apply",
            "confirmation": maintenance.MIGRATION_CONFIRMATION,
        },
    )
    monkeypatch.setattr(settings, "user_state_backend", "firestore")
    wrong_backend = migration_client.post(
        "/internal/maintenance/user-state-migration",
        headers=AUTHORIZATION,
        json={**base, "confirmation": maintenance.MIGRATION_CONFIRMATION},
    )

    assert missing_confirmation.status_code == 400
    assert missing_digest.status_code == 400
    assert wrong_backend.status_code == 409
    runner.assert_not_awaited()

    monkeypatch.setattr(settings, "user_state_backend", "postgres")
    accepted = migration_client.post(
        "/internal/maintenance/user-state-migration",
        headers=AUTHORIZATION,
        json={**base, "confirmation": maintenance.MIGRATION_CONFIRMATION},
    )
    assert accepted.status_code == 200
    payload = runner.await_args.args[0]
    assert payload.mode == "apply"
    assert payload.source_digest == "a" * 64


def test_migration_failures_do_not_leak_provider_or_secret_details(
    migration_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = AsyncMock(
        side_effect=MigrationError(
            f"{STRONG_SECRET} postgresql://owner:password@example Firebase key"
        )
    )
    monkeypatch.setattr(maintenance, "_execute_with_advisory_lock", runner)

    response = migration_client.post(
        "/internal/maintenance/user-state-migration",
        headers=AUTHORIZATION,
        json={"mode": "dry-run"},
    )

    assert response.status_code == 409
    assert response.json() == {
        "status": "error",
        "code": "MIGRATION_PRECONDITION_FAILED",
    }
    assert STRONG_SECRET not in response.text
    assert "postgresql" not in response.text
    assert "password" not in response.text


def test_control_page_cannot_execute_and_never_embeds_secret(
    migration_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = AsyncMock(return_value=_report())
    monkeypatch.setattr(maintenance, "_execute_with_advisory_lock", runner)

    response = migration_client.get(
        "/internal/maintenance/user-state-migration"
    )

    assert response.status_code == 200
    assert "Gatepath user-state migration" in response.text
    assert STRONG_SECRET not in response.text
    assert "localStorage" not in response.text
    assert response.headers["cache-control"] == "no-store"
    runner.assert_not_awaited()


def test_bearer_secret_uses_constant_time_comparison(
    migration_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    comparison = Mock(return_value=False)
    runner = AsyncMock(return_value=_report())
    monkeypatch.setattr(maintenance.secrets, "compare_digest", comparison)
    monkeypatch.setattr(maintenance, "_execute_with_advisory_lock", runner)

    response = migration_client.post(
        "/internal/maintenance/user-state-migration",
        headers={"Authorization": "Bearer candidate"},
        json={"mode": "dry-run"},
    )

    assert response.status_code == 401
    comparison.assert_called_once()
    runner.assert_not_awaited()


def test_normal_app_has_no_migration_route_and_maintenance_blocks_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert all(
        route.path != "/internal/maintenance/user-state-migration"
        for route in main_app.routes
    )
    monkeypatch.setattr(settings, "user_state_maintenance", True)

    with pytest.raises(UserStateUnavailable, match="maintenance"):
        get_user_state_repository()
