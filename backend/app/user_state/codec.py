from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Mapping

from app.user_state.domain import (
    ProgressProjection,
    QuestionEvidence,
    RecentAttemptProjection,
    StudyAttempt,
    StudyResponse,
    StudySession,
    SubjectProgressTotals,
    as_utc,
)
from app.user_state.repository import UserStatePayloadTooLarge


SCHEMA_VERSION = 1
MAX_DOCUMENT_BYTES = 900_000


def _string_value(value: Any) -> str:
    raw = getattr(value, "value", value)
    return str(raw)


def _datetime(value: Any, *, optional: bool = False) -> datetime | None:
    if value is None and optional:
        return None
    if not isinstance(value, datetime):
        raise ValueError("Stored timestamp is invalid")
    return as_utc(value)


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return as_utc(value).isoformat()
    raw = getattr(value, "value", None)
    if isinstance(raw, str):
        return raw
    raise TypeError(f"Unsupported value type: {type(value).__name__}")


def ensure_document_size(document: Mapping[str, Any], label: str) -> None:
    encoded = json.dumps(
        document,
        default=_json_default,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > MAX_DOCUMENT_BYTES:
        raise UserStatePayloadTooLarge(f"{label} exceeds the storage size limit")


def session_to_document(session: StudySession) -> dict[str, Any]:
    document = {
        "schema_version": SCHEMA_VERSION,
        "id": session.id,
        "user_key": session.user_key,
        "catalog_id": session.catalog_id,
        "mode": _string_value(session.mode),
        "subject_id": session.subject_id,
        "topic_id": session.topic_id,
        "question_ids": list(session.question_ids),
        "question_snapshots": list(session.question_snapshots),
        "question_count": session.question_count,
        "duration_seconds": session.duration_seconds,
        "total_marks": session.total_marks,
        "seed": session.seed,
        "started_at": as_utc(session.started_at),
        "expires_at": as_utc(session.expires_at) if session.expires_at else None,
        "is_submitted": session.is_submitted,
        "attempt_id": session.attempt_id,
    }
    ensure_document_size(document, "Study session")
    return document


def session_from_document(document: Mapping[str, Any]) -> StudySession:
    return StudySession(
        id=str(document["id"]),
        user_key=str(document["user_key"]),
        catalog_id=(
            str(document["catalog_id"])
            if document.get("catalog_id") is not None
            else None
        ),
        mode=str(document["mode"]),
        subject_id=(
            int(document["subject_id"])
            if document.get("subject_id") is not None
            else None
        ),
        topic_id=(
            int(document["topic_id"])
            if document.get("topic_id") is not None
            else None
        ),
        question_ids=tuple(int(item) for item in document.get("question_ids", [])),
        question_snapshots=tuple(
            dict(item) for item in document.get("question_snapshots", [])
        ),
        question_count=int(document["question_count"]),
        duration_seconds=(
            int(document["duration_seconds"])
            if document.get("duration_seconds") is not None
            else None
        ),
        total_marks=int(document["total_marks"]),
        seed=int(document["seed"]),
        started_at=_datetime(document.get("started_at")),  # type: ignore[arg-type]
        expires_at=_datetime(document.get("expires_at"), optional=True),
        is_submitted=bool(document.get("is_submitted", False)),
        attempt_id=(
            str(document["attempt_id"])
            if document.get("attempt_id") is not None
            else None
        ),
    )


def response_to_document(response: StudyResponse) -> dict[str, Any]:
    return {
        "question_id": response.question_id,
        "subject_id": response.subject_id,
        "topic_id": response.topic_id,
        "answer": response.answer,
        "correct_answer_snapshot": response.correct_answer_snapshot,
        "explanation_snapshot": response.explanation_snapshot,
        "status": _string_value(response.status),
        "awarded_marks": float(response.awarded_marks),
        "max_marks": float(response.max_marks),
        "negative_marks": float(response.negative_marks),
    }


def response_from_document(document: Mapping[str, Any]) -> StudyResponse:
    return StudyResponse(
        question_id=int(document["question_id"]),
        subject_id=int(document["subject_id"]),
        topic_id=int(document["topic_id"]),
        answer=document.get("answer"),
        correct_answer_snapshot=document.get("correct_answer_snapshot"),
        explanation_snapshot=(
            str(document["explanation_snapshot"])
            if document.get("explanation_snapshot") is not None
            else None
        ),
        status=str(document["status"]),
        awarded_marks=float(document["awarded_marks"]),
        max_marks=float(document["max_marks"]),
        negative_marks=float(document.get("negative_marks", 0.0)),
    )


def attempt_to_document(attempt: StudyAttempt) -> dict[str, Any]:
    document = {
        "schema_version": SCHEMA_VERSION,
        "id": attempt.id,
        "session_id": attempt.session_id,
        "user_key": attempt.user_key,
        "submitted_at": as_utc(attempt.submitted_at),
        "timed_out": attempt.timed_out,
        "score": float(attempt.score),
        "max_score": float(attempt.max_score),
        "correct_count": attempt.correct_count,
        "incorrect_count": attempt.incorrect_count,
        "unanswered_count": attempt.unanswered_count,
        "mode": _string_value(attempt.mode),
        "subject_id": attempt.subject_id,
        "topic_id": attempt.topic_id,
        "catalog_id": attempt.catalog_id,
        "responses": [response_to_document(item) for item in attempt.responses],
    }
    ensure_document_size(document, "Study attempt")
    return document


def attempt_from_document(document: Mapping[str, Any]) -> StudyAttempt:
    return StudyAttempt(
        id=str(document["id"]),
        session_id=str(document["session_id"]),
        user_key=str(document["user_key"]),
        submitted_at=_datetime(document.get("submitted_at")),  # type: ignore[arg-type]
        timed_out=bool(document.get("timed_out", False)),
        score=float(document["score"]),
        max_score=float(document["max_score"]),
        correct_count=int(document["correct_count"]),
        incorrect_count=int(document["incorrect_count"]),
        unanswered_count=int(document["unanswered_count"]),
        mode=str(document["mode"]),
        subject_id=(
            int(document["subject_id"])
            if document.get("subject_id") is not None
            else None
        ),
        topic_id=(
            int(document["topic_id"])
            if document.get("topic_id") is not None
            else None
        ),
        catalog_id=(
            str(document["catalog_id"])
            if document.get("catalog_id") is not None
            else None
        ),
        responses=tuple(
            response_from_document(item) for item in document.get("responses", [])
        ),
    )


def progress_to_document(progress: ProgressProjection) -> dict[str, Any]:
    document = {
        "schema_version": SCHEMA_VERSION,
        "user_key": progress.user_key,
        "total_attempts": progress.total_attempts,
        "total_responses": progress.total_responses,
        "correct_count": progress.correct_count,
        "incorrect_count": progress.incorrect_count,
        "unanswered_count": progress.unanswered_count,
        "total_score": float(progress.total_score),
        "total_max_score": float(progress.total_max_score),
        "percentage_sum": float(progress.percentage_sum),
        "subjects": {
            str(key): {
                "subject_id": value.subject_id,
                "attempted_questions": value.attempted_questions,
                "unique_questions_attempted": value.unique_questions_attempted,
                "correct_count": value.correct_count,
                "incorrect_count": value.incorrect_count,
                "unanswered_count": value.unanswered_count,
                "marks_earned": float(value.marks_earned),
                "marks_available": float(value.marks_available),
            }
            for key, value in progress.subjects.items()
        },
        "recent_attempts": [
            {
                "attempt_id": item.attempt_id,
                "session_id": item.session_id,
                "mode": _string_value(item.mode),
                "submitted_at": as_utc(item.submitted_at),
                "score": float(item.score),
                "max_score": float(item.max_score),
            }
            for item in progress.recent_attempts
        ],
        "evidence": {
            str(key): {
                "question_id": value.question_id,
                "subject_id": value.subject_id,
                "topic_id": value.topic_id,
                "attempt_count": value.attempt_count,
                "correct_count": value.correct_count,
                "incorrect_count": value.incorrect_count,
                "unanswered_count": value.unanswered_count,
                "latest_answered_status": value.latest_answered_status,
                "latest_answered_at": (
                    as_utc(value.latest_answered_at)
                    if value.latest_answered_at
                    else None
                ),
                "last_attempted_at": (
                    as_utc(value.last_attempted_at)
                    if value.last_attempted_at
                    else None
                ),
            }
            for key, value in progress.evidence.items()
        },
        "updated_at": as_utc(progress.updated_at) if progress.updated_at else None,
    }
    ensure_document_size(document, "Progress projection")
    return document


def progress_from_document(document: Mapping[str, Any]) -> ProgressProjection:
    subjects = {
        int(key): SubjectProgressTotals(
            subject_id=int(value["subject_id"]),
            attempted_questions=int(value.get("attempted_questions", 0)),
            unique_questions_attempted=int(
                value.get("unique_questions_attempted", 0)
            ),
            correct_count=int(value.get("correct_count", 0)),
            incorrect_count=int(value.get("incorrect_count", 0)),
            unanswered_count=int(value.get("unanswered_count", 0)),
            marks_earned=float(value.get("marks_earned", 0.0)),
            marks_available=float(value.get("marks_available", 0.0)),
        )
        for key, value in dict(document.get("subjects", {})).items()
    }
    recent = tuple(
        RecentAttemptProjection(
            attempt_id=str(item["attempt_id"]),
            session_id=str(item["session_id"]),
            mode=str(item["mode"]),
            submitted_at=_datetime(item.get("submitted_at")),  # type: ignore[arg-type]
            score=float(item["score"]),
            max_score=float(item["max_score"]),
        )
        for item in document.get("recent_attempts", [])
    )
    evidence = {
        int(key): QuestionEvidence(
            question_id=int(value["question_id"]),
            subject_id=int(value["subject_id"]),
            topic_id=int(value["topic_id"]),
            attempt_count=int(value.get("attempt_count", 0)),
            correct_count=int(value.get("correct_count", 0)),
            incorrect_count=int(value.get("incorrect_count", 0)),
            unanswered_count=int(value.get("unanswered_count", 0)),
            latest_answered_status=(
                str(value["latest_answered_status"])
                if value.get("latest_answered_status") is not None
                else None
            ),
            latest_answered_at=_datetime(
                value.get("latest_answered_at"), optional=True
            ),
            last_attempted_at=_datetime(
                value.get("last_attempted_at"), optional=True
            ),
        )
        for key, value in dict(document.get("evidence", {})).items()
    }
    return ProgressProjection(
        user_key=str(document["user_key"]),
        total_attempts=int(document.get("total_attempts", 0)),
        total_responses=int(document.get("total_responses", 0)),
        correct_count=int(document.get("correct_count", 0)),
        incorrect_count=int(document.get("incorrect_count", 0)),
        unanswered_count=int(document.get("unanswered_count", 0)),
        total_score=float(document.get("total_score", 0.0)),
        total_max_score=float(document.get("total_max_score", 0.0)),
        percentage_sum=float(document.get("percentage_sum", 0.0)),
        subjects=subjects,
        recent_attempts=recent,
        evidence=evidence,
        updated_at=_datetime(document.get("updated_at"), optional=True),
    )
