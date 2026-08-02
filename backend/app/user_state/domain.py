from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class StudySession:
    id: str
    user_key: str
    catalog_id: str | None
    mode: str
    subject_id: int | None
    topic_id: int | None
    question_ids: tuple[int, ...]
    question_snapshots: tuple[dict[str, Any], ...]
    question_count: int
    duration_seconds: int | None
    total_marks: int
    seed: int
    started_at: datetime
    expires_at: datetime | None
    is_submitted: bool = False
    attempt_id: str | None = None


@dataclass(frozen=True, slots=True)
class StudyResponse:
    question_id: int
    subject_id: int
    topic_id: int
    answer: Any | None
    correct_answer_snapshot: Any | None
    explanation_snapshot: str | None
    status: str
    awarded_marks: float
    max_marks: float
    negative_marks: float


@dataclass(frozen=True, slots=True)
class StudyAttempt:
    id: str
    session_id: str
    user_key: str
    submitted_at: datetime
    timed_out: bool
    score: float
    max_score: float
    correct_count: int
    incorrect_count: int
    unanswered_count: int
    mode: str
    subject_id: int | None
    topic_id: int | None
    catalog_id: str | None
    responses: tuple[StudyResponse, ...]


@dataclass(frozen=True, slots=True)
class SubjectProgressTotals:
    subject_id: int
    attempted_questions: int = 0
    unique_questions_attempted: int = 0
    correct_count: int = 0
    incorrect_count: int = 0
    unanswered_count: int = 0
    marks_earned: float = 0.0
    marks_available: float = 0.0


@dataclass(frozen=True, slots=True)
class RecentAttemptProjection:
    attempt_id: str
    session_id: str
    mode: str
    submitted_at: datetime
    score: float
    max_score: float


@dataclass(frozen=True, slots=True)
class QuestionEvidence:
    question_id: int
    subject_id: int
    topic_id: int
    attempt_count: int = 0
    correct_count: int = 0
    incorrect_count: int = 0
    unanswered_count: int = 0
    latest_answered_status: str | None = None
    latest_answered_at: datetime | None = None
    last_attempted_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ProgressProjection:
    user_key: str
    total_attempts: int
    total_responses: int
    correct_count: int
    incorrect_count: int
    unanswered_count: int
    total_score: float
    total_max_score: float
    percentage_sum: float
    subjects: dict[int, SubjectProgressTotals]
    recent_attempts: tuple[RecentAttemptProjection, ...]
    evidence: dict[int, QuestionEvidence]
    updated_at: datetime | None


def empty_progress_projection(user_key: str) -> ProgressProjection:
    return ProgressProjection(
        user_key=user_key,
        total_attempts=0,
        total_responses=0,
        correct_count=0,
        incorrect_count=0,
        unanswered_count=0,
        total_score=0.0,
        total_max_score=0.0,
        percentage_sum=0.0,
        subjects={},
        recent_attempts=(),
        evidence={},
        updated_at=None,
    )


