from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import (
    Difficulty,
    QuestionSource,
    QuestionType,
    ResponseStatus,
    SessionMode,
)


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class TopicSummary(ApiModel):
    id: int
    subject_id: int
    slug: str
    name: str
    description: str
    order_index: int
    question_count: int = 0
    note_available: bool = False


class SubjectSummary(ApiModel):
    id: int
    slug: str
    code: str
    name: str
    description: str
    order_index: int
    topic_count: int = 0
    question_count: int = 0


class SubjectDetail(SubjectSummary):
    topics: list[TopicSummary]


class WorkedExample(BaseModel):
    question: str
    solution: str


class RevisionNoteRead(ApiModel):
    id: int
    topic_id: int
    title: str
    summary: str
    content_md: str
    key_points: list[str]
    worked_examples: list[WorkedExample]
    updated_at: datetime


class QuestionOption(BaseModel):
    id: str
    text: str


class QuestionPublic(ApiModel):
    id: int
    subject_id: int
    subject_slug: str
    subject_name: str
    topic_id: int
    topic_slug: str
    topic_name: str
    source: QuestionSource
    year: int | None
    exam_session: str | None
    source_kind: QuestionSource
    source_year: int | None
    source_paper: str | None
    source_question_number: int | None
    source_url: str | None
    answer_key_url: str | None
    question_type: QuestionType
    difficulty: Difficulty
    text: str
    options: list[QuestionOption]
    numerical_tolerance: float | None = None
    marks: int
    tags: list[str]


class QuestionListResponse(BaseModel):
    items: list[QuestionPublic]
    total: int
    limit: int
    offset: int


class PracticeSessionCreate(BaseModel):
    user_key: str = Field(default="local-user", min_length=1, max_length=100)
    subject_id: int | None = None
    subject_slug: str | None = None
    topic_id: int | None = None
    count: int = Field(default=10, ge=1, le=100)
    question_types: list[QuestionType] | None = None
    difficulties: list[Difficulty] | None = None
    source: QuestionSource | None = None
    seed: int = 2027

    @model_validator(mode="after")
    def require_scope(self) -> PracticeSessionCreate:
        if self.topic_id is None and self.subject_id is None and self.subject_slug is None:
            raise ValueError("Provide topic_id, subject_id, or subject_slug")
        return self


class TestCreate(BaseModel):
    mode: Literal["sectional", "full"]
    user_key: str = Field(default="local-user", min_length=1, max_length=100)
    subject_id: int | None = None
    subject_slug: str | None = None
    count: int = Field(default=5, ge=1, le=65)
    duration_minutes: int | None = Field(default=None, ge=1, le=180)
    seed: int = 2027

    @model_validator(mode="after")
    def validate_sectional_scope(self) -> TestCreate:
        if self.mode == "sectional" and self.subject_id is None and self.subject_slug is None:
            raise ValueError("Sectional tests require subject_id or subject_slug")
        return self


class SessionRead(ApiModel):
    id: str
    user_key: str
    mode: SessionMode
    subject_id: int | None
    topic_id: int | None
    question_count: int
    duration_seconds: int | None
    total_marks: int
    seed: int
    started_at: datetime
    expires_at: datetime | None
    is_submitted: bool
    questions: list[QuestionPublic]


class AnswerSubmission(BaseModel):
    question_id: int
    answer: Any | None = None


class AttemptSubmit(BaseModel):
    session_id: str
    user_key: str = Field(default="local-user", min_length=1, max_length=100)
    answers: list[AnswerSubmission] = Field(default_factory=list)

    @field_validator("answers")
    @classmethod
    def unique_question_ids(
        cls, answers: list[AnswerSubmission]
    ) -> list[AnswerSubmission]:
        question_ids = [answer.question_id for answer in answers]
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("Only one answer per question is allowed")
        return answers


class QuestionResult(BaseModel):
    question_id: int
    answer: Any | None
    correct_answer: Any
    status: ResponseStatus
    awarded_marks: float
    max_marks: float
    negative_marks: float
    explanation: str


class AttemptResult(ApiModel):
    id: str
    session_id: str
    user_key: str
    submitted_at: datetime
    timed_out: bool
    score: float
    max_score: float
    percentage: float
    correct_count: int
    incorrect_count: int
    unanswered_count: int
    results: list[QuestionResult]


class SubjectProgress(BaseModel):
    subject_id: int
    subject_slug: str
    subject_name: str
    attempted_questions: int
    unique_questions_attempted: int
    correct: int
    incorrect: int
    unanswered: int
    accuracy: float
    marks_earned: float
    marks_available: float


class RecentAttempt(BaseModel):
    attempt_id: str
    session_id: str
    mode: SessionMode
    submitted_at: datetime
    score: float
    max_score: float
    percentage: float


class ProgressDashboard(BaseModel):
    user_key: str
    total_attempts: int
    total_responses: int
    correct: int
    incorrect: int
    unanswered: int
    accuracy: float
    total_score: float
    total_max_score: float
    average_test_percentage: float
    subjects: list[SubjectProgress]
    recent_attempts: list[RecentAttempt]


class RoadmapTopic(BaseModel):
    id: int
    slug: str
    name: str
    question_count: int
    note_available: bool
    attempted_questions: int
    accuracy: float | None


class RoadmapSubject(BaseModel):
    id: int
    slug: str
    code: str
    name: str
    order_index: int
    topic_count: int
    question_count: int
    attempted_questions: int
    accuracy: float | None
    topics: list[RoadmapTopic]


class RoadmapResponse(BaseModel):
    user_key: str
    subjects: list[RoadmapSubject]


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    database: str
