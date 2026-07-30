from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api import (
    create_practice_session,
    get_session,
    progress_analytics,
    submit_attempt,
)
from app.database import Base
from app.models import (
    Attempt,
    AttemptResponse,
    Difficulty,
    PracticeSession,
    Question,
    QuestionBankImport,
    QuestionSource,
    QuestionType,
    ResponseStatus,
    SessionMode,
    Subject,
    Topic,
)
from app.question_bank import QuestionBankValidationError, import_question_bank
from app.schemas import (
    AnswerSubmission,
    AttemptSubmit,
    PracticeSessionCreate,
)
from app.seed import seed_database


async def _isolated_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, factory


def _bank_question(external_id: str, question: str) -> dict[str, object]:
    return {
        "external_id": external_id,
        "question": question,
        "options": ["True", "False"],
        "course": "EM",
        "subject_slug": "engineering-mathematics",
        "topic": "Discrete Mathematics",
        "topic_slug": "discrete-mathematics",
        "correct_answer": "A",
        "question_type": "mcq",
        "difficulty": "easy",
        "marks": 1,
        "explanation": f"{question} The stated proposition is true.",
        "source_kind": "original",
    }


@pytest.mark.asyncio
async def test_import_validates_entire_document_before_mutating(
    tmp_path: Path,
) -> None:
    engine, factory = await _isolated_session()
    path = tmp_path / "invalid-bank.json"
    payload = {
        "schema_version": "1.0",
        "bank_version": "invalid-all-or-nothing",
        "questions": [
            _bank_question("hardening:valid-first", "A valid first row."),
            {
                **_bank_question("hardening:invalid-second", "An invalid second row."),
                "subject_slug": "algorithms",
            },
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")

    async with factory() as session:
        await seed_database(session)
        initial_count = await session.scalar(select(func.count(Question.id)))
        with pytest.raises(QuestionBankValidationError, match="conflicting course"):
            await import_question_bank(session, path)
        assert await session.scalar(select(func.count(Question.id))) == initial_count
        assert not session.new
        assert (
            await session.scalar(
                select(QuestionBankImport).where(
                    QuestionBankImport.bank_version == "invalid-all-or-nothing"
                )
            )
            is None
        )
    await engine.dispose()


@pytest.mark.asyncio
async def test_import_rejects_duplicate_provenance(tmp_path: Path) -> None:
    engine, factory = await _isolated_session()
    path = tmp_path / "duplicate-provenance.json"
    questions = []
    for index in range(2):
        question = _bank_question(
            f"hardening:pyq:{index}",
            f"Duplicate provenance row {index}.",
        )
        question.update(
            {
                "source_kind": "previous_year",
                "source_year": 2025,
                "source_paper": "GATE 2025 CS1",
                "source_question_number": 12,
            }
        )
        questions.append(question)
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "bank_version": "duplicate-provenance",
                "questions": questions,
            }
        ),
        encoding="utf-8",
    )

    async with factory() as session:
        await seed_database(session)
        with pytest.raises(QuestionBankValidationError, match="duplicate provenance"):
            await import_question_bank(session, path)
        assert not session.new
    await engine.dispose()


@pytest.mark.asyncio
async def test_import_retires_omissions_preserves_metadata_and_enriches_notes(
    tmp_path: Path,
) -> None:
    engine, factory = await _isolated_session()
    path = tmp_path / "authoritative-bank.json"
    original_questions = [
        _bank_question(
            f"hardening:example:{index}",
            f"Deterministic revision example {index}.",
        )
        for index in range(1, 4)
    ]
    omitted_question = _bank_question(
        "hardening:omitted",
        "This row will be retired by the next authoritative version.",
    )
    pyq = _bank_question("hardening:pyq", "A provenance-rich previous-year row.")
    pyq.update(
        {
            "source_kind": "previous_year",
            "source_year": 2025,
            "source_paper": "GATE 2025 CS1",
            "source_question_number": 7,
            "source_page": 4,
            "extraction_method": "pdf-text",
            "extraction_confidence": 0.98,
        }
    )

    async with factory() as session:
        await seed_database(session)
        topic = await session.scalar(
            select(Topic).where(Topic.slug == "discrete-mathematics")
        )
        assert topic is not None
        await session.refresh(topic, attribute_names=["note"])
        original_summary = topic.note.summary
        original_key_points = list(topic.note.key_points)

        path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "bank_version": "authoritative-v1",
                    "questions": original_questions + [omitted_question, pyq],
                }
            ),
            encoding="utf-8",
        )
        first = await import_question_bank(session, path)
        assert first.inserted_count == 5
        assert first.retired_count == 0

        path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "bank_version": "authoritative-v2",
                    "questions": original_questions + [pyq],
                }
            ),
            encoding="utf-8",
        )
        second = await import_question_bank(session, path)
        assert second.retired_count == 1

        retired = await session.scalar(
            select(Question).where(Question.external_id == "hardening:omitted")
        )
        preserved_pyq = await session.scalar(
            select(Question).where(Question.external_id == "hardening:pyq")
        )
        assert retired is not None and retired.is_active is False
        assert preserved_pyq is not None and preserved_pyq.is_active is True
        assert preserved_pyq.source_page == 4
        assert preserved_pyq.extraction_method == "pdf-text"
        assert preserved_pyq.extraction_confidence == pytest.approx(0.98)

        await session.refresh(topic, attribute_names=["note"])
        assert topic.note.summary == original_summary
        assert topic.note.key_points == original_key_points
        assert len(topic.note.worked_examples) == 3
        assert all(item["solution"] for item in topic.note.worked_examples)
    await engine.dispose()


