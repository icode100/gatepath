"""Audited, paper-scoped ingestion for GATE previous-year questions.

The archive deliberately stores every source item, including descriptive,
out-of-syllabus, image-dependent, and not-yet-keyed questions.  Only rows that
pass every explicit verification gate may be materialized into the auto-scored
``questions`` table.  Imports never retire originals or PYQs from another
paper.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Difficulty,
    PyqArchiveImport,
    PyqSourcePaper,
    PyqSourceQuestion,
    Question,
    QuestionSource,
    QuestionType,
    Subject,
    Topic,
)
from app.question_bank import _answer, _options


SUPPORTED_SCHEMA_MAJOR = "1"
PRACTICE_TYPES = {"mcq", "msq", "nat"}
VERIFIED_ANSWER_STATUSES = {"official", "community_verified"}


class PyqArchiveValidationError(ValueError):
    pass


class SourceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(min_length=1, max_length=48)
    url: str | None = None
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    note: str | None = None


class AssetReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(min_length=1, max_length=48)
    path: str = Field(min_length=1)
    alt: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")


class ArchivePaper(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=96)
    exam_code: str = Field(default="GATE", min_length=1, max_length=24)
    paper_code: str = Field(default="CS", min_length=1, max_length=24)
    year: int = Field(ge=1987, le=2100)
    session_label: str = Field(default="main", min_length=1, max_length=80)
    display_name: str = Field(min_length=1, max_length=180)
    expected_item_count: int = Field(ge=1)
    source_url: str | None = None
    answer_key_url: str | None = None
    source_pdf_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-fA-F]{64}$"
    )
    answer_key_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-fA-F]{64}$"
    )
    source_status: Literal["verified", "review_required", "rejected"] = (
        "review_required"
    )
    notes: str | None = None

    @model_validator(mode="after")
    def verified_papers_have_a_checksum(self) -> ArchivePaper:
        if self.source_status == "verified" and not self.source_pdf_sha256:
            raise ValueError("verified papers require source_pdf_sha256")
        return self


class ArchiveQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_paper_id: str = Field(min_length=1, max_length=96)
    item_label: str = Field(min_length=1, max_length=48)
    ordinal: int = Field(ge=1)
    parent_item_label: str | None = Field(default=None, max_length=48)
    source_page: int | None = Field(default=None, ge=1)
    marks: float | None = Field(default=None, gt=0)
    item_type: Literal[
        "mcq", "msq", "nat", "descriptive", "composite", "unknown"
    ] = "unknown"
    question_md: str | None = None
    options: list[Any] = Field(default_factory=list)
    accepted_answers: Any | None = None
    solution_md: str | None = None
    subject_code: str | None = Field(default=None, max_length=16)
    topic_slug: str | None = Field(default=None, max_length=100)
    syllabus_status: Literal[
        "in_syllabus", "out_of_syllabus", "review_required"
    ] = "review_required"
    transcription_status: Literal["verified", "review_required", "missing"] = (
        "missing"
    )
    answer_status: Literal[
        "official", "community_verified", "unresolved", "not_applicable"
    ] = "unresolved"
    classification_status: Literal[
        "verified", "review_required", "out_of_syllabus"
    ] = "review_required"
    practice_eligible: bool = False
    review_flags: list[str] = Field(default_factory=list)
    assets: list[AssetReference] = Field(default_factory=list)
    source_references: list[SourceReference] = Field(default_factory=list)
    extraction_method: str | None = Field(default=None, max_length=80)
    extraction_confidence: float | None = Field(default=None, ge=0, le=1)
    content_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-fA-F]{64}$"
    )

    @model_validator(mode="after")
    def validated_practice_gate(self) -> ArchiveQuestion:
        self.item_label = self.item_label.strip()
        self.question_md = self.question_md.strip() if self.question_md else None
        self.solution_md = self.solution_md.strip() if self.solution_md else None
        self.review_flags = list(
            dict.fromkeys(flag.strip() for flag in self.review_flags if flag.strip())
        )
        if self.transcription_status == "verified" and not self.question_md:
            raise ValueError("verified transcription requires question_md")
        if not self.practice_eligible:
            return self
        failures: list[str] = []
        if self.item_type not in PRACTICE_TYPES:
            failures.append("unsupported item_type")
        if self.transcription_status != "verified":
            failures.append("transcription is not verified")
        if self.answer_status not in VERIFIED_ANSWER_STATUSES:
            failures.append("answer is not verified")
        if self.classification_status != "verified":
            failures.append("classification is not verified")
        if self.syllabus_status != "in_syllabus":
            failures.append("item is outside or unverified against the syllabus")
        if not self.subject_code or not self.topic_slug:
            failures.append("course/topic is missing")
        if self.review_flags:
            failures.append("review_flags are present")
        if self.accepted_answers is None:
            failures.append("accepted_answers is missing")
        if not self.solution_md:
            failures.append("solution_md is missing")
        if self.marks not in {1, 2, 1.0, 2.0}:
            failures.append("auto-scored practice requires one or two marks")
        if failures:
            raise ValueError("practice_eligible item failed gates: " + "; ".join(failures))
        return self


class PyqArchiveDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    artifact_version: str = Field(min_length=1, max_length=96)
    papers: list[ArchivePaper] = Field(min_length=1)
    questions: list[ArchiveQuestion] = Field(min_length=1)


@dataclass(frozen=True, slots=True)
class PyqArchiveImportResult:
    artifact_version: str
    checksum: str
    paper_count: int
    item_count: int
    inserted_count: int
    updated_count: int
    unchanged_count: int
    materialized_count: int
    retired_count: int
    original_active_count: int
    already_applied: bool
    dry_run: bool


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _load_document(path: Path) -> tuple[PyqArchiveDocument, str]:
    raw = path.read_bytes()
    checksum = hashlib.sha256(raw).hexdigest()
    try:
        payload = json.loads(raw)
        document = PyqArchiveDocument.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise PyqArchiveValidationError(str(exc)) from exc
    if document.schema_version.split(".", 1)[0] != SUPPORTED_SCHEMA_MAJOR:
        raise PyqArchiveValidationError(
            f"Unsupported archive schema {document.schema_version!r}"
        )
    _validate_document(document)
    return document, checksum


def _content_sha256(item: ArchiveQuestion) -> str:
    payload = {
        "item_label": item.item_label,
        "question_md": item.question_md,
        "options": item.options,
        "accepted_answers": item.accepted_answers,
        "solution_md": item.solution_md,
        "subject_code": item.subject_code,
        "topic_slug": item.topic_slug,
        "assets": [asset.model_dump(mode="json") for asset in item.assets],
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_document(document: PyqArchiveDocument) -> None:
    papers_by_id: dict[str, ArchivePaper] = {}
    paper_sessions: set[tuple[str, str, int, str]] = set()
    for paper in document.papers:
        if paper.id in papers_by_id:
            raise PyqArchiveValidationError(f"Duplicate paper id {paper.id!r}")
        session_identity = (
            paper.exam_code.upper(),
            paper.paper_code.upper(),
            paper.year,
            paper.session_label.casefold(),
        )
        if session_identity in paper_sessions:
            raise PyqArchiveValidationError(
                f"Duplicate paper session {paper.year}/{paper.session_label}"
            )
        paper_sessions.add(session_identity)
        papers_by_id[paper.id] = paper

    questions_by_paper: dict[str, list[ArchiveQuestion]] = {
        paper_id: [] for paper_id in papers_by_id
    }
    labels: set[tuple[str, str]] = set()
    ordinals: set[tuple[str, int]] = set()
    for item in document.questions:
        paper = papers_by_id.get(item.source_paper_id)
        if paper is None:
            raise PyqArchiveValidationError(
                f"Question {item.item_label!r} references unknown paper "
                f"{item.source_paper_id!r}"
            )
        label_key = (paper.id, item.item_label.casefold())
        ordinal_key = (paper.id, item.ordinal)
        if label_key in labels:
            raise PyqArchiveValidationError(
                f"Duplicate item label {paper.id}/{item.item_label}"
            )
        if ordinal_key in ordinals:
            raise PyqArchiveValidationError(
                f"Duplicate item ordinal {paper.id}/{item.ordinal}"
            )
        labels.add(label_key)
        ordinals.add(ordinal_key)
        questions_by_paper[paper.id].append(item)
        computed_hash = _content_sha256(item)
        if item.content_sha256 and item.content_sha256.lower() != computed_hash:
            raise PyqArchiveValidationError(
                f"Content checksum mismatch for {paper.id}/{item.item_label}"
            )
        if item.practice_eligible and paper.source_status != "verified":
            raise PyqArchiveValidationError(
                f"Practice item {paper.id}/{item.item_label} uses an unverified paper"
            )

    for paper_id, paper in papers_by_id.items():
        items = questions_by_paper[paper_id]
        if len(items) != paper.expected_item_count:
            raise PyqArchiveValidationError(
                f"Paper {paper_id} expected {paper.expected_item_count} items, "
                f"found {len(items)}"
            )
        expected_ordinals = list(range(1, paper.expected_item_count + 1))
        actual_ordinals = sorted(item.ordinal for item in items)
        if actual_ordinals != expected_ordinals:
            raise PyqArchiveValidationError(
                f"Paper {paper_id} ordinals must be contiguous 1.."
                f"{paper.expected_item_count}"
            )


def _paper_values(paper: ArchivePaper) -> dict[str, Any]:
    return {
        "exam_code": paper.exam_code.upper(),
        "paper_code": paper.paper_code.upper(),
        "year": paper.year,
        "session_label": paper.session_label,
        "display_name": paper.display_name,
        "expected_item_count": paper.expected_item_count,
        "source_url": paper.source_url,
        "answer_key_url": paper.answer_key_url,
        "source_pdf_sha256": (
            paper.source_pdf_sha256.lower() if paper.source_pdf_sha256 else None
        ),
        "answer_key_sha256": (
            paper.answer_key_sha256.lower() if paper.answer_key_sha256 else None
        ),
        "source_status": paper.source_status,
        "notes": paper.notes,
    }


def _source_question_values(item: ArchiveQuestion) -> dict[str, Any]:
    return {
        "item_label": item.item_label,
        "ordinal": item.ordinal,
        "parent_item_label": item.parent_item_label,
        "source_page": item.source_page,
        "marks": item.marks,
        "item_type": item.item_type,
        "question_md": item.question_md,
        # Preserve the audited source transcription exactly.  Strict option
        # normalization happens only at the practice-materialization gate.
        "options": item.options,
        "accepted_answers": item.accepted_answers,
        "solution_md": item.solution_md,
        "subject_code": item.subject_code.upper() if item.subject_code else None,
        "topic_slug": item.topic_slug,
        "syllabus_status": item.syllabus_status,
        "transcription_status": item.transcription_status,
        "answer_status": item.answer_status,
        "classification_status": item.classification_status,
        "practice_eligible": item.practice_eligible,
        "review_flags": list(item.review_flags),
        "assets": [asset.model_dump(mode="json") for asset in item.assets],
        "source_references": [
            reference.model_dump(mode="json") for reference in item.source_references
        ],
        "extraction_method": item.extraction_method,
        "extraction_confidence": item.extraction_confidence,
        "content_sha256": _content_sha256(item),
    }


def _changed(model: Any, values: dict[str, Any]) -> bool:
    return any(getattr(model, field) != value for field, value in values.items())


def _resolved_practice_values(
    item: ArchiveQuestion,
    paper: ArchivePaper,
    *,
    subjects_by_code: dict[str, Subject],
    topics_by_scope: dict[tuple[int, str], Topic],
) -> dict[str, Any]:
    subject = subjects_by_code.get(str(item.subject_code).upper())
    if subject is None:
        raise PyqArchiveValidationError(
            f"{paper.id}/{item.item_label}: unknown course {item.subject_code!r}"
        )
    topic = topics_by_scope.get((subject.id, _slug(str(item.topic_slug))))
    if topic is None:
        raise PyqArchiveValidationError(
            f"{paper.id}/{item.item_label}: topic {item.topic_slug!r} is not in "
            f"{subject.code}"
        )
    question_type = QuestionType(item.item_type)
    options = _options(item.options)
    if question_type != QuestionType.NAT and len(options) < 2:
        raise PyqArchiveValidationError(
            f"{paper.id}/{item.item_label}: MCQ/MSQ needs at least two options"
        )
    if question_type == QuestionType.NAT and options:
        raise PyqArchiveValidationError(
            f"{paper.id}/{item.item_label}: NAT cannot contain options"
        )
    try:
        answer = _answer(
            item.accepted_answers,
            question_type,
            {option["id"] for option in options},
        )
    except ValueError as exc:
        raise PyqArchiveValidationError(
            f"{paper.id}/{item.item_label}: {exc}"
        ) from exc
    return {
        "external_id": f"pyq:{paper.id}:{_slug(item.item_label)}",
        # Archive-managed rows remain outside the globally authoritative bank
        # version so a normal full-bank bootstrap cannot retire them.
        "bank_version": None,
        "is_active": True,
        "subject_id": subject.id,
        "topic_id": topic.id,
        "source": QuestionSource.PREVIOUS_YEAR,
        "year": paper.year,
        "exam_session": paper.session_label,
        "source_kind": QuestionSource.PREVIOUS_YEAR,
        "source_year": paper.year,
        "source_paper": paper.id,
        "source_question_number": item.ordinal,
        "source_paper_id": paper.id,
        "source_item_label": item.item_label,
        "source_page": item.source_page,
        "source_url": paper.source_url,
        "answer_key_url": paper.answer_key_url,
        "extraction_method": item.extraction_method,
        "extraction_confidence": item.extraction_confidence,
        "question_type": question_type,
        "difficulty": Difficulty.MEDIUM,
        "text": str(item.question_md),
        "options": options,
        "correct_answer": answer,
        "numerical_tolerance": 0.01,
        "marks": int(float(item.marks or 1)),
        "explanation": str(item.solution_md),
        "tags": ["pyq", str(paper.year), paper.id, item.item_label],
    }


async def import_pyq_archive(
    session: AsyncSession,
    path: Path,
    *,
    dry_run: bool = True,
    materialize: bool = False,
    expected_original_count: int | None = None,
) -> PyqArchiveImportResult:
    """Validate and apply one immutable, paper-scoped PYQ artifact.

    ``dry_run`` is the default.  Materialization is opt-in and can only touch
    previous-year rows belonging to papers declared in this artifact.
    """

    document, checksum = _load_document(path)
    previous_version_rows = list(
        (
            await session.scalars(
                select(PyqArchiveImport).where(
                    PyqArchiveImport.artifact_version == document.artifact_version
                )
            )
        ).all()
    )
    conflicting_checksums = {
        row.checksum for row in previous_version_rows if row.checksum != checksum
    }
    if conflicting_checksums:
        raise PyqArchiveValidationError(
            f"Artifact version {document.artifact_version!r} was already used with "
            "a different checksum; create a new immutable version"
        )
    exact_import = next(
        (row for row in previous_version_rows if row.checksum == checksum), None
    )

    paper_ids = [paper.id for paper in document.papers]
    existing_papers = {
        paper.id: paper
        for paper in (
            await session.scalars(
                select(PyqSourcePaper).where(PyqSourcePaper.id.in_(paper_ids))
            )
        ).all()
    }
    existing_source_questions = list(
        (
            await session.scalars(
                select(PyqSourceQuestion).where(
                    PyqSourceQuestion.source_paper_id.in_(paper_ids)
                )
            )
        ).all()
    )
    by_paper_ordinal = {
        (item.source_paper_id, item.ordinal): item
        for item in existing_source_questions
    }

    subjects = list((await session.scalars(select(Subject))).all())
    topics = list((await session.scalars(select(Topic))).all())
    subjects_by_code = {subject.code.upper(): subject for subject in subjects}
    topics_by_scope = {
        (topic.subject_id, _slug(topic.slug)): topic for topic in topics
    }
    main_questions = list(
        (
            await session.scalars(
                select(Question).where(
                    (Question.source_paper_id.in_(paper_ids))
                    | (Question.external_id.like("pyq:%"))
                )
            )
        ).all()
    )
    main_by_external = {
        question.external_id: question
        for question in main_questions
        if question.external_id
    }
    main_by_id = {question.id: question for question in main_questions}

    original_count = int(
        await session.scalar(
            select(func.count(Question.id)).where(
                Question.source_kind == QuestionSource.ORIGINAL,
                Question.is_active.is_(True),
            )
        )
        or 0
    )
    if (
        expected_original_count is not None
        and original_count != expected_original_count
    ):
        raise PyqArchiveValidationError(
            "Active original-question count does not match the required baseline "
            f"({original_count} != {expected_original_count})"
        )

    inserted = updated = unchanged = materialized_count = retired = 0
    paper_models: dict[str, PyqSourcePaper] = {}
    for paper in document.papers:
        values = _paper_values(paper)
        existing = existing_papers.get(paper.id)
        if existing is None:
            inserted += 1
            model = PyqSourcePaper(id=paper.id, **values)
        else:
            model = existing
            if _changed(existing, values):
                updated += 1
            else:
                unchanged += 1
        if not dry_run:
            if existing is None:
                session.add(model)
            else:
                for field, value in values.items():
                    setattr(model, field, value)
        paper_models[paper.id] = model

    papers_by_id = {paper.id: paper for paper in document.papers}
    prepared_questions: list[
        tuple[ArchiveQuestion, dict[str, Any], PyqSourceQuestion | None]
    ] = []
    for item in document.questions:
        values = _source_question_values(item)
        existing = by_paper_ordinal.get((item.source_paper_id, item.ordinal))
        if existing is None:
            inserted += 1
        elif _changed(existing, values):
            updated += 1
        else:
            unchanged += 1
        prepared_questions.append((item, values, existing))

    # Resolve every materialization before mutating ORM objects.  A bad course,
    # topic, answer, or option therefore leaves the transaction untouched.
    resolved_materializations: dict[tuple[str, int], dict[str, Any]] = {}
    if materialize:
        for item, _, _ in prepared_questions:
            if item.practice_eligible:
                paper = papers_by_id[item.source_paper_id]
                resolved_materializations[(item.source_paper_id, item.ordinal)] = (
                    _resolved_practice_values(
                        item,
                        paper,
                        subjects_by_code=subjects_by_code,
                        topics_by_scope=topics_by_scope,
                    )
                )

    if not dry_run:
        await session.flush()

    for item, values, existing in prepared_questions:
        source_model = existing
        if source_model is None:
            source_model = PyqSourceQuestion(
                source_paper_id=item.source_paper_id,
                **values,
            )
            if not dry_run:
                session.add(source_model)
        elif not dry_run:
            for field, value in values.items():
                setattr(source_model, field, value)

        if not materialize:
            continue
        materialized_values = resolved_materializations.get(
            (item.source_paper_id, item.ordinal)
        )
        linked = (
            main_by_id.get(source_model.materialized_question_id)
            if source_model.materialized_question_id is not None
            else None
        )
        if materialized_values is None:
            if linked is not None and linked.is_active:
                retired += 1
                if not dry_run:
                    linked.is_active = False
            continue
        question = linked or main_by_external.get(materialized_values["external_id"])
        if question is None:
            materialized_count += 1
            if not dry_run:
                question = Question(**materialized_values)
                session.add(question)
                await session.flush()
                source_model.materialized_question_id = question.id
                main_by_external[question.external_id] = question
                main_by_id[question.id] = question
            continue
        if _changed(question, materialized_values):
            materialized_count += 1
            if not dry_run:
                for field, value in materialized_values.items():
                    setattr(question, field, value)
        if not dry_run:
            source_model.materialized_question_id = question.id

    if dry_run:
        return PyqArchiveImportResult(
            artifact_version=document.artifact_version,
            checksum=checksum,
            paper_count=len(document.papers),
            item_count=len(document.questions),
            inserted_count=inserted,
            updated_count=updated,
            unchanged_count=unchanged,
            materialized_count=materialized_count,
            retired_count=retired,
            original_active_count=original_count,
            already_applied=exact_import is not None and not any(
                (inserted, updated, materialized_count, retired)
            ),
            dry_run=True,
        )

    await session.flush()
    original_count_after = int(
        await session.scalar(
            select(func.count(Question.id)).where(
                Question.source_kind == QuestionSource.ORIGINAL,
                Question.is_active.is_(True),
            )
        )
        or 0
    )
    if original_count_after != original_count:
        await session.rollback()
        raise PyqArchiveValidationError(
            "PYQ import changed the active original-question count "
            f"({original_count} -> {original_count_after})"
        )

    if exact_import is None:
        session.add(
            PyqArchiveImport(
                schema_version=document.schema_version,
                artifact_version=document.artifact_version,
                checksum=checksum,
                source_path=str(path),
                paper_count=len(document.papers),
                item_count=len(document.questions),
                inserted_count=inserted,
                updated_count=updated,
                unchanged_count=unchanged,
                materialized_count=materialized_count,
                retired_count=retired,
            )
        )
    await session.commit()
    return PyqArchiveImportResult(
        artifact_version=document.artifact_version,
        checksum=checksum,
        paper_count=len(document.papers),
        item_count=len(document.questions),
        inserted_count=inserted,
        updated_count=updated,
        unchanged_count=unchanged,
        materialized_count=materialized_count,
        retired_count=retired,
        original_active_count=original_count_after,
        already_applied=exact_import is not None and not any(
            (inserted, updated, materialized_count, retired)
        ),
        dry_run=False,
    )
