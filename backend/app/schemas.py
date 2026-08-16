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


class CsrfResponse(BaseModel):
    csrf_token: str


class FirebaseSessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id_token: str = Field(min_length=1, max_length=20_000)
    csrf_token: str = Field(min_length=16, max_length=512)


class FirebaseLogout(BaseModel):
    model_config = ConfigDict(extra="forbid")

    csrf_token: str = Field(min_length=16, max_length=512)


class ProgressResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    csrf_token: str = Field(min_length=16, max_length=512)
    confirmation: Literal["RESET"]


class ProgressResetResult(BaseModel):
    user_key: str
    reset: bool = True
    sessions_deleted: int
    attempts_deleted: int
    progress_deleted: bool


class AuthUser(BaseModel):
    uid: str
    display_name: str | None = None
    email: str | None = None
    photo_url: str | None = None
    email_verified: bool = False


class AuthStatus(BaseModel):
    authenticated: bool
    mode: Literal["guest", "firebase"]
    user_key: str
    user: AuthUser | None = None


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


class QuestionAssetPublic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal[
        "answer_option_diagrams",
        "answer_option_table",
        "stem_and_answer_option_diagrams",
        "stem_and_answer_option_tables",
        "stem_chart",
        "stem_diagram",
        "stem_graph",
        "stem_table",
    ]
    url: str = Field(
        pattern=(
            r"^/question-assets/pyq/[a-z0-9]+(?:-[a-z0-9]+)*/"
            r"[0-9a-f]{64}\.png$"
        )
    )
    alt_text: str = Field(min_length=1, max_length=1_000)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


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
    source_paper_id: str | None
    source_item_label: str | None
    source_page: int | None
    source_url: str | None
    answer_key_url: str | None
    extraction_method: str | None
    extraction_confidence: float | None
    question_type: QuestionType
    difficulty: Difficulty
    text: str
    options: list[QuestionOption]
    numerical_tolerance: float | None = None
    marks: int
    tags: list[str]
    assets: list[QuestionAssetPublic] = Field(default_factory=list)


class QuestionListResponse(BaseModel):
    items: list[QuestionPublic]
    total: int
    limit: int
    offset: int


class PracticeSessionCreate(BaseModel):
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
    catalog_id: str | None
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
    solved_questions: int
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
    solved_questions: int
    accuracy: float | None
    topics: list[RoadmapTopic]


class RoadmapResponse(BaseModel):
    user_key: str
    subjects: list[RoadmapSubject]


class QuestionTypeCounts(BaseModel):
    mcq: int = 0
    msq: int = 0
    nat: int = 0


class TestCatalogItem(ApiModel):
    id: str
    title: str
    description: str
    mode: SessionMode
    subject_id: int | None
    subject_slug: str | None
    subject_code: str | None
    form_number: int
    question_count: int
    duration_seconds: int
    total_marks: int
    question_type_counts: QuestionTypeCounts
    topic_count: int
    is_available: bool
    unavailable_reason: str | None


class TestCatalogResponse(BaseModel):
    items: list[TestCatalogItem]
    total: int
    full_test_count: int
    course_test_count: int
    bank_version: str | None


class CatalogSessionCreate(BaseModel):
    pass


class AnalyticsOverall(BaseModel):
    attempted_responses: int
    answered_responses: int
    unique_questions_attempted: int
    unique_questions_solved: int
    available_questions: int
    accuracy_percent: float
    attempted_coverage_percent: float
    solved_coverage_percent: float
    coverage_percent: float
    recency_weighted_accuracy_percent: float
    mastery_score: float


class TopicAnalytics(BaseModel):
    topic_id: int
    topic_slug: str
    topic_name: str
    subject_id: int
    subject_slug: str
    subject_code: str
    subject_name: str
    available_questions: int
    attempt_count: int
    answered_count: int
    unique_questions_attempted: int
    unique_questions_solved: int
    correct_count: int
    incorrect_count: int
    unanswered_count: int
    accuracy_percent: float
    attempted_coverage_percent: float
    solved_coverage_percent: float
    coverage_percent: float
    recency_weighted_accuracy_percent: float
    mastery_score: float
    status: Literal["strong", "developing", "needs_practice", "unattempted"]
    last_attempted_at: datetime | None


class AnalyticsDashboard(BaseModel):
    user_key: str
    generated_at: datetime
    overall: AnalyticsOverall
    topics: list[TopicAnalytics]
    strong_topics: list[TopicAnalytics]
    needs_practice_topics: list[TopicAnalytics]
    unattempted_topics: list[TopicAnalytics]


class QuestionBankImportSummary(ApiModel):
    schema_version: str
    bank_version: str
    checksum: str
    question_count: int
    inserted_count: int
    updated_count: int
    unchanged_count: int
    retired_count: int
    imported_at: datetime


class QuestionBankStatus(BaseModel):
    configured_path: str
    total_questions: int
    latest_import: QuestionBankImportSummary | None


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    database: str
    configuration: str = "ok"
    configuration_issues: list[str] = Field(default_factory=list)
    authentication: str = "guest_only"
    authentication_issues: list[str] = Field(default_factory=list)
    user_state_backend: str = "postgres"
    user_state: str = "postgres"
    user_state_issues: list[str] = Field(default_factory=list)