def apply_attempt_to_projection(
    projection: ProgressProjection,
    attempt: StudyAttempt,
) -> ProgressProjection:
    """Return a new projection with one committed attempt applied."""

    if projection.user_key != attempt.user_key:
        raise ValueError("Attempt owner does not match progress owner")

    submitted_at = as_utc(attempt.submitted_at)
    subjects = dict(projection.subjects)
    evidence = dict(projection.evidence)
    correct = incorrect = unanswered = 0

    for response in attempt.responses:
        status = response.status.lower()
        if status == "correct":
            correct += 1
        elif status == "incorrect":
            incorrect += 1
        elif status == "unanswered":
            unanswered += 1
        else:
            raise ValueError(f"Unsupported response status: {response.status!r}")

        existing = evidence.get(response.question_id)
        subject = subjects.get(
            response.subject_id,
            SubjectProgressTotals(subject_id=response.subject_id),
        )
        subject = replace(
            subject,
            attempted_questions=subject.attempted_questions + 1,
            unique_questions_attempted=(
                subject.unique_questions_attempted + (1 if existing is None else 0)
            ),
            correct_count=subject.correct_count + (1 if status == "correct" else 0),
            incorrect_count=(
                subject.incorrect_count + (1 if status == "incorrect" else 0)
            ),
            unanswered_count=(
                subject.unanswered_count + (1 if status == "unanswered" else 0)
            ),
            marks_earned=subject.marks_earned + float(response.awarded_marks),
            marks_available=subject.marks_available + float(response.max_marks),
        )
        subjects[response.subject_id] = subject

        current = existing or QuestionEvidence(
            question_id=response.question_id,
            subject_id=response.subject_id,
            topic_id=response.topic_id,
        )
        latest_status = current.latest_answered_status
        latest_answered_at = current.latest_answered_at
        if status != "unanswered" and (
            latest_answered_at is None
            or submitted_at >= as_utc(latest_answered_at)
        ):
            latest_status = status
            latest_answered_at = submitted_at
        last_attempted_at = current.last_attempted_at
        if last_attempted_at is None or submitted_at >= as_utc(last_attempted_at):
            last_attempted_at = submitted_at
        evidence[response.question_id] = replace(
            current,
            subject_id=response.subject_id,
            topic_id=response.topic_id,
            attempt_count=current.attempt_count + 1,
            correct_count=current.correct_count + (1 if status == "correct" else 0),
            incorrect_count=(
                current.incorrect_count + (1 if status == "incorrect" else 0)
            ),
            unanswered_count=(
                current.unanswered_count + (1 if status == "unanswered" else 0)
            ),
            latest_answered_status=latest_status,
            latest_answered_at=latest_answered_at,
            last_attempted_at=last_attempted_at,
        )

    recent_by_id = {
        item.attempt_id: item for item in projection.recent_attempts
    }
    recent_by_id[attempt.id] = RecentAttemptProjection(
        attempt_id=attempt.id,
        session_id=attempt.session_id,
        mode=attempt.mode,
        submitted_at=submitted_at,
        score=float(attempt.score),
        max_score=float(attempt.max_score),
    )
    recent = tuple(
        sorted(
            recent_by_id.values(),
            key=lambda item: (as_utc(item.submitted_at), item.attempt_id),
            reverse=True,
        )[:5]
    )
    percentage = (
        float(attempt.score) / float(attempt.max_score) * 100
        if attempt.max_score
        else 0.0
    )
    updated_at = projection.updated_at
    if updated_at is None or submitted_at >= as_utc(updated_at):
        updated_at = submitted_at
    return ProgressProjection(
        user_key=projection.user_key,
        total_attempts=projection.total_attempts + 1,
        total_responses=projection.total_responses + len(attempt.responses),
        correct_count=projection.correct_count + correct,
        incorrect_count=projection.incorrect_count + incorrect,
        unanswered_count=projection.unanswered_count + unanswered,
        total_score=projection.total_score + float(attempt.score),
        total_max_score=projection.total_max_score + float(attempt.max_score),
        percentage_sum=projection.percentage_sum + percentage,
        subjects=subjects,
        recent_attempts=recent,
        evidence=evidence,
        updated_at=updated_at,
    )


def rebuild_progress_projection(
    user_key: str,
    attempts: list[StudyAttempt] | tuple[StudyAttempt, ...],
) -> ProgressProjection:
    """Build a deterministic projection from authoritative attempt records."""

    projection = empty_progress_projection(user_key)
    unique_attempts = {attempt.id: attempt for attempt in attempts}
    for attempt in sorted(
        unique_attempts.values(),
        key=lambda item: (as_utc(item.submitted_at), item.id),
    ):
        if attempt.user_key != user_key:
            raise ValueError("Cannot rebuild progress from another owner's attempt")
        projection = apply_attempt_to_projection(projection, attempt)
    return projection


