"""Validate or apply an audited, paper-scoped PYQ archive artifact."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.bootstrap import upgrade_database_schema  # noqa: E402
from app.config import settings  # noqa: E402
from app.database import build_engine_kwargs  # noqa: E402
from app.pyq_archive import (  # noqa: E402
    import_pyq_archive,
    restore_pyq_visibility,
)


class SchemaRevisionError(RuntimeError):
    pass


def _expected_schema_heads() -> set[str]:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return set(ScriptDirectory.from_config(config).get_heads())


async def assert_database_schema_current(engine: AsyncEngine) -> None:
    """Read the Alembic revision without applying or repairing migrations."""

    try:
        async with engine.connect() as connection:
            current_heads = set(
                (
                    await connection.execute(
                        text("SELECT version_num FROM alembic_version")
                    )
                ).scalars()
            )
    except SQLAlchemyError as exc:
        raise SchemaRevisionError(
            "Database schema revision could not be read. Run an explicit "
            "--apply --upgrade-schema command before previewing the archive."
        ) from exc
    expected_heads = _expected_schema_heads()
    if current_heads != expected_heads:
        raise SchemaRevisionError(
            "Database schema is not at the importer head "
            f"(current={sorted(current_heads)}, expected={sorted(expected_heads)}). "
            "No migration was run; use --apply --upgrade-schema explicitly."
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate every source slot in a PYQ archive, then optionally apply "
            "the paper-scoped archive and its fully verified practice rows."
        )
    )
    parser.add_argument("artifact", type=Path)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the archive. Without this flag the command is a dry run.",
    )
    parser.add_argument(
        "--materialize",
        action="store_true",
        help="Upsert fully verified, auto-gradable rows into the live question bank.",
    )
    parser.add_argument(
        "--expected-active-originals",
        type=int,
        help=(
            "Abort unless this many active original questions exist before and "
            "after the import. Use 2290 for the current production baseline."
        ),
    )
    parser.add_argument(
        "--unsafe-allow-unpinned-originals",
        action="store_true",
        help=(
            "UNSAFE: allow a live apply without pinning the active original-bank "
            "count. Never use this for the production database."
        ),
    )
    parser.add_argument(
        "--allow-retire",
        action="store_true",
        help=(
            "Allow reviewed deactivation of linked PYQs. Requires all exact "
            "retirement and active-PYQ count guards."
        ),
    )
    parser.add_argument("--expected-retirements", type=int)
    parser.add_argument(
        "--restore-retired",
        action="store_true",
        help=(
            "Reactivate only the exact fingerprint-bound rows from the reviewed "
            "visibility plan. Mutually exclusive with archive materialization."
        ),
    )
    parser.add_argument("--expected-reactivations", type=int)
    parser.add_argument("--expected-active-pyqs-before", type=int)
    parser.add_argument("--expected-active-pyqs-after", type=int)
    parser.add_argument(
        "--upgrade-schema",
        action="store_true",
        help=(
            "Explicitly apply Alembic migrations before a live --apply. "
            "Preview commands never migrate."
        ),
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if args.upgrade_schema and not args.apply:
        raise SystemExit("--upgrade-schema requires --apply; previews never migrate")
    if (
        args.expected_active_originals is not None
        and args.unsafe_allow_unpinned_originals
    ):
        raise SystemExit(
            "Do not combine --expected-active-originals with the unsafe unpinned "
            "override"
        )
    count_guards = {
        "--expected-active-originals": args.expected_active_originals,
        "--expected-retirements": args.expected_retirements,
        "--expected-reactivations": args.expected_reactivations,
        "--expected-active-pyqs-before": args.expected_active_pyqs_before,
        "--expected-active-pyqs-after": args.expected_active_pyqs_after,
    }
    for flag, value in count_guards.items():
        if value is not None and value < 0:
            raise SystemExit(f"{flag} cannot be negative")
    if (
        args.apply
        and args.expected_active_originals is None
        and not args.unsafe_allow_unpinned_originals
    ):
        raise SystemExit(
            "Live --apply requires --expected-active-originals. The only bypass "
            "is --unsafe-allow-unpinned-originals."
        )
    if (
        (args.allow_retire or args.restore_retired)
        and args.expected_active_originals is None
    ):
        raise SystemExit(
            "Visibility transitions require --expected-active-originals even in "
            "preview mode"
        )
    retirement_guards = (
        args.expected_retirements,
        args.expected_active_pyqs_before,
        args.expected_active_pyqs_after,
    )
    recovery_guards = (
        args.expected_reactivations,
        args.expected_active_pyqs_before,
        args.expected_active_pyqs_after,
    )
    if args.restore_retired and (args.materialize or args.allow_retire):
        raise SystemExit(
            "--restore-retired is mutually exclusive with --materialize and "
            "--allow-retire"
        )
    if args.restore_retired and args.expected_retirements is not None:
        raise SystemExit(
            "--expected-retirements cannot be combined with --restore-retired"
        )
    if args.restore_retired and any(value is None for value in recovery_guards):
        raise SystemExit(
            "--restore-retired requires --expected-reactivations, "
            "--expected-active-pyqs-before and --expected-active-pyqs-after"
        )
    if not args.restore_retired and args.expected_reactivations is not None:
        raise SystemExit("--expected-reactivations requires --restore-retired")
    if args.allow_retire and not args.materialize:
        raise SystemExit("--allow-retire requires --materialize")
    if args.allow_retire and any(value is None for value in retirement_guards):
        raise SystemExit(
            "--allow-retire requires --expected-retirements, "
            "--expected-active-pyqs-before and --expected-active-pyqs-after"
        )
    if (
        not args.allow_retire
        and not args.restore_retired
        and any(value is not None for value in retirement_guards)
    ):
        raise SystemExit("Retirement count guards require --allow-retire")


async def run(args: argparse.Namespace) -> dict[str, object]:
    engine = create_async_engine(
        settings.async_migration_database_url,
        **build_engine_kwargs(
            settings,
            database_url=settings.migration_database_url,
            force_null_pool=True,
        ),
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        await assert_database_schema_current(engine)
        async with factory() as session:
            if args.restore_retired:
                result = await restore_pyq_visibility(
                    session,
                    args.artifact.resolve(),
                    dry_run=not args.apply,
                    expected_original_count=args.expected_active_originals,
                    expected_reactivation_count=args.expected_reactivations,
                    expected_active_pyqs_before=args.expected_active_pyqs_before,
                    expected_active_pyqs_after=args.expected_active_pyqs_after,
                )
                return asdict(result)
            result = await import_pyq_archive(
                session,
                args.artifact.resolve(),
                dry_run=not args.apply,
                materialize=args.materialize,
                expected_original_count=args.expected_active_originals,
                unsafe_allow_unpinned_original_count=(
                    args.unsafe_allow_unpinned_originals
                ),
                allow_retire=args.allow_retire,
                expected_retirement_count=args.expected_retirements,
                expected_active_pyqs_before=args.expected_active_pyqs_before,
                expected_active_pyqs_after=args.expected_active_pyqs_after,
            )
            return asdict(result)
    finally:
        await engine.dispose()


def main() -> int:
    args = parse_args()
    validate_args(args)
    if args.materialize and not args.apply:
        # Materialization is still simulated during a dry run, which is useful
        # for validation; this message makes that behavior explicit.
        print("Materialization preview only: --apply was not supplied.")
    if args.restore_retired and not args.apply:
        print("Visibility recovery preview only: --apply was not supplied.")
    if args.upgrade_schema:
        upgrade_database_schema()
    try:
        summary = asyncio.run(run(args))
    except SchemaRevisionError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
