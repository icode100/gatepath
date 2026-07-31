from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.bootstrap import (  # noqa: E402
    BootstrapSummary,
    bootstrap_deployment_database,
    upgrade_database_schema,
)
from app.database import close_database  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Apply migrations, seed the syllabus, import the versioned question "
            "bank, and rebuild the deterministic test catalog."
        )
    )
    parser.add_argument(
        "--question-bank",
        type=Path,
        help="Override QUESTION_BANK_PATH for this bootstrap run.",
    )
    return parser.parse_args()


async def bootstrap(question_bank_path: Path | None) -> BootstrapSummary:
    try:
        return await bootstrap_deployment_database(question_bank_path)
    finally:
        await close_database()


def main() -> int:
    args = parse_args()
    upgrade_database_schema()
    summary = asyncio.run(bootstrap(args.question_bank))
    bank = summary.question_bank
    bank_status = "not imported"
    if bank is not None:
        bank_status = (
            f"{bank.bank_version} "
            f"({'already applied' if bank.already_applied else 'applied'})"
        )
    print(
        "Database bootstrap complete: "
        f"{summary.active_question_count} active questions, "
        f"{summary.test_form_count} test forms, bank {bank_status}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