def merge_progress_projections(
    target: ProgressProjection,
    guest: ProgressProjection,
    target_user_key: str,
) -> ProgressProjection:
    """Merge a frozen guest projection into the latest target projection.

    The caller must serialize this operation with the guest claim-control
    document and the target projection. The function is pure so a Firestore
    transaction can safely retry it after a concurrent target submission.
    """

    if target.user_key != target_user_key:
        raise ValueError("Target projection owner does not match")
    if guest.user_key == target_user_key:
        raise ValueError("Guest and target progress owners must differ")

    evidence = dict(target.evidence)
    for question_id, guest_item in guest.evidence.items():
        target_item = evidence.get(question_id)
        if target_item is None:
            evidence[question_id] = guest_item
            continue

        target_answered_at = target_item.latest_answered_at
        guest_answered_at = guest_item.latest_answered_at
        use_guest_answer = guest_answered_at is not None and (
            target_answered_at is None
            or as_utc(guest_answered_at) >= as_utc(target_answered_at)
        )
        latest_answered_at = (
            guest_answered_at if use_guest_answer else target_answered_at
        )
        latest_answered_status = (
            guest_item.latest_answered_status
            if use_guest_answer
            else target_item.latest_answered_status
        )

        target_last = target_item.last_attempted_at
        guest_last = guest_item.last_attempted_at
        use_guest_metadata = guest_last is not None and (
            target_last is None or as_utc(guest_last) >= as_utc(target_last)
        )
        last_attempted_at = guest_last if use_guest_metadata else target_last
        evidence[question_id] = QuestionEvidence(
            question_id=question_id,
            subject_id=(
                guest_item.subject_id
                if use_guest_metadata
                else target_item.subject_id
            ),
            topic_id=(
                guest_item.topic_id if use_guest_metadata else target_item.topic_id
            ),
            attempt_count=target_item.attempt_count + guest_item.attempt_count,
            correct_count=target_item.correct_count + guest_item.correct_count,
            incorrect_count=(
                target_item.incorrect_count + guest_item.incorrect_count
            ),
            unanswered_count=(
                target_item.unanswered_count + guest_item.unanswered_count
            ),
            latest_answered_status=latest_answered_status,
            latest_answered_at=latest_answered_at,
            last_attempted_at=last_attempted_at,
        )

    subjects: dict[int, SubjectProgressTotals] = {}
    subject_ids = set(target.subjects) | set(guest.subjects)
    for subject_id in subject_ids:
        target_subject = target.subjects.get(
            subject_id,
            SubjectProgressTotals(subject_id=subject_id),
        )
        guest_subject = guest.subjects.get(
            subject_id,
            SubjectProgressTotals(subject_id=subject_id),
        )
        unique_count = sum(
            item.subject_id == subject_id for item in evidence.values()
        )
        subjects[subject_id] = SubjectProgressTotals(
            subject_id=subject_id,
            attempted_questions=(
                target_subject.attempted_questions
                + guest_subject.attempted_questions
            ),
            unique_questions_attempted=unique_count,
            correct_count=(
                target_subject.correct_count + guest_subject.correct_count
            ),
            incorrect_count=(
                target_subject.incorrect_count + guest_subject.incorrect_count
            ),
            unanswered_count=(
                target_subject.unanswered_count + guest_subject.unanswered_count
            ),
            marks_earned=(
                target_subject.marks_earned + guest_subject.marks_earned
            ),
            marks_available=(
                target_subject.marks_available + guest_subject.marks_available
            ),
        )

    recent_by_id = {
        item.attempt_id: item
        for item in (*target.recent_attempts, *guest.recent_attempts)
    }
    recent = tuple(
        sorted(
            recent_by_id.values(),
            key=lambda item: (as_utc(item.submitted_at), item.attempt_id),
            reverse=True,
        )[:5]
    )
    timestamps = [
        as_utc(item)
        for item in (target.updated_at, guest.updated_at)
        if item is not None
    ]
    return ProgressProjection(
        user_key=target_user_key,
        total_attempts=target.total_attempts + guest.total_attempts,
        total_responses=target.total_responses + guest.total_responses,
        correct_count=target.correct_count + guest.correct_count,
        incorrect_count=target.incorrect_count + guest.incorrect_count,
        unanswered_count=target.unanswered_count + guest.unanswered_count,
        total_score=target.total_score + guest.total_score,
        total_max_score=target.total_max_score + guest.total_max_score,
        percentage_sum=target.percentage_sum + guest.percentage_sum,
        subjects=subjects,
        recent_attempts=recent,
        evidence=evidence,
        updated_at=max(timestamps) if timestamps else None,
    )
