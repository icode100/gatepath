from __future__ import annotations

from functools import lru_cache

from app.config import settings
from app.question_catalog.firestore import FirestoreQuestionCatalogRepository
from app.question_catalog.repository import QuestionCatalogRepository
from app.question_catalog.domain import QuestionCatalogUnavailable


@lru_cache(maxsize=1)
def get_question_catalog_repository() -> QuestionCatalogRepository | None:
    """Return Firestore catalog storage, or None for the relational fallback."""

    if settings.question_catalog_maintenance:
        raise QuestionCatalogUnavailable("Question catalog is in a maintenance window")
    if settings.question_catalog_backend == "postgres":
        return None
    if settings.question_catalog_configuration_issues:
        raise QuestionCatalogUnavailable("Firestore question catalog is not configured")
    return FirestoreQuestionCatalogRepository()


def reset_question_catalog_repository_cache() -> None:
    get_question_catalog_repository.cache_clear()
