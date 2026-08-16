from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.pyq_archive as pyq_archive_module
from app.database import Base
from app.models import (
    Difficulty,
    PyqArchiveExecution,
    PyqArchiveImport,
    PyqSourcePaper,
    PyqSourceQuestion,
    Question,
    QuestionSource,
    QuestionType,
    Subject,
    TestForm as CatalogForm,
    Topic,
)
from app.api import list_questions
from app.pyq_archive import (
    ArchivePaper,
    ArchiveQuestion,
    PyqArchiveValidationError,
    _content_sha256,
    _legacy_candidate_fingerprint,
    _load_legacy_collision_adoptions,
    _load_pyq_visibility_plan,
    _select_evidence_backed_collision_candidate,
    import_pyq_archive,
    restore_pyq_visibility,
)
from app.question_bank import import_question_bank
from app.seed import seed_database
from app.test_catalog import rebuild_test_catalog, validate_test_catalog


QUESTION_BANK_PATH = Path(__file__).resolve().parents[1] / "data" / "question_bank.json"
COLLISION_EVIDENCE_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "pyq_legacy_collision_adoptions.json"
)
COLLISION_CLEANUP_PLAN_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "pyq_legacy_collision_cleanup_plan.json"
)
PRACTICE_ARCHIVE_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "gate_cs_pyq_practice_1996_2025.json"
)


async def _isolated_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _active_original_count(session) -> int:
    return int(
        await session.scalar(
            select(func.count(Question.id)).where(
                Question.source_kind == QuestionSource.ORIGINAL,
                Question.is_active.is_(True),
            )
        )
        or 0
    )


async def _active_pyq_count(session) -> int:
    return int(
        await session.scalar(
            select(func.count(Question.id)).where(
                Question.source_kind == QuestionSource.PREVIOUS_YEAR,
                Question.is_active.is_(True),
            )
        )
        or 0
    )


async def _api_visible_pyq_identities(session) -> set[tuple[str, str, int]]:
    identities: set[tuple[str, str, int]] = set()
    offset = 0
    total: int | None = None
    while total is None or offset < total:
        page = await list_questions(
            subject_id=None,
            subject_slug=None,
            topic_id=None,
            source=None,
            source_kind=QuestionSource.PREVIOUS_YEAR,
            year=None,
            question_type=None,
            difficulty=None,
            search=None,
            limit=100,
            offset=offset,
            db=session,
        )
        total = page.total
        identities.update(
            (
                item.source_paper_id,
                item.source_item_label,
                item.source_question_number,
            )
            for item in page.items
            if item.source_paper_id is not None
            and item.source_item_label is not None
            and item.source_question_number is not None
        )
        offset += len(page.items)
        if not page.items:
            break
    assert total == len(identities)
    return identities


