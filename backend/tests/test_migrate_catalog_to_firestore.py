from __future__ import annotations

import copy
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from scripts import migrate_catalog_to_firestore as migration
from app.question_catalog.domain import CatalogSnapshot


DATA_DIR = Path(__file__).resolve().parents[1] / "data"
SOURCE_HASH = "a" * 64


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("A", "A"),
        (["A", "C"], ["A", "C"]),
        ({"lower": 1, "upper": 2}, {"lower": 1, "upper": 2}),
        (7, 7),
        (None, None),
    ],
)
def test_postgres_json_values_are_not_decoded_twice(
    value: Any,
    expected: Any,
) -> None:
    assert migration._decode_sql_value(
        "questions",
        "correct_answer",
        value,
        json_is_decoded=True,
    ) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('"A"', "A"),
        ('["A","C"]', ["A", "C"]),
        ('{"lower":1,"upper":2}', {"lower": 1, "upper": 2}),
        ("7", 7),
        ("null", None),
    ],
)
def test_sqlite_serialized_json_is_decoded_once(raw: str, expected: Any) -> None:
    assert migration._decode_sql_value(
        "questions",
        "correct_answer",
        raw,
        json_is_decoded=False,
    ) == expected


def test_sqlite_export_uses_frozen_columns_and_ignores_additive_assets() -> None:
    columns = migration.LEGACY_SOURCE_COLUMNS["questions"]
    connection = sqlite3.connect(":memory:")
    try:
        definition = ", ".join(f"{column} TEXT" for column in columns)
        connection.execute(f"CREATE TABLE questions ({definition}, assets TEXT)")
        values: list[Any] = [None] * len(columns)
        values[columns.index("id")] = "1"
        values[columns.index("options")] = "[]"
        values[columns.index("correct_answer")] = "null"
        values[columns.index("tags")] = "[]"
        values[columns.index("is_active")] = "1"
        placeholders = ", ".join("?" for _ in range(len(columns) + 1))
        connection.execute(
            f"INSERT INTO questions VALUES ({placeholders})",
            [*values, '[{"path":"catalog-only"}]'],
        )
        rows = migration._read_sqlite_table(connection, "questions")
    finally:
        connection.close()

    assert tuple(rows[0]) == columns
    assert "assets" not in rows[0]


def test_sqlite_export_fails_when_a_required_legacy_column_is_missing() -> None:
    columns = tuple(
        column
        for column in migration.LEGACY_SOURCE_COLUMNS["questions"]
        if column != "text"
    )
    connection = sqlite3.connect(":memory:")
    try:
        definition = ", ".join(f"{column} TEXT" for column in columns)
        connection.execute(f"CREATE TABLE questions ({definition}, assets TEXT)")
        with pytest.raises(migration.CatalogMigrationError, match="missing.*text"):
            migration._read_sqlite_table(connection, "questions")
    finally:
        connection.close()


def test_frozen_question_preflight_projection_excludes_catalog_only_fields() -> None:
    snapshot = json.loads(
        (DATA_DIR / "firestore_legacy_catalog_snapshot.json").read_text(
            encoding="utf-8"
        )
    )
    columns = migration._validated_legacy_source_columns(
        snapshot["collections"],
        "questions",
    )
    assert columns == migration.LEGACY_SOURCE_COLUMNS["questions"]
    assert "assets" not in columns


@pytest.fixture(scope="session")
def real_plan() -> migration.CatalogPlan:
    return migration.build_catalog_plan(
        snapshot_path=DATA_DIR / "firestore_legacy_catalog_snapshot.json",
        archive_path=DATA_DIR / "gate_cs_pyq_practice_1996_2025.json",
        allowlist_path=(
            DATA_DIR / "gate_cs_pyq_practice_1996_2025.allowlist.json"
        ),
        visibility_path=DATA_DIR / "pyq_legacy_collision_cleanup_plan.json",
    )


