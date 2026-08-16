from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class QuestionType(str, enum.Enum):
    MCQ = "mcq"
    MSQ = "msq"
    NAT = "nat"


class QuestionSource(str, enum.Enum):
    ORIGINAL = "original"
    PREVIOUS_YEAR = "previous_year"


class Difficulty(str, enum.Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class SessionMode(str, enum.Enum):
    PRACTICE = "practice"
    SECTIONAL = "sectional"
    FULL = "full"


class ResponseStatus(str, enum.Enum):
    CORRECT = "correct"
    INCORRECT = "incorrect"
    UNANSWERED = "unanswered"


class Subject(Base):
    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    code: Mapped[str] = mapped_column(String(16), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text)
    order_index: Mapped[int] = mapped_column(Integer, default=0, index=True)

    topics: Mapped[list[Topic]] = relationship(
        back_populates="subject",
        cascade="all, delete-orphan",
        order_by="Topic.order_index",
    )
    questions: Mapped[list[Question]] = relationship(back_populates="subject")


class Topic(Base):
    __tablename__ = "topics"
    __table_args__ = (
        UniqueConstraint("subject_id", "slug", name="uq_topic_subject_slug"),
        Index("ix_topics_subject_order", "subject_id", "order_index"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), index=True
    )
    slug: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text)
    order_index: Mapped[int] = mapped_column(Integer, default=0)

    subject: Mapped[Subject] = relationship(back_populates="topics")
    note: Mapped[RevisionNote | None] = relationship(
        back_populates="topic", cascade="all, delete-orphan", uselist=False
    )
    questions: Mapped[list[Question]] = relationship(
        back_populates="topic", cascade="all, delete-orphan"
    )


