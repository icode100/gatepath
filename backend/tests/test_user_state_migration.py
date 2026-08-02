from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from app.models import (
    Attempt,
    AttemptResponse,
    Difficulty,
    PracticeSession,
    Question,
    QuestionSource,
    QuestionType,
    ResponseStatus,
    SessionMode,
)
from app.user_state.domain import (
    ProgressProjection,
    StudyAttempt,
    StudyResponse,
    StudySession,
    empty_progress_projection,
)
from scripts import migrate_user_state_to_firestore as migration


BASE_TIME = datetime(2027, 2, 3, 4, 5, tzinfo=UTC)


def _legacy_session(
    *,
    session_id: str = "legacy-session",
    attempt_id: str | None = "legacy-attempt",
    is_submitted: bool = True,
) -> PracticeSession:
    snapshot = {
        "id": 701,
        "subject_id": 7,
        "topic_id": 70,
        "question_type": "mcq",
        "text": "Immutable question text",
        "options": [
            {"id": "A", "text": "First"},
            {"id": "B", "text": "Second"},
        ],
        "correct_answer": "B",
        "explanation": "Immutable explanation",
        "marks": 1,
        "tags": ["migration"],
    }
    session = PracticeSession(
        id=session_id,
        user_key="legacy-owner",
        catalog_id=None,
        mode=SessionMode.PRACTICE,
        subject_id=7,
        topic_id=70,
        question_ids=[701],
        question_snapshots=[snapshot],
        question_count=1,
        duration_seconds=None,
        total_marks=1,
        seed=71,
        started_at=BASE_TIME,
        expires_at=None,
        is_submitted=is_submitted,
    )
    if attempt_id is None:
        return session

    question = Question(
        id=701,
        external_id="migration:701",
        bank_version="test",
        is_active=True,
        subject_id=7,
        topic_id=70,
        source=QuestionSource.ORIGINAL,
        source_kind=QuestionSource.ORIGINAL,
        question_type=QuestionType.MCQ,
        difficulty=Difficulty.EASY,
        text="Mutable catalog text",
        options=snapshot["options"],
        correct_answer="A",
        numerical_tolerance=0.01,
        marks=1,
        explanation="Mutable catalog explanation",
        tags=[],
        created_at=BASE_TIME,
    )
    response = AttemptResponse(
        id=9001,
        attempt_id=attempt_id,
        question_id=question.id,
        answer="B",
        correct_answer_snapshot="B",
        explanation_snapshot="Immutable explanation",
        status=ResponseStatus.CORRECT,
        awarded_marks=1.0,
        max_marks=1.0,
        negative_marks=0.0,
    )
    response.question = question
    attempt = Attempt(
        id=attempt_id,
        session_id=session.id,
        user_key=session.user_key,
        submitted_at=BASE_TIME + timedelta(minutes=2),
        timed_out=False,
        score=1.0,
        max_score=1.0,
        correct_count=1,
        incorrect_count=0,
        unanswered_count=0,
        responses=[response],
    )
    session.attempt = attempt
    return session


def _study_record(
    session_id: str,
    user_key: str,
    question_id: int,
    *,
    attempt_id: str | None,
    status: str = "correct",
    submitted_at: datetime = BASE_TIME,
) -> migration.SourceRecord:
    has_attempt = attempt_id is not None
    session = StudySession(
        id=session_id,
        user_key=user_key,
        catalog_id=None,
        mode="practice",
        subject_id=7,
        topic_id=70,
        question_ids=(question_id,),
        question_snapshots=(
            {
                "id": question_id,
                "subject_id": 7,
                "topic_id": 70,
                "question_type": "mcq",
                "text": f"Question {question_id}",
                "correct_answer": "A",
                "explanation": "Explanation",
                "marks": 1,
            },
        ),
        question_count=1,
        duration_seconds=None,
        total_marks=1,
        seed=question_id,
        started_at=submitted_at - timedelta(minutes=1),
        expires_at=None,
        is_submitted=has_attempt,
        attempt_id=attempt_id,
    )
    if attempt_id is None:
        return migration.SourceRecord(session=session, attempt=None)

    awarded_marks = 1.0 if status == "correct" else -1 / 3
    attempt = StudyAttempt(
        id=attempt_id,
        session_id=session_id,
        user_key=user_key,
        submitted_at=submitted_at,
        timed_out=False,
        score=awarded_marks,
        max_score=1.0,
        correct_count=1 if status == "correct" else 0,
        incorrect_count=1 if status == "incorrect" else 0,
        unanswered_count=1 if status == "unanswered" else 0,
        mode="practice",
        subject_id=7,
        topic_id=70,
        catalog_id=None,
        responses=(
            StudyResponse(
                question_id=question_id,
                subject_id=7,
                topic_id=70,
                answer=None if status == "unanswered" else "A",
                correct_answer_snapshot="A",
                explanation_snapshot="Explanation",
                status=status,
                awarded_marks=awarded_marks,
                max_marks=1.0,
                negative_marks=abs(awarded_marks) if awarded_marks < 0 else 0.0,
            ),
        ),
    )
    return migration.SourceRecord(session=session, attempt=attempt)


