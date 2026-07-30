from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    Difficulty,
    Question,
    QuestionBankImport,
    QuestionSource,
    QuestionType,
    Subject,
    Topic,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_SCHEMA_MAJOR = "1"


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


class BankQuestion(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    external_id: str | None = Field(default=None, max_length=180)
    question: str | None = None
    text: str | None = None
    options: list[Any] = Field(default_factory=list)
    course: str | None = None
    subject_slug: str | None = None
    topic: str | None = None
    topic_slug: str | None = None
    correct_answer: Any
    question_type: str | None = None
    difficulty: str = "medium"
    marks: int = Field(default=1, ge=1, le=2)
    explanation: str = ""
    numerical_tolerance: float = Field(default=0.01, ge=0)
    source_kind: str = "original"
    source_year: int | None = Field(default=None, ge=1987, le=2100)
    source_paper: str | None = None
    source_question_number: int | None = Field(default=None, ge=1)
    source_url: str | None = None
    answer_key_url: str | None = None
    exam_session: str | None = None
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def required_content(self) -> BankQuestion:
        if not (self.question or self.text):
            raise ValueError("question (or text) is required")
        if not (self.course or self.subject_slug):
            raise ValueError("course (or subject_slug) is required")
        if not (self.topic or self.topic_slug):
            raise ValueError("topic (or topic_slug) is required")
        return self


class QuestionBankDocument(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: str = "1.0"
    bank_version: str
    generated_at: datetime | None = None
    questions: list[BankQuestion]


@dataclass(frozen=True, slots=True)
class ImportResult:
    bank_version: str
    checksum: str
    question_count: int
    inserted_count: int
    updated_count: int
    unchanged_count: int
    already_applied: bool


class QuestionBankValidationError(ValueError):
    pass


def resolve_question_bank_path(configured_path: str) -> Path:
    path = Path(configured_path)
    if path.is_absolute():
        return path
    backend_relative = BACKEND_ROOT / path
    if backend_relative.exists():
        return backend_relative
    return Path.cwd() / path


def _load_document(path: Path) -> tuple[QuestionBankDocument, str]:
    raw_bytes = path.read_bytes()
    checksum = hashlib.sha256(raw_bytes).hexdigest()
    try:
        payload = json.loads(raw_bytes.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QuestionBankValidationError(f"Invalid question-bank JSON: {exc}") from exc

    # A flat array is accepted for compatibility, but is wrapped in a versioned
    # document using a content-derived bank version.
    if isinstance(payload, list):
        payload = {
            "schema_version": "1.0",
            "bank_version": f"legacy-{checksum[:12]}",
            "questions": payload,
        }
    elif isinstance(payload, dict):
        if "questions" not in payload and isinstance(payload.get("items"), list):
            payload["questions"] = payload["items"]
        payload.setdefault("schema_version", payload.get("version", "1.0"))
        payload.setdefault(
            "bank_version",
            payload.get("version") or f"content-{checksum[:12]}",
        )
    try:
        document = QuestionBankDocument.model_validate(payload)
    except ValidationError as exc:
        raise QuestionBankValidationError(str(exc)) from exc
    if document.schema_version.split(".", 1)[0] != SUPPORTED_SCHEMA_MAJOR:
        raise QuestionBankValidationError(
            f"Unsupported schema_version {document.schema_version!r}; "
            f"expected major version {SUPPORTED_SCHEMA_MAJOR}"
        )
    if not document.questions:
        raise QuestionBankValidationError("Question bank contains no questions")
    return document, checksum


def _question_type(item: BankQuestion) -> QuestionType:
    raw = (item.question_type or "").strip().lower()
    aliases = {
        "multiple_choice": "mcq",
        "multiple-choice": "mcq",
        "multiple_select": "msq",
        "multiple-select": "msq",
        "numerical": "nat",
        "numerical_answer": "nat",
    }
    raw = aliases.get(raw, raw)
    if not raw:
        raw = "nat" if not item.options else "msq" if isinstance(item.correct_answer, list) else "mcq"
    try:
        return QuestionType(raw)
    except ValueError as exc:
        raise QuestionBankValidationError(
            f"Unsupported question_type {item.question_type!r}"
        ) from exc


def _source_kind(value: str) -> QuestionSource:
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "pyq": "previous_year",
        "previousyear": "previous_year",
        "generated": "original",
        "practice": "original",
    }
    try:
        return QuestionSource(aliases.get(normalized, normalized))
    except ValueError as exc:
        raise QuestionBankValidationError(
            f"Unsupported source_kind {value!r}"
        ) from exc


def _difficulty(value: str) -> Difficulty:
    try:
        return Difficulty(value.strip().lower())
    except ValueError as exc:
        raise QuestionBankValidationError(f"Unsupported difficulty {value!r}") from exc


def _options(values: list[Any]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for index, value in enumerate(values):
        default_id = chr(ord("A") + index)
        if isinstance(value, str):
            normalized.append({"id": default_id, "text": value})
            continue
        if not isinstance(value, dict):
            raise QuestionBankValidationError("Each option must be text or an object")
        identifier = value.get("id", value.get("label", value.get("key", default_id)))
        text = value.get("text", value.get("value", value.get("option")))
        if text is None:
            raise QuestionBankValidationError("Option objects require text or value")
        normalized.append(
            {"id": str(identifier).strip().upper(), "text": str(text).strip()}
        )
    identifiers = [item["id"] for item in normalized]
    if len(identifiers) != len(set(identifiers)):
        raise QuestionBankValidationError("Option identifiers must be unique")
    return normalized


def _answer(
    value: Any, question_type: QuestionType, option_ids: set[str]
) -> Any:
    if question_type == QuestionType.NAT:
        if isinstance(value, dict):
            if {"min", "max"}.issubset(value):
                return {"min": float(value["min"]), "max": float(value["max"])}
            if "value" in value:
                normalized = {"value": float(value["value"])}
                if "tolerance" in value:
                    normalized["tolerance"] = float(value["tolerance"])
                return normalized
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise QuestionBankValidationError(
                f"NAT correct_answer must be numeric or a range, got {value!r}"
            ) from exc

    if question_type == QuestionType.MSQ:
        if isinstance(value, str):
            value = [part for part in re.split(r"[\s,;|]+", value) if part]
        if not isinstance(value, (list, tuple, set)) or not value:
            raise QuestionBankValidationError(
                "MSQ correct_answer must be a non-empty option-ID list"
            )
        normalized = sorted({str(item).strip().upper() for item in value})
        if not set(normalized).issubset(option_ids):
            raise QuestionBankValidationError(
                "MSQ correct_answer references an unknown option"
            )
        return normalized

    normalized = str(value).strip().upper()
    if normalized not in option_ids:
        raise QuestionBankValidationError(
            "MCQ correct_answer references an unknown option"
        )
    return normalized


def _external_id(
    item: BankQuestion,
    *,
    subject: Subject,
    topic: Topic,
    text: str,
    options: list[dict[str, str]],
) -> str:
    if item.external_id:
        return item.external_id.strip()
    source = _source_kind(item.source_kind)
    if (
        source == QuestionSource.PREVIOUS_YEAR
        and item.source_year
        and item.source_paper
        and item.source_question_number
    ):
        paper = _slugify(item.source_paper)
        return f"pyq:{item.source_year}:{paper}:q{item.source_question_number}"
    identity = json.dumps(
        {
            "course": subject.code,
            "topic": topic.slug,
            "question": text,
            "options": options,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"local:{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:32]}"


def _question_values(
    item: BankQuestion,
    *,
    subject: Subject,
    topic: Topic,
    bank_version: str,
) -> dict[str, Any]:
    text = (item.question or item.text or "").strip()
    question_type = _question_type(item)
    options = _options(item.options)
    if question_type != QuestionType.NAT and len(options) < 2:
        raise QuestionBankValidationError(
            f"{question_type.value.upper()} questions require at least two options"
        )
    if question_type == QuestionType.NAT and options:
        raise QuestionBankValidationError("NAT questions cannot contain options")
    correct_answer = _answer(
        item.correct_answer,
        question_type,
        {option["id"] for option in options},
    )
    source_kind = _source_kind(item.source_kind)
    tags = list(dict.fromkeys(str(tag).strip() for tag in item.tags if str(tag).strip()))
    return {
        "external_id": _external_id(
            item,
            subject=subject,
            topic=topic,
            text=text,
            options=options,
        ),
        "bank_version": bank_version,
        "subject_id": subject.id,
        "topic_id": topic.id,
        "source": source_kind,
        "year": item.source_year,
        "exam_session": item.exam_session,
        "source_kind": source_kind,
        "source_year": item.source_year,
        "source_paper": item.source_paper,
        "source_question_number": item.source_question_number,
        "source_url": item.source_url,
        "answer_key_url": item.answer_key_url,
        "question_type": question_type,
        "difficulty": _difficulty(item.difficulty),
        "text": text,
        "options": options,
        "correct_answer": correct_answer,
        "numerical_tolerance": item.numerical_tolerance,
        "marks": item.marks,
        "explanation": item.explanation.strip(),
        "tags": tags,
    }


def _subject_lookup(subjects: list[Subject]) -> dict[str, Subject]:
    lookup: dict[str, Subject] = {}
    for subject in subjects:
        for key in (subject.code, subject.slug, subject.name):
            lookup[_slugify(key)] = subject
    aliases = {
        "math": "EM",
        "mathematics": "EM",
        "engineering-maths": "EM",
        "ds": "PDS",
        "data-structures": "PDS",
        "programming": "PDS",
        "algorithm": "ALG",
        "automata": "TOC",
        "theory-of-computation": "TOC",
        "compiler": "CD",
        "database": "DBMS",
        "networks": "CN",
        "aptitude": "GA",
    }
    by_code = {subject.code.upper(): subject for subject in subjects}
    for alias, code in aliases.items():
        if code in by_code:
            lookup[_slugify(alias)] = by_code[code]
    return lookup


def _topic_lookup(subjects: list[Subject]) -> dict[tuple[int, str], Topic]:
    lookup: dict[tuple[int, str], Topic] = {}
    for subject in subjects:
        for topic in subject.topics:
            lookup[(subject.id, _slugify(topic.slug))] = topic
            lookup[(subject.id, _slugify(topic.name))] = topic
    return lookup


async def import_question_bank(
    session: AsyncSession,
    path: Path,
) -> ImportResult:
    document, checksum = _load_document(path)
    existing_import = await session.scalar(
        select(QuestionBankImport).where(
            QuestionBankImport.bank_version == document.bank_version,
            QuestionBankImport.checksum == checksum,
        )
    )
    if existing_import:
        return ImportResult(
            bank_version=document.bank_version,
            checksum=checksum,
            question_count=existing_import.question_count,
            inserted_count=0,
            updated_count=0,
            unchanged_count=existing_import.question_count,
            already_applied=True,
        )

    subjects = list(
        (
            await session.scalars(
                select(Subject).options(selectinload(Subject.topics))
            )
        ).all()
    )
    subjects_by_key = _subject_lookup(subjects)
    topics_by_key = _topic_lookup(subjects)
    existing_questions = list((await session.scalars(select(Question))).all())
    by_external_id = {
        question.external_id: question
        for question in existing_questions
        if question.external_id
    }
    by_provenance = {
        (
            question.source_kind,
            question.source_year,
            question.source_paper,
            question.source_question_number,
        ): question
        for question in existing_questions
        if question.source_paper and question.source_question_number
    }

    inserted = updated = unchanged = 0
    seen_external_ids: set[str] = set()
    for index, item in enumerate(document.questions, start=1):
        subject_ref = item.course or item.subject_slug or ""
        subject = subjects_by_key.get(_slugify(subject_ref))
        if subject is None:
            raise QuestionBankValidationError(
                f"Question {index}: course {subject_ref!r} is outside the syllabus"
            )
        topic_ref = item.topic or item.topic_slug or ""
        topic = topics_by_key.get((subject.id, _slugify(topic_ref)))
        if topic is None:
            raise QuestionBankValidationError(
                f"Question {index}: topic {topic_ref!r} is not in {subject.code}"
            )
        try:
            values = _question_values(
                item,
                subject=subject,
                topic=topic,
                bank_version=document.bank_version,
            )
        except QuestionBankValidationError as exc:
            raise QuestionBankValidationError(f"Question {index}: {exc}") from exc
        external_id = values["external_id"]
        if external_id in seen_external_ids:
            raise QuestionBankValidationError(
                f"Question {index}: duplicate external_id {external_id!r}"
            )
        seen_external_ids.add(external_id)

        question = by_external_id.get(external_id)
        if question is None and values["source_kind"] == QuestionSource.PREVIOUS_YEAR:
            question = by_provenance.get(
                (
                    values["source_kind"],
                    values["source_year"],
                    values["source_paper"],
                    values["source_question_number"],
                )
            )
        if question is None:
            question = Question(**values)
            session.add(question)
            by_external_id[external_id] = question
            inserted += 1
            continue

        changed = any(getattr(question, field) != value for field, value in values.items())
        if changed:
            for field, value in values.items():
                setattr(question, field, value)
            updated += 1
        else:
            unchanged += 1

    session.add(
        QuestionBankImport(
            schema_version=document.schema_version,
            bank_version=document.bank_version,
            source_path=str(path),
            checksum=checksum,
            question_count=len(document.questions),
            inserted_count=inserted,
            updated_count=updated,
            unchanged_count=unchanged,
        )
    )
    await session.commit()
    return ImportResult(
        bank_version=document.bank_version,
        checksum=checksum,
        question_count=len(document.questions),
        inserted_count=inserted,
        updated_count=updated,
        unchanged_count=unchanged,
        already_applied=False,
    )

