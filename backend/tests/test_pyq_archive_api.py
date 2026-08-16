from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api import (
    list_pyq_archive,
    pyq_archive_progress,
    record_pyq_archive_practice,
)
from app.database import Base
from app.models import PyqSourcePaper, PyqSourceQuestion
from app.user_state.memory import MemoryUserStateRepository


@pytest.mark.asyncio
async def test_archive_listing_filters_paginates_and_never_exposes_answers() -> None:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with factory() as session:
        session.add_all(
            [
                PyqSourcePaper(
                    id="gate-cs-2024-set-1",
                    exam_code="GATE",
                    paper_code="CS",
                    year=2024,
                    session_label="set-1",
                    display_name="GATE CS 2024 Set 1",
                    expected_item_count=1,
                    source_status="verified",
                ),
                PyqSourcePaper(
                    id="gate-cs-2023",
                    exam_code="GATE",
                    paper_code="CS",
                    year=2023,
                    session_label="single",
                    display_name="GATE CS 2023",
                    expected_item_count=1,
                    source_status="review_required",
                ),
            ]
        )
        await session.flush()
        session.add_all(
            [
                PyqSourceQuestion(
                    source_paper_id="gate-cs-2024-set-1",
                    item_label="CS-10",
                    ordinal=20,
                    marks=2,
                    item_type="MCQ",
                    question_md="Which service is provided by TCP?",
                    options=[
                        {"id": "A", "text": "Reliable byte stream"},
                        {"identifier": "B", "content": "Datagram only"},
                    ],
                    accepted_answers=["A"],
                    solution_md="This must remain private.",
                    subject_code="CN",
                    topic_slug="transport-layer",
                    syllabus_status="mapped",
                    transcription_status="verified",
                    answer_status="official",
                    classification_status="verified",
                    practice_eligible=True,
                    materialized_question_id=123,
                ),
                PyqSourceQuestion(
                    source_paper_id="gate-cs-2023",
                    item_label="CS-1",
                    ordinal=11,
                    item_type="NAT",
                    question_md="A numerical archive question",
                    subject_code="CN",
                    topic_slug="transport-layer",
                    syllabus_status="mapped",
                    transcription_status="review_required",
                    answer_status="unresolved",
                    classification_status="verified",
                    practice_eligible=False,
                ),
            ]
        )
        await session.commit()

        response = await list_pyq_archive(
            subject_code="cn",
            topic_slug="transport-layer",
            year=2024,
            item_type="MCQ",
            search="tcp",
            limit=50,
            offset=0,
            db=session,
        )
        assert response.total == 1
        assert response.limit == 50
        assert response.offset == 0
        item = response.items[0]
        assert item.paper_name == "GATE CS 2024 Set 1"
        assert item.question_text == "Which service is provided by TCP?"
        assert [option.model_dump() for option in item.options] == [
            {"id": "A", "text": "Reliable byte stream"}
        ]
        public_payload = item.model_dump()
        assert "accepted_answers" not in public_payload
        assert "solution_md" not in public_payload
        assert item.practice_eligible is True
        assert item.runtime_question_id == 123

        first_page = await list_pyq_archive(
            subject_code=None,
            topic_slug=None,
            year=None,
            item_type=None,
            search=None,
            limit=1,
            offset=0,
            db=session,
        )
        second_page = await list_pyq_archive(
            subject_code=None,
            topic_slug=None,
            year=None,
            item_type=None,
            search=None,
            limit=1,
            offset=1,
            db=session,
        )
        assert first_page.total == second_page.total == 1
        assert first_page.items[0].year == 2024
        assert second_page.items == []

        user_state = MemoryUserStateRepository()
        initial_progress = await pyq_archive_progress(
            user_key="archive-learner",
            db=session,
            user_state=user_state,
        )
        assert initial_progress.practiced_count == 0
        assert initial_progress.total == 1
        assert initial_progress.coverage_percent == 0

        recorded = await record_pyq_archive_practice(
            first_page.items[0].id,
            user_key="archive-learner",
            db=session,
            user_state=user_state,
        )
        duplicate = await record_pyq_archive_practice(
            first_page.items[0].id,
            user_key="archive-learner",
            db=session,
            user_state=user_state,
        )
        assert recorded.practiced_count == duplicate.practiced_count == 1
        assert recorded.total == 1
        assert recorded.coverage_percent == 100

    await engine.dispose()
