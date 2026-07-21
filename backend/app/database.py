from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import event
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


async def close_database() -> None:
    await engine.dispose()
