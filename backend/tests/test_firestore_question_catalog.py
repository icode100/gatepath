from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api import _canonical_subject_progress, _question_snapshot
from app.config import Settings, settings
from app.identity import current_user_key
from app.main import app
from app.question_catalog.dependencies import get_question_catalog_repository
from app.question_catalog.domain import QuestionCatalogInvalid, QuestionCatalogUnavailable
from app.question_catalog.firestore import FirestoreQuestionCatalogRepository
from app.user_state.dependencies import get_user_state_repository
from app.user_state.domain import ProgressProjection, QuestionEvidence, StudySession
from app.user_state.memory import MemoryUserStateRepository


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def test_hosted_runtime_does_not_require_postgres_after_both_firestore_cutovers() -> None:
    credential = json.dumps(
        {
            "project_id": "gatepath-test",
            "client_email": "firebase-admin@gatepath-test.iam.gserviceaccount.com",
            "private_key": "-----BEGIN PRIVATE KEY-----\nfixture\n-----END PRIVATE KEY-----\n",
        }
    )
    fully_cut_over = Settings(
        _env_file=None,
        environment="production",
        serverless=True,
        database_url="sqlite+aiosqlite:///not-production.db",
        anonymous_identity_secret="x" * 48,
        user_state_backend="firestore",
        question_catalog_backend="firestore",
        firebase_project_id="gatepath-test",
        firebase_service_account_json=credential,
    )
    assert fully_cut_over.hosted_configuration_issues == []
    assert fully_cut_over.question_catalog_configuration_issues == []

    relational_fallback = Settings(
        _env_file=None,
        environment="production",
        serverless=True,
        database_url="sqlite+aiosqlite:///not-production.db",
        anonymous_identity_secret="x" * 48,
        user_state_backend="firestore",
        question_catalog_backend="postgres",
        firebase_project_id="gatepath-test",
        firebase_service_account_json=credential,
    )
    assert "DATABASE_URL_NOT_POSTGRESQL" in (
        relational_fallback.hosted_configuration_issues
    )


def test_firestore_catalog_requires_firestore_user_state_but_not_the_reverse() -> None:
    credential = json.dumps(
        {
            "project_id": "gatepath-test",
            "client_email": "firebase-admin@gatepath-test.iam.gserviceaccount.com",
            "private_key": "-----BEGIN PRIVATE KEY-----\nfixture\n-----END PRIVATE KEY-----\n",
        }
    )
    common = {
        "_env_file": None,
        "environment": "production",
        "serverless": True,
        "database_url": "postgresql://gatepath@example.invalid/gatepath",
        "anonymous_identity_secret": "x" * 48,
        "firebase_project_id": "gatepath-test",
        "firebase_service_account_json": credential,
    }

    unsafe_mixed_mode = Settings(
        **common,
        user_state_backend="postgres",
        question_catalog_backend="firestore",
    )
    assert "FIRESTORE_CATALOG_REQUIRES_FIRESTORE_USER_STATE" in (
        unsafe_mixed_mode.hosted_configuration_issues
    )
    assert "FIRESTORE_CATALOG_REQUIRES_FIRESTORE_USER_STATE" in (
        unsafe_mixed_mode.question_catalog_configuration_issues
    )

    firestore_state_with_postgres_catalog = Settings(
        **common,
        user_state_backend="firestore",
        question_catalog_backend="postgres",
    )
    assert firestore_state_with_postgres_catalog.hosted_configuration_issues == []
    assert (
        firestore_state_with_postgres_catalog.question_catalog_configuration_issues
        == []
    )

    postgres_only = Settings(
        **common,
        user_state_backend="postgres",
        question_catalog_backend="postgres",
    )
    assert postgres_only.hosted_configuration_issues == []
    assert postgres_only.question_catalog_configuration_issues == []