@pytest.mark.asyncio
async def test_session_snapshot_is_immutable_for_display_and_grading() -> None:
    engine, factory = await _isolated_session()
    async with factory() as session:
        await seed_database(session)
        user_key = "anon-snapshot-test"
        created = await create_practice_session(
            PracticeSessionCreate(
                subject_slug="engineering-mathematics",
                count=1,
                seed=17,
            ),
            db=session,
            user_key=user_key,
        )
        public_question = created.questions[0]
        question = await session.get(Question, public_question.id)
        assert question is not None
        original_answer = question.correct_answer
        original_explanation = question.explanation
        original_text = question.text

        if question.question_type == QuestionType.NAT:
            question.correct_answer = 987654321
        elif question.question_type == QuestionType.MSQ:
            question.correct_answer = ["Z"]
        else:
            question.correct_answer = next(
                option["id"]
                for option in question.options
                if option["id"] != original_answer
            )
        question.text = "MUTATED AFTER SESSION CREATION"
        question.explanation = "Mutated explanation."
        await session.commit()

        reread = await get_session(
            created.id,
            db=session,
            user_key=user_key,
        )
        assert reread.questions[0].text == original_text
        result = await submit_attempt(
            AttemptSubmit(
                session_id=created.id,
                answers=[
                    AnswerSubmission(
                        question_id=question.id,
                        answer=original_answer,
                    )
                ],
            ),
            db=session,
            user_key=user_key,
        )
        assert result.correct_count == 1
        assert result.results[0].correct_answer == original_answer
        assert result.results[0].explanation == original_explanation
    await engine.dispose()


@pytest.mark.asyncio
async def test_analytics_uses_latest_unique_answered_questions() -> None:
    engine, factory = await _isolated_session()
    async with factory() as session:
        await seed_database(session)
        user_key = "anon-unique-analytics"
        subject = await session.scalar(
            select(Subject).where(Subject.slug == "engineering-mathematics")
        )
        assert subject is not None
        topic = await session.scalar(
            select(Topic).where(
                Topic.subject_id == subject.id,
                Topic.slug == "discrete-mathematics",
            )
        )
        assert topic is not None
        question = await session.scalar(
            select(Question)
            .where(Question.topic_id == topic.id)
            .order_by(Question.id)
        )
        assert question is not None
        unanswered_question = Question(
            external_id="hardening:analytics:unanswered",
            subject=subject,
            topic=topic,
            source=QuestionSource.ORIGINAL,
            source_kind=QuestionSource.ORIGINAL,
            question_type=QuestionType.MCQ,
            difficulty=Difficulty.EASY,
            text="An unanswered coverage control.",
            options=[
                {"id": "A", "text": "Yes"},
                {"id": "B", "text": "No"},
            ],
            correct_answer="A",
            marks=1,
            explanation="Control row.",
            tags=[],
        )
        session.add(unanswered_question)
        await session.flush()

        base_time = datetime.now(UTC)
        for index in range(6):
            practice = PracticeSession(
                user_key=user_key,
                mode=SessionMode.PRACTICE,
                subject_id=subject.id,
                topic_id=topic.id,
                question_ids=[question.id],
                question_snapshots=[],
                question_count=1,
                duration_seconds=None,
                total_marks=question.marks,
                seed=index,
                started_at=base_time + timedelta(minutes=index),
                expires_at=None,
                is_submitted=True,
            )
            practice.attempt = Attempt(
                user_key=user_key,
                submitted_at=base_time + timedelta(minutes=index),
                timed_out=False,
                score=float(question.marks),
                max_score=float(question.marks),
                correct_count=1,
                incorrect_count=0,
                unanswered_count=0,
                responses=[
                    AttemptResponse(
                        question_id=question.id,
                        answer=question.correct_answer,
                        correct_answer_snapshot=question.correct_answer,
                        explanation_snapshot=question.explanation,
                        status=ResponseStatus.CORRECT,
                        awarded_marks=float(question.marks),
                        max_marks=float(question.marks),
                        negative_marks=0,
                    )
                ],
            )
            session.add(practice)

        unanswered_session = PracticeSession(
            user_key=user_key,
            mode=SessionMode.PRACTICE,
            subject_id=subject.id,
            topic_id=topic.id,
            question_ids=[unanswered_question.id],
            question_snapshots=[],
            question_count=1,
            duration_seconds=None,
            total_marks=1,
            seed=100,
            started_at=base_time + timedelta(minutes=10),
            expires_at=None,
            is_submitted=True,
        )
        unanswered_session.attempt = Attempt(
            user_key=user_key,
            submitted_at=base_time + timedelta(minutes=10),
            timed_out=False,
            score=0,
            max_score=1,
            correct_count=0,
            incorrect_count=0,
            unanswered_count=1,
            responses=[
                AttemptResponse(
                    question_id=unanswered_question.id,
                    answer=None,
                    correct_answer_snapshot="A",
                    explanation_snapshot="Control row.",
                    status=ResponseStatus.UNANSWERED,
                    awarded_marks=0,
                    max_marks=1,
                    negative_marks=0,
                )
            ],
        )
        session.add(unanswered_session)
        await session.commit()

        dashboard = await progress_analytics(db=session, user_key=user_key)
        topic_result = next(item for item in dashboard.topics if item.topic_id == topic.id)
        assert topic_result.attempt_count == 7
        assert topic_result.answered_count == 1
        assert topic_result.unique_questions_attempted == 1
        assert topic_result.correct_count == 1
        assert topic_result.unanswered_count == 1
        assert topic_result.coverage_percent == round(
            100 / topic_result.available_questions,
            2,
        )
        assert topic_result.status != "strong"
        assert dashboard.overall.answered_responses == 1
        assert dashboard.overall.unique_questions_attempted == 1
    await engine.dispose()
