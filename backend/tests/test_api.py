from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import api as api_module
from app.main import app


def _submission_answer(correct_answer: object) -> object:
    """Choose a concrete accepted NAT value when the key stores a range."""

    if isinstance(correct_answer, dict):
        if "min" in correct_answer and "max" in correct_answer:
            return (float(correct_answer["min"]) + float(correct_answer["max"])) / 2
        return correct_answer.get("value")
    return correct_answer


def test_practice_batch_selector_advances_only_after_complete_mastery() -> None:
    questions = [SimpleNamespace(id=question_id) for question_id in range(1, 24)]
    first = api_module._select_practice_batch(
        questions,
        count=8,
        seed=2027,
        solved_ids=set(),
    )
    first_ids = {question.id for question in first}

    partial = api_module._select_practice_batch(
        questions,
        count=8,
        seed=2027,
        solved_ids={question.id for question in first[:-1]},
    )
    assert [question.id for question in partial] == [question.id for question in first]

    second = api_module._select_practice_batch(
        questions,
        count=8,
        seed=2027,
        solved_ids=first_ids,
    )
    assert first_ids.isdisjoint(question.id for question in second)

    revision = api_module._select_practice_batch(
        questions,
        count=8,
        seed=2027,
        solved_ids={question.id for question in questions},
    )
    assert [question.id for question in revision] == [question.id for question in first]


def test_health_and_seeded_curriculum(client: TestClient) -> None:
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["database"] == "ok"

    response = client.get("/api/v1/subjects")
    assert response.status_code == 200
    subjects = response.json()
    assert len(subjects) == 11
    assert subjects[0]["slug"] == "engineering-mathematics"
    assert any(subject["slug"] == "computer-organization-and-architecture" for subject in subjects)

    detail = client.get("/api/v1/subjects/computer-networks")
    assert detail.status_code == 200
    assert detail.json()["topic_count"] == 7
    assert all(topic["note_available"] for topic in detail.json()["topics"])


def test_question_answers_are_not_exposed(client: TestClient) -> None:
    response = client.get("/api/v1/questions", params={"limit": 5})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 88
    assert len(body["items"]) == 5
    assert "correct_answer" not in body["items"][0]
    assert "explanation" not in body["items"][0]


def test_question_bank_has_stable_fifty_item_pagination(client: TestClient) -> None:
    first = client.get("/api/v1/questions")
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body["limit"] == 50
    assert first_body["offset"] == 0
    assert first_body["total"] > 50
    assert len(first_body["items"]) == 50

    second = client.get(
        "/api/v1/questions",
        params={"limit": 50, "offset": 50},
    )
    repeated_first = client.get(
        "/api/v1/questions",
        params={"limit": 50, "offset": 0},
    )
    assert second.status_code == 200, second.text
    assert repeated_first.status_code == 200, repeated_first.text
    second_body = second.json()
    first_ids = [item["id"] for item in first_body["items"]]
    second_ids = [item["id"] for item in second_body["items"]]
    assert first_ids == [item["id"] for item in repeated_first.json()["items"]]
    assert first_ids == sorted(first_ids)
    assert second_ids == sorted(second_ids)
    assert set(first_ids).isdisjoint(second_ids)
    assert second_body["total"] == first_body["total"]
    assert second_body["limit"] == 50
    assert second_body["offset"] == 50

    beyond_end = client.get(
        "/api/v1/questions",
        params={"limit": 50, "offset": first_body["total"]},
    )
    assert beyond_end.status_code == 200, beyond_end.text
    assert beyond_end.json()["items"] == []
    assert beyond_end.json()["total"] == first_body["total"]


