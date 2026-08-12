from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app import api as api_module
from app.main import app


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
        "coverage_percent",
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

        subject, topic = operating_systems_progress()
        assert subject["solved_questions"] == 0
        assert topic["solved_questions"] == 0

        correct_session = learner.post(
            "/api/v1/practice-sessions",
            json=session_payload,
        ).json()
        assert correct_session["questions"][0]["id"] == question["id"]
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

        later_wrong_session = learner.post(
            "/api/v1/practice-sessions",
            json=session_payload,
        ).json()
        learner.post(
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
        subject, topic = operating_systems_progress()
        assert subject["solved_questions"] == 1
        assert topic["solved_questions"] == 1
        assert topic["accuracy"] == 0

        repeated_correct_session = learner.post(
            "/api/v1/practice-sessions",
            json=session_payload,
        ).json()
        learner.post(
            "/api/v1/attempts",
            json={
                "session_id": repeated_correct_session["id"],
                "answers": [
                    {"question_id": question["id"], "answer": correct_answer}
                ],
            },
        )
        subject, topic = operating_systems_progress()
        assert subject["solved_questions"] == 1
        assert topic["solved_questions"] == 1
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