def test_real_plan_reconciles_every_question_without_duplicate_pyqs(
    real_plan: migration.CatalogPlan,
) -> None:
    counts = real_plan.counts
    assert counts["canonical_question_count"] == 5_163
    assert counts["active_question_count"] == 2_467
    assert counts["generated_original_count"] == 2_290
    assert counts["audited_pyq_count"] == 2_873
    assert counts["practice_pyq_count"] == 177
    assert counts["archive_only_pyq_count"] == 2_696
    assert counts["legacy_pyq_alias_count"] == 405
    assert counts["legacy_pyq_canonical_overlap_count"] == 391
    assert counts["legacy_duplicate_alias_count"] == 14
    assert counts["active_target_alias_count"] == 190
    assert counts["inactive_target_alias_count"] == 215
    assert counts["source_question_count"] == 2_873

    questions = [
        item.data for item in real_plan.entity_documents if item.kind == "questions"
    ]
    originals = [item for item in questions if item["record_kind"] == "generated_original"]
    pyqs = [item for item in questions if item["record_kind"] == "audited_pyq"]
    assert len(originals) == 2_290
    assert len(pyqs) == 2_873
    assert all(item["runtime_id"] < migration.ARCHIVE_RUNTIME_ID_BASE for item in originals)
    assert all(item["runtime_id"] >= migration.ARCHIVE_RUNTIME_ID_BASE for item in pyqs)
    runtime_ids = [item["runtime_id"] for item in questions]
    assert len(runtime_ids) == len(set(runtime_ids)) == 5_163
    assert max(runtime_ids) <= migration.JS_SAFE_INTEGER_MAX
    assert sum(item["is_active"] for item in originals) == 2_290
    assert sum(item["is_active"] for item in pyqs) == 177


def test_all_legacy_pyq_aliases_are_lossless_and_unambiguous(
    real_plan: migration.CatalogPlan,
) -> None:
    aliases = [
        item.data
        for item in real_plan.entity_documents
        if item.kind == "question_aliases"
    ]
    assert len(aliases) == 405
    assert len({item["legacy_question_id"] for item in aliases}) == 405
    required = {
        "text",
        "options",
        "correct_answer",
        "explanation",
        "question_type",
        "marks",
        "source_kind",
        "subject_id",
        "topic_id",
        "source_paper",
        "source_question_number",
    }
    for alias in aliases:
        assert alias["snapshot_complete"] is True
        assert required.issubset(alias["legacy_snapshot"])
        assert alias["legacy_content_sha256"] == migration.canonical_sha256(
            alias["legacy_snapshot"]
        )
        assert alias["canonical_runtime_id"] >= migration.ARCHIVE_RUNTIME_ID_BASE
        assert alias["canonical_runtime_id"] != alias["legacy_question_id"]
    target_counts = Counter(item["canonical_runtime_id"] for item in aliases)
    assert len(target_counts) == 391
    assert sum(count - 1 for count in target_counts.values()) == 14


def test_shards_and_manifest_are_checksum_bound_and_bounded(
    real_plan: migration.CatalogPlan,
) -> None:
    assert len(real_plan.shard_documents) == real_plan.counts["shard_count"]
    kind_counts: Counter[str] = Counter()
    question_ids: set[int] = set()
    index: dict[int, bool] = {}
    for shard in real_plan.shard_documents:
        data = shard.data
        assert data["payload_sha256"] == migration.canonical_sha256(data["items"])
        assert data["encoded_bytes"] == len(
            migration.canonical_json_bytes(data["items"])
        )
        assert len(migration.canonical_json_bytes(data)) <= migration.DEFAULT_SHARD_BYTES
        kind_counts[data["kind"]] += data["count"]
        if data["kind"] == "questions":
            question_ids.update(int(item["runtime_id"]) for item in data["items"])
            assert all(item["is_active"] is True for item in data["items"])
        elif data["kind"] == "question_index":
            index.update(
                {int(item["runtime_id"]): bool(item["is_active"]) for item in data["items"]}
            )
    assert kind_counts["questions"] == 2_467
    assert kind_counts["question_aliases"] == 405
    assert kind_counts["question_index"] == 5_163
    assert question_ids == {runtime_id for runtime_id, active in index.items() if active}
    root_payload = {
        "release_id": real_plan.release_id,
        "source_bindings": real_plan.source_bindings,
        "counts": real_plan.counts,
        "collections": real_plan.collections,
        "shards": real_plan.shards,
    }
    assert real_plan.manifest_root_sha256 == migration.canonical_sha256(root_payload)
    assert real_plan.pointer_document["checksum"] == real_plan.manifest_root_sha256