def test_question_bank_filters_and_search_paginate_without_gaps(
    client: TestClient,
) -> None:
    subject = client.get("/api/v1/subjects/computer-networks")
    assert subject.status_code == 200, subject.text
    transport = next(
        topic
        for topic in subject.json()["topics"]
        if topic["slug"] == "transport-layer"
    )
    pool_response = client.get(
        "/api/v1/questions",
        params={
            "subject_slug": "computer-networks",
            "topic_id": transport["id"],
            "limit": 100,
        },
    )
    assert pool_response.status_code == 200, pool_response.text
    pool = pool_response.json()["items"]
    assert len(pool) > 8

    # Pick the largest real type/source group in this topic.  This keeps the
    # assertion stable if the bundled bank grows while exercising every filter
    # used by the question-bank UI plus both provenance aliases.
    groups: dict[tuple[str, str, str], list[dict[str, object]]] = {}
    for question in pool:
        key = (
            question["question_type"],
            question["source"],
            question["source_kind"],
        )
        groups.setdefault(key, []).append(question)
    (question_type, source, source_kind), expected = max(
        groups.items(), key=lambda item: len(item[1])
    )
    params: dict[str, object] = {
        "subject_slug": "computer-networks",
        "topic_id": transport["id"],
        "question_type": question_type,
        "source": source,
        "source_kind": source_kind,
        "limit": 2,
    }
    collected: list[int] = []
    for offset in range(0, len(expected), 2):
        page = client.get(
            "/api/v1/questions",
            params={**params, "offset": offset},
        )
        assert page.status_code == 200, page.text
        body = page.json()
        assert body["total"] == len(expected)
        assert body["offset"] == offset
        collected.extend(item["id"] for item in body["items"])
        assert all(item["subject_slug"] == "computer-networks" for item in body["items"])
        assert all(item["topic_id"] == transport["id"] for item in body["items"])
        assert all(item["question_type"] == question_type for item in body["items"])
        assert all(item["source"] == source for item in body["items"])
        assert all(item["source_kind"] == source_kind for item in body["items"])

    expected_ids = [question["id"] for question in expected]
    assert collected == expected_ids
    assert len(collected) == len(set(collected))

    searched = client.get(
        "/api/v1/questions",
        params={"search": "tHe", "limit": 7},
    )
    assert searched.status_code == 200, searched.text
    searched_body = searched.json()
    assert searched_body["total"] > len(searched_body["items"])
    assert len(searched_body["items"]) == 7
    assert all(
        "the" in " ".join(
            str(item.get(field) or "")
            for field in (
                "text",
                "source_paper",
                "exam_session",
                "source_url",
            )
        ).casefold()
        for item in searched_body["items"]
    )
    searched_next = client.get(
        "/api/v1/questions",
        params={"search": "tHe", "limit": 7, "offset": 7},
    )
    assert searched_next.status_code == 200, searched_next.text
    assert searched_next.json()["total"] == searched_body["total"]
    assert {
        item["id"] for item in searched_body["items"]
    }.isdisjoint(item["id"] for item in searched_next.json()["items"])


def test_question_bank_pagination_bounds_are_validated(client: TestClient) -> None:
    for params in (
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
        {"search": "x" * 201},
    ):
        response = client.get("/api/v1/questions", params=params)
        assert response.status_code == 422, (params, response.text)


def test_full_mock_is_65_questions_100_marks_and_three_hours(client: TestClient) -> None:
    response = client.post(
        "/api/v1/tests",
        json={"mode": "full", "user_key": "full-mock-test", "seed": 42},
    )
    assert response.status_code == 201, response.text
    session = response.json()
    assert session["question_count"] == 65
    assert len(session["questions"]) == 65
    assert session["total_marks"] == 100
    assert session["duration_seconds"] == 3 * 60 * 60
    ga = [q for q in session["questions"] if q["subject_slug"] == "general-aptitude"]
    em = [
        q
        for q in session["questions"]
        if q["subject_slug"] == "engineering-mathematics"
    ]
    core = [
        q
        for q in session["questions"]
        if q["subject_slug"]
        not in {"general-aptitude", "engineering-mathematics"}
    ]
    assert len(ga) == 10
    assert len(em) == 9
    assert len(core) == 46
    assert sum(q["marks"] for q in ga) == 15
    assert sum(q["marks"] for q in em) == 13
    assert sum(q["marks"] for q in core) == 72


