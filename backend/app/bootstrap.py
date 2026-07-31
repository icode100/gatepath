from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings
from app.database import (
    AsyncSessionFactory,
    build_engine_kwargs,
    create_database_schema,
)
from app.models import Question, TestForm
from app.question_bank import (
    ImportResult,
    import_question_bank,
    resolve_question_bank_path,
)
from app.seed import seed_database
from app.test_catalog import rebuild_test_catalog


BACKEND_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True, slots=True)
class BootstrapSummary:
    active_question_count: int
    test_form_count: int
    question_bank: ImportResult | None


def upgrade_database_schema(revision: str = "head") -> None:
    """Apply the Alembic migration chain from any working directory."""

    alembic_config = Config(str(BACKEND_ROOT / "alembic.ini"))
    alembic_config.set_main_option(
        "script_location",
        str(BACKEND_ROOT / "migrations"),
    )
    command.upgrade(alembic_config, revision)


async def initialize_application_data(
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    question_bank_path: str | Path | None = None,
    seed: bool = True,
    import_bank: bool = True,
    rebuild_catalog: bool = True,
    require_question_bank: bool = False,
) -> BootstrapSummary:
    """Idempotently initialize data after the schema is at Alembic head."""

    factory = session_factory or AsyncSessionFactory
    imported: ImportResult | None = None
    async with factory() as session:
        if seed:
            await seed_database(session)
        if import_bank:
            configured_path = (
                str(question_bank_path)
                if question_bank_path is not None
                else settings.question_bank_path
            )
            resolved_path = resolve_question_bank_path(configured_path)
            if not resolved_path.is_file():
                if require_question_bank:
                    raise FileNotFoundError(
                        f"Question bank not found: {resolved_path}"
                    )
            else:
                imported = await import_question_bank(session, resolved_path)
        if rebuild_catalog:
            await rebuild_test_catalog(session)
        active_question_count = int(
            await session.scalar(
                select(func.count(Question.id)).where(
                    Question.is_active.is_(True)
                )
            )
            or 0
        )
        test_form_count = int(
            await session.scalar(select(func.count(TestForm.id))) or 0
        )
    return BootstrapSummary(
        active_question_count=active_question_count,
        test_form_count=test_form_count,
        question_bank=imported,
    )


async def initialize_local_development_database() -> BootstrapSummary:
    """Retain the zero-configuration local workflow outside hosted runtimes."""

    if settings.auto_create_db:
        await create_database_schema()
    return await initialize_application_data(
        seed=settings.seed_data,
        import_bank=settings.auto_import_question_bank,
        rebuild_catalog=True,
        require_question_bank=False,
    )


async def bootstrap_deployment_database(
    question_bank_path: str | Path | None = None,
) -> BootstrapSummary:
    """Initialize deployment data over the direct/unpooled database URL."""

    bootstrap_engine = create_async_engine(
        settings.async_migration_database_url,
        **build_engine_kwargs(
            settings,
            database_url=settings.migration_database_url,
            force_null_pool=True,
        ),
    )
    bootstrap_factory = async_sessionmaker(
        bind=bootstrap_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    try:
        return await initialize_application_data(
            session_factory=bootstrap_factory,
            question_bank_path=question_bank_path,
            seed=True,
            import_bank=True,
            rebuild_catalog=True,
            require_question_bank=True,
        )
    finally:
        await bootstrap_engine.dispose()
