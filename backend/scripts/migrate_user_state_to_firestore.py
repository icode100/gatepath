from __future__ import annotations

import argparse
import asyncio
import hashlib
import inspect
import json
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import selectinload


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings  # noqa: E402
from app.database import AsyncSessionFactory, close_database  # noqa: E402
from app.models import Attempt, AttemptResponse, PracticeSession  # noqa: E402
from app.user_state import (  # noqa: E402
    FirestoreUserStateRepository,
    ProgressProjection,
    StudyAttempt,
    StudyResponse,
    StudySession,
    UserStateError,
    rebuild_progress_projection,
)
from app.user_state.codec import (  # noqa: E402
    attempt_from_document,
    attempt_to_document,
    progress_from_document,
    progress_to_document,
    session_from_document,
    session_to_document,
)
from app.user_state.domain import as_utc, empty_progress_projection  # noqa: E402


MigrationMode = Literal["dry-run", "apply", "verify-only"]


class MigrationError(RuntimeError):
    """A safe, actionable migration failure."""


@dataclass(frozen=True, slots=True)
class SourceRecord:
    session: StudySession
    attempt: StudyAttempt | None


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    records: tuple[SourceRecord, ...]

    @property
    def attempts(self) -> tuple[StudyAttempt, ...]:
        return tuple(
            record.attempt
            for record in self.records
            if record.attempt is not None
        )

    @property
    def owners(self) -> tuple[str, ...]:
        return tuple(sorted({record.session.user_key for record in self.records}))

    @property
    def response_count(self) -> int:
        return sum(len(attempt.responses) for attempt in self.attempts)

    @property
    def digest(self) -> str:
        """Return a stable review token for this exact Postgres snapshot."""

        payload = [
            {
                "session": session_to_document(record.session),
                "attempt": (
                    attempt_to_document(record.attempt)
                    if record.attempt is not None
                    else None
                ),
            }
            for record in self.records
        ]

        def json_default(value: Any) -> str:
            if isinstance(value, datetime):
                return value.isoformat()
            raise TypeError(f"Unsupported digest value: {type(value).__name__}")

        canonical = json.dumps(
            payload,
            default=json_default,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()


@dataclass(frozen=True, slots=True)
class MigrationPlan:
    missing_sessions: int
    resumable_sessions: int
    matching_sessions: int
    missing_attempts: int
    matching_attempts: int
    progress_rebuilds: int
    matching_progress: int


@dataclass(slots=True)
class ApplySummary:
    created_sessions: int = 0
    submitted_attempts: int = 0
    rebuilt_progress: int = 0


@dataclass(frozen=True, slots=True)
class SourceSummary:
    sessions: int
    attempts: int
    responses: int
    owners: int


@dataclass(frozen=True, slots=True)
class MigrationReport:
    mode: MigrationMode
    source: SourceSummary
    source_digest: str
    plan: MigrationPlan | None = None
    applied: ApplySummary | None = None
    verified: bool = False

    def public_dict(self) -> dict[str, Any]:
        """Serialize only safe counts and the reviewed snapshot digest."""

        return {
            "mode": self.mode,
            "source": asdict(self.source),
            "source_digest": self.source_digest,
            "plan": asdict(self.plan) if self.plan is not None else None,
            "applied": asdict(self.applied) if self.applied is not None else None,
            "verified": self.verified,
        }


def _value(value: Any) -> str:
    return str(getattr(value, "value", value))


def _validate_document_id(value: str, label: str) -> None:
    if not value or "/" in value or len(value.encode("utf-8")) > 512:
        raise MigrationError(f"Legacy {label} has an invalid Firestore document ID")


def _study_response(response: AttemptResponse) -> StudyResponse:
    question = response.question
    if question is None:
        raise MigrationError(
            f"Response {response.id} refers to a missing static question"
        )
    return StudyResponse(
        question_id=response.question_id,
        subject_id=question.subject_id,
        topic_id=question.topic_id,
        answer=response.answer,
        correct_answer_snapshot=(
            response.correct_answer_snapshot
            if response.correct_answer_snapshot is not None
            else question.correct_answer
        ),
        explanation_snapshot=(
            response.explanation_snapshot
            if response.explanation_snapshot is not None
            else question.explanation
        ),
        status=_value(response.status),
        awarded_marks=float(response.awarded_marks),
        max_marks=float(response.max_marks),
        negative_marks=float(response.negative_marks),
    )


def _ordered_responses(
    session: PracticeSession,
    attempt: Attempt,
) -> tuple[StudyResponse, ...]:
    question_order = {
        question_id: index
        for index, question_id in enumerate(session.question_ids or [])
    }
    responses = sorted(
        attempt.responses,
        key=lambda response: (
            question_order.get(response.question_id, len(question_order)),
            response.id,
        ),
    )
    return tuple(_study_response(response) for response in responses)


def _source_record(session: PracticeSession) -> SourceRecord:
    owner = str(session.user_key)
    _validate_document_id(session.id, "session")
    _validate_document_id(owner, "owner")

    attempt_model = session.attempt
    if attempt_model is None and session.is_submitted:
        raise MigrationError(
            f"Legacy session {session.id} is submitted but has no attempt"
        )
    if attempt_model is not None and not session.is_submitted:
        raise MigrationError(
            f"Legacy session {session.id} has an attempt but is not submitted"
        )
    if attempt_model is not None and attempt_model.user_key != owner:
        raise MigrationError(
            f"Legacy session {session.id} and attempt {attempt_model.id} "
            "have different owners"
        )

    attempt_id = attempt_model.id if attempt_model is not None else None
    study_session = StudySession(
        id=session.id,
        user_key=owner,
        catalog_id=session.catalog_id,
        mode=_value(session.mode),
        subject_id=session.subject_id,
        topic_id=session.topic_id,
        question_ids=tuple(int(item) for item in (session.question_ids or [])),
        question_snapshots=tuple(
            dict(item) for item in (session.question_snapshots or [])
        ),
        question_count=int(session.question_count),
        duration_seconds=session.duration_seconds,
        total_marks=int(session.total_marks),
        seed=int(session.seed),
        started_at=as_utc(session.started_at),
        expires_at=as_utc(session.expires_at) if session.expires_at else None,
        is_submitted=bool(session.is_submitted),
        attempt_id=attempt_id,
    )
    session_to_document(study_session)

    if attempt_model is None:
        return SourceRecord(session=study_session, attempt=None)

    _validate_document_id(attempt_model.id, "attempt")
    study_attempt = StudyAttempt(
        id=attempt_model.id,
        session_id=session.id,
        user_key=owner,
        submitted_at=as_utc(attempt_model.submitted_at),
        timed_out=bool(attempt_model.timed_out),
        score=float(attempt_model.score),
        max_score=float(attempt_model.max_score),
        correct_count=int(attempt_model.correct_count),
        incorrect_count=int(attempt_model.incorrect_count),
        unanswered_count=int(attempt_model.unanswered_count),
        mode=_value(session.mode),
        subject_id=session.subject_id,
        topic_id=session.topic_id,
        catalog_id=session.catalog_id,
        responses=_ordered_responses(session, attempt_model),
    )
    attempt_to_document(study_attempt)
    return SourceRecord(session=study_session, attempt=study_attempt)


async def load_source_snapshot(
    session_factory: Any = AsyncSessionFactory,
) -> SourceSnapshot:
    async with session_factory() as database:
        sessions = list(
            (
                await database.scalars(
                    select(PracticeSession)
                    .options(
                        selectinload(PracticeSession.attempt)
                        .selectinload(Attempt.responses)
                        .selectinload(AttemptResponse.question)
                    )
                    .order_by(PracticeSession.started_at, PracticeSession.id)
                )
            )
            .unique()
            .all()
        )
        return SourceSnapshot(
            records=tuple(_source_record(session) for session in sessions)
        )


class FirestoreMigrationStore:
    """Migration-only inspection around the production repository contract."""

    def __init__(self) -> None:
        self.repository = FirestoreUserStateRepository()
        prefix = settings.firestore_collection_prefix.strip()
        self.sessions_name = f"{prefix}_sessions"
        self.attempts_name = f"{prefix}_attempts"
        self.progress_name = f"{prefix}_progress"
        self._client: Any | None = None

    async def connect(self) -> None:
        await self.repository.healthcheck()
        # The repository owns and caches the Admin SDK client. Reusing that
        # client keeps this one-shot script on the exact production database.
        self._client = await self.repository._get_client()  # noqa: SLF001

    async def close(self) -> None:
        client = self._client
        self._client = None
        if client is None:
            return
        result = client.close()
        if inspect.isawaitable(result):
            await result

    @property
    def client(self) -> Any:
        if self._client is None:
            raise MigrationError("Firestore migration store is not connected")
        return self._client

    async def session(self, session_id: str) -> StudySession | None:
        snapshot = await self.client.collection(self.sessions_name).document(
            session_id
        ).get()
        if not snapshot.exists:
            return None
        try:
            return session_from_document(snapshot.to_dict())
        except Exception as exc:
            raise MigrationError(
                f"Firestore session {session_id} has an invalid document"
            ) from exc

    async def attempt(self, attempt_id: str) -> StudyAttempt | None:
        snapshot = await self.client.collection(self.attempts_name).document(
            attempt_id
        ).get()
        if not snapshot.exists:
            return None
        try:
            return attempt_from_document(snapshot.to_dict())
        except Exception as exc:
            raise MigrationError(
                f"Firestore attempt {attempt_id} has an invalid document"
            ) from exc

    async def attempts_for_owner(self, user_key: str) -> tuple[StudyAttempt, ...]:
        query = self.client.collection(self.attempts_name).where(
            "user_key",
            "==",
            user_key,
        )
        attempts: list[StudyAttempt] = []
        try:
            async for snapshot in query.stream():
                attempt = attempt_from_document(snapshot.to_dict())
                if attempt.user_key != user_key:
                    raise MigrationError(
                        f"Firestore attempt {snapshot.id} has an invalid owner"
                    )
                attempts.append(attempt)
        except MigrationError:
            raise
        except Exception as exc:
            raise MigrationError(
                f"Could not read Firestore attempts for owner {user_key}"
            ) from exc
        return tuple(attempts)

    async def progress(self, user_key: str) -> ProgressProjection:
        snapshot = await self.client.collection(self.progress_name).document(
            user_key
        ).get()
        if not snapshot.exists:
            return empty_progress_projection(user_key)
        try:
            progress = progress_from_document(snapshot.to_dict())
        except Exception as exc:
            raise MigrationError(
                f"Firestore progress for owner {user_key} is invalid"
            ) from exc
        if progress.user_key != user_key:
            raise MigrationError(
                f"Firestore progress for owner {user_key} has an invalid owner"
            )
        return progress

    async def set_progress(self, progress: ProgressProjection) -> None:
        document = progress_to_document(progress)
        await self.client.collection(self.progress_name).document(
            progress.user_key
        ).set(document)


def _staging_session(record: SourceRecord) -> StudySession:
    if record.attempt is None:
        return record.session
    return replace(record.session, is_submitted=False, attempt_id=None)


async def _combined_projection(
    store: FirestoreMigrationStore,
    user_key: str,
    source_attempts: tuple[StudyAttempt, ...],
) -> ProgressProjection:
    attempts_by_id = {
        attempt.id: attempt for attempt in await store.attempts_for_owner(user_key)
    }
    for attempt in source_attempts:
        existing = attempts_by_id.get(attempt.id)
        if existing is not None and existing != attempt:
            raise MigrationError(
                f"Firestore attempt {attempt.id} conflicts with the legacy source"
            )
        attempts_by_id[attempt.id] = attempt
    projection = rebuild_progress_projection(
        user_key,
        tuple(attempts_by_id.values()),
    )
    progress_to_document(projection)
    return projection


async def build_plan(
    source: SourceSnapshot,
    store: FirestoreMigrationStore,
) -> MigrationPlan:
    missing_sessions = resumable_sessions = matching_sessions = 0
    missing_attempts = matching_attempts = 0
    conflicts: list[str] = []

    for record in source.records:
        destination_session = await store.session(record.session.id)
        staging_session = _staging_session(record)
        if destination_session is None:
            missing_sessions += 1
        elif destination_session == record.session:
            matching_sessions += 1
        elif record.attempt is not None and destination_session == staging_session:
            resumable_sessions += 1
        else:
            conflicts.append(f"session {record.session.id}")

        if record.attempt is None:
            continue
        destination_attempt = await store.attempt(record.attempt.id)
        if destination_attempt is None:
            missing_attempts += 1
            if destination_session == record.session:
                conflicts.append(
                    f"attempt {record.attempt.id} is missing behind a submitted session"
                )
        elif destination_attempt == record.attempt:
            matching_attempts += 1
        else:
            conflicts.append(f"attempt {record.attempt.id}")

    if conflicts:
        preview = ", ".join(conflicts[:10])
        remainder = len(conflicts) - min(len(conflicts), 10)
        suffix = f" (and {remainder} more)" if remainder else ""
        raise MigrationError(
            "Destination data conflicts with the legacy source: "
            f"{preview}{suffix}. No conflicting document was overwritten."
        )

    source_by_owner: dict[str, list[StudyAttempt]] = defaultdict(list)
    for attempt in source.attempts:
        source_by_owner[attempt.user_key].append(attempt)
    progress_rebuilds = matching_progress = 0
    for user_key in source.owners:
        projected = await _combined_projection(
            store,
            user_key,
            tuple(source_by_owner[user_key]),
        )
        if await store.progress(user_key) == projected:
            matching_progress += 1
        else:
            progress_rebuilds += 1

    return MigrationPlan(
        missing_sessions=missing_sessions,
        resumable_sessions=resumable_sessions,
        matching_sessions=matching_sessions,
        missing_attempts=missing_attempts,
        matching_attempts=matching_attempts,
        progress_rebuilds=progress_rebuilds,
        matching_progress=matching_progress,
    )


async def apply_migration(
    source: SourceSnapshot,
    store: FirestoreMigrationStore,
) -> ApplySummary:
    summary = ApplySummary()
    for record in source.records:
        destination_session = await store.session(record.session.id)
        if destination_session is None:
            await store.repository.create_session(_staging_session(record))
            summary.created_sessions += 1
            destination_session = _staging_session(record)

        if record.attempt is None or destination_session == record.session:
            continue
        committed = await store.repository.submit_attempt(
            record.session.user_key,
            record.session.id,
            record.attempt,
        )
        if committed != record.attempt:
            raise MigrationError(
                f"Firestore returned a different attempt for {record.attempt.id}"
            )
        summary.submitted_attempts += 1

    for user_key in source.owners:
        attempts = await store.attempts_for_owner(user_key)
        projection = rebuild_progress_projection(user_key, attempts)
        progress_to_document(projection)
        if await store.progress(user_key) != projection:
            await store.set_progress(projection)
            summary.rebuilt_progress += 1
    return summary


async def verification_issues(
    source: SourceSnapshot,
    store: FirestoreMigrationStore,
) -> list[str]:
    issues: list[str] = []
    for record in source.records:
        if await store.session(record.session.id) != record.session:
            issues.append(f"session {record.session.id} does not match")
        if record.attempt is not None:
            if await store.attempt(record.attempt.id) != record.attempt:
                issues.append(f"attempt {record.attempt.id} does not match")

    for user_key in source.owners:
        attempts = await store.attempts_for_owner(user_key)
        expected = rebuild_progress_projection(user_key, attempts)
        progress_to_document(expected)
        if await store.progress(user_key) != expected:
            issues.append(f"progress for owner {user_key} does not match")
    return issues


def _print_source(source: SourceSnapshot) -> None:
    print(
        "Legacy Postgres source: "
        f"{len(source.records)} sessions, "
        f"{len(source.attempts)} attempts, "
        f"{source.response_count} responses, "
        f"{len(source.owners)} owners."
    )


def _print_plan(plan: MigrationPlan) -> None:
    print(
        "Firestore plan: "
        f"{plan.missing_sessions} sessions to create, "
        f"{plan.resumable_sessions} sessions to resume, "
        f"{plan.matching_sessions} sessions already current; "
        f"{plan.missing_attempts} attempts to create, "
        f"{plan.matching_attempts} attempts already current; "
        f"{plan.progress_rebuilds} progress projections to rebuild, "
        f"{plan.matching_progress} already current."
    )


def _validate_configuration() -> None:
    migration_settings = settings.model_copy(
        update={"user_state_backend": "firestore"}
    )
    issues = migration_settings.user_state_configuration_issues
    if issues:
        raise MigrationError(
            "Firestore migration configuration is invalid: " + ", ".join(issues)
        )


async def execute_migration(
    mode: MigrationMode,
    *,
    expected_source_digest: str | None = None,
    session_factory: Any = AsyncSessionFactory,
    store: Any | None = None,
) -> MigrationReport:
    """Execute an idempotent migration and return a provider-safe report."""

    _validate_configuration()
    migration_store = store or FirestoreMigrationStore()
    owns_store = store is None
    try:
        connect = getattr(migration_store, "connect", None)
        if connect is not None:
            await connect()
        source = await load_source_snapshot(session_factory)
        summary = SourceSummary(
            sessions=len(source.records),
            attempts=len(source.attempts),
            responses=source.response_count,
            owners=len(source.owners),
        )
        source_digest = source.digest

        if mode == "apply" and expected_source_digest is not None:
            if expected_source_digest.strip().lower() != source_digest:
                raise MigrationError(
                    "Legacy Postgres learner state changed after the reviewed dry run"
                )

        if mode == "verify-only":
            issues = await verification_issues(source, migration_store)
            if issues:
                preview = ", ".join(issues[:10])
                remainder = len(issues) - min(len(issues), 10)
                suffix = f" (and {remainder} more)" if remainder else ""
                raise MigrationError(f"Verification failed: {preview}{suffix}")
            return MigrationReport(
                mode=mode,
                source=summary,
                source_digest=source_digest,
                verified=True,
            )

        plan = await build_plan(source, migration_store)
        if mode == "dry-run":
            return MigrationReport(
                mode=mode,
                source=summary,
                source_digest=source_digest,
                plan=plan,
            )

        applied = await apply_migration(source, migration_store)
        refreshed_source = await load_source_snapshot(session_factory)
        if refreshed_source != source:
            raise MigrationError(
                "Legacy Postgres learner state changed during migration. "
                "Keep the maintenance window active and rerun --apply."
            )
        issues = await verification_issues(refreshed_source, migration_store)
        if issues:
            preview = ", ".join(issues[:10])
            remainder = len(issues) - min(len(issues), 10)
            suffix = f" (and {remainder} more)" if remainder else ""
            raise MigrationError(f"Post-apply verification failed: {preview}{suffix}")
        return MigrationReport(
            mode=mode,
            source=summary,
            source_digest=source_digest,
            plan=plan,
            applied=applied,
            verified=True,
        )
    finally:
        if owns_store:
            close = getattr(migration_store, "close", None)
            if close is not None:
                await close()


def _print_report(report: MigrationReport) -> None:
    source = report.source
    print(
        "Legacy Postgres source: "
        f"{source.sessions} sessions, "
        f"{source.attempts} attempts, "
        f"{source.responses} responses, "
        f"{source.owners} owners."
    )
    print(f"Reviewed source digest: {report.source_digest}")
    if report.plan is not None:
        _print_plan(report.plan)
    if report.mode == "dry-run":
        print("Dry run complete. No Firestore or Postgres records were written.")
    elif report.mode == "apply":
        applied = report.applied or ApplySummary()
        print(
            "Migration applied: "
            f"{applied.created_sessions} sessions created, "
            f"{applied.submitted_attempts} attempts committed, "
            f"{applied.rebuilt_progress} progress projections rebuilt."
        )
        print("Verification passed. Legacy Postgres records were not modified.")
    else:
        print(
            "Verification passed. Firestore contains the complete legacy "
            "source and progress is current."
        )


async def migrate(mode: MigrationMode) -> MigrationReport:
    report = await execute_migration(mode)
    _print_report(report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Migrate legacy Postgres learner sessions, attempts, responses, "
            "and progress into Firestore without deleting the source rows."
        )
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument(
        "--dry-run",
        dest="mode",
        action="store_const",
        const="dry-run",
        help="Inspect both stores and print the idempotent write plan.",
    )
    modes.add_argument(
        "--apply",
        dest="mode",
        action="store_const",
        const="apply",
        help="Apply missing records, rebuild progress, and verify the result.",
    )
    modes.add_argument(
        "--verify-only",
        dest="mode",
        action="store_const",
        const="verify-only",
        help="Verify records and projections without writing either store.",
    )
    return parser.parse_args()


async def _run(mode: MigrationMode) -> None:
    try:
        await migrate(mode)
    finally:
        await close_database()


def main() -> int:
    args = parse_args()
    try:
        asyncio.run(_run(args.mode))
    except (MigrationError, UserStateError) as exc:
        print(f"Migration failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
