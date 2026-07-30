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
from sqlalchemy.pool import StaticPool

from app.config import settings


class Base(DeclarativeBase):
    pass


engine_kwargs: dict[str, object] = {
    "echo": settings.sql_echo,
    "pool_pre_ping": True,
}
if settings.async_database_url.endswith(":memory:"):
    engine_kwargs["poolclass"] = StaticPool

engine = create_async_engine(settings.async_database_url, **engine_kwargs)
AsyncSessionFactory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


if settings.async_database_url.startswith("sqlite"):

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

    if "practice_sessions" in table_names:
        session_columns = {
            column["name"] for column in inspector.get_columns("practice_sessions")
        }
        if "catalog_id" not in session_columns:
            connection.exec_driver_sql(
                "ALTER TABLE practice_sessions ADD COLUMN catalog_id VARCHAR(80)"
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


async def close_database() -> None:
    await engine.dispose()
