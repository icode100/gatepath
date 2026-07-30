from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    Question,
    QuestionBankImport,
    QuestionType,
    SessionMode,
    Subject,
    TestForm,
    utc_now,
)


FULL_TEST_COUNT = 25
COURSE_TEST_COUNT = 10
COURSE_QUESTION_COUNT = 30
FULL_QUESTION_COUNT = 65
FULL_DURATION_SECONDS = 180 * 60
COURSE_DURATION_SECONDS = 90 * 60
TECHNICAL_COURSE_CODES = {
    "EM",
    "DL",
    "COA",
    "PDS",
    "ALG",
    "TOC",
    "CD",
    "OS",
    "DBMS",
    "CN",
}

T = TypeVar("T")


def _hash_value(value: str) -> int:
    return int.from_bytes(hashlib.sha256(value.encode("utf-8")).digest()[:8], "big")


def _stable_order(items: Iterable[T], key: str, identity: Callable[[T], str]) -> list[T]:
    return sorted(items, key=lambda item: _hash_value(f"{key}:{identity(item)}"))


def _question_identity(question: Question) -> str:
    return question.external_id or str(question.id)


def _balanced_questions(
    candidates: list[Question],
    count: int,
    key: str,
    *,
    require_all_types: bool,
    group_by_subject: bool = False,
) -> tuple[list[Question], str | None]:
    if len(candidates) < count:
        return [], f"Requires {count} questions; only {len(candidates)} are available"

    types_present = {question.question_type for question in candidates}
    required_types = {QuestionType.MCQ, QuestionType.MSQ, QuestionType.NAT}
    if require_all_types and not required_types.issubset(types_present):
        missing = ", ".join(
            item.value.upper() for item in sorted(required_types - types_present, key=lambda x: x.value)
        )
        return [], f"Question bank is missing required type(s): {missing}"

    selected: list[Question] = []
    selected_ids: set[int] = set()

    def add(question: Question) -> None:
        if question.id not in selected_ids and len(selected) < count:
            selected.append(question)
            selected_ids.add(question.id)

    # Every course test explicitly contains MCQ, MSQ and NAT.
    if require_all_types:
        for question_type in (QuestionType.MCQ, QuestionType.MSQ, QuestionType.NAT):
            pool = [item for item in candidates if item.question_type == question_type]
            for question in _stable_order(
                pool, f"{key}:required:{question_type.value}", _question_identity
            ):
                if question.topic_id not in {item.topic_id for item in selected}:
                    add(question)
                    break
            else:
                add(
                    _stable_order(
                        pool, f"{key}:required:{question_type.value}", _question_identity
                    )[0]
                )

    # Touch every syllabus topic when the form has enough slots.
    by_topic: dict[int, list[Question]] = defaultdict(list)
    for question in candidates:
        by_topic[question.topic_id].append(question)
    for topic_id in _stable_order(
        by_topic,
        f"{key}:topics",
        lambda item: str(item),
    ):
        if topic_id in {item.topic_id for item in selected}:
            continue
        ordered = _stable_order(
            by_topic[topic_id], f"{key}:topic:{topic_id}", _question_identity
        )
        if ordered:
            add(ordered[0])

    # Fill by round-robin across subjects/topics, preventing a large topic from
    # crowding out the rest of the syllabus.
    grouped: dict[tuple[int, int] | tuple[int], list[Question]] = defaultdict(list)
    for question in candidates:
        if question.id in selected_ids:
            continue
        group = (
            (question.subject_id, question.topic_id)
            if group_by_subject
            else (question.topic_id,)
        )
        grouped[group].append(question)
    group_keys = _stable_order(
        grouped,
        f"{key}:groups",
        lambda item: ":".join(str(value) for value in item),
    )
    ordered_groups = {
        group: _stable_order(
            grouped[group],
            f"{key}:group:{':'.join(str(value) for value in group)}",
            _question_identity,
        )
        for group in group_keys
    }
    cursor = 0
    while len(selected) < count:
        made_progress = False
        for group in group_keys:
            bucket = ordered_groups[group]
            if cursor < len(bucket):
                add(bucket[cursor])
                made_progress = True
                if len(selected) == count:
                    break
        if not made_progress:
            break
        cursor += 1

    if len(selected) != count:
        return [], f"Could select only {len(selected)} of {count} required questions"
    return (
        _stable_order(selected, f"{key}:final-order", _question_identity),
        None,
    )


def _type_counts(questions: list[Question]) -> dict[str, int]:
    counts = Counter(question.question_type.value for question in questions)
    return {question_type.value: counts[question_type.value] for question_type in QuestionType}


async def _latest_bank_version(session: AsyncSession) -> str:
    version = await session.scalar(
        select(QuestionBankImport.bank_version)
        .order_by(QuestionBankImport.imported_at.desc(), QuestionBankImport.id.desc())
        .limit(1)
    )
    return version or "built-in-seed"


