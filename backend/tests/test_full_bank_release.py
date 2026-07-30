from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import (
    Question,
    QuestionType,
    SessionMode,
    Subject,
    TestForm as CatalogForm,
)
from app.question_bank import import_question_bank
from app.seed import seed_database
from app.test_catalog import TECHNICAL_COURSE_CODES, rebuild_test_catalog


QUESTION_BANK_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "question_bank.json"
)
REQUIRED_QUESTION_TYPES = set(QuestionType)


@pytest.mark.asyncio
async def test_full_question_bank_release_contract() -> None:
    """Exercise the shipped question bank and catalog in a fresh database."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            await seed_database(session)

            assert QUESTION_BANK_PATH.is_file(), (
                f"Release question bank is missing: {QUESTION_BANK_PATH}"
            )
            first_import = await import_question_bank(session, QUESTION_BANK_PATH)
            assert not first_import.already_applied
            assert first_import.question_count > 0
            assert (
                first_import.inserted_count
                + first_import.updated_count
                + first_import.unchanged_count
                == first_import.question_count
            )

            imported_count = await session.scalar(
                select(func.count(Question.id)).where(
                    Question.bank_version == first_import.bank_version,
                    Question.is_active.is_(True),
                )
            )
            assert imported_count == first_import.question_count

            second_import = await import_question_bank(session, QUESTION_BANK_PATH)
            assert second_import.already_applied
            assert second_import.bank_version == first_import.bank_version
            assert second_import.checksum == first_import.checksum
            assert second_import.question_count == first_import.question_count
            assert second_import.inserted_count == 0
            assert second_import.updated_count == 0
            assert second_import.retired_count == 0
            assert (
                await session.scalar(
                    select(func.count(Question.id)).where(
                        Question.bank_version == first_import.bank_version,
                        Question.is_active.is_(True),
                    )
                )
                == imported_count
            )

            subjects = list(
                (
                    await session.scalars(
                        select(Subject)
                        .options(selectinload(Subject.topics))
                        .order_by(Subject.order_index)
                    )
                ).all()
            )
            subjects_by_id = {subject.id: subject for subject in subjects}
            technical_subjects = {
                subject.code.upper(): subject
                for subject in subjects
                if subject.code.upper() in TECHNICAL_COURSE_CODES
            }
            assert set(technical_subjects) == TECHNICAL_COURSE_CODES
            assert len(technical_subjects) == 10

            imported_questions = list(
                (
                    await session.scalars(
                        select(Question).where(
                            Question.bank_version == first_import.bank_version,
                            Question.is_active.is_(True),
                        )
                    )
                ).all()
            )
            course_counts = Counter(
                subjects_by_id[question.subject_id].code.upper()
                for question in imported_questions
            )
            for course_code in sorted(TECHNICAL_COURSE_CODES):
                assert course_counts[course_code] >= 200, (
                    f"{course_code} has only {course_counts[course_code]} "
                    "release-bank questions"
                )

            types_by_topic: dict[int, set[QuestionType]] = defaultdict(set)
            counts_by_topic: Counter[int] = Counter()
            for question in imported_questions:
                types_by_topic[question.topic_id].add(question.question_type)
                counts_by_topic[question.topic_id] += 1

            for subject in subjects:
                for topic in subject.topics:
                    scope = f"{subject.code}/{topic.name}"
                    assert counts_by_topic[topic.id] > 0, (
                        f"Canonical topic {scope} has no release-bank questions"
                    )
                    missing_types = REQUIRED_QUESTION_TYPES - types_by_topic[topic.id]
                    assert not missing_types, (
                        f"Canonical topic {scope} is missing question types: "
                        f"{sorted(item.value for item in missing_types)}"
                    )

            await rebuild_test_catalog(session)
            forms = list(
                (
                    await session.scalars(
                        select(CatalogForm).order_by(CatalogForm.id)
                    )
                ).all()
            )
            full_forms = [
                form for form in forms if form.mode == SessionMode.FULL
            ]
            course_forms = [
                form for form in forms if form.mode == SessionMode.SECTIONAL
            ]

            assert len(forms) == 125
            assert len(full_forms) == 25
            assert len(course_forms) == 100
            assert all(form.is_available for form in forms)

            all_questions = list(
                (
                    await session.scalars(
                        select(Question).where(Question.is_active.is_(True))
                    )
                ).all()
            )
            questions_by_id = {question.id: question for question in all_questions}

            forms_by_course = Counter(
                subjects_by_id[form.subject_id].code.upper()
                for form in course_forms
                if form.subject_id is not None
            )
            assert forms_by_course == Counter(
                {course_code: 10 for course_code in TECHNICAL_COURSE_CODES}
            )

            for form in course_forms:
                assert form.subject_id is not None
                assert form.question_count == 30
                assert len(form.question_ids) == 30
                assert len(set(form.question_ids)) == 30
                selected = [questions_by_id[item] for item in form.question_ids]
                assert all(
                    question.subject_id == form.subject_id for question in selected
                )
                actual_type_counts = Counter(
                    question.question_type.value for question in selected
                )
                assert all(
                    actual_type_counts[question_type.value] > 0
                    for question_type in QuestionType
                )
                assert form.question_type_counts == {
                    question_type.value: actual_type_counts[question_type.value]
                    for question_type in QuestionType
                }

            fingerprints: set[str] = set()
            for form in full_forms:
                assert form.subject_id is None
                assert form.question_count == 65
                assert len(form.question_ids) == 65
                assert len(set(form.question_ids)) == 65
                assert form.total_marks == 100

                selected = [questions_by_id[item] for item in form.question_ids]
                assert sum(question.marks for question in selected) == 100
                selected_course_codes = Counter(
                    subjects_by_id[question.subject_id].code.upper()
                    for question in selected
                )
                assert selected_course_codes["GA"] == 10
                assert (
                    sum(
                        selected_course_codes[course_code]
                        for course_code in TECHNICAL_COURSE_CODES
                    )
                    == 55
                )
                assert set(selected_course_codes).issubset(
                    TECHNICAL_COURSE_CODES | {"GA"}
                )
                marks_by_course = Counter()
                for question in selected:
                    code = subjects_by_id[question.subject_id].code.upper()
                    marks_by_course[code] += question.marks
                assert marks_by_course["GA"] == 15
                assert marks_by_course["EM"] == 13
                assert (
                    sum(
                        marks_by_course[course_code]
                        for course_code in TECHNICAL_COURSE_CODES
                        if course_code != "EM"
                    )
                    == 72
                )

                question_id_fingerprint = hashlib.sha256(
                    ",".join(
                        str(question_id)
                        for question_id in sorted(form.question_ids)
                    ).encode("utf-8")
                ).hexdigest()
                fingerprints.add(question_id_fingerprint)

            assert len(fingerprints) == 25
    finally:
        await engine.dispose()