class RevisionNote(Base):
    __tablename__ = "revision_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    topic_id: Mapped[int] = mapped_column(
        ForeignKey("topics.id", ondelete="CASCADE"), unique=True, index=True
    )
    title: Mapped[str] = mapped_column(String(180))
    summary: Mapped[str] = mapped_column(Text)
    content_md: Mapped[str] = mapped_column(Text)
    key_points: Mapped[list[str]] = mapped_column(JSON, default=list)
    worked_examples: Mapped[list[dict[str, str]]] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    topic: Mapped[Topic] = relationship(back_populates="note")


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (
        Index("ix_questions_subject_topic", "subject_id", "topic_id"),
        Index("ix_questions_legacy_source_year", "source", "year"),
        UniqueConstraint(
            "source_kind",
            "source_year",
            "source_paper",
            "source_question_number",
            name="uq_question_provenance",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str | None] = mapped_column(
        String(180), nullable=True, unique=True, index=True
    )
    bank_version: Mapped[str | None] = mapped_column(
        String(80), nullable=True, index=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", index=True
    )
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), index=True
    )
    topic_id: Mapped[int] = mapped_column(
        ForeignKey("topics.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[QuestionSource] = mapped_column(
        Enum(QuestionSource, native_enum=False), default=QuestionSource.ORIGINAL
    )
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exam_session: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # Explicit provenance fields are preferred by new clients. The legacy
    # source/year/exam_session columns above remain for API compatibility.
    source_kind: Mapped[QuestionSource] = mapped_column(
        Enum(QuestionSource, native_enum=False),
        default=QuestionSource.ORIGINAL,
        index=True,
    )
    source_year: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    source_paper: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_question_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Canonical paper/item identity for the audited PYQ archive.  Legacy papers
    # use labels such as ``2.25`` and ``24-b`` which cannot be represented by
    # ``source_question_number`` alone.
    source_paper_id: Mapped[str | None] = mapped_column(
        String(96),
        ForeignKey("pyq_source_papers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_item_label: Mapped[str | None] = mapped_column(
        String(48), nullable=True
    )
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer_key_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_method: Mapped[str | None] = mapped_column(String(80), nullable=True)
    extraction_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    question_type: Mapped[QuestionType] = mapped_column(
        Enum(QuestionType, native_enum=False), index=True
    )
    difficulty: Mapped[Difficulty] = mapped_column(
        Enum(Difficulty, native_enum=False), default=Difficulty.MEDIUM, index=True
    )
    text: Mapped[str] = mapped_column(Text)
    options: Mapped[list[dict[str, str]]] = mapped_column(JSON, default=list)
    correct_answer: Mapped[Any] = mapped_column(JSON)
    numerical_tolerance: Mapped[float] = mapped_column(Float, default=0.01)
    marks: Mapped[int] = mapped_column(Integer, default=1)
    explanation: Mapped[str] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    # Immutable, same-origin projections of promotion-approved original-PDF
    # crops. Archive/review assets remain solely in ``pyq_source_questions``.
    assets: Mapped[list[dict[str, str]]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    subject: Mapped[Subject] = relationship(back_populates="questions")
    topic: Mapped[Topic] = relationship(back_populates="questions")
    responses: Mapped[list[AttemptResponse]] = relationship(back_populates="question")


class PracticeSession(Base):
    __tablename__ = "practice_sessions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_key: Mapped[str] = mapped_column(String(100), default="local-user", index=True)
    catalog_id: Mapped[str | None] = mapped_column(
        ForeignKey("test_forms.id", ondelete="SET NULL"), nullable=True, index=True
    )
    mode: Mapped[SessionMode] = mapped_column(Enum(SessionMode, native_enum=False))
    subject_id: Mapped[int | None] = mapped_column(
        ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True
    )
    topic_id: Mapped[int | None] = mapped_column(
        ForeignKey("topics.id", ondelete="SET NULL"), nullable=True
    )
    question_ids: Mapped[list[int]] = mapped_column(JSON)
    # Immutable copies of the questions as presented when the session starts.
    # This keeps both display and grading stable when a later bank import edits
    # or retires a question.
    question_snapshots: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list
    )
    question_count: Mapped[int] = mapped_column(Integer)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_marks: Mapped[int] = mapped_column(Integer)
    seed: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_submitted: Mapped[bool] = mapped_column(Boolean, default=False)

    attempt: Mapped[Attempt | None] = relationship(
        back_populates="session", uselist=False, cascade="all, delete-orphan"
    )


class QuestionBankImport(Base):
    __tablename__ = "question_bank_imports"
    __table_args__ = (
        UniqueConstraint(
            "bank_version", "checksum", name="uq_question_bank_version_checksum"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    schema_version: Mapped[str] = mapped_column(String(32))
    bank_version: Mapped[str] = mapped_column(String(80), index=True)
    source_path: Mapped[str] = mapped_column(Text)
    checksum: Mapped[str] = mapped_column(String(64), index=True)
    question_count: Mapped[int] = mapped_column(Integer)
    inserted_count: Mapped[int] = mapped_column(Integer)
    updated_count: Mapped[int] = mapped_column(Integer)
    unchanged_count: Mapped[int] = mapped_column(Integer)
    retired_count: Mapped[int] = mapped_column(Integer, default=0)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class PyqSourcePaper(Base):
    """One canonical GATE paper/session and its verified source artifacts."""

    __tablename__ = "pyq_source_papers"
    __table_args__ = (
        UniqueConstraint(
            "exam_code",
            "paper_code",
            "year",
            "session_label",
            name="uq_pyq_source_paper_session",
        ),
        Index("ix_pyq_source_papers_year_session", "year", "session_label"),
    )

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    exam_code: Mapped[str] = mapped_column(String(24), default="GATE")
    paper_code: Mapped[str] = mapped_column(String(24), default="CS")
    year: Mapped[int] = mapped_column(Integer, index=True)
    session_label: Mapped[str] = mapped_column(String(80), default="main")
    display_name: Mapped[str] = mapped_column(String(180))
    expected_item_count: Mapped[int] = mapped_column(Integer)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer_key_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_pdf_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    answer_key_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_status: Mapped[str] = mapped_column(
        String(32), default="review_required", index=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    source_questions: Mapped[list[PyqSourceQuestion]] = relationship(
        back_populates="source_paper",
        cascade="all, delete-orphan",
        order_by="PyqSourceQuestion.ordinal",
    )


class PyqSourceQuestion(Base):
    """Audited source record, including non-gradable and legacy questions."""

    __tablename__ = "pyq_source_questions"
    __table_args__ = (
        UniqueConstraint(
            "source_paper_id",
            "item_label",
            name="uq_pyq_source_question_label",
        ),
        UniqueConstraint(
            "source_paper_id",
            "ordinal",
            name="uq_pyq_source_question_ordinal",
        ),
        Index(
            "ix_pyq_source_questions_verification",
            "transcription_status",
            "answer_status",
            "classification_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_paper_id: Mapped[str] = mapped_column(
        String(96),
        ForeignKey("pyq_source_papers.id", ondelete="CASCADE"),
        index=True,
    )
    item_label: Mapped[str] = mapped_column(String(48))
    ordinal: Mapped[int] = mapped_column(Integer)
    parent_item_label: Mapped[str | None] = mapped_column(String(48), nullable=True)
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    marks: Mapped[float | None] = mapped_column(Float, nullable=True)
    item_type: Mapped[str] = mapped_column(String(24), default="unknown", index=True)
    question_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    options: Mapped[list[Any]] = mapped_column(JSON, default=list)
    accepted_answers: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    solution_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    subject_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    topic_slug: Mapped[str | None] = mapped_column(String(100), nullable=True)
    syllabus_status: Mapped[str] = mapped_column(
        String(32), default="review_required", index=True
    )
    transcription_status: Mapped[str] = mapped_column(
        String(32), default="missing", index=True
    )
    answer_status: Mapped[str] = mapped_column(
        String(32), default="unresolved", index=True
    )
    classification_status: Mapped[str] = mapped_column(
        String(32), default="review_required", index=True
    )
    practice_eligible: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", index=True
    )
    review_flags: Mapped[list[str]] = mapped_column(JSON, default=list)
    assets: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    source_references: Mapped[list[dict[str, str]]] = mapped_column(
        JSON, default=list
    )
    extraction_method: Mapped[str | None] = mapped_column(String(80), nullable=True)
    extraction_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    materialized_question_id: Mapped[int | None] = mapped_column(
        ForeignKey("questions.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    source_paper: Mapped[PyqSourcePaper] = relationship(
        back_populates="source_questions"
    )


class PyqArchiveImport(Base):
    """Immutable audit row for an applied paper-scoped archive artifact."""

    __tablename__ = "pyq_archive_imports"
    __table_args__ = (
        UniqueConstraint(
            "artifact_version",
            "checksum",
            name="uq_pyq_archive_version_checksum",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    schema_version: Mapped[str] = mapped_column(String(32))
    artifact_version: Mapped[str] = mapped_column(String(96), index=True)
    checksum: Mapped[str] = mapped_column(String(64), index=True)
    source_path: Mapped[str] = mapped_column(Text)
    paper_count: Mapped[int] = mapped_column(Integer)
    item_count: Mapped[int] = mapped_column(Integer)
    inserted_count: Mapped[int] = mapped_column(Integer)
    updated_count: Mapped[int] = mapped_column(Integer)
    unchanged_count: Mapped[int] = mapped_column(Integer)
    materialized_count: Mapped[int] = mapped_column(Integer, default=0)
    retired_count: Mapped[int] = mapped_column(Integer, default=0)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class PyqArchiveExecution(Base):
    """Immutable audit event for each live archive apply execution.

    ``PyqArchiveImport`` identifies immutable artifact bytes.  This table is
    deliberately one-to-many so applying the archive first and materializing
    it later cannot erase the second operation from the audit trail.
    """

    __tablename__ = "pyq_archive_executions"
    __table_args__ = (
        Index(
            "ix_pyq_archive_executions_artifact",
            "artifact_version",
            "checksum",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    archive_import_id: Mapped[int] = mapped_column(
        ForeignKey("pyq_archive_imports.id", ondelete="RESTRICT"),
        index=True,
    )
    artifact_version: Mapped[str] = mapped_column(String(96), index=True)
    checksum: Mapped[str] = mapped_column(String(64), index=True)
    execution_mode: Mapped[str] = mapped_column(String(32), index=True)
    inserted_count: Mapped[int] = mapped_column(Integer)
    updated_count: Mapped[int] = mapped_column(Integer)
    unchanged_count: Mapped[int] = mapped_column(Integer)
    materialized_inserted_count: Mapped[int] = mapped_column(Integer)
    materialized_adopted_count: Mapped[int] = mapped_column(Integer)
    materialized_updated_count: Mapped[int] = mapped_column(Integer)
    retired_count: Mapped[int] = mapped_column(Integer)
    reactivated_count: Mapped[int] = mapped_column(Integer, default=0)
    visibility_plan_sha256: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    original_active_before: Mapped[int] = mapped_column(Integer)
    original_active_after: Mapped[int] = mapped_column(Integer)
    pyq_active_before: Mapped[int] = mapped_column(Integer)
    pyq_active_after: Mapped[int] = mapped_column(Integer)
    expected_original_count: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    original_guard_bypassed: Mapped[bool] = mapped_column(Boolean)
    retirement_allowed: Mapped[bool] = mapped_column(Boolean)
    expected_retirement_count: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    expected_reactivation_count: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    expected_active_pyqs_before: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    expected_active_pyqs_after: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class TestForm(Base):
    __tablename__ = "test_forms"
    __table_args__ = (
        UniqueConstraint(
            "mode", "subject_id", "form_number", name="uq_test_form_scope_number"
        ),
        Index("ix_test_forms_mode_active", "mode", "is_available"),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    title: Mapped[str] = mapped_column(String(180))
    description: Mapped[str] = mapped_column(Text)
    mode: Mapped[SessionMode] = mapped_column(
        Enum(SessionMode, native_enum=False), index=True
    )
    subject_id: Mapped[int | None] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    form_number: Mapped[int] = mapped_column(Integer)
    question_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    question_count: Mapped[int] = mapped_column(Integer)
    duration_seconds: Mapped[int] = mapped_column(Integer)
    total_marks: Mapped[int] = mapped_column(Integer)
    seed: Mapped[int] = mapped_column(Integer)
    question_type_counts: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)
    topic_count: Mapped[int] = mapped_column(Integer, default=0)
    bank_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    is_available: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    unavailable_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    subject: Mapped[Subject | None] = relationship()


class Attempt(Base):
    __tablename__ = "attempts"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    session_id: Mapped[str] = mapped_column(
        ForeignKey("practice_sessions.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    user_key: Mapped[str] = mapped_column(String(100), default="local-user", index=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    timed_out: Mapped[bool] = mapped_column(Boolean, default=False)
    score: Mapped[float] = mapped_column(Float)
    max_score: Mapped[float] = mapped_column(Float)
    correct_count: Mapped[int] = mapped_column(Integer)
    incorrect_count: Mapped[int] = mapped_column(Integer)
    unanswered_count: Mapped[int] = mapped_column(Integer)

    session: Mapped[PracticeSession] = relationship(back_populates="attempt")
    responses: Mapped[list[AttemptResponse]] = relationship(
        back_populates="attempt", cascade="all, delete-orphan"
    )


class AttemptResponse(Base):
    __tablename__ = "attempt_responses"
    __table_args__ = (
        UniqueConstraint("attempt_id", "question_id", name="uq_attempt_question"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    attempt_id: Mapped[str] = mapped_column(
        ForeignKey("attempts.id", ondelete="CASCADE"), index=True
    )
    question_id: Mapped[int] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), index=True
    )
    answer: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    correct_answer_snapshot: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    explanation_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ResponseStatus] = mapped_column(
        Enum(ResponseStatus, native_enum=False), index=True
    )
    awarded_marks: Mapped[float] = mapped_column(Float)
    max_marks: Mapped[float] = mapped_column(Float)
    negative_marks: Mapped[float] = mapped_column(Float, default=0.0)

    attempt: Mapped[Attempt] = relationship(back_populates="responses")
    question: Mapped[Question] = relationship(back_populates="responses")