def test_rebuilt_catalog_has_all_125_available_test_forms(
    real_plan: migration.CatalogPlan,
) -> None:
    forms = [
        item.data for item in real_plan.entity_documents if item.kind == "test_forms"
    ]
    active_ids = {
        int(item.data["runtime_id"])
        for item in real_plan.entity_documents
        if item.kind == "questions" and item.data["is_active"] is True
    }
    assert len(forms) == 125
    assert Counter(item["mode"] for item in forms) == {"full": 25, "sectional": 100}
    for form in forms:
        assert form["is_available"] is True
        assert form["unavailable_reason"] is None
        assert len(form["question_ids"]) == len(set(form["question_ids"]))
        assert set(form["question_ids"]).issubset(active_ids)
        if form["mode"] == "full":
            assert form["question_count"] == 65
            assert form["total_marks"] == 100
            assert form["duration_seconds"] == 10_800
        else:
            assert form["question_count"] == 30
            assert form["duration_seconds"] == 5_400
            assert all(form["question_type_counts"][kind] > 0 for kind in ("mcq", "msq", "nat"))


def test_real_shards_parse_through_the_production_runtime_domain(
    real_plan: migration.CatalogPlan,
) -> None:
    items: dict[str, list[dict[str, Any]]] = {
        kind: []
        for kind in (
            "subjects",
            "topics",
            "revision_notes",
            "questions",
            "question_index",
            "question_aliases",
            "test_forms",
        )
    }
    for shard in real_plan.shard_documents:
        items[shard.data["kind"]].extend(shard.data["items"])
    snapshot = CatalogSnapshot.build(
        release_id=real_plan.release_id,
        metadata=real_plan.counts,
        subject_documents=items["subjects"],
        topic_documents=items["topics"],
        note_documents=items["revision_notes"],
        question_documents=items["questions"],
        question_index_documents=items["question_index"],
        question_alias_documents=items["question_aliases"],
        test_form_documents=items["test_forms"],
    )
    assert len(snapshot.questions) == 2_467
    assert len(snapshot.question_index) == 5_163
    assert len(snapshot.question_aliases) == 405
    assert len(snapshot.test_forms) == 125
    assert all(form.is_available for form in snapshot.test_forms)


class _Snapshot:
    def __init__(
        self,
        reference: "_Document",
        data: dict[str, Any] | None,
        update_time: int | None,
    ) -> None:
        self.reference = reference
        self.id = reference.id
        self.exists = data is not None
        self._data = copy.deepcopy(data)
        self.update_time = update_time

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self._data or {})


class _Document:
    def __init__(self, client: "_Client", path: tuple[str, ...]) -> None:
        self.client = client
        self.path = path
        self.id = path[-1]

    def get(self, transaction: "_Transaction | None" = None) -> _Snapshot:
        if transaction is not None:
            return transaction.get(self)
        data = self.client.data.get(self.path)
        revision = self.client.versions.get(self.path, 0) if data is not None else None
        return _Snapshot(self, data, revision)

    def collection(self, name: str) -> "_Collection":
        return _Collection(self.client, self.path + (name,))


class _Collection:
    def __init__(self, client: "_Client", path: tuple[str, ...]) -> None:
        self.client = client
        self.path = path

    def document(self, document_id: str) -> _Document:
        return _Document(self.client, self.path + (document_id,))

    def stream(self):
        expected_length = len(self.path) + 1
        for path, data in sorted(self.client.data.items()):
            if len(path) == expected_length and path[:-1] == self.path:
                yield _Snapshot(
                    _Document(self.client, path),
                    data,
                    self.client.versions.get(path, 0),
                )


class _Batch:
    def __init__(self, client: "_Client") -> None:
        self.client = client
        self.operations: list[tuple[str, tuple[str, ...], dict[str, Any]]] = []

    def set(self, reference: _Document, data: dict[str, Any]) -> None:
        self.operations.append(("set", reference.path, copy.deepcopy(data)))

    def create(self, reference: _Document, data: dict[str, Any]) -> None:
        self.operations.append(("create", reference.path, copy.deepcopy(data)))

    def commit(self) -> None:
        self.client.commit_attempts += 1
        if self.client.fail_commit_number == self.client.commit_attempts:
            raise RuntimeError("injected batch failure")
        if self.client.before_batch_commit is not None:
            callback = self.client.before_batch_commit
            self.client.before_batch_commit = None
            callback()
        for operation, path, _ in self.operations:
            if operation == "create" and path in self.client.data:
                raise RuntimeError("document already exists")
        for _, path, data in self.operations:
            self.client._write(path, data)