def _full_form(
    *,
    form_number: int,
    ga_questions: list[Question],
    technical_questions: list[Question],
    bank_version: str,
) -> dict[str, object]:
    catalog_id = f"full-{form_number:02d}"
    groups = (
        ("ga-1", [item for item in ga_questions if item.marks == 1], 5, False),
        ("ga-2", [item for item in ga_questions if item.marks == 2], 5, False),
        ("technical-1", [item for item in technical_questions if item.marks == 1], 25, True),
        ("technical-2", [item for item in technical_questions if item.marks == 2], 30, True),
    )
    selected: list[Question] = []
    unavailable_reason: str | None = None
    for label, candidates, count, by_subject in groups:
        group, reason = _balanced_questions(
            candidates,
            count,
            f"{catalog_id}:{label}",
            require_all_types=False,
            group_by_subject=by_subject,
        )
        if reason:
            unavailable_reason = f"{label}: {reason}"
            selected = []
            break
        selected.extend(group)

    is_available = len(selected) == FULL_QUESTION_COUNT
    if is_available and sum(item.marks for item in selected) != 100:
        is_available = False
        unavailable_reason = "The selected official mark split does not total 100 marks"
        selected = []
    return {
        "id": catalog_id,
        "title": f"Full-Length Mock {form_number:02d}",
        "description": "Official-format GATE CSE mock: 65 questions, 100 marks and 180 minutes.",
        "mode": SessionMode.FULL,
        "subject_id": None,
        "form_number": form_number,
        "question_ids": [item.id for item in selected],
        "question_count": FULL_QUESTION_COUNT,
        "duration_seconds": FULL_DURATION_SECONDS,
        "total_marks": 100,
        "seed": _hash_value(catalog_id) % (2**31),
        "question_type_counts": _type_counts(selected),
        "topic_count": len({item.topic_id for item in selected}),
        "bank_version": bank_version,
        "is_available": is_available,
        "unavailable_reason": unavailable_reason,
        "generated_at": utc_now(),
    }


def _course_form(
    *,
    subject: Subject,
    questions: list[Question],
    form_number: int,
    bank_version: str,
) -> dict[str, object]:
    catalog_id = f"{subject.code.lower()}-{form_number:02d}"
    selected, unavailable_reason = _balanced_questions(
        questions,
        COURSE_QUESTION_COUNT,
        catalog_id,
        require_all_types=True,
    )
    return {
        "id": catalog_id,
        "title": f"{subject.code} Course Test {form_number:02d}",
        "description": (
            f"A 30-question {subject.name} test balanced across available syllabus "
            "topics and containing MCQ, MSQ and NAT questions."
        ),
        "mode": SessionMode.SECTIONAL,
        "subject_id": subject.id,
        "form_number": form_number,
        "question_ids": [item.id for item in selected],
        "question_count": COURSE_QUESTION_COUNT,
        "duration_seconds": COURSE_DURATION_SECONDS,
        "total_marks": sum(item.marks for item in selected),
        "seed": _hash_value(catalog_id) % (2**31),
        "question_type_counts": _type_counts(selected),
        "topic_count": len({item.topic_id for item in selected}),
        "bank_version": bank_version,
        "is_available": len(selected) == COURSE_QUESTION_COUNT,
        "unavailable_reason": unavailable_reason,
        "generated_at": utc_now(),
    }


async def rebuild_test_catalog(session: AsyncSession) -> None:
    subjects = list(
        (
            await session.scalars(
                select(Subject)
                .options(selectinload(Subject.topics))
                .order_by(Subject.order_index)
            )
        ).all()
    )
    questions = list((await session.scalars(select(Question).order_by(Question.id))).all())
    bank_version = await _latest_bank_version(session)
    subject_by_id = {subject.id: subject for subject in subjects}
    by_subject: dict[int, list[Question]] = defaultdict(list)
    for question in questions:
        by_subject[question.subject_id].append(question)

    ga_subject = next(
        (subject for subject in subjects if subject.code.upper() == "GA"), None
    )
    ga_questions = by_subject.get(ga_subject.id, []) if ga_subject else []
    technical_questions = [
        question
        for question in questions
        if subject_by_id[question.subject_id].code.upper() in TECHNICAL_COURSE_CODES
    ]

    definitions: list[dict[str, object]] = [
        _full_form(
            form_number=form_number,
            ga_questions=ga_questions,
            technical_questions=technical_questions,
            bank_version=bank_version,
        )
        for form_number in range(1, FULL_TEST_COUNT + 1)
    ]
    technical_subjects = [
        subject
        for subject in subjects
        if subject.code.upper() in TECHNICAL_COURSE_CODES
    ]
    for subject in technical_subjects:
        for form_number in range(1, COURSE_TEST_COUNT + 1):
            definitions.append(
                _course_form(
                    subject=subject,
                    questions=by_subject.get(subject.id, []),
                    form_number=form_number,
                    bank_version=bank_version,
                )
            )

    existing = {
        form.id: form for form in (await session.scalars(select(TestForm))).all()
    }
    for definition in definitions:
        catalog_id = str(definition["id"])
        form = existing.get(catalog_id)
        if form is None:
            form = TestForm(id=catalog_id)
            session.add(form)
        for field, value in definition.items():
            setattr(form, field, value)
    await session.commit()

