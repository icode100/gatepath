from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import Response, status
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from app import bootstrap as bootstrap_module
from app import main as main_module
from app.config import DEFAULT_ANONYMOUS_IDENTITY_SECRET, Settings, settings
from app.database import build_engine_kwargs
from app.question_bank import ImportResult


def _hosted_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": (
            "postgres://gate:secret@ep-pooler.example.neon.tech/gatepath"
            "?sslmode=require&channel_binding=require"
        ),
        "database_url_unpooled": (
            "postgresql://gate:secret@ep-direct.example.neon.tech/gatepath"
            "?sslmode=verify-full&channel_binding=require"
        ),
        "environment": "production",
        "vercel": True,
        "anonymous_identity_secret": "v" * 40,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_neon_urls_are_normalized_and_unpooled_url_is_preferred() -> None:
    hosted = _hosted_settings()

    runtime_url = make_url(hosted.async_database_url)
    migration_url = make_url(hosted.async_migration_database_url)
    assert runtime_url.drivername == "postgresql+asyncpg"
    assert runtime_url.host == "ep-pooler.example.neon.tech"
    assert "sslmode" not in runtime_url.query
    assert "channel_binding" not in runtime_url.query
    assert migration_url.host == "ep-direct.example.neon.tech"
    assert "sslmode" not in migration_url.query
    assert hosted.async_database_connect_args == {"ssl": "require"}
    assert hosted.migration_database_connect_args == {"ssl": "verify-full"}

    engine_options = build_engine_kwargs(hosted)
    assert engine_options["poolclass"] is NullPool
    assert engine_options["connect_args"] == {"ssl": "require"}
    assert hosted.should_bootstrap_on_startup is False
    assert hosted.secure_identity_cookie is True


def test_database_pool_override_can_retain_a_managed_queue_pool() -> None:
    hosted = _hosted_settings(database_pool_mode="queue")
    engine_options = build_engine_kwargs(hosted)
    assert "poolclass" not in engine_options
    assert engine_options["pool_pre_ping"] is True


@pytest.mark.asyncio
async def test_hosted_lifespan_is_read_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "vercel", True)
    monkeypatch.setattr(
        settings,
        "database_url",
        "postgresql://gate:secret@example.neon.tech/gatepath?sslmode=require",
    )
    monkeypatch.setattr(settings, "anonymous_identity_secret", "s" * 40)
    initialize = AsyncMock()
    close = AsyncMock()
    monkeypatch.setattr(
        main_module,
        "initialize_local_development_database",
        initialize,
    )
    monkeypatch.setattr(main_module, "close_database", close)

    async with main_module.lifespan(main_module.app):
        pass

    initialize.assert_not_awaited()
    close.assert_awaited_once()


@pytest.mark.asyncio
async def test_hosted_lifespan_rejects_default_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "vercel", True)
    monkeypatch.setattr(
        settings,
        "database_url",
        "postgresql://gate:secret@example.neon.tech/gatepath?sslmode=require",
    )
    monkeypatch.setattr(
        settings,
        "anonymous_identity_secret",
        DEFAULT_ANONYMOUS_IDENTITY_SECRET,
    )

    with pytest.raises(RuntimeError, match="ANONYMOUS_IDENTITY_SECRET"):
        async with main_module.lifespan(main_module.app):
            pass


@pytest.mark.asyncio
async def test_hosted_lifespan_rejects_sqlite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "vercel", True)
    monkeypatch.setattr(
        settings,
        "database_url",
        "sqlite+aiosqlite:///./gate_prep.db",
    )
    monkeypatch.setattr(settings, "anonymous_identity_secret", "s" * 40)

    with pytest.raises(RuntimeError, match="PostgreSQL"):
        async with main_module.lifespan(main_module.app):
            pass


class _FailingSessionContext:
    async def __aenter__(self) -> object:
        raise OSError("database unavailable")

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> None:
        return None


@pytest.mark.asyncio
async def test_health_returns_503_when_database_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        main_module,
        "AsyncSessionFactory",
        lambda: _FailingSessionContext(),
    )
    response = Response(status_code=status.HTTP_200_OK)

    payload = await main_module.health(response)

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert payload.status == "degraded"
    assert payload.database == "unavailable"


class _FakeSession:
    def __init__(self) -> None:
        self.scalar_results = iter((2607, 125))

    async def scalar(self, _: object) -> int:
        return next(self.scalar_results)


class _FakeSessionContext:
    def __init__(self, session: _FakeSession) -> None:
        self.session = session

    async def __aenter__(self) -> _FakeSession:
        return self.session

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> None:
        return None


class _FakeSessionFactory:
    def __init__(self) -> None:
        self.session = _FakeSession()

    def __call__(self) -> _FakeSessionContext:
        return _FakeSessionContext(self.session)


@pytest.mark.asyncio
async def test_explicit_data_initializer_runs_complete_sequence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    question_bank = tmp_path / "question-bank.json"
    question_bank.write_text("{}", encoding="utf-8")
    calls: list[str] = []

    async def seed(_: object) -> None:
        calls.append("seed")

    async def import_bank(_: object, path: Path) -> ImportResult:
        calls.append(f"import:{path.name}")
        return ImportResult(
            bank_version="test-bank",
            checksum="0" * 64,
            question_count=2607,
            inserted_count=2607,
            updated_count=0,
            unchanged_count=0,
            retired_count=0,
            already_applied=False,
        )

    async def rebuild(_: object) -> None:
        calls.append("catalog")

    monkeypatch.setattr(bootstrap_module, "seed_database", seed)
    monkeypatch.setattr(bootstrap_module, "import_question_bank", import_bank)
    monkeypatch.setattr(bootstrap_module, "rebuild_test_catalog", rebuild)

    summary = await bootstrap_module.initialize_application_data(
        session_factory=_FakeSessionFactory(),  # type: ignore[arg-type]
        question_bank_path=question_bank,
        require_question_bank=True,
    )

    assert calls == ["seed", "import:question-bank.json", "catalog"]
    assert summary.active_question_count == 2607
    assert summary.test_form_count == 125
    assert summary.question_bank is not None
    assert summary.question_bank.bank_version == "test-bank"