def test_catalog_dependency_fails_closed_for_postgres_user_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "question_catalog_backend", "firestore")
    monkeypatch.setattr(settings, "user_state_backend", "postgres")
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
    get_question_catalog_repository.cache_clear()

    try:
        with pytest.raises(QuestionCatalogUnavailable, match="not configured"):
            get_question_catalog_repository()
    finally:
        get_question_catalog_repository.cache_clear()


class _Snapshot:
    def __init__(self, document_id: str, document: dict[str, Any] | None) -> None:
        self.id = document_id
        self.exists = document is not None
        self._document = document

    def to_dict(self) -> dict[str, Any] | None:
        return dict(self._document) if self._document is not None else None


class _DocumentReference:
    def __init__(self, client: _Client, path: str) -> None:
        self._client = client
        self.path = path
        self.id = path.rsplit("/", 1)[-1]

    async def get(self) -> _Snapshot:
        self._client.point_reads += 1
        return _Snapshot(self.id, self._client.documents.get(self.path))

    def collection(self, name: str) -> _CollectionReference:
        return _CollectionReference(self._client, f"{self.path}/{name}")


class _CollectionReference:
    def __init__(self, client: _Client, path: str) -> None:
        self._client = client
        self.path = path

    def document(self, document_id: str) -> _DocumentReference:
        return _DocumentReference(self._client, f"{self.path}/{document_id}")


class _Client:
    def __init__(self, documents: dict[str, dict[str, Any]]) -> None:
        self.documents = documents
        self.point_reads = 0
        self.batch_reads = 0

    def collection(self, name: str) -> _CollectionReference:
        return _CollectionReference(self, name)

    async def get_all(self, references: list[_DocumentReference]):
        self.batch_reads += len(references)
        for reference in reversed(references):
            yield _Snapshot(reference.id, self.documents.get(reference.path))


def _question(
    *,
    question_id: int,
    text: str,
    correct_answer: str,
    asset: bool = False,
) -> dict[str, Any]:
    return {
        "id": question_id,
        "external_id": f"question:{question_id}",
        "bank_version": "catalog-v1",
        "is_active": True,
        "subject_id": 1,
        "topic_id": 11,
        "source": "previous_year",
        "year": 2025,
        "exam_session": "Set 1",
        "source_kind": "previous_year",
        "source_year": 2025,
        "source_paper": "GATE 2025 CS Set 1",
        "source_question_number": 1,
        "source_paper_id": "gate-cs-2025-set-1",
        "source_item_label": "CS-1",
        "source_page": 2,
        "source_url": "https://gate2025.iitr.ac.in/question-paper.html",
        "answer_key_url": "https://gate2025.iitr.ac.in/answer-key.html",
        "extraction_method": "verified-pdf",
        "extraction_confidence": 1.0,
        "question_type": "mcq",
        "difficulty": "medium",
        "text": text,
        "options": [
            {"id": "A", "text": "Canonical A"},
            {"id": "B", "text": "Canonical B"},
        ],
        "correct_answer": correct_answer,
        "numerical_tolerance": 0.01,
        "marks": 1,
        "explanation": f"Explanation for {text}",
        "tags": ["verified"],
        "assets": (
            [
                {
                    "role": "stem_diagram",
                    "url": (
                        "/question-assets/pyq/gate-cs-2025-set-1/"
                        + "a" * 64
                        + ".png"
                    ),
                    "alt_text": "A verified diagram",
                    "sha256": "a" * 64,
                }
            ]
            if asset
            else []
        ),
        "created_at": "2026-08-16T00:00:00Z",
    }