def test_catalog_exposes_25_full_and_10_forms_for_each_course(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/tests/catalog")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 125
    assert body["full_test_count"] == 25
    assert body["course_test_count"] == 100
    full_forms = [item for item in body["items"] if item["mode"] == "full"]
    assert all(item["question_count"] == 65 for item in full_forms)
    assert all(item["duration_seconds"] == 10_800 for item in full_forms)
    assert all(item["total_marks"] == 100 for item in full_forms)
    course_codes = {
        item["subject_code"]
        for item in body["items"]
        if item["mode"] == "sectional"
    }
    assert course_codes == {
        "EM",
        "DL",
        "COA",
        "PDS",
        "ALG",
        "TOC",
        "CD",
        "OS",
        "DBMS",
        "CN",
    }
    assert all(
        sum(
            item["subject_code"] == code
            for item in body["items"]
            if item["mode"] == "sectional"
        )
        == 10
        for code in course_codes
    )

    selected = full_forms[0]
    assert selected["is_available"]
    session_response = client.post(
        f"/api/v1/tests/{selected['id']}/sessions",
        json={"user_key": "catalog-user"},
    )
    assert session_response.status_code == 201, session_response.text
    session = session_response.json()
    assert session["catalog_id"] == selected["id"]
    assert session["question_count"] == 65


def test_official_pyq_provenance(client: TestClient) -> None:
    response = client.get(
        "/api/v1/questions",
        params={"source_kind": "previous_year", "year": 2024, "limit": 100},
    )
    assert response.status_code == 200
    body = response.json()
    # The reproducible bank appends every safely verified 2024 extraction to
    # the original curated seed set, so the exact count can grow without
    # weakening provenance guarantees.
    assert body["total"] >= 18
    question_12 = next(
        item
        for item in body["items"]
        if item["source_question_number"] == 12
        and item["source_paper"] == "GATE 2024 CS1 (Session 5)"
    )
    assert question_12["source_paper"] == "GATE 2024 CS1 (Session 5)"
    assert question_12["source_url"].endswith("CS124S5.pdf")
    assert question_12["answer_key_url"].endswith("CS1FinalAnswerKey.pdf")


def test_topic_practice_repeats_partial_batch_then_serves_new_questions() -> None:
    """The API uses the same mastery progression for every subject/topic pool."""

    learner = TestClient(app)
    try:
        subject_response = learner.get("/api/v1/subjects/computer-networks")
        assert subject_response.status_code == 200
        transport = next(
            topic
            for topic in subject_response.json()["topics"]
            if topic["slug"] == "transport-layer"
        )
        assert transport["question_count"] >= 16
        request = {
            "subject_slug": "computer-networks",
            "topic_id": transport["id"],
            "count": 8,
            "seed": 2027,
        }

        first_response = learner.post("/api/v1/practice-sessions", json=request)
        assert first_response.status_code == 201, first_response.text
        first = first_response.json()
        first_ids = [question["id"] for question in first["questions"]]

        answer_key_response = learner.post(
            "/api/v1/attempts",
            json={"session_id": first["id"], "answers": []},
        )
        assert answer_key_response.status_code == 201, answer_key_response.text
        answer_key = {
            result["question_id"]: _submission_answer(result["correct_answer"])
            for result in answer_key_response.json()["results"]
        }

        partial_response = learner.post("/api/v1/practice-sessions", json=request)
        assert partial_response.status_code == 201, partial_response.text
        partial = partial_response.json()
        assert [question["id"] for question in partial["questions"]] == first_ids
        partial_attempt = learner.post(
            "/api/v1/attempts",
            json={
                "session_id": partial["id"],
                "answers": [
                    {"question_id": question_id, "answer": answer_key[question_id]}
                    for question_id in first_ids[:-1]
                ],
            },
        )
        assert partial_attempt.status_code == 201, partial_attempt.text
        assert partial_attempt.json()["correct_count"] == 7

        retry_response = learner.post("/api/v1/practice-sessions", json=request)
        assert retry_response.status_code == 201, retry_response.text
        retry = retry_response.json()
        assert [question["id"] for question in retry["questions"]] == first_ids
        final_question_id = first_ids[-1]
        final_attempt = learner.post(
            "/api/v1/attempts",
            json={
                "session_id": retry["id"],
                "answers": [
                    {
                        "question_id": final_question_id,
                        "answer": answer_key[final_question_id],
                    }
                ],
            },
        )
        assert final_attempt.status_code == 201, final_attempt.text
        assert final_attempt.json()["correct_count"] == 1

        next_response = learner.post("/api/v1/practice-sessions", json=request)
        assert next_response.status_code == 201, next_response.text
        next_batch = next_response.json()
        next_ids = [question["id"] for question in next_batch["questions"]]
        assert len(next_ids) == 8
        assert set(first_ids).isdisjoint(next_ids)
    finally:
        learner.close()


def test_submit_scores_and_updates_progress(client: TestClient) -> None:
    user_key = "integration-learner"
    response = client.post(
        "/api/v1/practice-sessions",
        json={
            "subject_slug": "engineering-mathematics",
            "count": 6,
            "seed": 7,
            "user_key": user_key,
        },
    )
    assert response.status_code == 201, response.text
    session = response.json()
    attempted = session["questions"][:2]

    submission = client.post(
        "/api/v1/attempts",
        json={
            "session_id": session["id"],
            "user_key": user_key,
            "answers": [
                {
                    "question_id": question["id"],
                    "answer": "definitely-not-a-valid-answer",
                }
                for question in attempted
            ],
        },
    )
    assert submission.status_code == 201, submission.text
    result = submission.json()
    assert result["correct_count"] == 0
    assert result["incorrect_count"] == 2
    assert result["unanswered_count"] == 4
    assert all("correct_answer" in item for item in result["results"])

    duplicate = client.post(
        "/api/v1/attempts",
        json={"session_id": session["id"], "user_key": user_key, "answers": []},
    )
    assert duplicate.status_code == 409

    dashboard = client.get("/api/v1/progress/dashboard", params={"user_key": user_key})
    assert dashboard.status_code == 200
    assert dashboard.json()["total_attempts"] == 1
    assert dashboard.json()["total_responses"] == 6

    analytics = client.get(
        "/api/v1/progress/analytics", params={"user_key": user_key}
    )
    assert analytics.status_code == 200
    analytics_body = analytics.json()
    assert analytics_body["overall"]["attempted_responses"] == 6
    assert analytics_body["overall"]["answered_responses"] == 2
    assert analytics_body["topics"]
    assert analytics_body["needs_practice_topics"]
    assert analytics_body["unattempted_topics"]
    assert {
        "accuracy_percent",
        "attempted_coverage_percent",
        "solved_coverage_percent",
        "coverage_percent",
        "unique_questions_solved",
        "recency_weighted_accuracy_percent",
        "mastery_score",
        "status",
    }.issubset(analytics_body["topics"][0])

    roadmap = client.get("/api/v1/roadmap", params={"user_key": user_key})
    assert roadmap.status_code == 200
    mathematics = next(
        item for item in roadmap.json()["subjects"] if item["slug"] == "engineering-mathematics"
    )
    assert mathematics["attempted_questions"] == 6
    assert mathematics["solved_questions"] == 0
    assert all(topic["solved_questions"] == 0 for topic in mathematics["topics"])


def test_progress_reset_requires_confirmation_and_is_owner_scoped() -> None:
    owner = TestClient(app)
    other = TestClient(app)
    try:
        owner_session_response = owner.post(
            "/api/v1/practice-sessions",
            json={
                "subject_slug": "operating-systems",
                "count": 3,
                "seed": 971,
            },
        )
        other_session_response = other.post(
            "/api/v1/practice-sessions",
            json={
                "subject_slug": "computer-networks",
                "count": 1,
                "seed": 972,
            },
        )
        assert owner_session_response.status_code == 201
        assert other_session_response.status_code == 201
        owner_session = owner_session_response.json()
        other_session = other_session_response.json()

        owner_attempt_response = owner.post(
            "/api/v1/attempts",
            json={"session_id": owner_session["id"], "answers": []},
        )
        other_attempt_response = other.post(
            "/api/v1/attempts",
            json={"session_id": other_session["id"], "answers": []},
        )
        assert owner_attempt_response.status_code == 201
        assert other_attempt_response.status_code == 201
        owner_attempt = owner_attempt_response.json()

        repeated_owner_session = owner.post(
            "/api/v1/practice-sessions",
            json={
                "subject_slug": "operating-systems",
                "count": 3,
                "seed": 971,
            },
        ).json()
        repeated_skip = owner.post(
            "/api/v1/attempts",
            json={"session_id": repeated_owner_session["id"], "answers": []},
        )
        assert repeated_skip.status_code == 201
        assert repeated_skip.json()["unanswered_count"] == 3

        owner_roadmap = owner.get("/api/v1/roadmap").json()
        operating_systems = next(
            item
            for item in owner_roadmap["subjects"]
            if item["slug"] == "operating-systems"
        )
        assert operating_systems["attempted_questions"] == 6
        assert operating_systems["solved_questions"] == 0

        csrf_token = owner.get("/api/v1/auth/csrf").json()["csrf_token"]
        invalid_csrf = owner.post(
            "/api/v1/progress/reset",
            json={"csrf_token": "x" * 32, "confirmation": "RESET"},
        )
        assert invalid_csrf.status_code == 403

        invalid_confirmation = owner.post(
            "/api/v1/progress/reset",
            json={"csrf_token": csrf_token, "confirmation": "reset"},
        )
        assert invalid_confirmation.status_code == 422

        reset_response = owner.post(
            "/api/v1/progress/reset",
            json={"csrf_token": csrf_token, "confirmation": "RESET"},
        )
        assert reset_response.status_code == 200, reset_response.text
        assert reset_response.headers["cache-control"] == "private, no-store"
        assert {"cookie", "authorization"}.issubset(
            {
                value.strip().casefold()
                for value in reset_response.headers["vary"].split(",")
            }
        )
        reset = reset_response.json()
        assert reset["reset"] is True
        assert reset["sessions_deleted"] == 2
        assert reset["attempts_deleted"] == 2
        assert owner.get(f"/api/v1/sessions/{owner_session['id']}").status_code == 404
        assert owner.get(f"/api/v1/attempts/{owner_attempt['id']}").status_code == 404

        dashboard = owner.get("/api/v1/progress/dashboard")
        assert dashboard.status_code == 200
        assert dashboard.json()["total_attempts"] == 0
        reset_roadmap = owner.get("/api/v1/roadmap").json()
        assert all(subject["solved_questions"] == 0 for subject in reset_roadmap["subjects"])
        assert all(subject["attempted_questions"] == 0 for subject in reset_roadmap["subjects"])

        other_dashboard = other.get("/api/v1/progress/dashboard")
        assert other_dashboard.status_code == 200
        assert other_dashboard.json()["total_attempts"] == 1
        assert other.get(f"/api/v1/sessions/{other_session['id']}").status_code == 200

        repeated = owner.post(
            "/api/v1/progress/reset",
            json={"csrf_token": csrf_token, "confirmation": "RESET"},
        )
        assert repeated.status_code == 200
        assert repeated.json()["sessions_deleted"] == 0
        assert repeated.json()["attempts_deleted"] == 0
        assert owner.get("/api/v1/questions", params={"limit": 1}).json()["total"] > 0
    finally:
        owner.close()
        other.close()


def test_roadmap_completion_counts_each_correctly_solved_question_once() -> None:
    learner = TestClient(app)
    try:
        session_payload = {
            "subject_slug": "operating-systems",
            "question_types": ["mcq"],
            "count": 1,
            "seed": 982,
        }

        first_session = learner.post(
            "/api/v1/practice-sessions",
            json=session_payload,
        ).json()
        question = first_session["questions"][0]
        wrong = learner.post(
            "/api/v1/attempts",
            json={
                "session_id": first_session["id"],
                "answers": [
                    {
                        "question_id": question["id"],
                        "answer": "definitely-not-a-valid-option",
                    }
                ],
            },
        )
        assert wrong.status_code == 201
        assert wrong.json()["incorrect_count"] == 1
        correct_answer = wrong.json()["results"][0]["correct_answer"]

        def operating_systems_progress() -> tuple[dict, dict]:
            roadmap = learner.get("/api/v1/roadmap")
            assert roadmap.status_code == 200
            subject = next(
                item
                for item in roadmap.json()["subjects"]
                if item["slug"] == "operating-systems"
            )
            topic = next(
                item for item in subject["topics"] if item["id"] == question["topic_id"]
            )
            return subject, topic

        def operating_systems_analytics() -> tuple[dict, dict]:
            analytics = learner.get("/api/v1/progress/analytics")
            assert analytics.status_code == 200
            payload = analytics.json()
            topic = next(
                item
                for item in payload["topics"]
                if item["topic_id"] == question["topic_id"]
            )
            return payload["overall"], topic

        subject, topic = operating_systems_progress()
        assert subject["solved_questions"] == 0
        assert topic["solved_questions"] == 0
        overall, analytics_topic = operating_systems_analytics()
        assert overall["unique_questions_attempted"] == 1
        assert overall["unique_questions_solved"] == 0
        assert overall["attempted_coverage_percent"] > 0
        assert overall["solved_coverage_percent"] == 0
        assert analytics_topic["unique_questions_attempted"] == 1
        assert analytics_topic["unique_questions_solved"] == 0

        correct_session = learner.post(
            "/api/v1/practice-sessions",
            json=session_payload,
        ).json()
        assert correct_session["questions"][0]["id"] == question["id"]
        # These concurrent sessions freeze the same unmastered one-question
        # batch, allowing the evidence regression below to prove that a later
        # miss never erases lifetime mastery.
        later_wrong_session = learner.post(
            "/api/v1/practice-sessions",
            json=session_payload,
        ).json()
        repeated_correct_session = learner.post(
            "/api/v1/practice-sessions",
            json=session_payload,
        ).json()
        assert later_wrong_session["questions"][0]["id"] == question["id"]
        assert repeated_correct_session["questions"][0]["id"] == question["id"]
        correct = learner.post(
            "/api/v1/attempts",
            json={
                "session_id": correct_session["id"],
                "answers": [
                    {"question_id": question["id"], "answer": correct_answer}
                ],
            },
        )
        assert correct.status_code == 201
        assert correct.json()["correct_count"] == 1
        subject, topic = operating_systems_progress()
        assert subject["solved_questions"] == 1
        assert topic["solved_questions"] == 1
        overall, analytics_topic = operating_systems_analytics()
        assert overall["unique_questions_attempted"] == 1
        assert overall["unique_questions_solved"] == 1
        assert analytics_topic["unique_questions_attempted"] == 1
        assert analytics_topic["unique_questions_solved"] == 1
        assert analytics_topic["solved_coverage_percent"] > 0

        later_wrong = learner.post(
            "/api/v1/attempts",
            json={
                "session_id": later_wrong_session["id"],
                "answers": [
                    {
                        "question_id": question["id"],
                        "answer": "still-not-a-valid-option",
                    }
                ],
            },
        )
        assert later_wrong.status_code == 201
        assert later_wrong.json()["incorrect_count"] == 1
        subject, topic = operating_systems_progress()
        assert subject["solved_questions"] == 1
        assert topic["solved_questions"] == 1
        assert topic["accuracy"] == 0
        overall, analytics_topic = operating_systems_analytics()
        assert overall["unique_questions_attempted"] == 1
        assert overall["unique_questions_solved"] == 1
        assert analytics_topic["unique_questions_solved"] == 1
        assert analytics_topic["correct_count"] == 0
        assert analytics_topic["accuracy_percent"] == 0

        repeated_correct = learner.post(
            "/api/v1/attempts",
            json={
                "session_id": repeated_correct_session["id"],
                "answers": [
                    {"question_id": question["id"], "answer": correct_answer}
                ],
            },
        )
        assert repeated_correct.status_code == 201
        subject, topic = operating_systems_progress()
        assert subject["solved_questions"] == 1
        assert topic["solved_questions"] == 1
        overall, analytics_topic = operating_systems_analytics()
        assert overall["unique_questions_solved"] == 1
        assert analytics_topic["unique_questions_solved"] == 1

        advanced_session = learner.post(
            "/api/v1/practice-sessions",
            json=session_payload,
        ).json()
        assert advanced_session["questions"][0]["id"] != question["id"]
    finally:
        learner.close()


def test_topic_note_contains_examples(client: TestClient) -> None:
    subject = client.get("/api/v1/subjects/engineering-mathematics").json()
    topic_id = subject["topics"][0]["id"]
    response = client.get(f"/api/v1/topics/{topic_id}/notes")
    assert response.status_code == 200
    note = response.json()
    assert note["content_md"].startswith("# ")
    assert note["key_points"]
    assert note["worked_examples"][0]["solution"]


def test_signed_identity_isolates_sessions_and_attempts(client: TestClient) -> None:
    owner_session_response = client.post(
        "/api/v1/practice-sessions",
        json={
            "subject_slug": "operating-systems",
            "count": 1,
            "seed": 31,
            "user_key": "client-controlled-value-is-ignored",
        },
    )
    assert owner_session_response.status_code == 201
    owner_session = owner_session_response.json()
    assert owner_session["user_key"].startswith("anon-")
    assert owner_session["user_key"] != "client-controlled-value-is-ignored"

    intruder = TestClient(app)
    try:
        own_identity = intruder.get("/api/v1/progress/dashboard")
        assert own_identity.status_code == 200
        assert own_identity.json()["user_key"].startswith("anon-")
        assert own_identity.json()["user_key"] != owner_session["user_key"]
        cookie_header = own_identity.headers.get("set-cookie", "").lower()
        assert "gatepath_identity=" in cookie_header
        assert "httponly" in cookie_header
        assert "samesite=lax" in cookie_header

        assert (
            intruder.get(f"/api/v1/sessions/{owner_session['id']}").status_code
            == 404
        )
        assert (
            intruder.post(
                "/api/v1/attempts",
                json={
                    "session_id": owner_session["id"],
                    "user_key": owner_session["user_key"],
                    "answers": [],
                },
            ).status_code
            == 404
        )
    finally:
        intruder.close()

    owner_attempt_response = client.post(
        "/api/v1/attempts",
        json={
            "session_id": owner_session["id"],
            "user_key": "still-ignored",
            "answers": [],
        },
    )
    assert owner_attempt_response.status_code == 201
    owner_attempt = owner_attempt_response.json()

    intruder = TestClient(app)
    try:
        assert (
            intruder.get(f"/api/v1/attempts/{owner_attempt['id']}").status_code
            == 404
        )
    finally:
        intruder.close()


def test_expired_session_discards_late_answers(
    client: TestClient,
    monkeypatch,
) -> None:
    response = client.post(
        "/api/v1/tests",
        json={
            "mode": "sectional",
            "subject_slug": "engineering-mathematics",
            "count": 1,
            "duration_minutes": 1,
            "seed": 99,
        },
    )
    assert response.status_code == 201, response.text
    session = response.json()
    expires_at = datetime.fromisoformat(session["expires_at"])
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    expired_now = expires_at + timedelta(seconds=1)
    monkeypatch.setattr(api_module, "utc_now", lambda: expired_now)

    result_response = client.post(
        "/api/v1/attempts",
        json={
            "session_id": session["id"],
            "answers": [
                {
                    "question_id": session["questions"][0]["id"],
                    "answer": "A",
                }
            ],
        },
    )
    assert result_response.status_code == 201, result_response.text
    result = result_response.json()
    assert result["timed_out"] is True
    assert result["score"] == 0
    assert result["correct_count"] == 0
    assert result["incorrect_count"] == 0
    assert result["unanswered_count"] == 1
    assert result["results"][0]["answer"] is None
