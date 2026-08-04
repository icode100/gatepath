from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.user_state.domain import ProgressProjection, StudyAttempt, StudySession


class UserStateError(Exception):
    """Base class for safe user-state failure categories."""


class UserStateNotFound(UserStateError):
    """The requested record does not exist for the current owner."""


class UserStateAlreadySubmitted(UserStateError):
    """The session was submitted without a recoverable committed attempt."""


class UserStateUnavailable(UserStateError):
    """The configured user-state store cannot currently process a request."""


class UserStatePayloadTooLarge(UserStateError):
    """A record is too large for the conservative Firestore safety limit."""


@dataclass(frozen=True, slots=True)
class UserStateResetSummary:
    """Owner-scoped records removed by a completed progress reset."""

    sessions_deleted: int
    attempts_deleted: int
    progress_deleted: bool


@runtime_checkable
class UserStateRepository(Protocol):
    async def create_session(self, session: StudySession) -> StudySession: ...

    async def get_session(
        self,
        user_key: str,
        session_id: str,
    ) -> StudySession: ...

    async def submit_attempt(
        self,
        user_key: str,
        session_id: str,
        candidate_attempt: StudyAttempt,
    ) -> StudyAttempt: ...

    async def get_attempt(
        self,
        user_key: str,
        attempt_id: str,
    ) -> StudyAttempt: ...

    async def get_progress(self, user_key: str) -> ProgressProjection: ...

    async def reset_progress(self, user_key: str) -> UserStateResetSummary: ...

    async def claim_guest_state(
        self,
        guest_user_key: str,
        target_user_key: str,
    ) -> ProgressProjection: ...

    async def healthcheck(self) -> None: ...
