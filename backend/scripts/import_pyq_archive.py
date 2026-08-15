"""Validate or apply an audited, paper-scoped PYQ archive artifact."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.bootstrap import upgrade_database_schema  # noqa: E402
from app.config import settings  # noqa: E402
from app.database import build_engine_kwargs  # noqa: E402
from app.pyq_archive import import_pyq_archive  # noqa: E402


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
        "--skip-migrations",
        action="store_true",
        help="Do not apply Alembic migrations before connecting.",
    )
    return parser.parse_args()


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
        async with factory() as session:
            result = await import_pyq_archive(
                session,
                args.artifact.resolve(),
                dry_run=not args.apply,
                materialize=args.materialize,
                expected_original_count=args.expected_active_originals,
            )
            return asdict(result)
    finally:
        await engine.dispose()


def main() -> int:
    args = parse_args()
    if args.materialize and not args.apply:
        # Materialization is still simulated during a dry run, which is useful
        # for validation; this message makes that behavior explicit.
        print("Materialization preview only: --apply was not supplied.")
    if not args.skip_migrations:
        upgrade_database_schema()
    summary = asyncio.run(run(args))
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
