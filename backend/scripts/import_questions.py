from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import select


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.database import AsyncSessionFactory, close_database, create_database_schema  # noqa: E402
from app.models import (  # noqa: E402
    Difficulty,
    Question,
    QuestionSource,
    QuestionType,
    Subject,
    Topic,
)


REQUIRED_FIELDS = {
    "subject_slug",
    "topic_slug",
    "source_kind",
    "question_type",
    "marks",
    "text",
    "correct_answer",
    "explanation",
}


def validate_record(record: dict[str, Any], index: int) -> None:
    missing = REQUIRED_FIELDS.difference(record)
    if missing:
        raise ValueError(f"Record {index}: missing {', '.join(sorted(missing))}")
    question_type = QuestionType(record["question_type"])
    marks = int(record["marks"])
    if marks not in (1, 2):
        raise ValueError(f"Record {index}: marks must be 1 or 2")
    options = record.get("options", [])
    if question_type in (QuestionType.MCQ, QuestionType.MSQ):
        if len(options) < 2:
            raise ValueError(f"Record {index}: MCQ/MSQ requires at least two options")
        option_ids = [item.get("id") for item in options]
        if len(option_ids) != len(set(option_ids)):
            raise ValueError(f"Record {index}: option IDs must be unique")
    elif options:
        raise ValueError(f"Record {index}: NAT questions cannot have options")

    source_kind = QuestionSource(record["source_kind"])
    if source_kind == QuestionSource.PREVIOUS_YEAR:
        provenance = {
            "source_year",
            "source_paper",
            "source_question_number",
            "source_url",
            "answer_key_url",
        }
        missing_provenance = [field for field in provenance if not record.get(field)]
        if missing_provenance:
            raise ValueError(
                f"Record {index}: previous-year question missing provenance: "
                f"{', '.join(sorted(missing_provenance))}"
            )


async def import_records(path: Path, *, dry_run: bool, update: bool) -> tuple[int, int]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("Import file must contain a JSON array")
    for index, record in enumerate(raw, start=1):
        if not isinstance(record, dict):
            raise ValueError(f"Record {index}: expected an object")
        validate_record(record, index)

    await create_database_schema()
    created = skipped = 0
    async with AsyncSessionFactory() as session:
        for index, record in enumerate(raw, start=1):
            subject = await session.scalar(
                select(Subject).where(Subject.slug == record["subject_slug"])
            )
            if subject is None:
                raise ValueError(
                    f"Record {index}: unknown subject_slug {record['subject_slug']!r}"
                )
            topic = await session.scalar(
                select(Topic).where(
                    Topic.subject_id == subject.id,
                    Topic.slug == record["topic_slug"],
                )
            )
            if topic is None:
                raise ValueError(
                    f"Record {index}: unknown topic_slug {record['topic_slug']!r} "
                    f"for {subject.slug}"
                )

            source_kind = QuestionSource(record["source_kind"])
            existing = None
            if source_kind == QuestionSource.PREVIOUS_YEAR:
                existing = await session.scalar(
                    select(Question).where(
                        Question.source_kind == source_kind,
                        Question.source_year == int(record["source_year"]),
                        Question.source_paper == record["source_paper"],
                        Question.source_question_number
                        == int(record["source_question_number"]),
                    )
                )
            if existing is not None and not update:
                skipped += 1
                continue

            question = existing or Question(subject=subject, topic=topic)
            question.subject = subject
            question.topic = topic
            question.source = source_kind
            question.year = record.get("source_year")
            question.exam_session = record.get("source_paper")
            question.source_kind = source_kind
            question.source_year = record.get("source_year")
            question.source_paper = record.get("source_paper")
            question.source_question_number = record.get("source_question_number")
            question.source_url = record.get("source_url")
            question.answer_key_url = record.get("answer_key_url")
            question.question_type = QuestionType(record["question_type"])
            question.difficulty = Difficulty(record.get("difficulty", "medium"))
            question.text = str(record["text"]).strip()
            question.options = record.get("options", [])
            question.correct_answer = record["correct_answer"]
            question.numerical_tolerance = float(record.get("numerical_tolerance", 0.01))
            question.marks = int(record["marks"])
            question.explanation = str(record["explanation"]).strip()
            question.tags = record.get("tags", [])
            session.add(question)
            created += 1

        if dry_run:
            await session.rollback()
        else:
            await session.commit()
    return created, skipped


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate and import topic-mapped GATE questions from JSON."
    )
    parser.add_argument("path", type=Path, help="Path to a JSON array of questions")
    parser.add_argument(
        "--dry-run", action="store_true", help="Validate and resolve mappings without committing"
    )
    parser.add_argument(
        "--update", action="store_true", help="Update a question with matching provenance"
    )
    return parser.parse_args()


async def async_main() -> int:
    args = parse_args()
    try:
        created, skipped = await import_records(
            args.path.resolve(), dry_run=args.dry_run, update=args.update
        )
        action = "validated" if args.dry_run else "imported"
        print(f"{action}: {created}; skipped existing: {skipped}")
        return 0
    finally:
        await close_database()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(async_main()))
