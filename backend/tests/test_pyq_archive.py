from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import (
    PyqArchiveImport,
    PyqSourcePaper,
    PyqSourceQuestion,
    Question,
    QuestionSource,
)
from app.pyq_archive import PyqArchiveValidationError, import_pyq_archive
from app.seed import seed_database


async def _isolated_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _artifact(
    *,
    paper_id: str = "gate-cs-1996-main",
    year: int = 1996,
    artifact_version: str = "archive-test-v1",
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "artifact_version": artifact_version,
        "papers": [
            {
                "id": paper_id,
                "year": year,
                "session_label": "main",
                "display_name": f"GATE CS {year}",
                "expected_item_count": 2,
                "source_pdf_sha256": "a" * 64,
                "source_status": "verified",
                "source_url": f"https://example.test/{paper_id}.pdf",
            }
        ],
        "questions": [
            {
                "source_paper_id": paper_id,
                "item_label": "1.1",
                "ordinal": 1,
                "source_page": 2,
                "marks": 1,
                "item_type": "mcq",
                "question_md": "Which connective is true only when both inputs are true?",
                "options": ["AND", "OR", "XOR", "NOT"],
                "accepted_answers": "A",
                "solution_md": "Conjunction requires both inputs to be true.",
                "subject_code": "EM",
                "topic_slug": "discrete-mathematics",
                "syllabus_status": "in_syllabus",
                "transcription_status": "verified",
                "answer_status": "community_verified",
                "classification_status": "verified",
                "practice_eligible": True,
                "extraction_method": "pdf-text+visual-review",
                "extraction_confidence": 1.0,
            },
            {
                "source_paper_id": paper_id,
                "item_label": "24-b",
                "ordinal": 2,
                "parent_item_label": "24",
                "source_page": 15,
                "marks": 5,
                "item_type": "descriptive",
                "question_md": "Draw and justify the requested state diagram.",
                "solution_md": "A descriptive rubric is retained in the archive.",
                "syllabus_status": "review_required",
                "transcription_status": "verified",
                "answer_status": "community_verified",
                "classification_status": "review_required",
                "practice_eligible": False,
                "review_flags": ["descriptive_not_auto_gradable"],
            },
        ],
    }


def _write(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_archive_dry_run_is_non_mutating_and_apply_preserves_originals(
    tmp_path: Path,
) -> None:
    engine, factory = await _isolated_session()
    path = tmp_path / "archive.json"
    _write(path, _artifact())

    async with factory() as session:
        await seed_database(session)
        originals_before = int(
            await session.scalar(
                select(func.count(Question.id)).where(
                    Question.source_kind == QuestionSource.ORIGINAL,
                    Question.is_active.is_(True),
                )
            )
            or 0
        )

        preview = await import_pyq_archive(
            session,
            path,
            dry_run=True,
            materialize=True,
        )
        assert preview.dry_run is True
        assert preview.inserted_count == 3
        assert preview.materialized_count == 1
        assert await session.scalar(select(func.count(PyqSourcePaper.id))) == 0
        assert await session.scalar(select(func.count(PyqSourceQuestion.id))) == 0

        applied = await import_pyq_archive(
            session,
            path,
            dry_run=False,
            materialize=True,
        )
        assert applied.dry_run is False
        assert applied.paper_count == 1
        assert applied.item_count == 2
        assert applied.inserted_count == 3
        assert applied.materialized_count == 1
        assert applied.retired_count == 0
        assert applied.original_active_count == originals_before

        source_items = list(
            (
                await session.scalars(
                    select(PyqSourceQuestion).order_by(PyqSourceQuestion.ordinal)
                )
            ).all()
        )
        assert [item.item_label for item in source_items] == ["1.1", "24-b"]
        assert source_items[0].materialized_question_id is not None
        assert source_items[1].materialized_question_id is None
        materialized = await session.get(
            Question, source_items[0].materialized_question_id
        )
        assert materialized is not None
        assert materialized.source_paper_id == "gate-cs-1996-main"
        assert materialized.source_item_label == "1.1"
        assert materialized.source_question_number == 1
        assert materialized.bank_version is None
        assert materialized.correct_answer == "A"
        assert await session.scalar(select(func.count(PyqArchiveImport.id))) == 1

        repeat = await import_pyq_archive(
            session,
            path,
            dry_run=True,
            materialize=True,
        )
        assert repeat.already_applied is True
        assert repeat.inserted_count == 0
        assert repeat.updated_count == 0
        assert repeat.materialized_count == 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_archive_rejects_missing_slots_and_unverified_practice(
    tmp_path: Path,
) -> None:
    engine, factory = await _isolated_session()
    path = tmp_path / "invalid.json"

    missing = _artifact()
    missing["questions"] = list(missing["questions"])[:1]
    _write(path, missing)
    async with factory() as session:
        await seed_database(session)
        with pytest.raises(PyqArchiveValidationError, match="expected 2 items"):
            await import_pyq_archive(session, path)
        assert await session.scalar(select(func.count(PyqSourcePaper.id))) == 0

    unverified = _artifact()
    unverified["questions"][0]["transcription_status"] = "review_required"
    _write(path, unverified)
    async with factory() as session:
        with pytest.raises(
            PyqArchiveValidationError,
            match="transcription is not verified",
        ):
            await import_pyq_archive(session, path)
        assert await session.scalar(select(func.count(PyqSourcePaper.id))) == 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_archive_version_is_immutable_and_import_is_paper_scoped(
    tmp_path: Path,
) -> None:
    engine, factory = await _isolated_session()
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"
    first = _artifact()
    second = _artifact(
        paper_id="gate-cs-1997-main",
        year=1997,
        artifact_version="archive-test-v2",
    )
    _write(first_path, first)
    _write(second_path, second)

    async with factory() as session:
        await seed_database(session)
        await import_pyq_archive(
            session, first_path, dry_run=False, materialize=True
        )
        first_question = await session.scalar(
            select(Question).where(
                Question.source_paper_id == "gate-cs-1996-main"
            )
        )
        assert first_question is not None and first_question.is_active is True

        await import_pyq_archive(
            session, second_path, dry_run=False, materialize=True
        )
        await session.refresh(first_question)
        assert first_question.is_active is True

        changed_same_version = deepcopy(first)
        changed_same_version["questions"][0]["question_md"] += " Changed."
        _write(first_path, changed_same_version)
        with pytest.raises(
            PyqArchiveValidationError,
            match="different checksum",
        ):
            await import_pyq_archive(session, first_path, dry_run=False)
    await engine.dispose()