def _release_documents(
    *,
    tamper_question_shard: bool = False,
    self_alias: bool = False,
    cross_subject_alias: bool = False,
) -> dict[str, dict[str, Any]]:
    release_id = "release-v1"
    subject = {
        "id": 1,
        "slug": "computer-networks",
        "code": "CN",
        "name": "Computer Networks",
        "description": "Networks",
        "order_index": 1,
    }
    topic = {
        "id": 11,
        "subject_id": 1,
        "slug": "transport-layer",
        "name": "Transport Layer",
        "description": "TCP and UDP",
        "order_index": 1,
    }
    legacy_subject = {
        "id": 2,
        "slug": "operating-systems",
        "code": "OS",
        "name": "Operating Systems",
        "description": "Operating systems",
        "order_index": 2,
    }
    legacy_topic = {
        "id": 22,
        "subject_id": 2,
        "slug": "process-management",
        "name": "Process Management",
        "description": "Processes",
        "order_index": 1,
    }
    note = {
        "id": 21,
        "topic_id": 11,
        "title": "Transport Layer",
        "summary": "Summary",
        "content_md": "# Transport Layer",
        "key_points": ["TCP is reliable"],
        "worked_examples": [{"question": "Example", "solution": "Solution"}],
        "updated_at": "2026-08-16T00:00:00Z",
    }
    canonical = _question(
        question_id=101,
        text="Canonical transport question",
        correct_answer="A",
        asset=True,
    )
    legacy = _question(
        question_id=77,
        text="Exact retired legacy wording",
        correct_answer="B",
    )
    if cross_subject_alias:
        legacy["subject_id"] = 2
        legacy["topic_id"] = 22
    alias = {
        "schema_version": "1.0",
        "catalog_version": "catalog-v1",
        "id": 77,
        "legacy_question_id": 77,
        "canonical_question_id": 77 if self_alias else 101,
        "legacy_content_sha256": hashlib.sha256(
            _canonical_bytes(legacy)
        ).hexdigest(),
        "legacy_snapshot": legacy,
    }
    form = {
        "id": "cn-01",
        "title": "CN Test 01",
        "description": "One-question fixture form",
        "mode": "sectional",
        "subject_id": 1,
        "form_number": 1,
        "question_ids": [101],
        "question_count": 1,
        "duration_seconds": 180,
        "total_marks": 1,
        "seed": 2027,
        "question_type_counts": {"mcq": 1, "msq": 0, "nat": 0},
        "topic_count": 1,
        "bank_version": "catalog-v1",
        "is_available": True,
        "unavailable_reason": None,
        "generated_at": "2026-08-16T00:00:00Z",
    }
    items_by_kind = {
        "subjects": [subject, legacy_subject] if cross_subject_alias else [subject],
        "topics": [topic, legacy_topic] if cross_subject_alias else [topic],
        "revision_notes": [note],
        "questions": [canonical],
        "question_index": [{"id": 101, "runtime_id": 101, "is_active": True}],
        "question_aliases": [alias],
        "test_forms": [form],
    }
    documents: dict[str, dict[str, Any]] = {}
    descriptors: list[dict[str, Any]] = []
    for kind, items in items_by_kind.items():
        encoded = _canonical_bytes(items)
        descriptor = {
            "kind": kind,
            "index": 0,
            "count": len(items),
            "payload_sha256": hashlib.sha256(encoded).hexdigest(),
            "encoded_bytes": len(encoded),
        }
        descriptors.append(descriptor)
        shard_items = list(items)
        if tamper_question_shard and kind == "questions":
            shard_items = [dict(canonical, text="Tampered after publication")]
        documents[
            f"gatepath_catalog_releases/{release_id}/shards/{kind}--000"
        ] = {
            "schema_version": "1.0",
            "release_id": release_id,
            "catalog_version": "catalog-v1",
            **descriptor,
            "items": shard_items,
        }
    counts = {
        "canonical_question_count": 1,
        "active_question_count": 1,
        "subject_count": 2 if cross_subject_alias else 1,
        "topic_count": 2 if cross_subject_alias else 1,
        "test_form_count": 1,
    }
    collections = [
        {"kind": kind, "count": len(items)}
        for kind, items in items_by_kind.items()
    ]
    source_bindings = {"question_archive_sha256": "b" * 64}
    root_payload = {
        "release_id": release_id,
        "source_bindings": source_bindings,
        "counts": counts,
        "collections": collections,
        "shards": descriptors,
    }
    root = hashlib.sha256(_canonical_bytes(root_payload)).hexdigest()
    documents[f"gatepath_catalog_releases/{release_id}"] = {
        "schema_version": "1.0",
        "release_id": release_id,
        "catalog_version": "catalog-v1",
        "status": "ready",
        "immutable": True,
        "manifest_root_sha256": root,
        **root_payload,
    }
    documents["gatepath_catalog_meta/current"] = {
        "schema_version": "1.0",
        "release_id": release_id,
        "catalog_version": "catalog-v1",
        "checksum": root,
        "counts": counts,
        "shard_count": len(descriptors),
    }
    return documents


