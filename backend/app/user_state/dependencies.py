from __future__ import annotations

from functools import lru_cache

from app.config import settings
from app.user_state.firestore import FirestoreUserStateRepository
from app.user_state.repository import UserStateRepository, UserStateUnavailable


@lru_cache(maxsize=1)
def get_user_state_repository() -> UserStateRepository | None:
    """Return Firestore state storage, or None while legacy Postgres is selected."""

    if settings.user_state_maintenance:
        raise UserStateUnavailable("Learner state is in a maintenance window")
    if settings.user_state_backend == "postgres":
        return None
    if settings.user_state_configuration_issues:
        raise UserStateUnavailable("Firestore user state is not configured")
    return FirestoreUserStateRepository()


def require_user_state_repository() -> UserStateRepository:
    repository = get_user_state_repository()
    if repository is None:
        raise UserStateUnavailable("Firestore user state is not enabled")
    return repository


def reset_user_state_repository_cache() -> None:
    """Reset the lazy provider between settings overrides in tests."""

    get_user_state_repository.cache_clear()