class _Transaction:
    def __init__(self, client: "_Client") -> None:
        self.client = client
        self.operations: list[tuple[str, tuple[str, ...], dict[str, Any]]] = []

    def get(self, reference: _Document) -> _Snapshot:
        data = self.client.data.get(reference.path)
        revision = (
            self.client.versions.get(reference.path, 0)
            if data is not None
            else None
        )
        return _Snapshot(reference, data, revision)

    def set(self, reference: _Document, data: dict[str, Any]) -> None:
        self.operations.append(("set", reference.path, copy.deepcopy(data)))

    def create(self, reference: _Document, data: dict[str, Any]) -> None:
        self.operations.append(("create", reference.path, copy.deepcopy(data)))

    def commit(self) -> None:
        for operation, path, _ in self.operations:
            if operation == "create" and path in self.client.data:
                raise RuntimeError("document already exists")
        for _, path, data in self.operations:
            self.client._write(path, data)


class _Client:
    def __init__(self) -> None:
        self.data: dict[tuple[str, ...], dict[str, Any]] = {}
        self.commit_attempts = 0
        self.fail_commit_number: int | None = None
        self.versions: dict[tuple[str, ...], int] = {}
        self.revision = 0
        self.before_batch_commit: Any = None
        self.before_transaction: Any = None

    def _write(self, path: tuple[str, ...], data: dict[str, Any]) -> None:
        self.revision += 1
        self.data[path] = copy.deepcopy(data)
        self.versions[path] = self.revision

    def collection(self, name: str) -> _Collection:
        return _Collection(self, (name,))

    def batch(self) -> _Batch:
        return _Batch(self)

    def run_transaction(self, callback: Any) -> Any:
        if self.before_transaction is not None:
            race = self.before_transaction
            self.before_transaction = None
            race()
        transaction = _Transaction(self)
        result = callback(transaction)
        transaction.commit()
        return result


def _mini_plan() -> migration.CatalogPlan:
    entity = migration.EntityDocument(
        "subjects",
        "1",
        {"id": 1, "catalog_version": "mini"},
    )
    collections = (migration._collection_descriptor("subjects", [entity]),)
    counts = {
        "canonical_question_count": 0,
        "active_question_count": 0,
        "subject_count": 1,
        "topic_count": 0,
        "test_form_count": 0,
        "shard_count": 0,
    }
    source_bindings: tuple[dict[str, Any], ...] = ()
    root = migration.canonical_sha256(
        {
            "release_id": "mini",
            "source_bindings": source_bindings,
            "counts": counts,
            "collections": collections,
            "shards": (),
        }
    )
    release = {
        "schema_version": migration.SCHEMA_VERSION,
        "release_id": "mini",
        "catalog_version": "mini",
        "status": "ready",
        "immutable": True,
        "manifest_root_sha256": root,
        "source_bindings": [],
        "counts": counts,
        "collections": list(collections),
        "shards": [],
    }
    pointer = {
        "schema_version": migration.SCHEMA_VERSION,
        "release_id": "mini",
        "catalog_version": "mini",
        "checksum": root,
        "manifest_root_sha256": root,
        "question_count": 0,
        "active_question_count": 0,
        "subject_count": 1,
        "topic_count": 0,
        "test_form_count": 0,
        "shard_count": 0,
    }
    return migration.CatalogPlan(
        release_id="mini",
        manifest_root_sha256=root,
        source_bindings=source_bindings,
        counts=counts,
        collections=collections,
        shards=(),
        entity_documents=(entity,),
        shard_documents=(),
        release_document=release,
        pointer_document=pointer,
    )


def test_apply_is_resumable_idempotent_and_publishes_pointer_last() -> None:
    client = _Client()
    plan = _mini_plan()
    client.fail_commit_number = 2  # entity checkpoint committed; manifest fails
    with pytest.raises(RuntimeError, match="injected"):
        migration.apply_release(
            client,
            plan,
            prefix="gatepath",
            batch_size=1,
            source_preflight_sha256=SOURCE_HASH,
            source_preflight_backend="postgresql",
            expected_current_release=None,
        )
    checkpoint = client.data[("gatepath_catalog_migration_runs", "mini")]
    assert checkpoint["next_write_index"] == 1
    assert ("gatepath_catalog_meta", "current") not in client.data

    client.fail_commit_number = None
    report = migration.apply_release(
        client,
        plan,
        prefix="gatepath",
        batch_size=1,
        source_preflight_sha256=SOURCE_HASH,
        source_preflight_backend="postgresql",
        expected_current_release=None,
    )
    assert report["verified"] is True
    assert report["pointer_published"] is True
    assert client.data[("gatepath_catalog_meta", "current")] == plan.pointer_document
    assert client.data[("gatepath_catalog_migration_runs", "mini")]["status"] == "complete"
    migration.verify_release(client, plan, prefix="gatepath", require_pointer=True)


