from __future__ import annotations

import os
import json
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


DEFAULT_ANONYMOUS_IDENTITY_SECRET = (
    "gatepath-local-dev-secret-change-before-public-deployment"
)


class Settings(BaseSettings):
    app_name: str = "GATE 2027 Prep API"
    app_version: str = "0.1.0"
    environment: str = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"

    database_url: str = "sqlite+aiosqlite:///./gate_prep.db"
    database_url_unpooled: str | None = None
    database_pool_mode: Literal["auto", "queue", "null"] = "auto"
    serverless: bool = False
    vercel: bool = False
    auto_bootstrap_on_startup: bool = True
    auto_create_db: bool = True
    seed_data: bool = True
    auto_import_question_bank: bool = True
    question_bank_path: str = "data/question_bank.json"
    sql_echo: bool = False
    anonymous_identity_secret: str = DEFAULT_ANONYMOUS_IDENTITY_SECRET
    identity_cookie_name: str = "gatepath_identity"
    identity_cookie_secure: bool = False
    firebase_auth_enabled: bool = False
    firebase_project_id: str = ""
    firebase_service_account_json: str | None = None
    firebase_session_cookie_name: str = "gatepath_session"
    firebase_csrf_cookie_name: str = "gatepath_csrf"
    firebase_session_max_age_seconds: int = 60 * 60 * 24 * 5
    firebase_recent_auth_seconds: int = 5 * 60
    firebase_check_revoked: bool = False

    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def async_database_url(self) -> str:
        """Normalize deployment URLs for SQLAlchemy's asyncpg driver.

        Managed PostgreSQL providers commonly publish libpq URLs containing
        ``sslmode`` and ``channel_binding``. SQLAlchemy otherwise forwards
        those query keys as keyword arguments that asyncpg does not accept.
        SSL is preserved separately in ``async_database_connect_args``.
        """

        return self.normalize_async_database_url(self.database_url)

    @property
    def migration_database_url(self) -> str:
        """Prefer the direct URL supplied by managed database integrations."""

        return self.database_url_unpooled or self.database_url

    @property
    def async_migration_database_url(self) -> str:
        return self.normalize_async_database_url(self.migration_database_url)

    @staticmethod
    def normalize_async_database_url(database_url: str) -> str:
        url = database_url
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        parsed = make_url(url)
        if parsed.get_backend_name() != "postgresql":
            return url
        parsed = parsed.set(drivername="postgresql+asyncpg")
        query = dict(parsed.query)
        query.pop("sslmode", None)
        query.pop("ssl", None)
        query.pop("channel_binding", None)
        parsed = parsed.set(query=query)
        return parsed.render_as_string(hide_password=False)

    @property
    def async_database_connect_args(self) -> dict[str, object]:
        """Translate libpq SSL query options into asyncpg connect arguments."""

        return self.asyncpg_connect_args(self.database_url)

    @property
    def migration_database_connect_args(self) -> dict[str, object]:
        return self.asyncpg_connect_args(self.migration_database_url)

    @staticmethod
    def asyncpg_connect_args(database_url: str) -> dict[str, object]:
        normalized_url = database_url
        if normalized_url.startswith("postgres://"):
            normalized_url = normalized_url.replace(
                "postgres://",
                "postgresql://",
                1,
            )
        parsed = make_url(normalized_url)
        if parsed.get_backend_name() != "postgresql":
            return {}
        ssl_mode = parsed.query.get("sslmode") or parsed.query.get("ssl")
        if isinstance(ssl_mode, tuple):
            ssl_mode = ssl_mode[-1] if ssl_mode else None
        if ssl_mode is None:
            return {}
        normalized = str(ssl_mode).strip().lower()
        if normalized in {"0", "false", "no", "off", "disable"}:
            return {"ssl": False}
        if normalized in {"1", "true", "yes", "on"}:
            return {"ssl": True}
        if normalized in {
            "allow",
            "prefer",
            "require",
            "verify-ca",
            "verify-full",
        }:
            return {"ssl": normalized}
        raise ValueError(f"Unsupported PostgreSQL SSL mode: {ssl_mode!r}")

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def is_serverless_runtime(self) -> bool:
        return self.serverless or self.vercel

    @property
    def is_hosted(self) -> bool:
        return self.is_production or self.is_serverless_runtime

    @property
    def database_configuration_issue(self) -> str | None:
        """Return a safe hosted-database diagnostic without exposing its URL."""

        if not self.is_hosted:
            return None
        try:
            parsed = make_url(self.database_url.strip())
        except (ArgumentError, ValueError):
            return "DATABASE_URL_MALFORMED"
        if parsed.get_backend_name() != "postgresql":
            return "DATABASE_URL_NOT_POSTGRESQL"
        return None

    @property
    def hosted_configuration_issues(self) -> list[str]:
        """List actionable, non-secret issues that must block hosted API use."""

        if not self.is_hosted:
            return []
        issues: list[str] = []
        if (
            self.anonymous_identity_secret
            == DEFAULT_ANONYMOUS_IDENTITY_SECRET
            or len(self.anonymous_identity_secret) < 32
        ):
            issues.append("ANONYMOUS_IDENTITY_SECRET_MISSING_OR_WEAK")
        database_issue = self.database_configuration_issue
        if database_issue is not None:
            issues.append(database_issue)
        return issues

    @property
    def firebase_configuration_issues(self) -> list[str]:
        """Return safe diagnostics for the optional Firebase auth feature.

        Firebase is deliberately not part of ``hosted_configuration_issues``:
        a missing Firebase credential must never make guest study mode
        unavailable. Only the Firebase session exchange endpoint is disabled
        while these issues are present.
        """

        if not self.firebase_auth_enabled:
            return []
        issues: list[str] = []
        if not self.firebase_project_id.strip():
            issues.append("FIREBASE_PROJECT_ID_MISSING")
        if not (
            self.firebase_service_account_json
            or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        ):
            issues.append("FIREBASE_ADMIN_CREDENTIALS_MISSING")
        if self.firebase_service_account_json:
            try:
                service_account = json.loads(self.firebase_service_account_json)
            except (TypeError, ValueError):
                issues.append("FIREBASE_SERVICE_ACCOUNT_JSON_MALFORMED")
            else:
                if not isinstance(service_account, dict):
                    issues.append("FIREBASE_SERVICE_ACCOUNT_JSON_MALFORMED")
                else:
                    required_fields = ("project_id", "client_email", "private_key")
                    if any(
                        not isinstance(service_account.get(field), str)
                        or not service_account[field].strip()
                        for field in required_fields
                    ):
                        issues.append("FIREBASE_SERVICE_ACCOUNT_JSON_INVALID")
                    credential_project = service_account.get("project_id")
                    if (
                        isinstance(credential_project, str)
                        and credential_project.strip()
                        and self.firebase_project_id.strip()
                        and credential_project.strip()
                        != self.firebase_project_id.strip()
                    ):
                        issues.append("FIREBASE_SERVICE_ACCOUNT_PROJECT_MISMATCH")
        if not 300 <= self.firebase_session_max_age_seconds <= 60 * 60 * 24 * 14:
            issues.append("FIREBASE_SESSION_MAX_AGE_INVALID")
        if not 0 < self.firebase_recent_auth_seconds <= 60 * 60:
            issues.append("FIREBASE_RECENT_AUTH_WINDOW_INVALID")
        cookie_names = {
            self.identity_cookie_name.strip(),
            self.firebase_session_cookie_name.strip(),
            self.firebase_csrf_cookie_name.strip(),
        }
        if "" in cookie_names or len(cookie_names) != 3:
            issues.append("FIREBASE_COOKIE_NAMES_INVALID")
        return issues

    @property
    def use_null_database_pool(self) -> bool:
        if self.database_pool_mode == "null":
            return True
        if self.database_pool_mode == "queue":
            return False
        return self.is_serverless_runtime

    @property
    def should_bootstrap_on_startup(self) -> bool:
        """Allow convenient local initialization but never write on cold start."""

        return (
            self.auto_bootstrap_on_startup
            and not self.is_production
            and not self.is_serverless_runtime
        )

    @property
    def allowed_origins(self) -> list[str]:
        origins = [origin.strip() for origin in self.cors_origins.split(",")]
        return [origin for origin in origins if origin]

    @property
    def secure_identity_cookie(self) -> bool:
        return (
            self.identity_cookie_secure
            or self.is_production
            or self.is_serverless_runtime
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
