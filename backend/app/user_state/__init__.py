from app.user_state.dependencies import (
    get_user_state_repository,
    require_user_state_repository,
    reset_user_state_repository_cache,
)
from app.user_state.domain import (
    ProgressProjection,
    QuestionEvidence,
    RecentAttemptProjection,
    StudyAttempt,
    StudyResponse,
    StudySession,
    SubjectProgressTotals,
    apply_attempt_to_projection,
    empty_progress_projection,
    merge_progress_projections,
    rebuild_progress_projection,
)
from app.user_state.firestore import FirestoreUserStateRepository
from app.user_state.memory import MemoryUserStateRepository
from app.user_state.repository import (
    UserStateAlreadySubmitted,
    UserStateError,
    UserStateNotFound,
    UserStatePayloadTooLarge,
    UserStateRepository,
    UserStateUnavailable,
)

__all__ = [
    "FirestoreUserStateRepository",
    "MemoryUserStateRepository",
    "ProgressProjection",
    "QuestionEvidence",
    "RecentAttemptProjection",
    "StudyAttempt",
    "StudyResponse",
    "StudySession",
    "SubjectProgressTotals",
    "UserStateAlreadySubmitted",
    "UserStateError",
    "UserStateNotFound",
    "UserStatePayloadTooLarge",
    "UserStateRepository",
    "UserStateUnavailable",
    "apply_attempt_to_projection",
    "empty_progress_projection",
    "get_user_state_repository",
    "merge_progress_projections",
    "rebuild_progress_projection",
    "require_user_state_repository",
    "reset_user_state_repository_cache",
]
