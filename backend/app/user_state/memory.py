from __future__ import annotations

import asyncio
import copy
from dataclasses import dataclass, replace
from typing import TypeVar

from app.user_state.codec import (
    attempt_to_document,
    progress_to_document,
    session_to_document,
)
from app.user_state.domain import (
    ProgressProjection,
    StudyAttempt,
    StudySession,
    apply_attempt_to_projection,
    empty_progress_projection,
    mark_archive_practiced,
    merge_progress_projections,
)
from app.user_state.repository import (
    UserStateAlreadySubmitted,
    UserStateNotFound,
    UserStateResetSummary,
)


T = TypeVar("T")


@dataclass(slots=True)
class _ClaimControl:
    target_user_key: str
    status: str = "claiming"
    projection_merged: bool = False


class MemoryUserStateRepository:
    """Concurrency-safe in-memory implementation for tests and local adapters."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._sessions: dict[str, StudySession] = {}
        self._attempts: dict[str, StudyAttempt] = {}
        self._progress: dict[str, ProgressProjection] = {}
        self._claims: dict[str, _ClaimControl] = {}

    @staticmethod
    def _copy(value: T) -> T:
        return copy.deepcopy(value)

    async def create_session(self, session: StudySession) -> StudySession:
        session_to_document(session)
        async with self._lock:
            if session.user_key in self._claims:
                raise UserStateNotFound("User state is no longer available")
            existing = self._sessions.get(session.id)
            if existing is not None:
                if existing == session:
                    return self._copy(existing)
                raise UserStateAlreadySubmitted("Study session already exists")
            self._sessions[session.id] = self._copy(session)
            return self._copy(session)

    async def get_session(
        self,
        user_key: str,
        session_id: str,
    ) -> StudySession:
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None or session.user_key != user_key:
                raise UserStateNotFound("Study session not found")
            return self._copy(session)

    async def submit_attempt(
        self,
        user_key: str,
        session_id: str,
        candidate_attempt: StudyAttempt,
    ) -> StudyAttempt:
        if (
            candidate_attempt.user_key != user_key
            or candidate_attempt.session_id != session_id
        ):
            raise UserStateNotFound("Study session not found")
        attempt_to_document(candidate_attempt)
        async with self._lock:
            if user_key in self._claims:
                raise UserStateNotFound("User state is no longer available")
            session = self._sessions.get(session_id)
            if session is None or session.user_key != user_key:
                raise UserStateNotFound("Study session not found")
            if session.is_submitted:
                committed = (
                    self._attempts.get(session.attempt_id)
                    if session.attempt_id
                    else None
                )
                if committed is not None and committed.user_key == user_key:
                    return self._copy(committed)
                raise UserStateAlreadySubmitted("Study session is already submitted")

            existing_attempt = self._attempts.get(candidate_attempt.id)
            if existing_attempt is not None:
                if (
                    existing_attempt.user_key == user_key
                    and existing_attempt.session_id == session_id
                ):
                    self._sessions[session_id] = replace(
                        session,
                        is_submitted=True,
                        attempt_id=existing_attempt.id,
                    )
                    return self._copy(existing_attempt)
                raise UserStateAlreadySubmitted("Study attempt already exists")

            current_progress = self._progress.get(
                user_key,
                empty_progress_projection(user_key),
            )
            updated_progress = apply_attempt_to_projection(
                current_progress,
                candidate_attempt,
            )
            progress_to_document(updated_progress)
            self._attempts[candidate_attempt.id] = self._copy(candidate_attempt)
            self._sessions[session_id] = replace(
                session,
                is_submitted=True,
                attempt_id=candidate_attempt.id,
            )
            self._progress[user_key] = self._copy(updated_progress)
            return self._copy(candidate_attempt)

    async def get_attempt(
        self,
        user_key: str,
        attempt_id: str,
    ) -> StudyAttempt:
        async with self._lock:
            attempt = self._attempts.get(attempt_id)
            if attempt is None or attempt.user_key != user_key:
                raise UserStateNotFound("Study attempt not found")
            return self._copy(attempt)

    async def get_progress(self, user_key: str) -> ProgressProjection:
        async with self._lock:
            progress = self._progress.get(
                user_key,
                empty_progress_projection(user_key),
            )
            return self._copy(progress)

    async def record_archive_practice(
        self,
        user_key: str,
        archive_question_id: int,
    ) -> ProgressProjection:
        async with self._lock:
            if user_key in self._claims:
                raise UserStateNotFound("User state is no longer available")
            updated = mark_archive_practiced(
                self._progress.get(user_key, empty_progress_projection(user_key)),
                archive_question_id,
            )
            progress_to_document(updated)
            self._progress[user_key] = self._copy(updated)
            return self._copy(updated)

    async def reset_progress(self, user_key: str) -> UserStateResetSummary:
        async with self._lock:
            if user_key.startswith("anon-") and user_key in self._claims:
                raise UserStateNotFound("User state is no longer available")

            session_ids = [
                session_id
                for session_id, session in self._sessions.items()
                if session.user_key == user_key
            ]
            attempt_ids = [
                attempt_id
                for attempt_id, attempt in self._attempts.items()
                if attempt.user_key == user_key
            ]
            for session_id in session_ids:
                self._sessions.pop(session_id, None)
            for attempt_id in attempt_ids:
                self._attempts.pop(attempt_id, None)
            progress_deleted = self._progress.pop(user_key, None) is not None
            return UserStateResetSummary(
                sessions_deleted=len(session_ids),
                attempts_deleted=len(attempt_ids),
                progress_deleted=progress_deleted,
            )

    async def claim_guest_state(
        self,
        guest_user_key: str,
        target_user_key: str,
    ) -> ProgressProjection:
        if not guest_user_key.startswith("anon-"):
            raise UserStateNotFound("Guest state is not available")
        if guest_user_key == target_user_key:
            return await self.get_progress(target_user_key)
        async with self._lock:
            control = self._claims.get(guest_user_key)
            if control is None:
                control = _ClaimControl(target_user_key=target_user_key)
                self._claims[guest_user_key] = control
            elif control.target_user_key != target_user_key:
                raise UserStateNotFound("Guest state is no longer available")
            elif control.status == "claimed":
                return self._copy(
                    self._progress.get(
                        target_user_key,
                        empty_progress_projection(target_user_key),
                    )
                )

            if not control.projection_merged:
                target_progress = self._progress.get(
                    target_user_key,
                    empty_progress_projection(target_user_key),
                )
                guest_progress = self._progress.get(
                    guest_user_key,
                    empty_progress_projection(guest_user_key),
                )
                merged = merge_progress_projections(
                    target_progress,
                    guest_progress,
                    target_user_key,
                )
                progress_to_document(merged)
                self._progress[target_user_key] = self._copy(merged)
                control.projection_merged = True

            for session_id, session in list(self._sessions.items()):
                if session.user_key == guest_user_key:
                    self._sessions[session_id] = replace(
                        session,
                        user_key=target_user_key,
                    )
            for attempt_id, attempt in list(self._attempts.items()):
                if attempt.user_key == guest_user_key:
                    self._attempts[attempt_id] = replace(
                        attempt,
                        user_key=target_user_key,
                    )
            self._progress.pop(guest_user_key, None)
            control.status = "claimed"
            return self._copy(
                self._progress.get(
                    target_user_key,
                    empty_progress_projection(target_user_key),
                )
            )

    async def healthcheck(self) -> None:
        return None
