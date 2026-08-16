"""Build the portable 405 -> 177 PYQ visibility ledger from disposable SQLite.

This command is intentionally read-only with respect to the database and
refuses every non-SQLite URL.  Run it only after normal materialization of the
frozen practice artifact has adopted the 177 reviewed keep rows.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings  # noqa: E402
from app.database import build_engine_kwargs  # noqa: E402
from app.models import (  # noqa: E402
    PyqSourceQuestion,
    Question,
    QuestionSource,
    Subject,
    TestForm,
    Topic,
)
from app.pyq_archive import (  # noqa: E402
    _canonical_json_sha256,
    _legacy_candidate_fingerprint,
    _slug,
)


EXPECTED_QUESTION_ROWS = 2695
EXPECTED_PYQ_ROWS = 405
EXPECTED_ACTIVE_ORIGINALS = 2290
EXPECTED_ACTIVE_PYQS_BEFORE = 405
EXPECTED_KEEP = 177
EXPECTED_RETIRE = 228
EXPECTED_ARCHIVE_ROWS = 2873


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"Expected a JSON object: {path}")
    return value


def _binding_path(path: Path) -> str:
    return path.resolve().relative_to(BACKEND_DIR.resolve()).as_posix()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifact",
        type=Path,
        default=BACKEND_DIR / "data" / "gate_cs_pyq_practice_1996_2025.json",
    )
    parser.add_argument(
        "--allowlist",
        type=Path,
        default=(
            BACKEND_DIR
            / "data"
            / "gate_cs_pyq_practice_1996_2025.allowlist.json"
        ),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=(
            BACKEND_DIR / "data" / "gate_cs_pyq_practice_1996_2025.report.json"
        ),
    )
    parser.add_argument(
        "--source-archive",
        type=Path,
        default=BACKEND_DIR / "data" / "gate_cs_pyq_archive_1996_2025.json",
    )
    parser.add_argument(
        "--source-report",
        type=Path,
        default=(
            BACKEND_DIR / "data" / "gate_cs_pyq_archive_1996_2025.report.json"
        ),
    )
    parser.add_argument(
        "--collision-evidence",
        type=Path,
        default=BACKEND_DIR / "data" / "pyq_legacy_collision_adoptions.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=BACKEND_DIR / "data" / "pyq_legacy_collision_cleanup_plan.json",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write the ledger. Without this flag only a summary is printed.",
    )
    return parser.parse_args()


async def build_plan(args: argparse.Namespace) -> dict[str, Any]:
    if not settings.migration_database_url.startswith("sqlite"):
        raise RuntimeError(
            "Visibility-plan generation is restricted to disposable SQLite"
        )
    artifact_path = args.artifact.resolve()
    allowlist_path = args.allowlist.resolve()
    report_path = args.report.resolve()
    source_path = args.source_archive.resolve()
    source_report_path = args.source_report.resolve()
    collision_path = args.collision_evidence.resolve()
    artifact = _load_json(artifact_path)
    allowlist = _load_json(allowlist_path)
    report = _load_json(report_path)
    source = _load_json(source_path)
    source_report = _load_json(source_report_path)

    allowlist_records = allowlist.get("records")
    if not isinstance(allowlist_records, list) or len(allowlist_records) != EXPECTED_KEEP:
        raise RuntimeError("Frozen promotion allowlist does not contain 177 records")
    if _canonical_json_sha256(allowlist_records) != allowlist.get("selection_sha256"):
        raise RuntimeError("Frozen promotion selection checksum drifted")
    source_by_key = {
        (item["source_paper_id"], item["ordinal"]): item
        for item in source["questions"]
    }
    promoted_by_key = {
        (item["source_paper_id"], item["ordinal"]): item
        for item in artifact["questions"]
    }

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
            subjects = list((await session.scalars(select(Subject))).all())
            topics = list((await session.scalars(select(Topic))).all())
            subject_codes = {subject.id: subject.code.upper() for subject in subjects}
            topic_slugs = {topic.id: topic.slug for topic in topics}
            questions = list((await session.scalars(select(Question))).all())
            pyqs = [
                question
                for question in questions
                if question.source_kind == QuestionSource.PREVIOUS_YEAR
            ]
            active_originals = sum(
                question.is_active
                and question.source_kind == QuestionSource.ORIGINAL
                for question in questions
            )
            active_pyqs = [question for question in pyqs if question.is_active]
            archive_rows = int(
                await session.scalar(select(func.count(PyqSourceQuestion.id))) or 0
            )
            if (
                len(questions) != EXPECTED_QUESTION_ROWS
                or len(pyqs) != EXPECTED_PYQ_ROWS
                or active_originals != EXPECTED_ACTIVE_ORIGINALS
                or len(active_pyqs) != EXPECTED_ACTIVE_PYQS_BEFORE
                or archive_rows != EXPECTED_ARCHIVE_ROWS
            ):
                raise RuntimeError(
                    "Disposable database is not at the reviewed 2695/405/2290/"
                    "405/2873 baseline"
                )

            by_external: dict[str, list[Question]] = {}
            for question in pyqs:
                if question.external_id:
                    by_external.setdefault(question.external_id, []).append(question)
            keep_targets: list[dict[str, Any]] = []
            keep_ids: set[int] = set()
            for record in allowlist_records:
                key = record["source_paper_id"], record["ordinal"]
                source_item = source_by_key.get(key)
                promoted_item = promoted_by_key.get(key)
                external_id = (
                    f"pyq:{record['source_paper_id']}:{_slug(record['item_label'])}"
                )
                candidates = by_external.get(external_id, [])
                if (
                    len(candidates) != 1
                    or source_item is None
                    or promoted_item is None
                    or source_item.get("item_label") != record["item_label"]
                    or promoted_item.get("item_label") != record["item_label"]
                    or source_item.get("content_sha256")
                    != record["source_content_sha256"]
                    or promoted_item.get("practice_eligible") is not True
                ):
                    raise RuntimeError(f"Keep identity drifted: {key}")
                keep_ids.add(candidates[0].id)
                keep_targets.append(
                    {
                        **record,
                        "promoted_content_sha256": promoted_item["content_sha256"],
                        "external_id": external_id,
                    }
                )
            if len(keep_ids) != EXPECTED_KEEP:
                raise RuntimeError("Keep-row identities are not unique")

            retire_rows = [
                question for question in active_pyqs if question.id not in keep_ids
            ]
            if len(retire_rows) != EXPECTED_RETIRE:
                raise RuntimeError("Retirement complement is not exactly 228 rows")
            retire_targets = []
            fingerprints: set[str] = set()
            for question in retire_rows:
                fingerprint = _legacy_candidate_fingerprint(
                    question,
                    subject_codes_by_id=subject_codes,
                    topic_slugs_by_id=topic_slugs,
                )
                if fingerprint in fingerprints:
                    raise RuntimeError("Retirement fingerprint is not unique")
                fingerprints.add(fingerprint)
                retire_targets.append(
                    {
                        "fingerprint_sha256": fingerprint,
                        "external_id": question.external_id,
                        "source_paper": question.source_paper,
                        "source_year": (
                            question.source_year
                            if question.source_year is not None
                            else question.year
                        ),
                        "source_question_number": question.source_question_number,
                    }
                )
            form_references = sum(
                question_id in {question.id for question in retire_rows}
                for form in (await session.scalars(select(TestForm))).all()
                for question_id in (form.question_ids or [])
            )
    finally:
        await engine.dispose()

    keep_targets.sort(key=lambda row: (row["source_paper_id"], row["ordinal"]))
    retire_targets.sort(
        key=lambda row: (
            row["source_year"] or 0,
            row["source_paper"] or "",
            row["source_question_number"] or 0,
            row["fingerprint_sha256"],
        )
    )
    plan = {
        "schema_version": "2.0",
        "plan_version": (
            "gate-cs-pyq-visibility-"
            f"{allowlist['selection_sha256'][:12]}-405-to-177-v1"
        ),
        "status": "authorized_opt_in_only",
        "database_writes_performed": False,
        "bindings": {
            "source_archive": {
                "path": _binding_path(source_path),
                "file_sha256": _file_sha256(source_path),
                "canonical_sha256": _canonical_json_sha256(source),
            },
            "source_archive_report": {
                "path": _binding_path(source_report_path),
                "file_sha256": _file_sha256(source_report_path),
                "report_sha256": source_report["report_sha256"],
            },
            "promotion_artifact": {
                "path": _binding_path(artifact_path),
                "file_sha256": _file_sha256(artifact_path),
                "canonical_sha256": _canonical_json_sha256(artifact),
                "artifact_version": artifact["artifact_version"],
            },
            "promotion_allowlist": {
                "path": _binding_path(allowlist_path),
                "file_sha256": _file_sha256(allowlist_path),
                "artifact_sha256": allowlist["artifact_sha256"],
            },
            "promotion_report": {
                "path": _binding_path(report_path),
                "file_sha256": _file_sha256(report_path),
                "report_sha256": report["report_sha256"],
            },
            "collision_evidence": {
                "path": _binding_path(collision_path),
                "file_sha256": _file_sha256(collision_path),
            },
            "selection_sha256": allowlist["selection_sha256"],
        },
        "guards": {
            "expected_question_rows": EXPECTED_QUESTION_ROWS,
            "expected_pyq_rows": EXPECTED_PYQ_ROWS,
            "expected_active_originals": EXPECTED_ACTIVE_ORIGINALS,
            "expected_active_pyqs_before": EXPECTED_ACTIVE_PYQS_BEFORE,
            "expected_retirements": EXPECTED_RETIRE,
            "expected_active_pyqs_after": EXPECTED_KEEP,
            "archive_record_count": EXPECTED_ARCHIVE_ROWS,
            "practice_eligible_count": EXPECTED_KEEP,
            "delete_rows": False,
        },
        "keep_targets": keep_targets,
        "retire_targets": retire_targets,
        "recovery": {
            "expected_active_originals": EXPECTED_ACTIVE_ORIGINALS,
            "expected_active_pyqs_before": EXPECTED_KEEP,
            "expected_reactivations": EXPECTED_RETIRE,
            "expected_active_pyqs_after": EXPECTED_ACTIVE_PYQS_BEFORE,
            "delete_rows": False,
        },
    }
    plan["_generation_summary"] = {
        "disposable_sqlite_only": True,
        "test_form_references_requiring_transactional_rebuild": form_references,
    }
    # Generation-only metadata is printed but deliberately excluded from the
    # strict runtime ledger schema.
    summary = plan.pop("_generation_summary")
    if args.write:
        args.output.resolve().write_text(
            json.dumps(plan, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    print(json.dumps({**summary, "plan_sha256": _canonical_json_sha256(plan)}, indent=2))
    return plan


def main() -> int:
    args = parse_args()
    asyncio.run(build_plan(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
