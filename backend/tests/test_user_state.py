from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import json

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.config import settings
from app.main import app
from app.user_state.dependencies import get_user_state_repository
from app.user_state.domain import (
    StudyAttempt,
    StudyResponse,
    StudySession,
    merge_progress_projections,
    rebuild_progress_projection,
)
from app.user_state.memory import MemoryUserStateRepository
from app.user_state.repository import UserStateNotFound, UserStateUnavailable


BASE_TIME = datetime(2027, 1, 2, 3, 4, tzinfo=UTC)


def _session(
    session_id: str,
    user_key: str,
    *,
    question_ids: tuple[int, ...] = (101, 102, 103),
) -> StudySession:
    return StudySession(
        id=session_id,
        user_key=user_key,
        catalog_id=None,
        mode="practice",
        subject_id=7,
        topic_id=70,
        question_ids=question_ids,
        question_snapshots=tuple(
            {
                "id": question_id,
                "subject_id": 7,
                "topic_id": 70,
                "text": f"Question {question_id}",
            }
            for question_id in question_ids
        ),
        question_count=len(question_ids),
        duration_seconds=None,
        total_marks=len(question_ids),
        seed=17,
        started_at=BASE_TIME,
        expires_at=None,
    )


def _response(
    question_id: int,
    status: str,
    *,
    awarded_marks: float,
) -> StudyResponse:
    return StudyResponse(
        question_id=question_id,
        subject_id=7,
        topic_id=70,
        answer=None if status == "unanswered" else "A",
        correct_answer_snapshot="A",
        explanation_snapshot="Explanation",
        status=status,
        awarded_marks=awarded_marks,
        max_marks=1.0,
        negative_marks=abs(awarded_marks) if awarded_marks < 0 else 0.0,
    )


def _attempt(
    session_id: str,
    user_key: str,
    responses: tuple[StudyResponse, ...],
    *,
    submitted_at: datetime = BASE_TIME,
) -> StudyAttempt:
    correct = sum(response.status == "correct" for response in responses)
    incorrect = sum(response.status == "incorrect" for response in responses)
    unanswered = sum(response.status == "unanswered" for response in responses)
    return StudyAttempt(
        id=session_id,
        session_id=session_id,
        user_key=user_key,
        submitted_at=submitted_at,
        timed_out=False,
        score=sum(response.awarded_marks for response in responses),
        max_score=sum(response.max_marks for response in responses),
        correct_count=correct,
        incorrect_count=incorrect,
        unanswered_count=unanswered,
        mode="practice",
        subject_id=7,
        topic_id=70,
        catalog_id=None,
        responses=responses,
    )


@pytest.mark.asyncio
async def test_memory_repository_enforces_ownership_and_idempotent_submit() -> None:
    repository = MemoryUserStateRepository()
    session = _session("session-1", "owner")
    attempt = _attempt(
        session.id,
        "owner",
        (
            _response(101, "correct", awarded_marks=1.0),
            _response(102, "incorrect", awarded_marks=-1 / 3),
            _response(103, "unanswered", awarded_marks=0.0),
        ),
    )

    await repository.create_session(session)
    with pytest.raises(UserStateNotFound):
        await repository.get_session("intruder", session.id)
    with pytest.raises(UserStateNotFound):
        await repository.submit_attempt("intruder", session.id, attempt)

    first = await repository.submit_attempt("owner", session.id, attempt)
    retry = await repository.submit_attempt("owner", session.id, attempt)

    assert retry == first
    assert (await repository.get_session("owner", session.id)).is_submitted
    assert (await repository.get_attempt("owner", attempt.id)) == attempt
    with pytest.raises(UserStateNotFound):
        await repository.get_attempt("intruder", attempt.id)
    progress = await repository.get_progress("owner")
    assert progress.total_attempts == 1
    assert progress.total_responses == 3
    assert (progress.correct_count, progress.incorrect_count, progress.unanswered_count) == (
        1,
        1,
        1,
    )


