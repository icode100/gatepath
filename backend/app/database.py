from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import event, inspect
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool, StaticPool

from app.config import Settings, settings


class Base(DeclarativeBase):
    pass


def build_engine_kwargs(
    app_settings: Settings,
    *,
    database_url: str | None = None,
    force_null_pool: bool = False,
) -> dict[str, object]:
    """Build engine options that are safe for both local and serverless use."""

    source_url = database_url or app_settings.database_url
    async_url = app_settings.normalize_async_database_url(source_url)
    engine_options: dict[str, object] = {"echo": app_settings.sql_echo}
    if async_url.endswith(":memory:"):
        engine_options["poolclass"] = StaticPool
    elif force_null_pool or app_settings.use_null_database_pool:
        # A serverless instance must not retain its own PostgreSQL connection
        # pool. Neon (or another managed pooler) remains the connection owner.
        engine_options["poolclass"] = NullPool
    else:
        engine_options["pool_pre_ping"] = True
    connect_args = app_settings.asyncpg_connect_args(source_url)
    if connect_args:
        engine_options["connect_args"] = connect_args
    return engine_options


database_configuration_issue = settings.database_configuration_issue
if database_configuration_issue is not None:
    # Keep the application importable so /health can explain a hosted
    # configuration problem. API requests remain blocked by the middleware in
    # app.main, and this in-memory fallback is never used as production data.
    engine_url = "sqlite+aiosqlite:///:memory:"
    engine_kwargs: dict[str, object] = {
        "echo": False,
        "poolclass": StaticPool,
    }
else:
    engine_url = settings.async_database_url
    engine_kwargs = build_engine_kwargs(settings)
engine = create_async_engine(engine_url, **engine_kwargs)
AsyncSessionFactory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


if engine_url.startswith("sqlite"):

    @event.listens_for(engine.sync_engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection: object, _: object) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


async def get_db() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionFactory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def create_database_schema() -> None:
    # Import models so every table is registered on Base.metadata.
    from app import models  # noqa: F401

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.run_sync(_add_local_upgrade_columns)


def _add_local_upgrade_columns(connection: Connection) -> None:
    """Keep AUTO_CREATE_DB useful for an existing zero-config local database.

    Managed deployments should still run Alembic. ``create_all`` cannot add
    columns to an existing SQLite file, so development startup performs only
    the additive, nullable column changes needed before the importer/catalog
    can run. New tables are already handled by ``create_all``.
    """

    inspector = inspect(connection)
    table_names = set(inspector.get_table_names())
    if "questions" in table_names:
        question_columns = {
            column["name"] for column in inspector.get_columns("questions")
        }
        if "external_id" not in question_columns:
            connection.exec_driver_sql(
                "ALTER TABLE questions ADD COLUMN external_id VARCHAR(180)"
            )
        if "bank_version" not in question_columns:
            connection.exec_driver_sql(
                "ALTER TABLE questions ADD COLUMN bank_version VARCHAR(80)"
            )
        if "is_active" not in question_columns:
            connection.exec_driver_sql(
                "ALTER TABLE questions ADD COLUMN "
                "is_active BOOLEAN NOT NULL DEFAULT 1"
            )
        if "source_page" not in question_columns:
            connection.exec_driver_sql(
                "ALTER TABLE questions ADD COLUMN source_page INTEGER"
            )
        if "extraction_method" not in question_columns:
            connection.exec_driver_sql(
                "ALTER TABLE questions ADD COLUMN extraction_method VARCHAR(80)"
            )
        if "extraction_confidence" not in question_columns:
            connection.exec_driver_sql(
                "ALTER TABLE questions ADD COLUMN extraction_confidence FLOAT"
            )
        if "source_paper_id" not in question_columns:
            connection.exec_driver_sql(
                "ALTER TABLE questions ADD COLUMN source_paper_id VARCHAR(96)"
            )
        if "source_item_label" not in question_columns:
            connection.exec_driver_sql(
                "ALTER TABLE questions ADD COLUMN source_item_label VARCHAR(48)"
            )
        question_indexes = {
            index["name"]
            for index in inspect(connection).get_indexes("questions")
            if index.get("name")
        }
        if "ix_questions_external_id" not in question_indexes:
            connection.exec_driver_sql(
                "CREATE UNIQUE INDEX ix_questions_external_id "
                "ON questions (external_id)"
            )
        if "ix_questions_bank_version" not in question_indexes:
            connection.exec_driver_sql(
                "CREATE INDEX ix_questions_bank_version "
                "ON questions (bank_version)"
            )
        if "ix_questions_is_active" not in question_indexes:
            connection.exec_driver_sql(
                "CREATE INDEX ix_questions_is_active "
                "ON questions (is_active)"
            )
        if "ix_questions_source_paper_id" not in question_indexes:
            connection.exec_driver_sql(
                "CREATE INDEX ix_questions_source_paper_id "
                "ON questions (source_paper_id)"
            )

    if "practice_sessions" in table_names:
        session_columns = {
            column["name"] for column in inspector.get_columns("practice_sessions")
        }
        if "catalog_id" not in session_columns:
            connection.exec_driver_sql(
                "ALTER TABLE practice_sessions ADD COLUMN catalog_id VARCHAR(80)"
            )
        if "question_snapshots" not in session_columns:
            connection.exec_driver_sql(
                "ALTER TABLE practice_sessions ADD COLUMN "
                "question_snapshots JSON NOT NULL DEFAULT '[]'"
            )
        session_indexes = {
            index["name"]
            for index in inspect(connection).get_indexes("practice_sessions")
            if index.get("name")
        }
        if "ix_practice_sessions_catalog_id" not in session_indexes:
            connection.exec_driver_sql(
                "CREATE INDEX ix_practice_sessions_catalog_id "
                "ON practice_sessions (catalog_id)"
            )

    if "attempt_responses" in table_names:
        response_columns = {
            column["name"] for column in inspector.get_columns("attempt_responses")
        }
        if "correct_answer_snapshot" not in response_columns:
            connection.exec_driver_sql(
                "ALTER TABLE attempt_responses ADD COLUMN "
                "correct_answer_snapshot JSON"
            )
        if "explanation_snapshot" not in response_columns:
            connection.exec_driver_sql(
                "ALTER TABLE attempt_responses ADD COLUMN "
                "explanation_snapshot TEXT"
            )

    if "question_bank_imports" in table_names:
        import_columns = {
            column["name"]
            for column in inspector.get_columns("question_bank_imports")
        }
        if "retired_count" not in import_columns:
            connection.exec_driver_sql(
                "ALTER TABLE question_bank_imports ADD COLUMN "
                "retired_count INTEGER NOT NULL DEFAULT 0"
            )


async def close_database() -> None:
    await engine.dispose()
