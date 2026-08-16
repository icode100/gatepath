from __future__ import annotations

from typing import Protocol

from app.models import Difficulty, QuestionSource, QuestionType, SessionMode
from app.question_catalog.domain import (
    CatalogQuestion,
    CatalogSnapshot,
    CatalogSubject,
    CatalogTestForm,
    CatalogTopic,
)


class QuestionCatalogRepository(Protocol):
    async def healthcheck(self) -> None: ...

    async def snapshot(self, *, force_refresh: bool = False) -> CatalogSnapshot: ...

    async def find_subject(
        self,
        *,
        subject_id: int | None = None,
        subject_slug: str | None = None,
    ) -> CatalogSubject | None: ...

    async def find_topic(self, topic_id: int) -> CatalogTopic | None: ...

    async def find_question(
        self,
        question_id: int,
        *,
        active_only: bool = True,
    ) -> CatalogQuestion | None: ...

    async def questions_by_ids(
        self,
        question_ids: list[int] | tuple[int, ...],
    ) -> list[CatalogQuestion]: ...

    async def filter_questions(
        self,
        *,
        subject_id: int | None = None,
        topic_id: int | None = None,
        source: QuestionSource | None = None,
        source_kind: QuestionSource | None = None,
        year: int | None = None,
        question_type: QuestionType | None = None,
        question_types: tuple[QuestionType, ...] | None = None,
        difficulty: Difficulty | None = None,
        difficulties: tuple[Difficulty, ...] | None = None,
        search: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> tuple[list[CatalogQuestion], int]: ...

    async def list_test_forms(
        self,
        *,
        mode: SessionMode | None = None,
        subject_id: int | None = None,
    ) -> list[CatalogTestForm]: ...

    async def find_test_form(self, catalog_id: str) -> CatalogTestForm | None: ...