def test_immutable_create_race_fails_without_overwriting_winner() -> None:
    client = _Client()
    reference = client.collection("immutable").document("one")
    batch = client.batch()
    assert migration._safe_create_if_missing_or_equal(
        reference=reference,
        data={"owner": "migration"},
        batch=batch,
        label="immutable/one",
    )
    client.before_batch_commit = lambda: client._write(
        reference.path,
        {"owner": "concurrent-writer"},
    )

    with pytest.raises(RuntimeError, match="already exists"):
        batch.commit()

    assert client.data[reference.path] == {"owner": "concurrent-writer"}


def test_pointer_cas_blocks_a_concurrent_publisher() -> None:
    client = _Client()
    plan = _mini_plan()
    pointer_path = ("gatepath_catalog_meta", "current")
    raced_pointer = {
        "release_id": "concurrent",
        "catalog_version": "concurrent",
    }
    client.before_transaction = lambda: client._write(pointer_path, raced_pointer)

    with pytest.raises(migration.CatalogMigrationError, match="CAS blocked"):
        migration.apply_release(
            client,
            plan,
            prefix="gatepath",
            batch_size=1,
            source_preflight_sha256=SOURCE_HASH,
            source_preflight_backend="postgresql",
            expected_current_release=None,
        )

    assert client.data[pointer_path] == raced_pointer
    assert client.data[("gatepath_catalog_migration_runs", "mini")][
        "status"
    ] == "verifying"


def test_post_pointer_crash_recovers_and_reapply_is_a_noop() -> None:
    client = _Client()
    plan = _mini_plan()
    client.fail_commit_number = 3  # entities, release, then post-CAS audit
    with pytest.raises(RuntimeError, match="injected"):
        migration.apply_release(
            client,
            plan,
            prefix="gatepath",
            batch_size=1,
            source_preflight_sha256=SOURCE_HASH,
            source_preflight_backend="postgresql",
            expected_current_release=None,
        )

    pointer_path = ("gatepath_catalog_meta", "current")
    run_path = ("gatepath_catalog_migration_runs", "mini")
    assert client.data[pointer_path] == plan.pointer_document
    assert client.data[run_path]["status"] == "verifying"

    client.fail_commit_number = None
    recovered = migration.apply_release(
        client,
        plan,
        prefix="gatepath",
        batch_size=1,
        source_preflight_sha256=SOURCE_HASH,
        source_preflight_backend="postgresql",
        expected_current_release=None,
    )
    assert recovered["recovered_after_pointer_commit"] is True
    assert client.data[run_path]["status"] == "complete"

    commits_before = client.commit_attempts
    reapplied = migration.apply_release(
        client,
        plan,
        prefix="gatepath",
        batch_size=1,
        source_preflight_sha256=SOURCE_HASH,
        source_preflight_backend="postgresql",
        expected_current_release=None,
    )
    assert reapplied["recovered_after_pointer_commit"] is False
    assert client.commit_attempts == commits_before


def test_resume_blocks_pointer_aba_revision_change() -> None:
    client = _Client()
    plan = _mini_plan()
    pointer_path = ("gatepath_catalog_meta", "current")
    pointer_a = {"release_id": "release-a", "catalog_version": "release-a"}
    client._write(pointer_path, pointer_a)
    client.fail_commit_number = 2
    with pytest.raises(RuntimeError, match="injected"):
        migration.apply_release(
            client,
            plan,
            prefix="gatepath",
            batch_size=1,
            source_preflight_sha256=SOURCE_HASH,
            source_preflight_backend="postgresql",
            expected_current_release="release-a",
        )

    client._write(
        pointer_path,
        {"release_id": "release-b", "catalog_version": "release-b"},
    )
    client._write(pointer_path, pointer_a)
    client.fail_commit_number = None
    with pytest.raises(migration.CatalogMigrationError, match="revision changed"):
        migration.apply_release(
            client,
            plan,
            prefix="gatepath",
            batch_size=1,
            source_preflight_sha256=SOURCE_HASH,
            source_preflight_backend="postgresql",
            expected_current_release="release-a",
        )

    assert client.data[pointer_path] == pointer_a