@pytest.mark.asyncio
async def test_memory_reset_is_idempotent_and_owner_scoped() -> None:
    repository = MemoryUserStateRepository()
    owner_session = _session("reset-owner-session", "reset-owner")
    other_session = _session(
        "reset-other-session",
        "reset-other",
        question_ids=(201,),
    )
    owner_attempt = _attempt(
        owner_session.id,
        "reset-owner",
        (_response(101, "correct", awarded_marks=1.0),),
    )
    other_attempt = _attempt(
        other_session.id,
        "reset-other",
        (_response(201, "incorrect", awarded_marks=-1 / 3),),
    )
    await repository.create_session(owner_session)
    await repository.create_session(other_session)
    await repository.submit_attempt(
        "reset-owner",
        owner_session.id,
        owner_attempt,
    )
    await repository.submit_attempt(
        "reset-other",
        other_session.id,
        other_attempt,
    )

    first = await repository.reset_progress("reset-owner")
    second = await repository.reset_progress("reset-owner")

    assert first.sessions_deleted == 1
    assert first.attempts_deleted == 1
    assert first.progress_deleted is True
    assert second.sessions_deleted == 0
    assert second.attempts_deleted == 0
    assert second.progress_deleted is False
    with pytest.raises(UserStateNotFound):
        await repository.get_session("reset-owner", owner_session.id)
    with pytest.raises(UserStateNotFound):
        await repository.get_attempt("reset-owner", owner_attempt.id)
    assert (await repository.get_progress("reset-owner")).total_attempts == 0
    assert await repository.get_session("reset-other", other_session.id)
    assert await repository.get_attempt("reset-other", other_attempt.id)
    assert (await repository.get_progress("reset-other")).total_attempts == 1


@pytest.mark.asyncio
async def test_memory_reset_allows_fresh_post_reset_submission() -> None:
    repository = MemoryUserStateRepository()
    stale_session = _session("reset-stale-session", "reset-learner")
    stale_attempt = _attempt(
        stale_session.id,
        "reset-learner",
        (_response(101, "incorrect", awarded_marks=-1 / 3),),
    )
    await repository.create_session(stale_session)
    await repository.submit_attempt(
        "reset-learner",
        stale_session.id,
        stale_attempt,
    )
    await repository.reset_progress("reset-learner")

    with pytest.raises(UserStateNotFound):
        await repository.submit_attempt(
            "reset-learner",
            stale_session.id,
            stale_attempt,
        )

    fresh_session = _session(
        "reset-fresh-session",
        "reset-learner",
        question_ids=(301,),
    )
    fresh_attempt = _attempt(
        fresh_session.id,
        "reset-learner",
        (_response(301, "correct", awarded_marks=1.0),),
        submitted_at=BASE_TIME + timedelta(minutes=1),
    )
    await repository.create_session(fresh_session)
    committed = await repository.submit_attempt(
        "reset-learner",
        fresh_session.id,
        fresh_attempt,
    )

    assert committed == fresh_attempt
    progress = await repository.get_progress("reset-learner")
    assert progress.total_attempts == 1
    assert progress.correct_count == 1
    assert set(progress.evidence) == {301}


@pytest.mark.asyncio
async def test_memory_progress_tracks_unique_questions_and_latest_answered_state() -> None:
    repository = MemoryUserStateRepository()
    first_session = _session("progress-1", "learner", question_ids=(101, 102))
    second_session = _session("progress-2", "learner", question_ids=(101, 102, 103))
    await repository.create_session(first_session)
    await repository.create_session(second_session)

    await repository.submit_attempt(
        "learner",
        first_session.id,
        _attempt(
            first_session.id,
            "learner",
            (
                _response(101, "incorrect", awarded_marks=-1 / 3),
                _response(102, "unanswered", awarded_marks=0.0),
            ),
        ),
    )
    await repository.submit_attempt(
        "learner",
        second_session.id,
        _attempt(
            second_session.id,
            "learner",
            (
                _response(101, "correct", awarded_marks=1.0),
                _response(102, "unanswered", awarded_marks=0.0),
                _response(103, "incorrect", awarded_marks=-1 / 3),
            ),
            submitted_at=BASE_TIME + timedelta(hours=1),
        ),
    )

    progress = await repository.get_progress("learner")
    subject = progress.subjects[7]
    assert progress.total_attempts == 2
    assert progress.total_responses == 5
    assert (progress.correct_count, progress.incorrect_count, progress.unanswered_count) == (
        1,
        2,
        2,
    )
    assert subject.attempted_questions == 5
    assert subject.unique_questions_attempted == 3
    assert progress.evidence[101].attempt_count == 2
    assert progress.evidence[101].latest_answered_status == "correct"
    assert progress.evidence[102].latest_answered_status is None
    assert progress.evidence[102].unanswered_count == 2
    assert [item.attempt_id for item in progress.recent_attempts] == [
        "progress-2",
        "progress-1",
    ]


