from __future__ import annotations

from fastapi.testclient import TestClient


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
    cs = [q for q in session["questions"] if q["subject_slug"] != "general-aptitude"]
    assert len(ga) == 10
    assert len(cs) == 55


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
    assert body["total"] == 18
    question_12 = next(
        item for item in body["items"] if item["source_question_number"] == 12
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
    eigen = next(q for q in session["questions"] if "eigenvalues" in q["text"])
    wrong_mcq = next(
        q
        for q in session["questions"]
        if q["question_type"] == "mcq" and q["id"] != eigen["id"]
    )

    submission = client.post(
        "/api/v1/attempts",
        json={
            "session_id": session["id"],
            "user_key": user_key,
            "answers": [
                {"question_id": eigen["id"], "answer": "B"},
                {"question_id": wrong_mcq["id"], "answer": "Z"},
            ],
        },
    )
    assert submission.status_code == 201, submission.text
    result = submission.json()
    assert result["correct_count"] == 1
    assert result["incorrect_count"] == 1
    assert result["unanswered_count"] == 4
    assert any(item["correct_answer"] == "B" for item in result["results"])
    incorrect = next(item for item in result["results"] if item["question_id"] == wrong_mcq["id"])
    assert incorrect["awarded_marks"] < 0

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


def test_topic_note_contains_examples(client: TestClient) -> None:
    subject = client.get("/api/v1/subjects/engineering-mathematics").json()
    topic_id = subject["topics"][0]["id"]
    response = client.get(f"/api/v1/topics/{topic_id}/notes")
    assert response.status_code == 200
    note = response.json()
    assert note["content_md"].startswith("# ")
    assert note["key_points"]
    assert note["worked_examples"][0]["solution"]