async def _minimal_catalog(session) -> tuple[Subject, Topic]:
    subject = Subject(
        slug="engineering-mathematics",
        code="EM",
        name="Engineering Mathematics",
        description="Test subject",
        order_index=1,
    )
    session.add(subject)
    await session.flush()
    topic = Topic(
        subject_id=subject.id,
        slug="discrete-mathematics",
        name="Discrete Mathematics",
        description="Test topic",
        order_index=1,
    )
    session.add(topic)
    await session.commit()
    return subject, topic


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
                "assets": [
                    {
                        "kind": "stem_diagram",
                        "path": (
                            f"tmp/pyq/build/figure-assets/{paper_id}/"
                            "verified-stem-diagram.png"
                        ),
                        "alt": "Truth-table diagram for the conjunction question.",
                        "sha256": "c" * 64,
                    }
                ],
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
        generated = await session.scalar(
            select(Question)
            .where(Question.source_kind == QuestionSource.ORIGINAL)
            .order_by(Question.id)
        )
        assert generated is not None
        generated.external_id = "generated-original-sentinel"
        generated.bank_version = "generated-bank-v1"
        await session.commit()
        generated_snapshot = {
            "id": generated.id,
            "external_id": generated.external_id,
            "bank_version": generated.bank_version,
            "subject_id": generated.subject_id,
            "topic_id": generated.topic_id,
            "source_kind": generated.source_kind,
            "text": generated.text,
            "correct_answer": generated.correct_answer,
            "is_active": generated.is_active,
        }
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
            expected_original_count=originals_before,
        )
        assert applied.dry_run is False
        assert applied.paper_count == 1
        assert applied.item_count == 2
        assert applied.inserted_count == 3
        assert applied.materialized_count == 1
        assert applied.materialized_inserted_count == 1
        assert applied.materialized_adopted_count == 0
        assert applied.materialized_updated_count == 0
        assert applied.retired_count == 0
        assert applied.original_active_count == originals_before
        assert applied.execution_id is not None

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
        assert materialized.assets == [
            {
                "role": "stem_diagram",
                "url": (
                    "/question-assets/pyq/gate-cs-1996-main/"
                    f"{'c' * 64}.png"
                ),
                "alt_text": "Truth-table diagram for the conjunction question.",
                "sha256": "c" * 64,
            }
        ]
        assert await session.scalar(select(func.count(PyqArchiveImport.id))) == 1
        assert await session.scalar(select(func.count(PyqArchiveExecution.id))) == 1

        await session.refresh(generated)
        assert {
            "id": generated.id,
            "external_id": generated.external_id,
            "bank_version": generated.bank_version,
            "subject_id": generated.subject_id,
            "topic_id": generated.topic_id,
            "source_kind": generated.source_kind,
            "text": generated.text,
            "correct_answer": generated.correct_answer,
            "is_active": generated.is_active,
        } == generated_snapshot

        repeat = await import_pyq_archive(
            session,
            path,
            dry_run=False,
            materialize=True,
            expected_original_count=originals_before,
        )
        assert repeat.already_applied is True
        assert repeat.inserted_count == 0
        assert repeat.updated_count == 0
        assert repeat.materialized_count == 0
        assert repeat.retired_count == 0
        assert repeat.execution_id is not None
        assert repeat.execution_id != applied.execution_id
        assert await session.scalar(select(func.count(PyqArchiveImport.id))) == 1
        assert await session.scalar(select(func.count(PyqArchiveExecution.id))) == 2
        assert (
            await session.scalar(
                select(func.count(Question.id)).where(
                    Question.source_paper_id == "gate-cs-1996-main"
                )
            )
            == 1
        )
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
        originals_before = await _active_original_count(session)
        await import_pyq_archive(
            session,
            first_path,
            dry_run=False,
            materialize=True,
            expected_original_count=originals_before,
        )
        first_question = await session.scalar(
            select(Question).where(
                Question.source_paper_id == "gate-cs-1996-main"
            )
        )
        assert first_question is not None and first_question.is_active is True

        await import_pyq_archive(
            session,
            second_path,
            dry_run=False,
            materialize=True,
            expected_original_count=originals_before,
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
            await import_pyq_archive(
                session,
                first_path,
                dry_run=False,
                expected_original_count=originals_before,
            )
        assert await session.scalar(select(func.count(PyqArchiveImport.id))) == 2
        await session.refresh(first_question)
        assert first_question.text == first["questions"][0]["question_md"]
    await engine.dispose()


@pytest.mark.asyncio
async def test_live_apply_requires_a_pinned_original_count_before_mutation(
    tmp_path: Path,
) -> None:
    engine, factory = await _isolated_session()
    path = tmp_path / "guarded.json"
    _write(path, _artifact(artifact_version="archive-guarded-v1"))

    async with factory() as session:
        with pytest.raises(
            PyqArchiveValidationError,
            match="require expected_original_count",
        ):
            await import_pyq_archive(session, path, dry_run=False)
        assert await session.scalar(select(func.count(PyqSourcePaper.id))) == 0
        assert await session.scalar(select(func.count(PyqSourceQuestion.id))) == 0
        assert await session.scalar(select(func.count(PyqArchiveImport.id))) == 0
        assert await session.scalar(select(func.count(PyqArchiveExecution.id))) == 0

        unsafe = await import_pyq_archive(
            session,
            path,
            dry_run=False,
            unsafe_allow_unpinned_original_count=True,
        )
        assert unsafe.execution_id is not None
        execution = await session.get(PyqArchiveExecution, unsafe.execution_id)
        assert execution is not None
        assert execution.original_guard_bypassed is True
        assert execution.expected_original_count is None
    await engine.dispose()


@pytest.mark.asyncio
async def test_reused_artifact_logs_each_execution_and_split_preview_counts(
    tmp_path: Path,
) -> None:
    engine, factory = await _isolated_session()
    path = tmp_path / "reused.json"
    payload = _artifact(artifact_version="archive-reused-v1")
    _write(path, payload)

    async with factory() as session:
        await _minimal_catalog(session)
        archived = await import_pyq_archive(
            session,
            path,
            dry_run=False,
            expected_original_count=0,
        )
        assert archived.materialized_count == 0

        materialized = await import_pyq_archive(
            session,
            path,
            dry_run=False,
            materialize=True,
            expected_original_count=0,
        )
        assert materialized.materialized_inserted_count == 1
        assert materialized.materialized_adopted_count == 0
        assert materialized.materialized_updated_count == 0
        assert await session.scalar(select(func.count(PyqArchiveImport.id))) == 1

        executions = list(
            (
                await session.scalars(
                    select(PyqArchiveExecution).order_by(PyqArchiveExecution.id)
                )
            ).all()
        )
        assert [event.execution_mode for event in executions] == [
            "archive_only",
            "materialize",
        ]
        assert executions[0].archive_import_id == executions[1].archive_import_id
        assert executions[1].materialized_inserted_count == 1

        changed = deepcopy(payload)
        changed["artifact_version"] = "archive-reused-v2"
        changed["questions"][0]["question_md"] += " Updated after review."
        changed_path = tmp_path / "reused-v2.json"
        _write(changed_path, changed)
        preview = await import_pyq_archive(
            session,
            changed_path,
            materialize=True,
        )
        assert preview.materialized_inserted_count == 0
        assert preview.materialized_adopted_count == 0
        assert preview.materialized_updated_count == 1
        assert preview.execution_id is None
        assert await session.scalar(select(func.count(PyqArchiveExecution.id))) == 2
    await engine.dispose()


@pytest.mark.asyncio
async def test_retirement_requires_exact_reviewed_guards_and_preview_is_read_only(
    tmp_path: Path,
) -> None:
    engine, factory = await _isolated_session()
    first_path = tmp_path / "retire-v1.json"
    second_path = tmp_path / "retire-v2.json"
    first = _artifact(artifact_version="archive-retire-v1")
    second = _artifact(artifact_version="archive-retire-v2")
    second["questions"][0]["practice_eligible"] = False
    second["questions"][0]["review_flags"] = ["retirement_review"]
    _write(first_path, first)
    _write(second_path, second)

    async with factory() as session:
        await _minimal_catalog(session)
        await import_pyq_archive(
            session,
            first_path,
            dry_run=False,
            materialize=True,
            expected_original_count=0,
        )
        source_item = await session.scalar(
            select(PyqSourceQuestion).where(PyqSourceQuestion.ordinal == 1)
        )
        assert source_item is not None
        materialized = await session.get(Question, source_item.materialized_question_id)
        assert materialized is not None and materialized.is_active is True

        preview = await import_pyq_archive(
            session,
            second_path,
            materialize=True,
        )
        assert preview.retired_count == 1
        assert preview.retirement_approval_required is True
        assert preview.active_pyq_count_before == 1
        assert preview.active_pyq_count_after == 0
        await session.refresh(source_item)
        await session.refresh(materialized)
        assert source_item.practice_eligible is True
        assert materialized.is_active is True
        assert await session.scalar(select(func.count(PyqArchiveImport.id))) == 1

        with pytest.raises(PyqArchiveValidationError, match="would retire 1"):
            await import_pyq_archive(
                session,
                second_path,
                dry_run=False,
                materialize=True,
                expected_original_count=0,
            )
        await session.refresh(source_item)
        await session.refresh(materialized)
        assert source_item.practice_eligible is True
        assert materialized.is_active is True
        assert await session.scalar(select(func.count(PyqArchiveImport.id))) == 1

        with pytest.raises(
            PyqArchiveValidationError,
            match="exact reviewed promotion artifact",
        ):
            await import_pyq_archive(
                session,
                second_path,
                dry_run=False,
                materialize=True,
                expected_original_count=0,
                allow_retire=True,
                expected_retirement_count=2,
                expected_active_pyqs_before=1,
                expected_active_pyqs_after=0,
            )
        assert materialized.is_active is True
        assert await session.scalar(select(func.count(PyqArchiveExecution.id))) == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_archive_adopts_exact_2024_session_5_alias_without_duplication(
    tmp_path: Path,
) -> None:
    """The 14 reviewed overlaps adopt; four seed-only rows remain untouched."""

    engine, factory = await _isolated_session()
    path = tmp_path / "exact-production-alias.json"
    payload = _artifact(
        paper_id="gate-cs-2024-set-1",
        year=2024,
        artifact_version="archive-exact-production-alias-v1",
    )
    paper = payload["papers"][0]
    paper["session_label"] = "set-1"
    paper["display_name"] = "GATE CS 2024 Set 1"
    paper["expected_item_count"] = 18
    template = deepcopy(payload["questions"][0])
    questions: list[dict[str, object]] = []
    for ordinal in range(1, 19):
        question = deepcopy(template)
        question.update(
            {
                "source_paper_id": paper["id"],
                "item_label": f"CS-{ordinal}",
                "ordinal": ordinal,
                "legacy_source_ordinals": [ordinal],
                "question_md": f"Reviewed canonical question {ordinal}?",
                "solution_md": f"Reviewed canonical solution {ordinal}.",
                "practice_eligible": ordinal <= 14,
                "review_flags": [] if ordinal <= 14 else ["seed_only_unreviewed"],
            }
        )
        questions.append(question)
    payload["questions"] = questions
    _write(path, payload)

    async with factory() as session:
        subject, topic = await _minimal_catalog(session)
        legacy_rows: list[Question] = []
        for ordinal in range(1, 19):
            legacy_rows.append(
                Question(
                    external_id=f"legacy-gate-2024-session-5-{ordinal}",
                    bank_version="legacy-pyq-2017-2025-v1",
                    is_active=True,
                    subject_id=subject.id,
                    topic_id=topic.id,
                    source=QuestionSource.PREVIOUS_YEAR,
                    year=2024,
                    exam_session="CS1",
                    source_kind=QuestionSource.PREVIOUS_YEAR,
                    source_year=2024,
                    source_paper="GATE 2024 CS1 (Session 5)",
                    source_question_number=ordinal,
                    source_url="https://legacy.example.test/cs1.pdf",
                    answer_key_url="https://legacy.example.test/cs1-key.pdf",
                    extraction_method="verified-legacy-import",
                    extraction_confidence=1.0,
                    question_type=QuestionType.MCQ,
                    difficulty=Difficulty.MEDIUM,
                    text=f"Legacy transcription {ordinal}.",
                    options=[
                        {"id": "A", "text": "AND"},
                        {"id": "B", "text": "OR"},
                        {"id": "C", "text": "XOR"},
                        {"id": "D", "text": "NOT"},
                    ],
                    correct_answer="A",
                    numerical_tolerance=0.01,
                    marks=1,
                    explanation="Legacy verified explanation.",
                    tags=["official-pyq", "gate-2024"],
                )
            )
        session.add_all(legacy_rows)
        await session.commit()
        legacy_ids = [row.id for row in legacy_rows]

        result = await import_pyq_archive(
            session,
            path,
            dry_run=False,
            materialize=True,
            expected_original_count=0,
        )
        assert result.materialized_count == 14
        assert result.materialized_inserted_count == 0
        assert result.materialized_adopted_count == 14
        assert result.materialized_updated_count == 0
        assert int(await session.scalar(select(func.count(Question.id))) or 0) == 18

        source_items = list(
            (
                await session.scalars(
                    select(PyqSourceQuestion).order_by(PyqSourceQuestion.ordinal)
                )
            ).all()
        )
        assert [row.materialized_question_id for row in source_items[:14]] == (
            legacy_ids[:14]
        )
        assert all(row.materialized_question_id is None for row in source_items[14:])
        for ordinal, legacy_id in enumerate(legacy_ids, start=1):
            legacy = await session.get(Question, legacy_id)
            assert legacy is not None and legacy.is_active is True
            if ordinal <= 14:
                assert legacy.source_paper_id == "gate-cs-2024-set-1"
                assert legacy.external_id == f"pyq:gate-cs-2024-set-1:cs-{ordinal}"
            else:
                assert legacy.source_paper_id is None
                assert legacy.external_id == f"legacy-gate-2024-session-5-{ordinal}"
    await engine.dispose()


@pytest.mark.asyncio
async def test_reviewed_2024_collisions_are_exactly_bound_and_fail_closed() -> None:
    """All 13 production-shaped pairs match evidence; any row drift is fatal."""

    engine, factory = await _isolated_session()
    try:
        async with factory() as session:
            await seed_database(session)
            imported = await import_question_bank(session, QUESTION_BANK_PATH)
            assert imported.bank_version == "gate-cs-2027-v1"
            assert await _active_original_count(session) == 2290
            assert await _active_pyq_count(session) == 405

            subjects = list((await session.scalars(select(Subject))).all())
            topics = list((await session.scalars(select(Topic))).all())
            subject_codes = {
                subject.id: subject.code.upper() for subject in subjects
            }
            topic_slugs = {topic.id: topic.slug for topic in topics}
            candidates = list(
                (
                    await session.scalars(
                        select(Question).where(
                            Question.source_year == 2024,
                            Question.source_kind == QuestionSource.PREVIOUS_YEAR,
                        )
                    )
                ).all()
            )
            evidence = _load_legacy_collision_adoptions()
            assert sorted(key[1] for key in evidence) == [
                12,
                13,
                17,
                21,
                22,
                23,
                24,
                25,
                26,
                27,
                29,
                30,
                31,
            ]

            paper = ArchivePaper.model_validate(
                {
                    "id": "gate-cs-2024-set-1",
                    "year": 2024,
                    "session_label": "set-1",
                    "display_name": "GATE CS 2024 Set 1",
                    "expected_item_count": 65,
                    "source_pdf_sha256": (
                        "18cf9ac15c01bdbf9d767c7a402d63234a28ae91c8ec227090ba5a5fdef121dd"
                    ),
                    "answer_key_sha256": (
                        "f713276ef5a4cc59d6c5925ba7e4c72f6f669ab6866956cc45cb8f3e0f5817cf"
                    ),
                    "source_aliases": ["CS1-2024"],
                    "source_status": "verified",
                }
            )
            selected_by_ordinal: dict[int, Question] = {}
            preserved_by_ordinal: dict[int, Question] = {}
            for key, adoption in sorted(evidence.items()):
                pair = [
                    candidate
                    for candidate in candidates
                    if candidate.source_question_number == adoption.ordinal
                    and candidate.source_paper
                    in {"CS1-2024", "GATE 2024 CS1 (Session 5)"}
                ]
                assert len(pair) == 2
                by_fingerprint = {
                    _legacy_candidate_fingerprint(
                        candidate,
                        subject_codes_by_id=subject_codes,
                        topic_slugs_by_id=topic_slugs,
                    ): candidate
                    for candidate in pair
                }
                assert set(by_fingerprint) == {
                    adoption.selected_pre_adoption_fingerprint_sha256,
                    *adoption.preserved_duplicate_fingerprint_sha256s,
                }
                selected = by_fingerprint[
                    adoption.selected_pre_adoption_fingerprint_sha256
                ]
                preserved = next(
                    by_fingerprint[fingerprint]
                    for fingerprint in adoption.preserved_duplicate_fingerprint_sha256s
                )
                assert selected.external_id == (
                    f"gate-cs1-2024-q{adoption.ordinal:02d}"
                )
                assert selected.bank_version == "gate-cs-2027-v1"
                assert preserved.external_id is None
                assert preserved.bank_version is None
                assert selected.question_type == preserved.question_type
                assert selected.correct_answer == preserved.correct_answer
                assert selected.marks == preserved.marks
                assert selected.source_url == preserved.source_url
                assert selected.answer_key_url == preserved.answer_key_url
                selected_by_ordinal[adoption.ordinal] = selected
                preserved_by_ordinal[adoption.ordinal] = preserved

            adoption = evidence[(paper.id, 12)]
            selected = selected_by_ordinal[12]
            preserved = preserved_by_ordinal[12]
            item = ArchiveQuestion.model_validate(
                {
                    "source_paper_id": paper.id,
                    "item_label": adoption.item_label,
                    "ordinal": 12,
                }
            )
            materialized_values = {
                "external_id": "pyq:gate-cs-2024-set-1:cs-2",
                "question_type": selected.question_type,
                "text": selected.text,
                "options": selected.options,
                "correct_answer": selected.correct_answer,
                "marks": selected.marks,
            }
            resolved = _select_evidence_backed_collision_candidate(
                paper=paper,
                item=item,
                materialized_values=materialized_values,
                candidates={candidate.id: candidate for candidate in (selected, preserved)},
                subject_codes_by_id=subject_codes,
                topic_slugs_by_id=topic_slugs,
            )
            assert resolved.id == selected.id

            original_preserved_text = preserved.text
            preserved.text += " unreviewed drift"
            with pytest.raises(
                PyqArchiveValidationError,
                match="preserved legacy duplicate drifted",
            ):
                _select_evidence_backed_collision_candidate(
                    paper=paper,
                    item=item,
                    materialized_values=materialized_values,
                    candidates={
                        candidate.id: candidate for candidate in (selected, preserved)
                    },
                    subject_codes_by_id=subject_codes,
                    topic_slugs_by_id=topic_slugs,
                )
            preserved.text = original_preserved_text

            unknown_item = item.model_copy(
                update={"item_label": "CS-1", "ordinal": 11}
            )
            with pytest.raises(
                PyqArchiveValidationError,
                match="multiple existing PYQs",
            ):
                _select_evidence_backed_collision_candidate(
                    paper=paper,
                    item=unknown_item,
                    materialized_values=materialized_values,
                    candidates={
                        candidate.id: candidate for candidate in (selected, preserved)
                    },
                    subject_codes_by_id=subject_codes,
                    topic_slugs_by_id=topic_slugs,
                )
    finally:
        await engine.dispose()


def test_visibility_plan_is_exact_bound_and_carries_both_content_hashes() -> None:
    plan = json.loads(COLLISION_CLEANUP_PLAN_PATH.read_text(encoding="utf-8"))
    runtime = _load_pyq_visibility_plan()
    plan_sha256 = hashlib.sha256(COLLISION_CLEANUP_PLAN_PATH.read_bytes()).hexdigest()
    assert runtime.plan_sha256 == plan_sha256
    assert plan["schema_version"] == "2.0"
    assert plan["status"] == "authorized_opt_in_only"
    assert plan["database_writes_performed"] is False
    evidence_sha256 = hashlib.sha256(COLLISION_EVIDENCE_PATH.read_bytes()).hexdigest()
    assert plan["bindings"]["collision_evidence"]["file_sha256"] == evidence_sha256
    guards = plan["guards"]
    assert guards == {
        "expected_question_rows": 2695,
        "expected_pyq_rows": 405,
        "expected_active_originals": 2290,
        "expected_active_pyqs_before": 405,
        "expected_retirements": 228,
        "expected_active_pyqs_after": 177,
        "archive_record_count": 2873,
        "practice_eligible_count": 177,
        "delete_rows": False,
    }
    assert plan["recovery"] == {
        "expected_active_originals": 2290,
        "expected_active_pyqs_before": 177,
        "expected_reactivations": 228,
        "expected_active_pyqs_after": 405,
        "delete_rows": False,
    }
    assert len(plan["keep_targets"]) == 177
    assert len(plan["retire_targets"]) == 228
    assert len(runtime.keep_external_ids) == 177
    assert len(runtime.retire_fingerprints) == 228
    # Promotion toggles practice_eligible, which is part of the content hash.
    # Both the staging/source and promoted hashes must therefore be retained
    # and independently verified for every selected identity.
    assert all(
        entry["source_content_sha256"] != entry["promoted_content_sha256"]
        for entry in plan["keep_targets"]
    )


@pytest.mark.parametrize("binding_name", ["source_archive", "promotion_artifact"])
def test_visibility_plan_rejects_tampered_source_or_promoted_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    binding_name: str,
) -> None:
    plan = json.loads(COLLISION_CLEANUP_PLAN_PATH.read_text(encoding="utf-8"))
    binding = plan["bindings"][binding_name]
    bound_path = Path(__file__).resolve().parents[1] / binding["path"]
    tampered = json.loads(bound_path.read_text(encoding="utf-8"))
    selected_keys = {
        (entry["source_paper_id"], entry["ordinal"])
        for entry in plan["keep_targets"]
    }
    selected = next(
        item
        for item in tampered["questions"]
        if (item["source_paper_id"], item["ordinal"]) in selected_keys
    )
    selected["question_md"] += " tampered"
    tampered_path = tmp_path / f"{binding_name}.json"
    tampered_path.write_text(
        json.dumps(tampered, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    plan["bindings"][binding_name]["path"] = str(tampered_path)
    plan_path = tmp_path / "visibility-plan.json"
    plan_path.write_text(
        json.dumps(plan, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(pyq_archive_module, "PYQ_VISIBILITY_PLAN_PATH", plan_path)
    monkeypatch.setattr(
        pyq_archive_module,
        "PYQ_VISIBILITY_PLAN_SHA256",
        hashlib.sha256(plan_path.read_bytes()).hexdigest(),
    )
    pyq_archive_module._load_pyq_visibility_plan.cache_clear()
    with pytest.raises(PyqArchiveValidationError, match="binding checksum drifted"):
        pyq_archive_module._load_pyq_visibility_plan()
    pyq_archive_module._load_pyq_visibility_plan.cache_clear()


@pytest.mark.asyncio
async def test_guarded_visibility_cleanup_api_equality_catalog_and_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, factory = await _isolated_session()
    try:
        async with factory() as session:
            await seed_database(session)
            await import_question_bank(session, QUESTION_BANK_PATH)
            await rebuild_test_catalog(session)
            initial = await import_pyq_archive(
                session,
                PRACTICE_ARCHIVE_PATH,
                dry_run=False,
                materialize=True,
                expected_original_count=2290,
            )
            assert initial.materialized_adopted_count == 177
            assert initial.materialized_inserted_count == 0
            assert initial.active_pyq_count_after == 405
            # Adoption changes stable question identities, so establish the
            # canonical 405-row derived catalog used for recovery symmetry.
            await rebuild_test_catalog(session)
            await validate_test_catalog(session)
            baseline_forms = {
                form.id: list(form.question_ids or [])
                for form in (await session.scalars(select(CatalogForm))).all()
            }

            preview = await import_pyq_archive(
                session,
                PRACTICE_ARCHIVE_PATH,
                materialize=True,
                expected_original_count=2290,
                allow_retire=True,
                expected_retirement_count=228,
                expected_active_pyqs_before=405,
                expected_active_pyqs_after=177,
            )
            assert preview.dry_run is True
            assert preview.retired_count == 228
            assert preview.active_pyq_count_before == 405
            assert preview.active_pyq_count_after == 177
            assert await _active_pyq_count(session) == 405
            assert await session.scalar(select(func.count(PyqArchiveExecution.id))) == 1

            with pytest.raises(
                PyqArchiveValidationError,
                match="guards do not equal",
            ):
                await import_pyq_archive(
                    session,
                    PRACTICE_ARCHIVE_PATH,
                    dry_run=False,
                    materialize=True,
                    expected_original_count=2290,
                    allow_retire=True,
                    expected_retirement_count=227,
                    expected_active_pyqs_before=405,
                    expected_active_pyqs_after=178,
                )

            original_catalog_validator = pyq_archive_module.validate_test_catalog

            async def _fail_catalog_validation(_session) -> None:
                raise ValueError("injected catalog failure")

            monkeypatch.setattr(
                pyq_archive_module,
                "validate_test_catalog",
                _fail_catalog_validation,
            )
            with pytest.raises(
                PyqArchiveValidationError,
                match="catalog rebuild failed",
            ):
                await import_pyq_archive(
                    session,
                    PRACTICE_ARCHIVE_PATH,
                    dry_run=False,
                    materialize=True,
                    expected_original_count=2290,
                    allow_retire=True,
                    expected_retirement_count=228,
                    expected_active_pyqs_before=405,
                    expected_active_pyqs_after=177,
                )
            monkeypatch.setattr(
                pyq_archive_module,
                "validate_test_catalog",
                original_catalog_validator,
            )
            assert await _active_pyq_count(session) == 405
            assert {
                form.id: list(form.question_ids or [])
                for form in (await session.scalars(select(CatalogForm))).all()
            } == baseline_forms
            assert await session.scalar(select(func.count(PyqArchiveExecution.id))) == 1

            cleaned = await import_pyq_archive(
                session,
                PRACTICE_ARCHIVE_PATH,
                dry_run=False,
                materialize=True,
                expected_original_count=2290,
                allow_retire=True,
                expected_retirement_count=228,
                expected_active_pyqs_before=405,
                expected_active_pyqs_after=177,
            )
            plan = _load_pyq_visibility_plan()
            assert cleaned.retired_count == 228
            assert cleaned.visibility_plan_sha256 == plan.plan_sha256
            assert cleaned.active_pyq_count_after == 177
            assert await _active_original_count(session) == 2290
            assert await _active_pyq_count(session) == 177
            assert await session.scalar(select(func.count(Question.id))) == 2695
            assert (
                await session.scalar(select(func.count(PyqSourceQuestion.id)))
                == 2873
            )
            assert await _api_visible_pyq_identities(session) == {
                (
                    entry["source_paper_id"],
                    entry["item_label"],
                    entry["ordinal"],
                )
                for entry in plan.keep_records
            }
            await validate_test_catalog(session)
            inactive_pyq_ids = set(
                (
                    await session.scalars(
                        select(Question.id).where(
                            Question.source_kind == QuestionSource.PREVIOUS_YEAR,
                            Question.is_active.is_(False),
                        )
                    )
                ).all()
            )
            # The pre-cleanup catalog really did contain stale-prone rows; the
            # guarded transaction rebuilt all 364 references away from them.
            assert sum(
                question_id in inactive_pyq_ids
                for question_ids in baseline_forms.values()
                for question_id in question_ids
            ) == 364
            cleaned_forms = list((await session.scalars(select(CatalogForm))).all())
            assert all(
                inactive_pyq_ids.isdisjoint(form.question_ids or [])
                for form in cleaned_forms
            )
            cleanup_execution = await session.get(
                PyqArchiveExecution, cleaned.execution_id
            )
            assert cleanup_execution is not None
            assert cleanup_execution.execution_mode == "materialize_retire"
            assert cleanup_execution.retired_count == 228
            assert cleanup_execution.reactivated_count == 0
            assert cleanup_execution.visibility_plan_sha256 == plan.plan_sha256
            assert cleanup_execution.pyq_active_before == 405
            assert cleanup_execution.pyq_active_after == 177

            with pytest.raises(
                PyqArchiveValidationError,
                match="literal reviewed guard",
            ):
                await import_pyq_archive(
                    session,
                    PRACTICE_ARCHIVE_PATH,
                    dry_run=False,
                    materialize=True,
                    expected_original_count=2290,
                    allow_retire=True,
                    expected_retirement_count=228,
                    expected_active_pyqs_before=405,
                    expected_active_pyqs_after=177,
                )

            normal_repeat = await import_pyq_archive(
                session,
                PRACTICE_ARCHIVE_PATH,
                dry_run=False,
                materialize=True,
                expected_original_count=2290,
            )
            assert normal_repeat.already_applied is True
            assert normal_repeat.materialized_count == 0
            assert normal_repeat.retired_count == 0
            assert normal_repeat.active_pyq_count_before == 177
            assert normal_repeat.active_pyq_count_after == 177

            recovery_preview = await restore_pyq_visibility(
                session,
                PRACTICE_ARCHIVE_PATH,
                expected_original_count=2290,
                expected_reactivation_count=228,
                expected_active_pyqs_before=177,
                expected_active_pyqs_after=405,
            )
            assert recovery_preview.dry_run is True
            assert recovery_preview.reactivated_count == 228
            assert await _active_pyq_count(session) == 177

            restored = await restore_pyq_visibility(
                session,
                PRACTICE_ARCHIVE_PATH,
                dry_run=False,
                expected_original_count=2290,
                expected_reactivation_count=228,
                expected_active_pyqs_before=177,
                expected_active_pyqs_after=405,
            )
            assert restored.reactivated_count == 228
            assert restored.active_pyq_count_after == 405
            assert await _active_original_count(session) == 2290
            assert await _active_pyq_count(session) == 405
            assert await session.scalar(select(func.count(Question.id))) == 2695
            assert (
                await session.scalar(select(func.count(PyqSourceQuestion.id)))
                == 2873
            )
            await validate_test_catalog(session)
            restored_forms = {
                form.id: list(form.question_ids or [])
                for form in (await session.scalars(select(CatalogForm))).all()
            }
            assert restored_forms == baseline_forms
            recovery_execution = await session.get(
                PyqArchiveExecution, restored.execution_id
            )
            assert recovery_execution is not None
            assert recovery_execution.execution_mode == "visibility_restore"
            assert recovery_execution.retired_count == 0
            assert recovery_execution.reactivated_count == 228
            assert recovery_execution.expected_reactivation_count == 228
            assert recovery_execution.visibility_plan_sha256 == plan.plan_sha256
            assert recovery_execution.pyq_active_before == 177
            assert recovery_execution.pyq_active_after == 405

            with pytest.raises(
                PyqArchiveValidationError,
                match="before recovery",
            ):
                await restore_pyq_visibility(
                    session,
                    PRACTICE_ARCHIVE_PATH,
                    dry_run=False,
                    expected_original_count=2290,
                    expected_reactivation_count=228,
                    expected_active_pyqs_before=177,
                    expected_active_pyqs_after=405,
                )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_archive_rejects_same_year_source_alias_shared_by_two_papers(
    tmp_path: Path,
) -> None:
    engine, factory = await _isolated_session()
    path = tmp_path / "ambiguous-alias.json"
    payload = _artifact(artifact_version="archive-ambiguous-alias-v1")
    first_paper = payload["papers"][0]
    first_paper["source_aliases"] = ["CS1-2024"]
    second_paper = deepcopy(first_paper)
    second_paper["id"] = "gate-cs-1996-second"
    second_paper["session_label"] = "second"
    second_paper["display_name"] = "GATE CS 1996 Second"
    second_paper["source_aliases"] = ["cs1 2024"]
    payload["papers"].append(second_paper)
    payload["questions"].extend(
        [
            {
                **deepcopy(item),
                "source_paper_id": second_paper["id"],
            }
            for item in payload["questions"]
        ]
    )
    _write(path, payload)

    async with factory() as session:
        with pytest.raises(PyqArchiveValidationError, match="Ambiguous source alias"):
            await import_pyq_archive(session, path)
        assert await session.scalar(select(func.count(PyqSourcePaper.id))) == 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_archive_rejects_two_items_targeting_one_legacy_source_ordinal(
    tmp_path: Path,
) -> None:
    engine, factory = await _isolated_session()
    path = tmp_path / "ambiguous-legacy-ordinal.json"
    payload = _artifact(artifact_version="archive-ambiguous-legacy-ordinal-v1")
    payload["questions"][0]["legacy_source_ordinals"] = [2]
    _write(path, payload)

    async with factory() as session:
        with pytest.raises(
            PyqArchiveValidationError,
            match="Duplicate legacy source ordinal",
        ):
            await import_pyq_archive(session, path)
        assert await session.scalar(select(func.count(PyqSourcePaper.id))) == 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_archive_rejects_legacy_source_ordinal_outside_paper(
    tmp_path: Path,
) -> None:
    engine, factory = await _isolated_session()
    path = tmp_path / "out-of-range-legacy-ordinal.json"
    payload = _artifact(artifact_version="archive-out-of-range-legacy-v1")
    payload["questions"][0]["legacy_source_ordinals"] = [3]
    _write(path, payload)

    async with factory() as session:
        with pytest.raises(
            PyqArchiveValidationError,
            match="exceeds the paper's audited item count",
        ):
            await import_pyq_archive(session, path)
        assert await session.scalar(select(func.count(PyqSourcePaper.id))) == 0
    await engine.dispose()


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("source_page", 9),
        ("marks", 2),
        ("answer_status", "official"),
        ("classification_status", "out_of_syllabus"),
        ("practice_eligible", True),
        ("review_flags", ["manual_review_required"]),
        (
            "source_references",
            [
                {
                    "kind": "original_question_page",
                    "url": "https://example.test/paper.pdf#page=2",
                    "sha256": "b" * 64,
                }
            ],
        ),
    ],
)
def test_item_checksum_covers_review_and_provenance_fields(
    field: str,
    replacement: object,
) -> None:
    payload = deepcopy(_artifact()["questions"][0])
    payload["practice_eligible"] = False
    item = ArchiveQuestion.model_validate(payload)
    baseline = _content_sha256(item)

    payload[field] = replacement
    changed = ArchiveQuestion.model_validate(payload)

    assert _content_sha256(changed) != baseline


@pytest.mark.asyncio
async def test_archive_never_retires_original_through_a_corrupt_source_link(
    tmp_path: Path,
) -> None:
    engine, factory = await _isolated_session()
    first_path = tmp_path / "linked-v1.json"
    second_path = tmp_path / "linked-v2.json"
    first = _artifact(artifact_version="archive-link-safety-v1")
    _write(first_path, first)

    async with factory() as session:
        await seed_database(session)
        originals_before = await _active_original_count(session)
        await import_pyq_archive(
            session,
            first_path,
            dry_run=False,
            materialize=True,
            expected_original_count=originals_before,
        )
        source_item = await session.scalar(
            select(PyqSourceQuestion).where(PyqSourceQuestion.ordinal == 1)
        )
        generated = await session.scalar(
            select(Question)
            .where(Question.source_kind == QuestionSource.ORIGINAL)
            .order_by(Question.id)
        )
        assert source_item is not None and generated is not None
        original_text = generated.text
        source_item.materialized_question_id = generated.id
        await session.commit()

        second = _artifact(artifact_version="archive-link-safety-v2")
        second["questions"][0]["practice_eligible"] = False
        second["questions"][0]["review_flags"] = ["manual_review"]
        _write(second_path, second)
        with pytest.raises(
            PyqArchiveValidationError,
            match="materialized link targets a non-PYQ question",
        ):
            await import_pyq_archive(
                session,
                second_path,
                dry_run=False,
                materialize=True,
                expected_original_count=originals_before,
            )

        await session.refresh(generated)
        assert generated.is_active is True
        assert generated.source_kind == QuestionSource.ORIGINAL
        assert generated.text == original_text
        assert await session.scalar(select(func.count(PyqArchiveImport.id))) == 1
    await engine.dispose()


def test_archive_migration_and_import_cli_are_deployable(tmp_path: Path) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    database_path = (tmp_path / "archive-migration.db").resolve()
    database_url = f"sqlite+aiosqlite:///{database_path.as_posix()}"
    artifact_path = (tmp_path / "archive.json").resolve()
    _write(artifact_path, _artifact(artifact_version="archive-cli-v1"))
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    environment.pop("DATABASE_URL_UNPOOLED", None)

    migrate_to_previous_head = [
        sys.executable,
        "-m",
        "alembic",
        "-c",
        "alembic.ini",
        "upgrade",
        "0004_pyq_archive",
    ]
    completed = subprocess.run(
        migrate_to_previous_head,
        cwd=backend_dir,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

    preview = subprocess.run(
        [sys.executable, "scripts/import_pyq_archive.py", str(artifact_path)],
        cwd=backend_dir,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert preview.returncode == 2
    assert "No migration was run" in preview.stderr

    with sqlite3.connect(database_path) as connection:
        stale_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        revision = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()
        assert revision == ("0004_pyq_archive",)
        # Fresh installs may already contain current metadata-created tables;
        # the Alembic revision is the authoritative stale-schema guard.
        assert "pyq_archive_imports" in stale_tables
        assert connection.execute("SELECT COUNT(*) FROM pyq_source_papers").fetchone() == (
            0,
        )

    rejected_upgrade_preview = subprocess.run(
        [
            sys.executable,
            "scripts/import_pyq_archive.py",
            str(artifact_path),
            "--upgrade-schema",
        ],
        cwd=backend_dir,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert rejected_upgrade_preview.returncode != 0
    assert "previews never migrate" in (
        rejected_upgrade_preview.stdout + rejected_upgrade_preview.stderr
    )

    apply_with_explicit_upgrade = [
        sys.executable,
        "scripts/import_pyq_archive.py",
        str(artifact_path),
        "--apply",
        "--upgrade-schema",
        "--expected-active-originals",
        "0",
    ]
    completed = subprocess.run(
        apply_with_explicit_upgrade,
        cwd=backend_dir,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

    repeated_apply = subprocess.run(
        [
            sys.executable,
            "scripts/import_pyq_archive.py",
            str(artifact_path),
            "--apply",
            "--expected-active-originals",
            "0",
        ],
        cwd=backend_dir,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert repeated_apply.returncode == 0, (
        repeated_apply.stdout + repeated_apply.stderr
    )

    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {
            "pyq_source_papers",
            "pyq_source_questions",
            "pyq_archive_imports",
            "pyq_archive_executions",
        }.issubset(tables)
        question_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(questions)")
        }
        assert {"source_paper_id", "source_item_label", "assets"}.issubset(
            question_columns
        )
        revision = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()
        assert revision == ("0007_pyq_visibility_audit",)
        assert connection.execute("SELECT COUNT(*) FROM pyq_archive_imports").fetchone() == (
            1,
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM pyq_archive_executions"
        ).fetchone() == (2,)
        execution_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(pyq_archive_executions)"
            )
        }
        assert {
            "archive_import_id",
            "execution_mode",
            "materialized_inserted_count",
            "materialized_adopted_count",
            "materialized_updated_count",
            "retired_count",
            "reactivated_count",
            "visibility_plan_sha256",
            "expected_reactivation_count",
            "original_active_before",
            "original_active_after",
            "pyq_active_before",
            "pyq_active_after",
        }.issubset(execution_columns)

    migration_steps = (
        ("downgrade", "0004_pyq_archive"),
        ("upgrade", "head"),
    )
    for migration_action, target in migration_steps:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "alembic",
                "-c",
                "alembic.ini",
                migration_action,
                target,
            ],
            cwd=backend_dir,
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        with sqlite3.connect(database_path) as connection:
            current_revision = connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone()
            expected_revision = (
                "0004_pyq_archive"
                if migration_action == "downgrade"
                else "0007_pyq_visibility_audit"
            )
            assert current_revision == (expected_revision,)
            table_names = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            assert ("pyq_archive_executions" in table_names) is (
                migration_action == "upgrade"
            )

    dockerfile = (backend_dir / "Dockerfile").read_text(encoding="utf-8")
    importer = (backend_dir / "scripts" / "import_pyq_archive.py").read_text(
        encoding="utf-8"
    )
    assert "COPY migrations ./migrations" in dockerfile
    assert "COPY alembic.ini ./alembic.ini" in dockerfile
    assert "COPY scripts ./scripts" in dockerfile
    assert "upgrade_database_schema()" in importer
    assert "if args.upgrade_schema" in importer
    assert "assert_database_schema_current" in importer


def test_tracked_practice_package_cli_preview_is_importable(tmp_path: Path) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    artifact_path = backend_dir / "data" / "gate_cs_pyq_practice_1996_2025.json"
    database_path = (tmp_path / "tracked-practice-preview.sqlite3").resolve()
    environment = os.environ.copy()
    database_url = f"sqlite+aiosqlite:///{database_path.as_posix()}"
    environment["DATABASE_URL"] = database_url
    environment["DATABASE_URL_UNPOOLED"] = database_url

    bootstrapped = subprocess.run(
        [sys.executable, "scripts/bootstrap_database.py"],
        cwd=backend_dir,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert bootstrapped.returncode == 0, bootstrapped.stdout + bootstrapped.stderr
    assert "2695 active questions" in bootstrapped.stdout

    previewed = subprocess.run(
        [
            sys.executable,
            "scripts/import_pyq_archive.py",
            str(artifact_path),
            "--materialize",
            "--expected-active-originals",
            "2290",
        ],
        cwd=backend_dir,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert previewed.returncode == 0, previewed.stdout + previewed.stderr
    summary = json.loads(previewed.stdout[previewed.stdout.index("{") :])
    assert summary == {
        "active_pyq_count_after": 405,
        "active_pyq_count_before": 405,
        "already_applied": False,
        "artifact_version": "gate-cs-pyq-practice-0aa05b22e3bf-88c192e62efb",
        "checksum": "1c34407a6b71459d5c89f837fa0f3ef00190a27740b876008d79b22cd29c9dec",
        "dry_run": True,
        "execution_id": None,
        "inserted_count": 2912,
        "item_count": 2873,
        "materialized_adopted_count": 177,
        "materialized_count": 177,
        "materialized_inserted_count": 0,
        "materialized_updated_count": 0,
        "original_active_count": 2290,
        "paper_count": 39,
        "reactivated_count": 0,
        "retired_count": 0,
        "retirement_approval_required": False,
        "unchanged_count": 0,
        "updated_count": 0,
        "visibility_plan_sha256": None,
    }
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM questions").fetchone() == (
            2695,
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM pyq_source_questions"
        ).fetchone() == (0,)
