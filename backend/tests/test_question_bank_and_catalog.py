from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import func, inspect, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database import Base, _add_local_upgrade_columns
from app.models import (
    Difficulty,
    Question,
    QuestionSource,
    QuestionType,
    SessionMode,
    Subject,
    TestForm as CatalogForm,
)
from app.question_bank import import_question_bank
from app.seed import seed_database
from app.test_catalog import rebuild_test_catalog


async def _isolated_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, factory


@pytest.mark.asyncio
async def test_local_auto_create_adds_columns_to_an_existing_database() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.exec_driver_sql(
            "CREATE TABLE questions (id INTEGER PRIMARY KEY)"
        )
        await connection.exec_driver_sql(
            "CREATE TABLE practice_sessions (id VARCHAR(36) PRIMARY KEY)"
        )
        await connection.run_sync(_add_local_upgrade_columns)

        def schema(sync_connection):
            schema_inspector = inspect(sync_connection)
            return (
                {
                    item["name"]
                    for item in schema_inspector.get_columns("questions")
                },
                {
                    item["name"]
                    for item in schema_inspector.get_columns("practice_sessions")
                },
            )

        question_columns, session_columns = await connection.run_sync(schema)
        assert {"external_id", "bank_version"}.issubset(question_columns)
        assert "catalog_id" in session_columns
    await engine.dispose()


@pytest.mark.asyncio
async def test_versioned_question_bank_import_is_idempotent_and_updates(
    tmp_path: Path,
) -> None:
    engine, factory = await _isolated_session()
    bank_path = tmp_path / "question_bank.json"
    payload = {
        "schema_version": "1.0",
        "bank_version": "test-bank-1",
        "generated_at": "2026-07-30T00:00:00Z",
        "questions": [
            {
                "external_id": "test:em:logic:001",
                "question": "Which connective is true only when both operands are true?",
                "options": ["AND", "OR", "NOT", "XOR"],
                "course": "EM",
                "topic": "Discrete Mathematics",
                "correct_answer": "A",
                "question_type": "mcq",
                "difficulty": "easy",
                "marks": 1,
                "explanation": "Conjunction is true only when both inputs are true.",
                "source_kind": "original",
            }
        ],
    }
    bank_path.write_text(json.dumps(payload), encoding="utf-8")

    async with factory() as session:
        await seed_database(session)
        initial_count = await session.scalar(select(func.count(Question.id)))
        first = await import_question_bank(session, bank_path)
        assert first.inserted_count == 1
        assert first.updated_count == 0
        assert not first.already_applied

        second = await import_question_bank(session, bank_path)
        assert second.already_applied
        assert second.inserted_count == 0
        assert await session.scalar(select(func.count(Question.id))) == initial_count + 1

        payload["questions"][0]["question"] = (
            "Which Boolean connective is true only when both operands are true?"
        )
        bank_path.write_text(json.dumps(payload), encoding="utf-8")
        third = await import_question_bank(session, bank_path)
        assert third.inserted_count == 0
        assert third.updated_count == 1
        imported = await session.scalar(
            select(Question).where(Question.external_id == "test:em:logic:001")
        )
        assert imported is not None
        assert imported.text.startswith("Which Boolean connective")
        assert await session.scalar(select(func.count(Question.id))) == initial_count + 1
    await engine.dispose()


def _synthetic_question(
    *,
    subject: Subject,
    index: int,
) -> Question:
    topic = subject.topics[index % len(subject.topics)]
    question_type = (QuestionType.MCQ, QuestionType.MSQ, QuestionType.NAT)[index % 3]
    options = (
        []
        if question_type == QuestionType.NAT
        else [
            {"id": "A", "text": "Choice A"},
            {"id": "B", "text": "Choice B"},
            {"id": "C", "text": "Choice C"},
            {"id": "D", "text": "Choice D"},
        ]
    )
    answer: object
    if question_type == QuestionType.NAT:
        answer = index
    elif question_type == QuestionType.MSQ:
        answer = ["A", "C"]
    else:
        answer = "A"
    return Question(
        external_id=f"catalog:{subject.code.lower()}:{index:03d}",
        bank_version="catalog-test",
        subject=subject,
        topic=topic,
        source=QuestionSource.ORIGINAL,
        source_kind=QuestionSource.ORIGINAL,
        question_type=question_type,
        difficulty=Difficulty.MEDIUM,
        text=f"Synthetic {subject.code} catalog question {index}",
        options=options,
        correct_answer=answer,
        numerical_tolerance=0.01,
        marks=1 if index % 2 == 0 else 2,
        explanation="A deterministic test fixture.",
        tags=["catalog-fixture"],
    )


@pytest.mark.asyncio
async def test_catalog_has_25_full_and_10_per_course_with_stable_mixed_forms() -> None:
    engine, factory = await _isolated_session()
    async with factory() as session:
        await seed_database(session)
        subjects = list(
            (
                await session.scalars(
                    select(Subject).order_by(Subject.order_index)
                )
            ).all()
        )
        for subject in subjects:
            await session.refresh(subject, attribute_names=["topics"])
            if subject.code == "GA":
                continue
            for index in range(42):
                session.add(_synthetic_question(subject=subject, index=index))
        await session.commit()

        await rebuild_test_catalog(session)
        forms = list(
            (
                await session.scalars(
                    select(CatalogForm).order_by(CatalogForm.id)
                )
            ).all()
        )
        full_forms = [form for form in forms if form.mode == SessionMode.FULL]
        course_forms = [
            form for form in forms if form.mode == SessionMode.SECTIONAL
        ]
        assert len(full_forms) == 25
        assert len(course_forms) == 100
        assert all(form.is_available for form in full_forms)
        assert all(form.question_count == 65 for form in full_forms)
        assert all(form.duration_seconds == 10_800 for form in full_forms)
        assert all(form.total_marks == 100 for form in full_forms)
        subject_code_by_id = {subject.id: subject.code for subject in subjects}
        questions_by_id = {
            question.id: question
            for question in (await session.scalars(select(Question))).all()
        }
        for form in full_forms:
            selected = [questions_by_id[question_id] for question_id in form.question_ids]
            assert sum(
                subject_code_by_id[question.subject_id] == "GA"
                for question in selected
            ) == 10
            assert sum(
                subject_code_by_id[question.subject_id] != "GA"
                for question in selected
            ) == 55
        assert all(form.is_available for form in course_forms)
        assert all(len(form.question_ids) == 30 for form in course_forms)
        assert all(
            all(form.question_type_counts[item] > 0 for item in ("mcq", "msq", "nat"))
            for form in course_forms
        )
        first_ids = {form.id: list(form.question_ids) for form in forms}

        await rebuild_test_catalog(session)
        rebuilt = list((await session.scalars(select(CatalogForm))).all())
        assert {form.id: form.question_ids for form in rebuilt} == first_ids
    await engine.dispose()