class _MemoryMigrationRepository:
    def __init__(self, store: "_MemoryMigrationStore") -> None:
        self.store = store

    async def create_session(self, session: StudySession) -> StudySession:
        existing = self.store.sessions.get(session.id)
        if existing is not None:
            if existing == session:
                return existing
            raise AssertionError(f"conflicting session {session.id}")
        self.store.sessions[session.id] = session
        return session

    async def submit_attempt(
        self,
        user_key: str,
        session_id: str,
        candidate_attempt: StudyAttempt,
    ) -> StudyAttempt:
        session = self.store.sessions[session_id]
        assert session.user_key == user_key
        assert candidate_attempt.user_key == user_key
        assert candidate_attempt.session_id == session_id
        if session.is_submitted:
            assert session.attempt_id is not None
            return self.store.attempts[session.attempt_id]
        existing = self.store.attempts.get(candidate_attempt.id)
        if existing is not None:
            assert existing == candidate_attempt
        else:
            self.store.attempts[candidate_attempt.id] = candidate_attempt
        self.store.sessions[session_id] = replace(
            session,
            is_submitted=True,
            attempt_id=candidate_attempt.id,
        )
        return candidate_attempt


class _MemoryMigrationStore:
    def __init__(self) -> None:
        self.sessions: dict[str, StudySession] = {}
        self.attempts: dict[str, StudyAttempt] = {}
        self.progress_documents: dict[str, ProgressProjection] = {}
        self.repository = _MemoryMigrationRepository(self)

    async def session(self, session_id: str) -> StudySession | None:
        return self.sessions.get(session_id)

    async def attempt(self, attempt_id: str) -> StudyAttempt | None:
        return self.attempts.get(attempt_id)

    async def attempts_for_owner(self, user_key: str) -> tuple[StudyAttempt, ...]:
        return tuple(
            attempt
            for attempt in self.attempts.values()
            if attempt.user_key == user_key
        )

    async def progress(self, user_key: str) -> ProgressProjection:
        return self.progress_documents.get(
            user_key,
            empty_progress_projection(user_key),
        )

    async def set_progress(self, progress: ProgressProjection) -> None:
        self.progress_documents[progress.user_key] = progress


def test_source_conversion_preserves_distinct_ids_and_immutable_snapshots() -> None:
    legacy = _legacy_session(
        session_id="session-id-stays-distinct",
        attempt_id="attempt-id-stays-distinct",
    )

    record = migration._source_record(legacy)

    assert record.session.id == "session-id-stays-distinct"
    assert record.session.attempt_id == "attempt-id-stays-distinct"
    assert record.attempt is not None
    assert record.attempt.id == "attempt-id-stays-distinct"
    assert record.attempt.session_id == "session-id-stays-distinct"
    assert record.session.question_snapshots == tuple(legacy.question_snapshots)
    assert record.attempt.responses[0].correct_answer_snapshot == "B"
    assert record.attempt.responses[0].explanation_snapshot == "Immutable explanation"


@pytest.mark.parametrize(
    ("is_submitted", "attempt_id", "message"),
    [
        (False, "orphan-attempt", "has an attempt but is not submitted"),
        (True, None, "is submitted but has no attempt"),
    ],
)
def test_source_conversion_rejects_inconsistent_submission_state(
    is_submitted: bool,
    attempt_id: str | None,
    message: str,
) -> None:
    legacy = _legacy_session(
        is_submitted=is_submitted,
        attempt_id=attempt_id,
    )

    with pytest.raises(migration.MigrationError, match=message):
        migration._source_record(legacy)


@pytest.mark.asyncio
async def test_apply_is_idempotent_and_preserves_unsubmitted_and_extra_state() -> None:
    user_key = "migration-owner"
    submitted = _study_record(
        "source-session",
        user_key,
        801,
        attempt_id="source-attempt",
    )
    unsubmitted = _study_record(
        "unfinished-session",
        user_key,
        802,
        attempt_id=None,
    )
    source = migration.SourceSnapshot(records=(submitted, unsubmitted))
    store = _MemoryMigrationStore()

    extra = _study_record(
        "destination-only-session",
        user_key,
        999,
        attempt_id="destination-only-attempt",
        status="incorrect",
        submitted_at=BASE_TIME + timedelta(hours=1),
    )
    await store.repository.create_session(migration._staging_session(extra))
    assert extra.attempt is not None
    await store.repository.submit_attempt(
        user_key,
        extra.session.id,
        extra.attempt,
    )

    first = await migration.apply_migration(source, store)  # type: ignore[arg-type]
    second = await migration.apply_migration(source, store)  # type: ignore[arg-type]

    assert first == migration.ApplySummary(
        created_sessions=2,
        submitted_attempts=1,
        rebuilt_progress=1,
    )
    assert second == migration.ApplySummary()
    assert await store.session(unsubmitted.session.id) == unsubmitted.session
    progress = await store.progress(user_key)
    assert progress.total_attempts == 2
    assert progress.total_responses == 2
    assert set(progress.evidence) == {801, 999}
    assert {item.attempt_id for item in progress.recent_attempts} == {
        "source-attempt",
        "destination-only-attempt",
    }
    assert await migration.verification_issues(source, store) == []  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_verification_reports_session_attempt_and_progress_mismatches() -> None:
    record = _study_record(
        "verify-session",
        "verify-owner",
        901,
        attempt_id="verify-attempt",
    )
    source = migration.SourceSnapshot(records=(record,))
    store = _MemoryMigrationStore()
    await migration.apply_migration(source, store)  # type: ignore[arg-type]
    assert record.attempt is not None

    store.sessions[record.session.id] = replace(record.session, seed=999)
    store.attempts[record.attempt.id] = replace(record.attempt, score=0.0)
    store.progress_documents[record.session.user_key] = empty_progress_projection(
        record.session.user_key
    )

    issues = await migration.verification_issues(source, store)  # type: ignore[arg-type]

    assert f"session {record.session.id} does not match" in issues
    assert f"attempt {record.attempt.id} does not match" in issues
    assert f"progress for owner {record.session.user_key} does not match" in issues