def test_repointing_existing_release_requires_explicit_rollback() -> None:
    client = _Client()
    plan = _mini_plan()
    migration.apply_release(
        client,
        plan,
        prefix="gatepath",
        batch_size=1,
        source_preflight_sha256=SOURCE_HASH,
        source_preflight_backend="postgresql",
        expected_current_release=None,
    )
    pointer_path = ("gatepath_catalog_meta", "current")
    client._write(
        pointer_path,
        {"release_id": "newer", "catalog_version": "newer"},
    )

    with pytest.raises(migration.CatalogMigrationError, match="requires --rollback"):
        migration.apply_release(
            client,
            plan,
            prefix="gatepath",
            run_id="unsafe-repoint",
            source_preflight_sha256=SOURCE_HASH,
            source_preflight_backend="postgresql",
            expected_current_release="newer",
        )

    report = migration.apply_release(
        client,
        plan,
        prefix="gatepath",
        source_preflight_sha256=SOURCE_HASH,
        source_preflight_backend="postgresql",
        expected_current_release="newer",
        rollback=True,
    )
    assert report["rollback_mode"] is True
    assert report["previous_release_id"] == "newer"
    assert client.data[pointer_path] == plan.pointer_document


def test_apply_refuses_a_local_sqlite_preflight() -> None:
    with pytest.raises(migration.CatalogMigrationError, match="PostgreSQL"):
        migration.apply_release(
            _Client(),
            _mini_plan(),
            prefix="gatepath",
            source_preflight_sha256=SOURCE_HASH,
            source_preflight_backend="sqlite",
            expected_current_release=None,
        )


def test_snapshotless_sessions_are_resolved_from_alias_payloads(
    real_plan: migration.CatalogPlan,
) -> None:
    client = _Client()
    alias = next(
        item.data
        for item in real_plan.entity_documents
        if item.kind == "question_aliases"
    )
    original = next(
        item.data
        for item in real_plan.entity_documents
        if item.kind == "questions" and item.data["record_kind"] == "generated_original"
    )
    client.data[("gatepath_sessions", "old-session")] = {
        "question_ids": [alias["legacy_question_id"], original["runtime_id"]],
        "question_snapshots": [],
    }
    report = migration.verify_user_state_hydration(
        client, real_plan, prefix="gatepath"
    )
    assert report == {
        "sessions": 1,
        "question_references": 2,
        "missing_snapshot_references": 2,
        "alias_hydrations": 1,
        "canonical_hydrations": 1,
        "unresolved_references": 0,
    }
    client.data[("gatepath_sessions", "broken-session")] = {
        "question_ids": [999_999_999],
        "question_snapshots": [],
    }
    with pytest.raises(migration.CatalogMigrationError, match="unresolvable"):
        migration.verify_user_state_hydration(client, real_plan, prefix="gatepath")


def test_checked_in_manifest_matches_the_real_plan(
    real_plan: migration.CatalogPlan,
) -> None:
    manifest = json.loads(
        (DATA_DIR / "firestore_catalog_release_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest == real_plan.public_manifest()


def test_snapshot_export_refuses_reviewed_artifact_targets() -> None:
    args = migration.parse_args(
        [
            "--snapshot-from-sqlite",
            str(Path(__file__)),
            "--source-snapshot",
            str(DATA_DIR / "gate_cs_pyq_archive_1996_2025.json"),
        ]
    )
    with pytest.raises(migration.CatalogMigrationError, match="overwrite"):
        migration._guard_snapshot_output(args)


def test_manifest_export_refuses_reviewed_artifact_targets() -> None:
    args = migration.parse_args(
        [
            "--manifest-out",
            str(DATA_DIR / "gate_cs_pyq_practice_1996_2025.json"),
        ]
    )
    with pytest.raises(migration.CatalogMigrationError, match="overwrite"):
        migration._guard_manifest_output(args)


def test_remote_client_refuses_stale_emulator_without_test_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8080")
    with pytest.raises(migration.CatalogMigrationError, match="test-only"):
        migration.create_firestore_client(database_id="(default)")