@pytest.mark.asyncio
async def test_memory_guest_claim_merges_state_and_is_repeatable() -> None:
    repository = MemoryUserStateRepository()
    with pytest.raises(UserStateNotFound):
        await repository.claim_guest_state("untrusted-owner", "target")
    guest_session = _session("guest-session", "anon-guest")
    target_session = _session("target-session", "target", question_ids=(201,))
    await repository.create_session(guest_session)
    await repository.create_session(target_session)
    await repository.submit_attempt(
        "anon-guest",
        guest_session.id,
        _attempt(
            guest_session.id,
            "anon-guest",
            (_response(101, "correct", awarded_marks=1.0),),
        ),
    )
    await repository.submit_attempt(
        "target",
        target_session.id,
        _attempt(
            target_session.id,
            "target",
            (_response(201, "incorrect", awarded_marks=-1 / 3),),
            submitted_at=BASE_TIME + timedelta(minutes=1),
        ),
    )

    claimed = await repository.claim_guest_state("anon-guest", "target")
    repeated = await repository.claim_guest_state("anon-guest", "target")

    assert repeated == claimed
    assert claimed.user_key == "target"
    assert claimed.total_attempts == 2
    assert claimed.total_responses == 2
    assert set(claimed.evidence) == {101, 201}
    assert (await repository.get_session("target", guest_session.id)).user_key == "target"
    assert (await repository.get_attempt("target", guest_session.id)).user_key == "target"
    with pytest.raises(UserStateNotFound):
        await repository.get_session("anon-guest", guest_session.id)
    assert (await repository.get_progress("anon-guest")).total_attempts == 0

    with pytest.raises(UserStateNotFound):
        await repository.claim_guest_state("anon-guest", "different-target")
    with pytest.raises(UserStateNotFound):
        await repository.reset_progress("anon-guest")
    with pytest.raises(UserStateNotFound):
        await repository.create_session(
            _session("late-guest-session", "anon-guest")
        )
    with pytest.raises(UserStateNotFound):
        await repository.submit_attempt(
            "anon-guest",
            guest_session.id,
            _attempt(
                guest_session.id,
                "anon-guest",
                (_response(101, "correct", awarded_marks=1.0),),
                submitted_at=BASE_TIME + timedelta(hours=1),
            ),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("claim_scheduled_first", [False, True])
async def test_concurrent_target_submit_and_guest_claim_has_no_lost_progress(
    claim_scheduled_first: bool,
) -> None:
    repository = MemoryUserStateRepository()
    guest_session = _session(
        "concurrent-guest-session",
        "anon-concurrent-guest",
        question_ids=(301,),
    )
    target_session = _session(
        "concurrent-target-session",
        "concurrent-target",
        question_ids=(302,),
    )
    guest_attempt = _attempt(
        guest_session.id,
        "anon-concurrent-guest",
        (_response(301, "correct", awarded_marks=1.0),),
        submitted_at=BASE_TIME,
    )
    target_attempt = _attempt(
        target_session.id,
        "concurrent-target",
        (_response(302, "incorrect", awarded_marks=-1 / 3),),
        submitted_at=BASE_TIME + timedelta(minutes=1),
    )
    await repository.create_session(guest_session)
    await repository.create_session(target_session)
    await repository.submit_attempt(
        "anon-concurrent-guest",
        guest_session.id,
        guest_attempt,
    )

    submit = repository.submit_attempt(
        "concurrent-target",
        target_session.id,
        target_attempt,
    )
    claim = repository.claim_guest_state(
        "anon-concurrent-guest",
        "concurrent-target",
    )
    await asyncio.gather(*(claim, submit) if claim_scheduled_first else (submit, claim))

    migrated_guest_attempt = await repository.get_attempt(
        "concurrent-target",
        guest_attempt.id,
    )
    committed_target_attempt = await repository.get_attempt(
        "concurrent-target",
        target_attempt.id,
    )
    expected = rebuild_progress_projection(
        "concurrent-target",
        (migrated_guest_attempt, committed_target_attempt),
    )
    actual = await repository.get_progress("concurrent-target")

    assert actual == expected
    assert actual.total_attempts == 2
    assert actual.total_responses == 2
    assert set(actual.evidence) == {301, 302}
    assert (actual.correct_count, actual.incorrect_count) == (1, 1)


def test_merge_progress_combines_overlap_latest_answers_and_recent_attempts() -> None:
    target_attempts = (
        _attempt(
            "target-old-overlap",
            "target",
            (_response(101, "correct", awarded_marks=1.0),),
            submitted_at=BASE_TIME,
        ),
        _attempt(
            "target-new-overlap",
            "target",
            (_response(102, "correct", awarded_marks=1.0),),
            submitted_at=BASE_TIME + timedelta(minutes=3),
        ),
        _attempt(
            "target-recent-1",
            "target",
            (_response(201, "correct", awarded_marks=1.0),),
            submitted_at=BASE_TIME + timedelta(minutes=5),
        ),
        _attempt(
            "target-recent-2",
            "target",
            (_response(301, "correct", awarded_marks=1.0),),
            submitted_at=BASE_TIME + timedelta(minutes=7),
        ),
    )
    guest_attempts = (
        _attempt(
            "guest-old-overlap",
            "guest",
            (_response(102, "incorrect", awarded_marks=-1 / 3),),
            submitted_at=BASE_TIME + timedelta(minutes=1),
        ),
        _attempt(
            "guest-new-overlap",
            "guest",
            (_response(101, "incorrect", awarded_marks=-1 / 3),),
            submitted_at=BASE_TIME + timedelta(minutes=2),
        ),
        _attempt(
            "guest-unanswered-overlap",
            "guest",
            (_response(101, "unanswered", awarded_marks=0.0),),
            submitted_at=BASE_TIME + timedelta(minutes=4),
        ),
        _attempt(
            "guest-recent",
            "guest",
            (_response(401, "correct", awarded_marks=1.0),),
            submitted_at=BASE_TIME + timedelta(minutes=6),
        ),
    )
    target = rebuild_progress_projection("target", target_attempts)
    guest = rebuild_progress_projection("guest", guest_attempts)

    merged = merge_progress_projections(target, guest, "target")

    assert merged.user_key == "target"
    assert merged.total_attempts == 8
    assert merged.total_responses == 8
    assert merged.subjects[7].attempted_questions == 8
    assert merged.subjects[7].unique_questions_attempted == 5

    first_overlap = merged.evidence[101]
    assert (
        first_overlap.attempt_count,
        first_overlap.correct_count,
        first_overlap.incorrect_count,
        first_overlap.unanswered_count,
    ) == (3, 1, 1, 1)
    assert first_overlap.latest_answered_status == "incorrect"
    assert first_overlap.latest_answered_at == BASE_TIME + timedelta(minutes=2)
    assert first_overlap.last_attempted_at == BASE_TIME + timedelta(minutes=4)

    second_overlap = merged.evidence[102]
    assert second_overlap.attempt_count == 2
    assert second_overlap.latest_answered_status == "correct"
    assert second_overlap.latest_answered_at == BASE_TIME + timedelta(minutes=3)

    assert [item.attempt_id for item in merged.recent_attempts] == [
        "target-recent-2",
        "guest-recent",
        "target-recent-1",
        "guest-unanswered-overlap",
        "target-new-overlap",
    ]
    assert merged.updated_at == BASE_TIME + timedelta(minutes=7)


def test_api_uses_user_state_repository_for_sessions_attempts_and_progress(
    client: TestClient,
) -> None:
    repository = MemoryUserStateRepository()
    app.dependency_overrides[get_user_state_repository] = lambda: repository
    try:
        created_response = client.post(
            "/api/v1/practice-sessions",
            json={
                "subject_slug": "engineering-mathematics",
                "count": 3,
                "seed": 712,
            },
        )
        assert created_response.status_code == 201, created_response.text
        created = created_response.json()
        owner_key = created["user_key"]

        reread = client.get(f"/api/v1/sessions/{created['id']}")
        assert reread.status_code == 200, reread.text
        assert reread.json()["id"] == created["id"]

        submitted_response = client.post(
            "/api/v1/attempts",
            json={
                "session_id": created["id"],
                "answers": [
                    {
                        "question_id": created["questions"][0]["id"],
                        "answer": "definitely-not-valid",
                    }
                ],
            },
        )
        assert submitted_response.status_code == 201, submitted_response.text
        submitted = submitted_response.json()
        assert submitted["incorrect_count"] == 1
        assert submitted["unanswered_count"] == 2

        retry = client.post(
            "/api/v1/attempts",
            json={"session_id": created["id"], "answers": []},
        )
        assert retry.status_code == 201, retry.text
        assert retry.json() == submitted

        attempt = client.get(f"/api/v1/attempts/{submitted['id']}")
        assert attempt.status_code == 200
        assert attempt.json() == submitted

        dashboard = client.get("/api/v1/progress/dashboard")
        assert dashboard.status_code == 200, dashboard.text
        assert dashboard.json()["user_key"] == owner_key
        assert dashboard.json()["total_attempts"] == 1
        assert dashboard.json()["total_responses"] == 3

        analytics = client.get("/api/v1/progress/analytics")
        assert analytics.status_code == 200, analytics.text
        assert analytics.json()["overall"]["attempted_responses"] == 3
        assert analytics.json()["overall"]["answered_responses"] == 1

        intruder = TestClient(app)
        try:
            assert intruder.get(f"/api/v1/sessions/{created['id']}").status_code == 404
            assert intruder.get(f"/api/v1/attempts/{submitted['id']}").status_code == 404
        finally:
            intruder.close()

        csrf_token = client.get("/api/v1/auth/csrf").json()["csrf_token"]
        reset = client.post(
            "/api/v1/progress/reset",
            json={"csrf_token": csrf_token, "confirmation": "RESET"},
        )
        assert reset.status_code == 200, reset.text
        assert reset.json()["progress_deleted"] is True
        assert reset.json()["sessions_deleted"] == 1
        assert reset.json()["attempts_deleted"] == 1
        assert client.get(f"/api/v1/sessions/{created['id']}").status_code == 404
        assert client.get(f"/api/v1/attempts/{submitted['id']}").status_code == 404
        assert client.get("/api/v1/progress/dashboard").json()["total_attempts"] == 0
    finally:
        app.dependency_overrides.pop(get_user_state_repository, None)


def _enable_valid_firestore_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "user_state_backend", "firestore")
    monkeypatch.setattr(settings, "firebase_auth_enabled", True)
    monkeypatch.setattr(settings, "firebase_project_id", "gatepath-test")
    monkeypatch.setattr(
        settings,
        "firebase_service_account_json",
        json.dumps(
            {
                "project_id": "gatepath-test",
                "client_email": "firebase-admin@example.test",
                "private_key": "test-only-private-key",
            }
        ),
    )
    monkeypatch.setattr(settings, "firestore_database_id", "(default)")
    monkeypatch.setattr(settings, "firestore_collection_prefix", "gatepath")