@pytest.mark.asyncio
async def test_firestore_catalog_uses_bounded_verified_shards_and_cache() -> None:
    client = _Client(_release_documents())
    repository = FirestoreQuestionCatalogRepository(
        client=client,
        cache_seconds=300,
    )

    snapshot = await repository.snapshot()
    assert snapshot.release_id == "release-v1"
    assert len(snapshot.active_questions) == 1
    assert client.batch_reads == 7

    questions, total = await repository.filter_questions(
        subject_id=1,
        search="CANONICAL TRANSPORT",
        limit=50,
    )
    assert total == 1
    assert questions[0].id == 101
    assert (await repository.snapshot()) is snapshot
    assert client.batch_reads == 7


@pytest.mark.asyncio
async def test_firestore_catalog_rejects_a_tampered_shard() -> None:
    repository = FirestoreQuestionCatalogRepository(
        client=_Client(_release_documents(tamper_question_shard=True)),
    )
    with pytest.raises(QuestionCatalogInvalid, match="failed integrity"):
        await repository.snapshot()


@pytest.mark.asyncio
async def test_firestore_catalog_rejects_a_self_alias_collision() -> None:
    repository = FirestoreQuestionCatalogRepository(
        client=_Client(_release_documents(self_alias=True)),
    )
    with pytest.raises(QuestionCatalogInvalid, match="forbidden self-alias"):
        await repository.snapshot()


@pytest.mark.asyncio
async def test_cross_subject_alias_progress_uses_canonical_taxonomy_and_exact_marks() -> None:
    repository = FirestoreQuestionCatalogRepository(
        client=_Client(_release_documents(cross_subject_alias=True)),
    )
    snapshot = await repository.snapshot()
    attempted_at = datetime(2026, 8, 16, tzinfo=UTC)
    progress = ProgressProjection(
        user_key="learner",
        total_attempts=2,
        total_responses=2,
        correct_count=1,
        incorrect_count=1,
        unanswered_count=0,
        total_score=2 / 3,
        total_max_score=2,
        percentage_sum=0,
        subjects={},
        recent_attempts=(),
        evidence={
            77: QuestionEvidence(
                question_id=77,
                subject_id=2,
                topic_id=22,
                attempt_count=2,
                correct_count=1,
                incorrect_count=1,
                latest_answered_status="incorrect",
                latest_answered_at=attempted_at,
                last_attempted_at=attempted_at,
            )
        },
        updated_at=attempted_at,
    )

    buckets = _canonical_subject_progress(progress, snapshot)
    assert 2 not in buckets
    assert buckets[1].attempted_questions == 2
    assert buckets[1].unique_questions_attempted == 1
    assert buckets[1].correct_count == 1
    assert buckets[1].incorrect_count == 1
    assert buckets[1].marks_available == 2
    assert buckets[1].marks_earned == pytest.approx(2 / 3, abs=1e-6)


