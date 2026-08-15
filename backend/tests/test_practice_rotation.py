from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.user_state.dependencies import get_user_state_repository
from app.user_state.memory import MemoryUserStateRepository


def _submission_answer(correct_answer: object) -> object:
    """Choose a concrete accepted value when a NAT key stores a range."""

    if isinstance(correct_answer, dict):
        if "min" in correct_answer and "max" in correct_answer:
            return (float(correct_answer["min"]) + float(correct_answer["max"])) / 2
        return correct_answer.get("value")
    return correct_answer


def _topic(client: TestClient, subject_slug: str, topic_slug: str) -> dict[str, Any]:
    response = client.get(f"/api/v1/subjects/{subject_slug}")
    assert response.status_code == 200, response.text
    return next(
        topic for topic in response.json()["topics"] if topic["slug"] == topic_slug
    )


def _launch(
    client: TestClient,
    *,
    subject_slug: str,
    topic_id: int,
    count: int,
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/practice-sessions",
        json={
            "subject_slug": subject_slug,
            "topic_id": topic_id,
            "count": count,
            "seed": 2027,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _question_ids(session: dict[str, Any]) -> list[int]:
    return [question["id"] for question in session["questions"]]


def _submit(
    client: TestClient,
    session: dict[str, Any],
    answers: dict[int, object],
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/attempts",
        json={
            "session_id": session["id"],
            "answers": [
                {"question_id": question_id, "answer": answer}
                for question_id, answer in answers.items()
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _answer_key(attempt: dict[str, Any]) -> dict[int, object]:
    return {
        result["question_id"]: _submission_answer(result["correct_answer"])
        for result in attempt["results"]
    }


@contextmanager
def _memory_user_state() -> Iterator[MemoryUserStateRepository]:
    """Exercise the same repository interface used by hosted Firestore."""

    repository = MemoryUserStateRepository()
    previous = app.dependency_overrides.get(get_user_state_repository)
    app.dependency_overrides[get_user_state_repository] = lambda: repository
    try:
        yield repository
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_user_state_repository, None)
        else:
            app.dependency_overrides[get_user_state_repository] = previous


@pytest.mark.parametrize(
    ("subject_slug", "topic_slug"),
    [
        ("engineering-mathematics", "linear-algebra"),
        ("operating-systems", "processes-and-threads"),
        ("databases", "sql"),
    ],
)
def test_every_course_topic_uses_cumulative_mastery_rotation(
    subject_slug: str,
    topic_slug: str,
    client: TestClient,
) -> None:
    """Rotation is topic-generic and mastery may be accumulated across retries."""

    topic = _topic(client, subject_slug, topic_slug)
    assert topic["question_count"] >= 4

    first = _launch(
        client,
        subject_slug=subject_slug,
        topic_id=topic["id"],
        count=2,
    )
    first_ids = _question_ids(first)
    reveal = _submit(client, first, {})
    key = _answer_key(reveal)

    first_half = _launch(
        client,
        subject_slug=subject_slug,
        topic_id=topic["id"],
        count=2,
    )
    assert _question_ids(first_half) == first_ids
    first_half_result = _submit(
        client,
        first_half,
        {first_ids[0]: key[first_ids[0]]},
    )
    assert first_half_result["correct_count"] == 1
    assert first_half_result["unanswered_count"] == 1

    second_half = _launch(
        client,
        subject_slug=subject_slug,
        topic_id=topic["id"],
        count=2,
    )
    assert _question_ids(second_half) == first_ids
    second_half_result = _submit(
        client,
        second_half,
        {first_ids[1]: key[first_ids[1]]},
    )
    assert second_half_result["correct_count"] == 1
    assert second_half_result["unanswered_count"] == 1

    advanced = _launch(
        client,
        subject_slug=subject_slug,
        topic_id=topic["id"],
        count=2,
    )
    advanced_ids = _question_ids(advanced)
    assert len(advanced_ids) == 2
    assert set(first_ids).isdisjoint(advanced_ids)


def test_hosted_user_state_rotation_is_isolated_per_learner(
    client: TestClient,
) -> None:
    """One learner's mastered batch must remain new for every other learner."""

    with _memory_user_state():
        other_learner = TestClient(app)
        try:
            topic = _topic(client, "computer-networks", "transport-layer")
            first = _launch(
                client,
                subject_slug="computer-networks",
                topic_id=topic["id"],
                count=4,
            )
            first_ids = _question_ids(first)
            reveal = _submit(client, first, {})
            key = _answer_key(reveal)

            mastered = _launch(
                client,
                subject_slug="computer-networks",
                topic_id=topic["id"],
                count=4,
            )
            assert _question_ids(mastered) == first_ids
            mastered_result = _submit(client, mastered, key)
            assert mastered_result["correct_count"] == 4

            learner_next = _launch(
                client,
                subject_slug="computer-networks",
                topic_id=topic["id"],
                count=4,
            )
            assert set(first_ids).isdisjoint(_question_ids(learner_next))

            other_first = _launch(
                other_learner,
                subject_slug="computer-networks",
                topic_id=topic["id"],
                count=4,
            )
            assert _question_ids(other_first) == first_ids
            assert other_first["user_key"] != learner_next["user_key"]
        finally:
            other_learner.close()


def test_exhausted_topic_cycles_for_revision_without_double_counting_solved(
    client: TestClient,
) -> None:
    """After exhaustion, revision may cycle but solved coverage stays distinct."""

    with _memory_user_state():
        topic = _topic(client, "computer-networks", "transport-layer")
        assert 1 <= topic["question_count"] <= 100

        first = _launch(
            client,
            subject_slug="computer-networks",
            topic_id=topic["id"],
            count=100,
        )
        first_ids = _question_ids(first)
        assert len(first_ids) == topic["question_count"]
        reveal = _submit(client, first, {})
        key = _answer_key(reveal)

        mastery = _launch(
            client,
            subject_slug="computer-networks",
            topic_id=topic["id"],
            count=100,
        )
        assert _question_ids(mastery) == first_ids
        mastered = _submit(client, mastery, key)
        assert mastered["correct_count"] == topic["question_count"]

        revision = _launch(
            client,
            subject_slug="computer-networks",
            topic_id=topic["id"],
            count=100,
        )
        assert _question_ids(revision) == first_ids
        repeated = _submit(client, revision, key)
        assert repeated["correct_count"] == topic["question_count"]

        analytics_response = client.get("/api/v1/progress/analytics")
        assert analytics_response.status_code == 200, analytics_response.text
        analytics_topic = next(
            item
            for item in analytics_response.json()["topics"]
            if item["topic_id"] == topic["id"]
        )
        assert analytics_topic["unique_questions_solved"] == topic["question_count"]
        assert analytics_topic["solved_coverage_percent"] == 100.0