def test_health_checks_the_selected_firestore_repository(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = MemoryUserStateRepository()
    _enable_valid_firestore_configuration(monkeypatch)
    monkeypatch.setattr(
        main_module,
        "get_user_state_repository",
        lambda: repository,
    )

    response = client.get("/health")

    assert response.status_code == 200, response.text
    assert response.json()["user_state_backend"] == "firestore"
    assert response.json()["user_state"] == "ok"
    assert response.json()["user_state_issues"] == []


def test_health_reports_invalid_firestore_configuration_without_connecting(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "user_state_backend", "firestore")
    monkeypatch.setattr(settings, "firebase_auth_enabled", False)
    monkeypatch.setattr(settings, "firebase_project_id", "")
    monkeypatch.setattr(settings, "firebase_service_account_json", None)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.delenv("FIRESTORE_EMULATOR_HOST", raising=False)

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["user_state"] == "invalid"
    assert response.json()["user_state_issues"] == [
        "FIREBASE_PROJECT_ID_MISSING",
        "FIREBASE_ADMIN_CREDENTIALS_MISSING",
    ]


def test_firestore_user_state_does_not_require_browser_authentication(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = MemoryUserStateRepository()
    _enable_valid_firestore_configuration(monkeypatch)
    monkeypatch.setattr(settings, "firebase_auth_enabled", False)
    monkeypatch.setattr(
        main_module,
        "get_user_state_repository",
        lambda: repository,
    )

    response = client.get("/health")

    assert response.status_code == 200, response.text
    assert response.json()["authentication"] == "guest_only"
    assert response.json()["user_state"] == "ok"


@pytest.mark.parametrize(
    ("setting_name", "value", "issue"),
    [
        (
            "firestore_database_id",
            "preview-db",
            "FIRESTORE_DATABASE_ID_UNSUPPORTED",
        ),
        (
            "firestore_collection_prefix",
            "gatepath_preview",
            "FIRESTORE_COLLECTION_PREFIX_UNSUPPORTED",
        ),
    ],
)
def test_health_rejects_firestore_targets_without_matching_deployment_config(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    setting_name: str,
    value: str,
    issue: str,
) -> None:
    _enable_valid_firestore_configuration(monkeypatch)
    monkeypatch.setattr(settings, setting_name, value)

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json()["user_state"] == "invalid"
    assert response.json()["user_state_issues"] == [issue]


def test_maintenance_switch_blocks_user_state_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "user_state_maintenance", True)
    get_user_state_repository.cache_clear()

    try:
        with pytest.raises(UserStateUnavailable, match="maintenance window"):
            get_user_state_repository()
    finally:
        get_user_state_repository.cache_clear()


def test_health_reports_user_state_maintenance(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "user_state_maintenance", True)

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["user_state"] == "maintenance"