def test_firestore_routes_and_snapshotless_legacy_session_use_exact_alias(
    client: TestClient,
) -> None:
    repository = FirestoreQuestionCatalogRepository(
        client=_Client(_release_documents()),
    )
    user_state = MemoryUserStateRepository()
    asyncio.run(
        user_state.create_session(
            StudySession(
                id="legacy-session",
                user_key="firestore-test-user",
                catalog_id=None,
                mode="practice",
                subject_id=1,
                topic_id=11,
                question_ids=(77,),
                question_snapshots=(),
                question_count=1,
                duration_seconds=None,
                total_marks=1,
                seed=1,
                started_at=datetime(2026, 8, 16, tzinfo=UTC),
                expires_at=None,
            )
        )
    )
    canonical_question = asyncio.run(repository.find_question(101))
    assert canonical_question is not None
    asyncio.run(
        user_state.create_session(
            StudySession(
                id="partial-legacy-session",
                user_key="firestore-test-user",
                catalog_id=None,
                mode="practice",
                subject_id=1,
                topic_id=11,
                question_ids=(101, 77),
                question_snapshots=(_question_snapshot(canonical_question),),
                question_count=2,
                duration_seconds=None,
                total_marks=2,
                seed=2,
                started_at=datetime(2026, 8, 16, tzinfo=UTC),
                expires_at=None,
            )
        )
    )
    app.dependency_overrides[get_question_catalog_repository] = lambda: repository
    app.dependency_overrides[get_user_state_repository] = lambda: user_state
    app.dependency_overrides[current_user_key] = lambda: "firestore-test-user"
    try:
        subjects = client.get("/api/v1/subjects")
        assert subjects.status_code == 200, subjects.text
        assert subjects.json()[0]["question_count"] == 1
        subject = client.get("/api/v1/subjects/computer-networks")
        assert subject.status_code == 200, subject.text
        assert subject.json()["topics"][0]["note_available"] is True

        listed = client.get("/api/v1/questions", params={"limit": 50})
        assert listed.status_code == 200, listed.text
        assert listed.json()["total"] == 1
        assert listed.json()["items"][0]["assets"][0]["role"] == "stem_diagram"

        restored = client.get("/api/v1/sessions/legacy-session")
        assert restored.status_code == 200, restored.text
        restored_question = restored.json()["questions"][0]
        assert restored_question["id"] == 77
        assert restored_question["text"] == "Exact retired legacy wording"

        partially_restored = client.get(
            "/api/v1/sessions/partial-legacy-session"
        )
        assert partially_restored.status_code == 200, partially_restored.text
        assert [
            item["id"] for item in partially_restored.json()["questions"]
        ] == [101, 77]
        assert partially_restored.json()["questions"][1]["text"] == (
            "Exact retired legacy wording"
        )

        submitted = client.post(
            "/api/v1/attempts",
            json={
                "session_id": "legacy-session",
                "answers": [{"question_id": 77, "answer": "B"}],
            },
        )
        assert submitted.status_code == 201, submitted.text
        assert submitted.json()["correct_count"] == 1
        assert submitted.json()["results"][0]["correct_answer"] == "B"

        catalog = client.get("/api/v1/tests/catalog")
        assert catalog.status_code == 200, catalog.text
        assert catalog.json()["items"][0]["id"] == "cn-01"
        catalog_session = client.post(
            "/api/v1/tests/cn-01/sessions",
            json={},
        )
        assert catalog_session.status_code == 201, catalog_session.text
        assert catalog_session.json()["questions"][0]["id"] == 101

        practice = client.post(
            "/api/v1/practice-sessions",
            json={"subject_slug": "computer-networks", "count": 1},
        )
        assert practice.status_code == 201, practice.text
        assert practice.json()["questions"][0]["id"] == 101

        dashboard = client.get("/api/v1/progress/dashboard")
        assert dashboard.status_code == 200, dashboard.text
        assert dashboard.json()["subjects"][0]["unique_questions_attempted"] == 1
        analytics = client.get("/api/v1/progress/analytics")
        assert analytics.status_code == 200, analytics.text
        assert analytics.json()["overall"]["available_questions"] == 1
        assert analytics.json()["overall"]["unique_questions_solved"] == 1
        roadmap = client.get("/api/v1/roadmap")
        assert roadmap.status_code == 200, roadmap.text
        assert roadmap.json()["subjects"][0]["solved_questions"] == 1
    finally:
        app.dependency_overrides.pop(get_question_catalog_repository, None)
        app.dependency_overrides.pop(get_user_state_repository, None)
        app.dependency_overrides.pop(current_user_key, None)
