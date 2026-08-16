"""Build and safely publish the immutable question catalog to Firestore.

The default command is an offline dry run.  It joins the reviewed relational
catalog snapshot (2,695 rows) with the audited PYQ archive (2,873 rows),
deduplicates the 405 legacy PYQ rows into archive provenance, and produces one
immutable 5,163-question release.  Firestore is contacted only with
``--apply`` or ``--verify-only``.

Publication is release scoped.  Entity documents and bounded cold-load shards
are written below ``gatepath_catalog_releases/{release_id}``, verified, and
only then made visible by swapping ``gatepath_catalog_meta/current``.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import os
import re
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable, Iterator, Mapping, Sequence


BACKEND_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

SCHEMA_VERSION = "1.0"
EXPECTED_BASELINE_QUESTIONS = 2_695
EXPECTED_GENERATED_ORIGINALS = 2_290
EXPECTED_LEGACY_PYQS = 405
EXPECTED_ARCHIVE_QUESTIONS = 2_873
EXPECTED_ARCHIVE_PAPERS = 39
EXPECTED_PRACTICE_PYQS = 177
EXPECTED_CANONICAL_QUESTIONS = 5_163
EXPECTED_ACTIVE_QUESTIONS = 2_467
EXPECTED_UNIQUE_LEGACY_OVERLAPS = 391
EXPECTED_DUPLICATE_LEGACY_ALIASES = 14

MAX_BATCH_WRITES = 400
DEFAULT_BATCH_SIZE = 399  # one extra write is reserved for the checkpoint
DEFAULT_SHARD_BYTES = 600 * 1024
MAX_DOCUMENT_BYTES = 900 * 1024
JS_SAFE_INTEGER_MAX = 9_007_199_254_740_991
ARCHIVE_RUNTIME_ID_BASE = 1_000_000_000_000

COLLECTION_KINDS = (
    "subjects",
    "topics",
    "revision_notes",
    "questions",
    "question_aliases",
    "test_forms",
    "source_papers",
    "source_questions",
)
SHARD_KINDS = (
    "subjects",
    "topics",
    "revision_notes",
    "questions",
    "question_aliases",
    "test_forms",
    "question_index",
)

LEGACY_PAPER_ALIASES = {
    "CS-2018": "gate-cs-2018",
    "CS-2019": "gate-cs-2019",
    "CS1-2021": "gate-cs-2021-session-1",
    "CS2-2021": "gate-cs-2021-session-2",
    "CS-2022": "gate-cs-2022",
    "CS-2023": "gate-cs-2023",
    "CS1-2024": "gate-cs-2024-set-1",
    "GATE 2024 CS1 (Session 5)": "gate-cs-2024-set-1",
    "CS2-2024": "gate-cs-2024-set-2",
    "CS1-2025": "gate-cs-2025-set-1",
    "CS2-2025": "gate-cs-2025-set-2",
}

JSON_COLUMNS = {
    "revision_notes": {"key_points", "worked_examples"},
    "questions": {"options", "correct_answer", "tags", "assets"},
    "test_forms": {"question_ids", "question_type_counts"},
}
JSON_COLUMN_DEFAULTS: dict[tuple[str, str], Any] = {
    ("revision_notes", "key_points"): [],
    ("revision_notes", "worked_examples"): [],
    ("questions", "options"): [],
    ("questions", "correct_answer"): None,
    ("questions", "tags"): [],
    ("questions", "assets"): [],
    ("test_forms", "question_ids"): [],
    ("test_forms", "question_type_counts"): {},
}
BOOLEAN_COLUMNS = {
    "questions": {"is_active"},
    "test_forms": {"is_available"},
}

# This is the reviewed relational surface bound into the frozen legacy snapshot.
# Later catalog-only migrations (for example 0006 ``questions.assets``) are
# intentionally excluded: the migration verifies the same legacy content
# whether Neon is currently on 0005 or a later additive schema revision.
LEGACY_SOURCE_COLUMNS: dict[str, tuple[str, ...]] = {
    "subjects": (
        "id",
        "slug",
        "code",
        "name",
        "description",
        "order_index",
    ),
    "topics": (
        "id",
        "subject_id",
        "slug",
        "name",
        "description",
        "order_index",
    ),
    "revision_notes": (
        "id",
        "topic_id",
        "title",
        "summary",
        "content_md",
        "key_points",
        "worked_examples",
        "updated_at",
    ),
    "questions": (
        "id",
        "subject_id",
        "topic_id",
        "source",
        "year",
        "exam_session",
        "source_kind",
        "source_year",
        "source_paper",
        "source_question_number",
        "source_url",
        "answer_key_url",
        "question_type",
        "difficulty",
        "text",
        "options",
        "correct_answer",
        "numerical_tolerance",
        "marks",
        "explanation",
        "tags",
        "created_at",
        "external_id",
        "bank_version",
        "is_active",
        "source_page",
        "extraction_method",
        "extraction_confidence",
    ),
    "test_forms": (
        "id",
        "title",
        "description",
        "mode",
        "subject_id",
        "form_number",
        "question_ids",
        "question_count",
        "duration_seconds",
        "total_marks",
        "seed",
        "question_type_counts",
        "topic_count",
        "bank_version",
        "is_available",
        "unavailable_reason",
        "generated_at",
    ),
}


class CatalogMigrationError(RuntimeError):
    """A fail-closed catalog validation or publication error."""


_EXPECTED_CURRENT_UNSET = object()


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _replace_exact_string(value: Any, old: str, new: str) -> Any:
    if isinstance(value, dict):
        return {
            key: _replace_exact_string(item, old, new)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_replace_exact_string(item, old, new) for item in value]
    if isinstance(value, str) and value == old:
        return new
    return value


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CatalogMigrationError(f"Cannot read valid JSON artifact: {path}") from exc
    if not isinstance(value, dict):
        raise CatalogMigrationError(f"Expected a JSON object: {path}")
    return value


def _portable_path(path: Path) -> str:
    resolved = path.resolve()
    for base in (BACKEND_DIR.resolve(), ROOT_DIR.resolve()):
        try:
            return resolved.relative_to(base).as_posix()
        except ValueError:
            continue
    return path.name


def _enum_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _slug(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")


def _decode_sql_value(
    table: str,
    column: str,
    value: Any,
    *,
    json_is_decoded: bool = False,
) -> Any:
    if column in JSON_COLUMNS.get(table, set()):
        if value is None:
            if json_is_decoded:
                return None
            return copy.deepcopy(JSON_COLUMN_DEFAULTS[(table, column)])
        # asyncpg/SQLAlchemy already decodes PostgreSQL JSON/JSONB, including
        # scalar JSON strings such as ``"A"`` into the Python string ``A``.
        # Parsing that string again would either fail or silently reinterpret
        # a valid scalar. SQLite's DB-API, by contrast, returns serialized JSON
        # text and therefore needs one explicit json.loads pass.
        if json_is_decoded:
            return value
        if not isinstance(value, str):
            return value
        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError) as exc:
            raise CatalogMigrationError(
                f"Invalid JSON in {table}.{column}"
            ) from exc
    if column in BOOLEAN_COLUMNS.get(table, set()):
        return bool(value)
    return value


def _read_sqlite_table(connection: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    actual_columns = {
        str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")
    }
    if not actual_columns:
        raise CatalogMigrationError(f"Missing required SQLite table: {table}")
    columns = LEGACY_SOURCE_COLUMNS[table]
    missing = sorted(set(columns) - actual_columns)
    if missing:
        raise CatalogMigrationError(
            f"SQLite {table} is missing required legacy columns: {missing}"
        )
    rows: list[dict[str, Any]] = []
    projection = ", ".join(columns)
    for raw in connection.execute(f"SELECT {projection} FROM {table} ORDER BY id"):
        rows.append(
            {
                column: _decode_sql_value(table, column, value)
                for column, value in zip(columns, raw, strict=True)
            }
        )
    return rows


def export_sqlite_snapshot(source_path: Path) -> dict[str, Any]:
    """Return a portable snapshot of the frozen legacy catalog projection."""

    if not source_path.is_file():
        raise CatalogMigrationError(f"SQLite source does not exist: {source_path}")
    try:
        connection = sqlite3.connect(f"file:{source_path.resolve()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise CatalogMigrationError("Could not open the SQLite source read-only") from exc
    try:
        collections = {
            table: _read_sqlite_table(connection, table)
            for table in (
                "subjects",
                "topics",
                "revision_notes",
                "questions",
                "test_forms",
            )
        }
    finally:
        connection.close()

    original_count = sum(
        _enum_text(row.get("source_kind")) == "original"
        for row in collections["questions"]
    )
    pyq_count = sum(
        _enum_text(row.get("source_kind")) == "previous_year"
        for row in collections["questions"]
    )
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "snapshot_role": "legacy_relational_catalog_source",
        "database_writes_performed": False,
        "counts": {
            "subjects": len(collections["subjects"]),
            "topics": len(collections["topics"]),
            "revision_notes": len(collections["revision_notes"]),
            "questions": len(collections["questions"]),
            "generated_originals": original_count,
            "legacy_pyqs": pyq_count,
            "test_forms": len(collections["test_forms"]),
        },
        "collections": collections,
    }
    payload["canonical_sha256"] = canonical_sha256(payload)
    payload["snapshot_version"] = (
        f"gatepath-legacy-catalog-{payload['canonical_sha256'][:16]}"
    )
    return payload


def validate_snapshot(snapshot: Mapping[str, Any]) -> None:
    checksum = snapshot.get("canonical_sha256")
    unsigned = dict(snapshot)
    unsigned.pop("canonical_sha256", None)
    unsigned.pop("snapshot_version", None)
    actual = canonical_sha256(unsigned)
    if checksum != actual:
        raise CatalogMigrationError("Legacy catalog snapshot checksum mismatch")
    expected_version = f"gatepath-legacy-catalog-{actual[:16]}"
    if snapshot.get("snapshot_version") != expected_version:
        raise CatalogMigrationError("Legacy catalog snapshot version mismatch")
    counts = snapshot.get("counts") or {}
    expected = {
        "questions": EXPECTED_BASELINE_QUESTIONS,
        "generated_originals": EXPECTED_GENERATED_ORIGINALS,
        "legacy_pyqs": EXPECTED_LEGACY_PYQS,
    }
    for key, value in expected.items():
        if counts.get(key) != value:
            raise CatalogMigrationError(
                f"Legacy snapshot {key} guard failed: {counts.get(key)} != {value}"
            )
    collections = snapshot.get("collections")
    if not isinstance(collections, dict):
        raise CatalogMigrationError("Legacy snapshot collections are unavailable")
    for table in LEGACY_SOURCE_COLUMNS:
        _validated_legacy_source_columns(collections, table)


def _comparison_value(column: str, value: Any) -> Any:
    if column.endswith("_at") and value is not None:
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise CatalogMigrationError(
                    f"Invalid source timestamp in {column}"
                ) from exc
        if not isinstance(value, datetime):
            raise CatalogMigrationError(f"Invalid source timestamp type in {column}")
        if value.tzinfo is not None:
            value = value.astimezone(UTC).replace(tzinfo=None)
        return value.isoformat(timespec="microseconds")
    return value


def _comparison_collections(
    collections: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    return {
        table: [
            {
                column: _comparison_value(column, value)
                for column, value in row.items()
            }
            for row in rows
        ]
        for table, rows in collections.items()
    }


def _validated_legacy_source_columns(
    expected_collections: Mapping[str, Any],
    table: str,
) -> tuple[str, ...]:
    """Return the frozen SELECT projection, rejecting snapshot schema drift."""

    expected_columns = LEGACY_SOURCE_COLUMNS[table]
    expected_rows = expected_collections.get(table)
    if not isinstance(expected_rows, list) or not expected_rows:
        raise CatalogMigrationError(f"Snapshot table is unavailable: {table}")
    expected_set = set(expected_columns)
    for index, row in enumerate(expected_rows):
        if not isinstance(row, dict):
            raise CatalogMigrationError(
                f"Snapshot {table} row {index} is not an object"
            )
        actual_set = set(row)
        if actual_set != expected_set:
            missing = sorted(expected_set - actual_set)
            extra = sorted(actual_set - expected_set)
            raise CatalogMigrationError(
                f"Snapshot {table} legacy column set differs; "
                f"missing={missing}, extra={extra}"
            )
    return expected_columns


async def verify_configured_source_database(
    snapshot: Mapping[str, Any],
) -> tuple[str, str]:
    """Compare every source row/field with DATABASE_URL without revealing it."""

    from sqlalchemy import text

    from app.config import settings
    from app.database import engine

    if settings.database_configuration_issue is not None:
        raise CatalogMigrationError("Configured source database is unavailable")
    source_backend = (
        "postgresql"
        if settings.async_database_url.startswith("postgresql+")
        else "sqlite"
        if settings.async_database_url.startswith("sqlite+")
        else "unsupported"
    )
    if source_backend == "unsupported":
        raise CatalogMigrationError("Configured source database backend is unsupported")
    expected_collections = snapshot.get("collections") or {}
    actual_collections: dict[str, list[dict[str, Any]]] = {}
    async with engine.connect() as connection:
        for table in (
            "subjects",
            "topics",
            "revision_notes",
            "questions",
            "test_forms",
        ):
            columns = _validated_legacy_source_columns(
                expected_collections,
                table,
            )
            if not all(re.fullmatch(r"[a-z_][a-z0-9_]*", item) for item in [table, *columns]):
                raise CatalogMigrationError("Unsafe identifier in source snapshot")
            statement = text(
                f"SELECT {', '.join(columns)} FROM {table} ORDER BY id"
            )
            try:
                result = await connection.execute(statement)
            except Exception as exc:
                raise CatalogMigrationError(
                    f"Could not read configured source table: {table}"
                ) from exc
            rows: list[dict[str, Any]] = []
            for raw in result.mappings():
                rows.append(
                    {
                        column: _decode_sql_value(
                            table,
                            column,
                            raw[column],
                            json_is_decoded=(source_backend == "postgresql"),
                        )
                        for column in columns
                    }
                )
            actual_collections[table] = rows

    expected_digest = canonical_sha256(
        _comparison_collections(expected_collections)
    )
    actual_digest = canonical_sha256(_comparison_collections(actual_collections))
    if actual_digest != expected_digest:
        raise CatalogMigrationError(
            "Configured source database differs from the reviewed row-level snapshot"
        )
    return actual_digest, source_backend


def _legacy_payload(
    row: Mapping[str, Any],
    *,
    subject: Mapping[str, Any],
    topic: Mapping[str, Any],
) -> dict[str, Any]:
    """Lossless legacy CatalogQuestion payload used for recovery/hydration."""

    payload = copy.deepcopy(dict(row))
    payload.setdefault("assets", [])
    payload.update(
        {
            "id": int(row["id"]),
            "subject_code": subject["code"],
            "subject_slug": subject["slug"],
            "subject_name": subject["name"],
            "topic_slug": topic["slug"],
            "topic_name": topic["name"],
            "source": _enum_text(row.get("source")),
            "source_kind": _enum_text(row.get("source_kind")),
            "question_type": _enum_text(row.get("question_type")),
            "difficulty": _enum_text(row.get("difficulty")),
            "is_active": bool(row.get("is_active")),
        }
    )
    return payload


def _archive_runtime_id(identity: str) -> int:
    candidate = ARCHIVE_RUNTIME_ID_BASE + int(
        hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12], 16
    )
    if candidate > JS_SAFE_INTEGER_MAX:
        raise CatalogMigrationError("Archive runtime ID is not JavaScript-safe")
    return candidate


def _normalize_options(options: Any) -> list[dict[str, str]]:
    if not isinstance(options, list):
        return []
    normalized: list[dict[str, str]] = []
    for index, item in enumerate(options):
        default_id = chr(ord("A") + index) if index < 26 else str(index + 1)
        if isinstance(item, dict):
            option_id = str(item.get("id") or item.get("label") or default_id)
            text = item.get("text")
            if text is None:
                text = item.get("value")
            normalized.append({"id": option_id, "text": str(text or "")})
        else:
            normalized.append({"id": default_id, "text": str(item)})
    return normalized


@dataclass(frozen=True, slots=True)
class EntityDocument:
    kind: str
    document_id: str
    data: dict[str, Any]


@dataclass(frozen=True, slots=True)
class PointerObservation:
    data: dict[str, Any] | None
    release_id: str | None
    revision: Any
    revision_token: str | None


@dataclass(frozen=True, slots=True)
class CatalogPlan:
    release_id: str
    manifest_root_sha256: str
    source_bindings: tuple[dict[str, Any], ...]
    counts: dict[str, int]
    collections: tuple[dict[str, Any], ...]
    shards: tuple[dict[str, Any], ...]
    entity_documents: tuple[EntityDocument, ...]
    shard_documents: tuple[EntityDocument, ...]
    release_document: dict[str, Any]
    pointer_document: dict[str, Any]

    @property
    def publish_documents(self) -> tuple[EntityDocument, ...]:
        return self.entity_documents + self.shard_documents

    def public_manifest(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "migration_role": "immutable_firestore_catalog_release",
            "database_writes_performed": False,
            "production_apply_requires_release_confirmation": self.release_id,
            "release_id": self.release_id,
            "manifest_root_sha256": self.manifest_root_sha256,
            "source_bindings": list(self.source_bindings),
            "counts": self.counts,
            "collections": list(self.collections),
            "shards": list(self.shards),
            "publication_order": [
                "release-scoped entities",
                "release-scoped active catalog shards",
                "immutable release manifest",
                "exact remote verification",
                "gatepath_catalog_meta/current pointer",
            ],
        }


def _collection_descriptor(kind: str, documents: Sequence[EntityDocument]) -> dict[str, Any]:
    items = [{"id": item.document_id, "data": item.data} for item in documents]
    return {
        "kind": kind,
        "subcollection": kind,
        "count": len(items),
        "sha256": canonical_sha256(items),
    }


def _shard_document(
    *,
    release_id: str,
    kind: str,
    index: int,
    items: list[dict[str, Any]],
) -> EntityDocument:
    payload_sha256 = canonical_sha256(items)
    document_id = f"{kind}--{index:03d}"
    data = {
        "schema_version": SCHEMA_VERSION,
        "release_id": release_id,
        "catalog_version": release_id,
        "kind": kind,
        "index": index,
        "count": len(items),
        "payload_sha256": payload_sha256,
        "encoded_bytes": len(canonical_json_bytes(items)),
        "items": items,
    }
    if len(canonical_json_bytes(data)) > MAX_DOCUMENT_BYTES:
        raise CatalogMigrationError(f"Shard exceeds safe document size: {document_id}")
    return EntityDocument("shards", document_id, data)


def build_shards(
    release_id: str,
    documents_by_kind: Mapping[str, Sequence[EntityDocument]],
    *,
    max_bytes: int = DEFAULT_SHARD_BYTES,
) -> tuple[EntityDocument, ...]:
    if max_bytes <= 0 or max_bytes > MAX_DOCUMENT_BYTES:
        raise CatalogMigrationError("Shard byte limit is outside the safe range")
    shards: list[EntityDocument] = []
    wrapper_reserve = 1_024
    for kind in SHARD_KINDS:
        source = list(documents_by_kind[kind])
        if kind == "questions":
            source = [item for item in source if item.data.get("is_active") is True]
        current: list[dict[str, Any]] = []
        current_payload_bytes = 2  # JSON list brackets
        index = 0
        for document in source:
            item = copy.deepcopy(document.data)
            item_size = len(canonical_json_bytes(item))
            addition = item_size + (1 if current else 0)
            if current_payload_bytes + addition + wrapper_reserve <= max_bytes:
                current.append(item)
                current_payload_bytes += addition
                continue
            if not current:
                raise CatalogMigrationError(
                    f"One {kind} record cannot fit in a {max_bytes}-byte shard"
                )
            shards.append(
                _shard_document(
                    release_id=release_id,
                    kind=kind,
                    index=index,
                    items=current,
                )
            )
            index += 1
            current = [item]
            current_payload_bytes = 2 + item_size
            if current_payload_bytes + wrapper_reserve > max_bytes:
                raise CatalogMigrationError(
                    f"One {kind} record cannot fit in a {max_bytes}-byte shard"
                )
        if current:
            shards.append(
                _shard_document(
                    release_id=release_id,
                    kind=kind,
                    index=index,
                    items=current,
                )
            )
    return tuple(shards)


def build_catalog_plan(
    *,
    snapshot_path: Path,
    archive_path: Path,
    allowlist_path: Path,
    visibility_path: Path,
    shard_bytes: int = DEFAULT_SHARD_BYTES,
) -> CatalogPlan:
    snapshot = _load_object(snapshot_path)
    archive = _load_object(archive_path)
    allowlist = _load_object(allowlist_path)
    visibility = _load_object(visibility_path)
    validate_snapshot(snapshot)

    archive_questions = archive.get("questions")
    archive_papers = archive.get("papers")
    if not isinstance(archive_questions, list) or len(archive_questions) != EXPECTED_ARCHIVE_QUESTIONS:
        raise CatalogMigrationError("Audited archive question-count guard failed")
    if not isinstance(archive_papers, list) or len(archive_papers) != EXPECTED_ARCHIVE_PAPERS:
        raise CatalogMigrationError("Audited archive paper-count guard failed")
    allowlist_records = allowlist.get("records")
    if not isinstance(allowlist_records, list) or len(allowlist_records) != EXPECTED_PRACTICE_PYQS:
        raise CatalogMigrationError("Practice allowlist count guard failed")
    guards = visibility.get("guards") or {}
    guard_expectations = {
        "expected_question_rows": EXPECTED_BASELINE_QUESTIONS,
        "expected_pyq_rows": EXPECTED_LEGACY_PYQS,
        "expected_active_originals": EXPECTED_GENERATED_ORIGINALS,
        "expected_retirements": 228,
        "archive_record_count": EXPECTED_ARCHIVE_QUESTIONS,
        "practice_eligible_count": EXPECTED_PRACTICE_PYQS,
    }
    for key, expected in guard_expectations.items():
        if guards.get(key) != expected:
            raise CatalogMigrationError(f"Visibility-plan guard drifted: {key}")
    bindings = visibility.get("bindings") or {}
    promotion_binding = bindings.get("promotion_artifact") or {}
    allowlist_binding = bindings.get("promotion_allowlist") or {}
    if promotion_binding.get("file_sha256") != file_sha256(archive_path):
        raise CatalogMigrationError("Visibility plan does not bind this promotion artifact")
    if promotion_binding.get("artifact_version") != archive.get("artifact_version"):
        raise CatalogMigrationError("Promotion artifact version drifted")
    if promotion_binding.get("canonical_sha256") != canonical_sha256(archive):
        raise CatalogMigrationError("Promotion artifact canonical hash drifted")
    if allowlist_binding.get("file_sha256") != file_sha256(allowlist_path):
        raise CatalogMigrationError("Visibility plan does not bind this allowlist")
    if allowlist_binding.get("artifact_sha256") != allowlist.get("artifact_sha256"):
        raise CatalogMigrationError("Promotion allowlist artifact hash drifted")
    if bindings.get("selection_sha256") != allowlist.get("selection_sha256"):
        raise CatalogMigrationError("Promotion selection hash drifted")
    # Revalidate every additional lineage file named by the reviewed visibility
    # plan.  Paths are repository-local; credentials and database URLs are
    # never part of these bindings.
    for role in (
        "source_archive",
        "source_archive_report",
        "promotion_report",
        "collision_evidence",
    ):
        binding = bindings.get(role) or {}
        relative = binding.get("path")
        expected_hash = binding.get("file_sha256")
        if not isinstance(relative, str) or not isinstance(expected_hash, str):
            raise CatalogMigrationError(f"Visibility plan lacks {role} binding")
        bound_path = BACKEND_DIR / relative
        if not bound_path.is_file() or file_sha256(bound_path) != expected_hash:
            raise CatalogMigrationError(f"Visibility lineage binding drifted: {role}")

    source_bindings = (
        {
            "role": "legacy_relational_catalog_snapshot",
            "path": _portable_path(snapshot_path),
            "file_sha256": file_sha256(snapshot_path),
            "canonical_sha256": snapshot["canonical_sha256"],
        },
        {
            "role": "audited_pyq_archive_and_practice_projection",
            "path": _portable_path(archive_path),
            "file_sha256": file_sha256(archive_path),
            "artifact_version": archive.get("artifact_version"),
        },
        {
            "role": "practice_allowlist",
            "path": _portable_path(allowlist_path),
            "file_sha256": file_sha256(allowlist_path),
            "selection_sha256": allowlist.get("selection_sha256"),
        },
        {
            "role": "legacy_visibility_and_retirement_plan",
            "path": _portable_path(visibility_path),
            "file_sha256": file_sha256(visibility_path),
            "plan_version": visibility.get("plan_version"),
        },
    )
    release_seed = canonical_sha256(
        {
            "schema_version": SCHEMA_VERSION,
            "source_bindings": source_bindings,
            "expected_canonical_questions": EXPECTED_CANONICAL_QUESTIONS,
            "expected_active_questions": EXPECTED_ACTIVE_QUESTIONS,
        }
    )
    release_id = f"gatepath-catalog-{release_seed[:20]}"

    collections = snapshot.get("collections") or {}
    subjects = [copy.deepcopy(row) for row in collections.get("subjects", [])]
    topics = [copy.deepcopy(row) for row in collections.get("topics", [])]
    revision_notes = [
        copy.deepcopy(row) for row in collections.get("revision_notes", [])
    ]
    baseline_questions = [
        copy.deepcopy(row) for row in collections.get("questions", [])
    ]
    test_forms = [copy.deepcopy(row) for row in collections.get("test_forms", [])]
    baseline_count_guards = {
        "subjects": (len(subjects), 11),
        "topics": (len(topics), 64),
        "revision_notes": (len(revision_notes), 64),
        "test_forms": (len(test_forms), 125),
    }
    for label, (actual, expected) in baseline_count_guards.items():
        if actual != expected:
            raise CatalogMigrationError(
                f"Legacy snapshot {label} guard failed: {actual} != {expected}"
            )
    if len(baseline_questions) != EXPECTED_BASELINE_QUESTIONS:
        raise CatalogMigrationError("Snapshot question rows do not match its count guard")

    subject_by_id = {int(row["id"]): row for row in subjects}
    subject_by_code = {str(row["code"]): row for row in subjects}
    topic_by_id = {int(row["id"]): row for row in topics}
    topic_by_key = {
        (int(row["subject_id"]), str(row["slug"])): row for row in topics
    }
    paper_by_id = {str(row["id"]): row for row in archive_papers}
    if len(subject_by_id) != len(subjects) or len(subject_by_code) != len(subjects):
        raise CatalogMigrationError("Subject IDs/codes are not unique")
    if len(topic_by_id) != len(topics) or len(topic_by_key) != len(topics):
        raise CatalogMigrationError("Topic IDs/taxonomy keys are not unique")
    if len(paper_by_id) != EXPECTED_ARCHIVE_PAPERS:
        raise CatalogMigrationError("Archive paper IDs are not unique")
    if len({int(row["id"]) for row in revision_notes}) != len(revision_notes):
        raise CatalogMigrationError("Revision-note IDs are not unique")
    if len({str(row["id"]) for row in test_forms}) != len(test_forms):
        raise CatalogMigrationError("Test-form IDs are not unique")
    archive_by_identity = {
        (str(row["source_paper_id"]), int(row["ordinal"])): row
        for row in archive_questions
    }
    if len(archive_by_identity) != EXPECTED_ARCHIVE_QUESTIONS:
        raise CatalogMigrationError("Audited archive identities are not unique")

    keep_targets = visibility.get("keep_targets")
    if not isinstance(keep_targets, list) or len(keep_targets) != EXPECTED_PRACTICE_PYQS:
        raise CatalogMigrationError("Visibility keep-target count guard failed")
    keep_by_identity = {
        (str(row["source_paper_id"]), int(row["ordinal"])): row
        for row in keep_targets
    }
    if len(keep_by_identity) != EXPECTED_PRACTICE_PYQS:
        raise CatalogMigrationError("Visibility keep-target identity is duplicated")
    promoted_by_identity: dict[tuple[str, int], dict[str, Any]] = {}
    for row in allowlist_records:
        identity = (str(row["source_paper_id"]), int(row["ordinal"]))
        if identity in promoted_by_identity:
            raise CatalogMigrationError("Practice allowlist identity is duplicated")
        archive_row = archive_by_identity.get(identity)
        if archive_row is None:
            raise CatalogMigrationError("Practice allowlist points outside the archive")
        if str(archive_row.get("item_label")) != str(row.get("item_label")):
            raise CatalogMigrationError("Practice allowlist item label drifted")
        keep = keep_by_identity.get(identity)
        if keep is None or keep.get("source_content_sha256") != row.get(
            "source_content_sha256"
        ):
            raise CatalogMigrationError("Practice allowlist/visibility binding drifted")
        # This input is the promotion artifact: eligible rows carry the
        # promoted checksum, while both ledgers bind the staging source hash.
        if archive_row.get("content_sha256") != keep.get("promoted_content_sha256"):
            raise CatalogMigrationError("Practice allowlist promoted hash drifted")
        if archive_row.get("practice_eligible") is not True:
            raise CatalogMigrationError("Promoted archive row is not practice eligible")
        promoted_by_identity[identity] = {**row, **keep}
    archive_promoted = {
        (str(row["source_paper_id"]), int(row["ordinal"]))
        for row in archive_questions
        if row.get("practice_eligible") is True
    }
    if archive_promoted != set(promoted_by_identity):
        raise CatalogMigrationError("Archive practice flags differ from the allowlist")

    legacy_aliases_by_identity: dict[
        tuple[str, int], list[dict[str, Any]]
    ] = defaultdict(list)
    original_rows: list[dict[str, Any]] = []
    legacy_ids: set[int] = set()
    for row in baseline_questions:
        row_id = int(row["id"])
        if row_id in legacy_ids:
            raise CatalogMigrationError("Legacy question ID is duplicated")
        legacy_ids.add(row_id)
        subject = subject_by_id.get(int(row["subject_id"]))
        topic = topic_by_id.get(int(row["topic_id"]))
        if subject is None or topic is None:
            raise CatalogMigrationError(f"Legacy question {row_id} has broken taxonomy")
        payload = _legacy_payload(row, subject=subject, topic=topic)
        if _enum_text(row.get("source_kind")) == "original":
            original_rows.append(payload)
            continue
        if _enum_text(row.get("source_kind")) != "previous_year":
            raise CatalogMigrationError(f"Unsupported legacy source kind on {row_id}")
        paper_id = LEGACY_PAPER_ALIASES.get(str(row.get("source_paper")))
        question_number = row.get("source_question_number")
        if paper_id is None or not isinstance(question_number, int):
            raise CatalogMigrationError(
                f"Legacy PYQ {row_id} has no reviewed archive provenance mapping"
            )
        identity = (paper_id, question_number)
        if identity not in archive_by_identity:
            raise CatalogMigrationError(
                f"Legacy PYQ {row_id} maps outside the audited archive"
            )
        legacy_aliases_by_identity[identity].append(payload)

    if len(original_rows) != EXPECTED_GENERATED_ORIGINALS:
        raise CatalogMigrationError("Generated-original guard failed")
    legacy_alias_count = sum(len(rows) for rows in legacy_aliases_by_identity.values())
    if legacy_alias_count != EXPECTED_LEGACY_PYQS:
        raise CatalogMigrationError("Legacy-PYQ alias guard failed")
    if len(legacy_aliases_by_identity) != EXPECTED_UNIQUE_LEGACY_OVERLAPS:
        raise CatalogMigrationError("Unique legacy-PYQ overlap guard failed")
    duplicate_aliases = legacy_alias_count - len(legacy_aliases_by_identity)
    if duplicate_aliases != EXPECTED_DUPLICATE_LEGACY_ALIASES:
        raise CatalogMigrationError("Duplicate legacy-PYQ alias guard failed")

    used_runtime_ids = {int(row["id"]) for row in original_rows}
    archive_runtime_ids: dict[tuple[str, int], int] = {}
    for identity in sorted(archive_by_identity):
        # Every PYQ uses a synthetic canonical ID.  Reusing a primary legacy
        # SQL ID would make a snapshotless historical lookup ambiguous: the
        # same number could mean either old legacy content or canonical content.
        runtime_id = _archive_runtime_id(f"{identity[0]}\0{identity[1]}")
        if runtime_id in used_runtime_ids:
            raise CatalogMigrationError(
                f"Canonical runtime ID collision for {identity[0]} question {identity[1]}"
            )
        used_runtime_ids.add(runtime_id)
        archive_runtime_ids[identity] = runtime_id
    if len(used_runtime_ids) != EXPECTED_CANONICAL_QUESTIONS:
        raise CatalogMigrationError("Canonical runtime IDs are not one-to-one")

    docs_by_kind: dict[str, list[EntityDocument]] = {
        kind: [] for kind in COLLECTION_KINDS
    }
    for row in subjects:
        data = copy.deepcopy(row)
        data.update({"catalog_version": release_id, "id": int(row["id"])})
        docs_by_kind["subjects"].append(
            EntityDocument("subjects", str(row["id"]), data)
        )
    for row in topics:
        data = copy.deepcopy(row)
        subject = subject_by_id[int(row["subject_id"])]
        data.update(
            {
                "catalog_version": release_id,
                "id": int(row["id"]),
                "subject_slug": subject["slug"],
                "subject_code": subject["code"],
            }
        )
        docs_by_kind["topics"].append(EntityDocument("topics", str(row["id"]), data))
    for row in revision_notes:
        data = copy.deepcopy(row)
        data.update({"catalog_version": release_id, "id": int(row["id"])})
        docs_by_kind["revision_notes"].append(
            EntityDocument("revision_notes", str(row["id"]), data)
        )

    canonical_question_by_id: dict[int, dict[str, Any]] = {}
    for payload in original_rows:
        runtime_id = int(payload["id"])
        data = copy.deepcopy(payload)
        data.update(
            {
                "schema_version": SCHEMA_VERSION,
                "catalog_version": release_id,
                "id": runtime_id,
                "runtime_id": runtime_id,
                "canonical_runtime_id": runtime_id,
                "record_kind": "generated_original",
                "is_active": bool(payload.get("is_active", True)),
                "practice_eligible": bool(payload.get("is_active", True)),
                "legacy_question_ids": [runtime_id],
                "legacy_content_sha256": canonical_sha256(payload),
            }
        )
        canonical_question_by_id[runtime_id] = data

    alias_target_active_count = 0
    for identity in sorted(archive_by_identity):
        row = archive_by_identity[identity]
        paper = paper_by_id.get(identity[0])
        if paper is None:
            raise CatalogMigrationError(f"Archive paper is missing: {identity[0]}")
        runtime_id = archive_runtime_ids[identity]
        aliases = sorted(
            legacy_aliases_by_identity.get(identity, []), key=lambda item: int(item["id"])
        )
        is_active = identity in promoted_by_identity
        if is_active:
            alias_target_active_count += len(aliases)
        subject = subject_by_code.get(str(row.get("subject_code")))
        topic = (
            topic_by_key.get((int(subject["id"]), str(row.get("topic_slug"))))
            if subject is not None
            else None
        )
        if subject is None or topic is None:
            if is_active:
                raise CatalogMigrationError("An active PYQ lacks verified taxonomy")
            subject_id = 0
            topic_id = 0
            subject_slug = "archive-unclassified"
            subject_name = "Archive (unclassified)"
            topic_slug = "archive-unclassified"
            topic_name = "Archive (unclassified)"
        else:
            subject_id = int(subject["id"])
            topic_id = int(topic["id"])
            subject_slug = str(subject["slug"])
            subject_name = str(subject["name"])
            topic_slug = str(topic["slug"])
            topic_name = str(topic["name"])
        item_label = str(row["item_label"])
        external_id = (
            str(promoted_by_identity[identity].get("external_id"))
            if is_active
            else f"pyq:{identity[0]}:{_slug(item_label)}"
        )
        item_type = _enum_text(row.get("item_type"))
        runtime_type = item_type if item_type in {"mcq", "msq", "nat"} else "mcq"
        marks_value = row.get("marks")
        runtime_marks: int | float = (
            marks_value if isinstance(marks_value, (int, float)) else 0
        )
        if (
            isinstance(runtime_marks, float)
            and runtime_marks.is_integer()
        ):
            runtime_marks = int(runtime_marks)
        legacy_summaries = [
            {
                "legacy_question_id": int(alias["id"]),
                "legacy_external_id": alias.get("external_id"),
                "legacy_content_sha256": canonical_sha256(alias),
            }
            for alias in aliases
        ]
        data = {
            "schema_version": SCHEMA_VERSION,
            "catalog_version": release_id,
            "id": runtime_id,
            "runtime_id": runtime_id,
            "canonical_runtime_id": runtime_id,
            "external_id": external_id,
            "record_kind": "audited_pyq",
            "is_active": is_active,
            "practice_eligible": is_active,
            "subject_id": subject_id,
            "subject_slug": subject_slug,
            "subject_name": subject_name,
            "topic_id": topic_id,
            "topic_slug": topic_slug,
            "topic_name": topic_name,
            "source": "previous_year",
            "source_kind": "previous_year",
            "year": int(paper["year"]),
            "source_year": int(paper["year"]),
            "exam_session": paper.get("session_label"),
            "source_paper": paper.get("display_name") or identity[0],
            "source_paper_id": identity[0],
            "source_question_number": identity[1],
            "source_item_label": item_label,
            "source_page": row.get("source_page"),
            "source_url": paper.get("source_url"),
            "answer_key_url": paper.get("answer_key_url"),
            "question_type": runtime_type,
            "archive_item_type": item_type,
            "difficulty": "medium",
            # Archive-only values remain exact: null/empty content is not fabricated.
            "text": row.get("question_md"),
            "options": _normalize_options(row.get("options")),
            "correct_answer": row.get("accepted_answers"),
            "numerical_tolerance": 0.01,
            "marks": runtime_marks,
            "explanation": row.get("solution_md"),
            "tags": ["gate-pyq", identity[0], str(row.get("topic_slug") or "unclassified")],
            "assets": copy.deepcopy(row.get("assets") or []),
            "created_at": None,
            "bank_version": release_id,
            "legacy_question_ids": [int(alias["id"]) for alias in aliases],
            "legacy_aliases": legacy_summaries,
            "archive_content_sha256": row.get("content_sha256"),
            "archive_record": copy.deepcopy(row),
        }
        if is_active:
            if not isinstance(data["text"], str) or not data["text"].strip():
                raise CatalogMigrationError("An active PYQ has empty question text")
            if (
                runtime_type not in {"mcq", "msq", "nat"}
                or isinstance(runtime_marks, bool)
                or not isinstance(runtime_marks, int)
                or runtime_marks not in {1, 2}
            ):
                raise CatalogMigrationError("An active PYQ has invalid runtime grading fields")
        canonical_question_by_id[runtime_id] = data

        source_data = copy.deepcopy(row)
        source_data.update(
            {
                "schema_version": SCHEMA_VERSION,
                "catalog_version": release_id,
                "runtime_id": runtime_id,
                "canonical_runtime_id": runtime_id,
            }
        )
        docs_by_kind["source_questions"].append(
            EntityDocument(
                "source_questions",
                f"{identity[0]}--{identity[1]:03d}",
                source_data,
            )
        )

        for alias in aliases:
            alias_id = int(alias["id"])
            legacy_content_sha256 = canonical_sha256(alias)
            alias_data = {
                "schema_version": SCHEMA_VERSION,
                "catalog_version": release_id,
                "id": alias_id,
                "legacy_question_id": alias_id,
                "canonical_question_id": runtime_id,
                "canonical_runtime_id": runtime_id,
                "canonical_source_paper_id": identity[0],
                "canonical_ordinal": identity[1],
                "canonical_item_label": item_label,
                "canonical_is_active": is_active,
                "legacy_content_sha256": legacy_content_sha256,
                "legacy_snapshot": copy.deepcopy(alias),
                "snapshot_complete": all(
                    key in alias
                    for key in (
                        "text",
                        "options",
                        "correct_answer",
                        "explanation",
                        "question_type",
                        "marks",
                        "source_kind",
                        "subject_id",
                        "topic_id",
                    )
                ),
            }
            if alias_data["snapshot_complete"] is not True:
                raise CatalogMigrationError(f"Legacy alias {alias_id} is incomplete")
            docs_by_kind["question_aliases"].append(
                EntityDocument("question_aliases", str(alias_id), alias_data)
            )

    if len(canonical_question_by_id) != EXPECTED_CANONICAL_QUESTIONS:
        raise CatalogMigrationError("Canonical question-count guard failed")
    if len(docs_by_kind["source_questions"]) != EXPECTED_ARCHIVE_QUESTIONS:
        raise CatalogMigrationError("Source-question archive count guard failed")
    active_count = sum(
        document.get("is_active") is True
        for document in canonical_question_by_id.values()
    )
    if active_count != EXPECTED_ACTIVE_QUESTIONS:
        raise CatalogMigrationError("Active question-count guard failed")
    if len(docs_by_kind["question_aliases"]) != EXPECTED_LEGACY_PYQS:
        raise CatalogMigrationError("Alias-document count guard failed")
    inactive_alias_count = EXPECTED_LEGACY_PYQS - alias_target_active_count

    docs_by_kind["questions"] = [
        EntityDocument("questions", str(runtime_id), data)
        for runtime_id, data in sorted(canonical_question_by_id.items())
    ]

    legacy_to_canonical = {
        int(row["legacy_question_id"]): int(row["canonical_question_id"])
        for row in (document.data for document in docs_by_kind["question_aliases"])
    }
    for row in original_rows:
        legacy_to_canonical[int(row["id"])] = int(row["id"])
    if len(legacy_to_canonical) != EXPECTED_BASELINE_QUESTIONS:
        raise CatalogMigrationError("Not every legacy question ID is resolvable")

    active_ids = {
        runtime_id
        for runtime_id, data in canonical_question_by_id.items()
        if data["is_active"] is True
    }
    # Rebuild—not merely remap—the 25 full and 100 sectional forms from the
    # final 2,467-row active pool.  Remapping old forms would carry retired,
    # unverified PYQs into a supposedly verified Firestore catalog.
    from app.models import QuestionType
    from app.test_catalog import (
        CORE_COURSE_CODES,
        COURSE_TEST_COUNT,
        FULL_TEST_COUNT,
        TECHNICAL_COURSE_CODES,
        _course_form,
        _full_form,
    )

    active_proxies: list[Any] = []
    for runtime_id in sorted(active_ids):
        data = canonical_question_by_id[runtime_id]
        try:
            question_type = QuestionType(str(data["question_type"]))
        except ValueError as exc:
            raise CatalogMigrationError(
                f"Active question {runtime_id} has an invalid type"
            ) from exc
        marks = data.get("marks")
        if isinstance(marks, bool) or not isinstance(marks, (int, float)):
            raise CatalogMigrationError(
                f"Active question {runtime_id} has invalid marks"
            )
        if float(marks).is_integer():
            marks = int(marks)
        active_proxies.append(
            SimpleNamespace(
                id=runtime_id,
                external_id=data.get("external_id"),
                subject_id=int(data["subject_id"]),
                topic_id=int(data["topic_id"]),
                question_type=question_type,
                marks=marks,
            )
        )
    active_by_subject: dict[int, list[Any]] = defaultdict(list)
    for question in active_proxies:
        active_by_subject[question.subject_id].append(question)
    subject_proxies = [
        SimpleNamespace(
            id=int(row["id"]),
            code=str(row["code"]),
            name=str(row["name"]),
        )
        for row in subjects
    ]
    subject_proxy_by_code = {
        subject.code.upper(): subject for subject in subject_proxies
    }
    ga_subject = subject_proxy_by_code.get("GA")
    em_subject = subject_proxy_by_code.get("EM")
    if ga_subject is None or em_subject is None:
        raise CatalogMigrationError("GA/EM taxonomy required for full forms is missing")
    core_questions = [
        question
        for question in active_proxies
        if str(subject_by_id[question.subject_id]["code"]).upper()
        in CORE_COURSE_CODES
    ]
    definitions: list[dict[str, Any]] = [
        _full_form(
            form_number=form_number,
            ga_questions=active_by_subject[ga_subject.id],
            engineering_mathematics_questions=active_by_subject[em_subject.id],
            core_questions=core_questions,
            bank_version=release_id,
        )
        for form_number in range(1, FULL_TEST_COUNT + 1)
    ]
    technical_subjects = [
        subject
        for subject in subject_proxies
        if subject.code.upper() in TECHNICAL_COURSE_CODES
    ]
    for subject in technical_subjects:
        for form_number in range(1, COURSE_TEST_COUNT + 1):
            definitions.append(
                _course_form(
                    subject=subject,
                    questions=active_by_subject[subject.id],
                    form_number=form_number,
                    bank_version=release_id,
                )
            )
    if len(definitions) != 125:
        raise CatalogMigrationError("Rebuilt test-form count is not 125")
    baseline_form_by_id = {str(row["id"]): row for row in test_forms}
    stable_generated_at = max(
        str(row.get("generated_at") or "1970-01-01T00:00:00+00:00")
        for row in test_forms
    ).replace(" ", "T")
    for definition in definitions:
        data = copy.deepcopy(definition)
        mode = data.get("mode")
        data["mode"] = str(getattr(mode, "value", mode)).lower()
        data["catalog_version"] = release_id
        data["bank_version"] = release_id
        data["generated_at"] = stable_generated_at
        data["legacy_form_snapshot"] = copy.deepcopy(
            baseline_form_by_id.get(str(data["id"]))
        )
        if data.get("is_available") is not True or data.get("unavailable_reason") is not None:
            raise CatalogMigrationError(
                f"Rebuilt test form {data['id']} is unavailable"
            )
        selected = [canonical_question_by_id[int(item)] for item in data["question_ids"]]
        if len(selected) != len(set(data["question_ids"])):
            raise CatalogMigrationError(f"Rebuilt test form {data['id']} has duplicates")
        if any(item.get("is_active") is not True for item in selected):
            raise CatalogMigrationError(
                f"Rebuilt test form {data['id']} contains an inactive question"
            )
        if data["mode"] == "full":
            split = defaultdict(int)
            for item in selected:
                code = str(subject_by_id[int(item["subject_id"])]["code"]).upper()
                group = "ga" if code == "GA" else "em" if code == "EM" else "core"
                split[(group, int(item["marks"]))] += 1
            if dict(split) != {
                ("ga", 1): 5,
                ("ga", 2): 5,
                ("em", 1): 5,
                ("em", 2): 4,
                ("core", 1): 20,
                ("core", 2): 26,
            }:
                raise CatalogMigrationError(
                    f"Rebuilt full form {data['id']} has a non-GATE mark split"
                )
        elif data["mode"] == "sectional":
            if len(selected) != 30 or any(
                int(item["subject_id"]) != int(data["subject_id"])
                for item in selected
            ):
                raise CatalogMigrationError(
                    f"Rebuilt sectional form {data['id']} has invalid scope"
                )
            if any(data["question_type_counts"].get(kind, 0) == 0 for kind in ("mcq", "msq", "nat")):
                raise CatalogMigrationError(
                    f"Rebuilt sectional form {data['id']} lacks a question type"
                )
        docs_by_kind["test_forms"].append(
            EntityDocument("test_forms", str(data["id"]), data)
        )

    for row in archive_papers:
        data = copy.deepcopy(row)
        data.update({"schema_version": SCHEMA_VERSION, "catalog_version": release_id})
        docs_by_kind["source_papers"].append(
            EntityDocument("source_papers", str(row["id"]), data)
        )

    for kind in COLLECTION_KINDS:
        docs_by_kind[kind].sort(key=lambda item: item.document_id)
        seen: set[str] = set()
        for document in docs_by_kind[kind]:
            if document.document_id in seen or "/" in document.document_id:
                raise CatalogMigrationError(f"Invalid or duplicate {kind} document ID")
            seen.add(document.document_id)
            if len(canonical_json_bytes(document.data)) > MAX_DOCUMENT_BYTES:
                raise CatalogMigrationError(
                    f"{kind}/{document.document_id} exceeds the safe size limit"
                )

    provisional_release_id = release_id
    neutral_documents = [
        {
            "kind": kind,
            "id": document.document_id,
            "data": _replace_exact_string(
                document.data,
                provisional_release_id,
                "$CATALOG_VERSION",
            ),
        }
        for kind in COLLECTION_KINDS
        for document in docs_by_kind[kind]
    ]
    projection_sha256 = canonical_sha256(neutral_documents)
    release_identity_sha256 = canonical_sha256(
        {
            "schema_version": SCHEMA_VERSION,
            "source_bindings": source_bindings,
            "normalized_projection_sha256": projection_sha256,
        }
    )
    release_id = f"gatepath-catalog-{release_identity_sha256[:20]}"
    source_bindings = (
        *source_bindings,
        {
            "role": "normalized_catalog_projection",
            "canonical_sha256": projection_sha256,
        },
    )
    for kind in COLLECTION_KINDS:
        docs_by_kind[kind] = [
            EntityDocument(
                document.kind,
                document.document_id,
                _replace_exact_string(
                    document.data,
                    provisional_release_id,
                    release_id,
                ),
            )
            for document in docs_by_kind[kind]
        ]

    entity_documents = tuple(
        document
        for kind in COLLECTION_KINDS
        for document in docs_by_kind[kind]
    )
    collection_descriptors = tuple(
        _collection_descriptor(kind, docs_by_kind[kind]) for kind in COLLECTION_KINDS
    )
    shard_sources: dict[str, Sequence[EntityDocument]] = dict(docs_by_kind)
    shard_sources["question_index"] = [
        EntityDocument(
            "question_index",
            str(runtime_id),
            {
                "id": runtime_id,
                "runtime_id": runtime_id,
                "is_active": data["is_active"],
            },
        )
        for runtime_id, data in sorted(canonical_question_by_id.items())
    ]
    shard_documents = build_shards(
        release_id, shard_sources, max_bytes=shard_bytes
    )
    shard_descriptors = tuple(
        {
            "kind": document.data["kind"],
            "index": document.data["index"],
            "count": document.data["count"],
            "payload_sha256": document.data["payload_sha256"],
            "encoded_bytes": document.data["encoded_bytes"],
        }
        for document in shard_documents
    )
    counts = {
        "canonical_question_count": EXPECTED_CANONICAL_QUESTIONS,
        "question_count": EXPECTED_CANONICAL_QUESTIONS,
        "active_question_count": active_count,
        "generated_original_count": EXPECTED_GENERATED_ORIGINALS,
        "audited_pyq_count": EXPECTED_ARCHIVE_QUESTIONS,
        "practice_pyq_count": EXPECTED_PRACTICE_PYQS,
        "archive_only_pyq_count": EXPECTED_ARCHIVE_QUESTIONS - EXPECTED_PRACTICE_PYQS,
        "legacy_question_count": EXPECTED_BASELINE_QUESTIONS,
        "legacy_pyq_alias_count": EXPECTED_LEGACY_PYQS,
        "legacy_pyq_canonical_overlap_count": EXPECTED_UNIQUE_LEGACY_OVERLAPS,
        "legacy_duplicate_alias_count": EXPECTED_DUPLICATE_LEGACY_ALIASES,
        "active_target_alias_count": alias_target_active_count,
        "inactive_target_alias_count": inactive_alias_count,
        "subject_count": len(subjects),
        "topic_count": len(topics),
        "revision_note_count": len(revision_notes),
        "test_form_count": len(test_forms),
        "source_paper_count": len(archive_papers),
        "source_question_count": len(docs_by_kind["source_questions"]),
        "question_index_count": EXPECTED_CANONICAL_QUESTIONS,
        "shard_count": len(shard_documents),
        "direct_entity_document_count": len(entity_documents),
    }
    root_payload = {
        "release_id": release_id,
        "source_bindings": source_bindings,
        "counts": counts,
        "collections": collection_descriptors,
        "shards": shard_descriptors,
    }
    manifest_root_sha256 = canonical_sha256(root_payload)
    release_document = {
        "schema_version": SCHEMA_VERSION,
        "release_id": release_id,
        "catalog_version": release_id,
        "status": "ready",
        "immutable": True,
        "manifest_root_sha256": manifest_root_sha256,
        "source_bindings": list(source_bindings),
        "counts": counts,
        "collections": list(collection_descriptors),
        "shards": list(shard_descriptors),
    }
    pointer_document = {
        "schema_version": SCHEMA_VERSION,
        "release_id": release_id,
        "catalog_version": release_id,
        "checksum": manifest_root_sha256,
        "manifest_root_sha256": manifest_root_sha256,
        "question_count": EXPECTED_CANONICAL_QUESTIONS,
        "active_question_count": active_count,
        "subject_count": len(subjects),
        "topic_count": len(topics),
        "test_form_count": len(test_forms),
        "shard_count": len(shard_documents),
    }
    return CatalogPlan(
        release_id=release_id,
        manifest_root_sha256=manifest_root_sha256,
        source_bindings=source_bindings,
        counts=counts,
        collections=collection_descriptors,
        shards=shard_descriptors,
        entity_documents=entity_documents,
        shard_documents=shard_documents,
        release_document=release_document,
        pointer_document=pointer_document,
    )


def _snapshot_data(snapshot: Any) -> dict[str, Any] | None:
    if snapshot is None or not getattr(snapshot, "exists", False):
        return None
    value = snapshot.to_dict()
    return dict(value) if isinstance(value, dict) else None


def _release_reference(client: Any, prefix: str, release_id: str) -> Any:
    return client.collection(f"{prefix}_catalog_releases").document(release_id)


def _entity_reference(
    client: Any,
    prefix: str,
    release_id: str,
    document: EntityDocument,
) -> Any:
    return (
        _release_reference(client, prefix, release_id)
        .collection(document.kind)
        .document(document.document_id)
    )


def _safe_create_if_missing_or_equal(
    *,
    reference: Any,
    data: Mapping[str, Any],
    batch: Any,
    label: str,
) -> bool:
    existing = _snapshot_data(reference.get())
    if existing is not None:
        if canonical_json_bytes(existing) != canonical_json_bytes(data):
            raise CatalogMigrationError(
                f"Immutable Firestore document conflicts with this release: {label}"
            )
        return False
    # Firestore create carries an exists=false precondition. If another
    # publisher wins the race after the read, commit fails instead of
    # overwriting an immutable release document.
    batch.create(reference, copy.deepcopy(dict(data)))
    return True


def _pointer_revision_token(revision: Any) -> str | None:
    if revision is None:
        return None
    isoformat = getattr(revision, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())
    return str(revision)


def _observe_pointer(reference: Any) -> PointerObservation:
    snapshot = reference.get()
    data = _snapshot_data(snapshot)
    revision = getattr(snapshot, "update_time", None)
    if data is None:
        return PointerObservation(None, None, revision, _pointer_revision_token(revision))
    release_id = data.get("release_id")
    if not isinstance(release_id, str) or not release_id.strip():
        raise CatalogMigrationError("Current catalog pointer has no valid release ID")
    if revision is None:
        raise CatalogMigrationError("Current catalog pointer has no CAS revision")
    return PointerObservation(
        data,
        release_id,
        revision,
        _pointer_revision_token(revision),
    )


def _validate_expected_current_release(value: Any) -> str | None:
    if value is _EXPECTED_CURRENT_UNSET:
        raise CatalogMigrationError("An explicit expected current release is required")
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or not value.strip()
        or "/" in value
        or len(value.encode("utf-8")) > 512
    ):
        raise CatalogMigrationError("Expected current release ID is invalid")
    return value


def _run_transaction(client: Any, callback: Any) -> Any:
    # The small in-memory test client exposes this hook. Production clients use
    # the official retrying transaction decorator, which reruns the callback
    # when a write races the transaction after its read.
    runner = getattr(client, "run_transaction", None)
    if callable(runner):
        return runner(callback)
    from google.cloud.firestore_v1 import transactional

    return transactional(callback)(client.transaction())


def _publish_pointer_cas(
    client: Any,
    reference: Any,
    data: Mapping[str, Any],
    observation: PointerObservation,
) -> bool:
    target = copy.deepcopy(dict(data))

    def swap(transaction: Any) -> bool:
        latest_snapshot = reference.get(transaction=transaction)
        latest_data = _snapshot_data(latest_snapshot)
        latest_revision = getattr(latest_snapshot, "update_time", None)
        if (
            canonical_json_bytes(latest_data) != canonical_json_bytes(observation.data)
            or latest_revision != observation.revision
        ):
            raise CatalogMigrationError(
                "Current catalog pointer changed during publication; CAS blocked"
            )
        if latest_data == target:
            return False
        if latest_data is None:
            transaction.create(reference, target)
        else:
            transaction.set(reference, target)
        return True

    return bool(_run_transaction(client, swap))


def _stream_collection(reference: Any) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for snapshot in reference.stream():
        document_id = str(snapshot.id)
        if document_id in rows:
            raise CatalogMigrationError("Firestore returned a duplicate document ID")
        data = snapshot.to_dict()
        if not isinstance(data, dict):
            raise CatalogMigrationError("Firestore returned a non-object document")
        rows[document_id] = data
    return rows


def verify_release(
    client: Any,
    plan: CatalogPlan,
    *,
    prefix: str,
    require_pointer: bool,
) -> dict[str, Any]:
    release_ref = _release_reference(client, prefix, plan.release_id)
    release_data = _snapshot_data(release_ref.get())
    if release_data != plan.release_document:
        raise CatalogMigrationError("Remote immutable release manifest differs")

    expected_by_kind: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for document in plan.publish_documents:
        expected_by_kind[document.kind][document.document_id] = document.data
    verified_count = 0
    for kind, expected in expected_by_kind.items():
        actual = _stream_collection(release_ref.collection(kind))
        if set(actual) != set(expected):
            missing = sorted(set(expected) - set(actual))[:5]
            extra = sorted(set(actual) - set(expected))[:5]
            raise CatalogMigrationError(
                f"Remote {kind} ID set differs; missing={missing}, extra={extra}"
            )
        if canonical_sha256(
            [{"id": key, "data": actual[key]} for key in sorted(actual)]
        ) != canonical_sha256(
            [{"id": key, "data": expected[key]} for key in sorted(expected)]
        ):
            raise CatalogMigrationError(f"Remote {kind} content hash differs")
        verified_count += len(actual)

    if require_pointer:
        pointer = _snapshot_data(
            client.collection(f"{prefix}_catalog_meta").document("current").get()
        )
        if pointer != plan.pointer_document:
            raise CatalogMigrationError("Current catalog pointer differs")
    return {
        "release_id": plan.release_id,
        "manifest_root_sha256": plan.manifest_root_sha256,
        "verified_release_documents": verified_count,
        "pointer_verified": require_pointer,
    }


def verify_user_state_hydration(
    client: Any,
    plan: CatalogPlan,
    *,
    prefix: str,
) -> dict[str, int]:
    """Prove old session IDs can be hydrated without the relational catalog."""

    canonical_ids = {
        int(document.data["runtime_id"])
        for document in plan.entity_documents
        if document.kind == "questions"
    }
    aliases = {
        int(document.data["legacy_question_id"]): document.data
        for document in plan.entity_documents
        if document.kind == "question_aliases"
    }
    sessions = 0
    references = 0
    missing_snapshot_references = 0
    alias_hydrations = 0
    canonical_hydrations = 0
    unresolved: list[tuple[str, int]] = []
    session_collection = client.collection(f"{prefix}_sessions")
    for snapshot in session_collection.stream():
        sessions += 1
        data = snapshot.to_dict() or {}
        question_ids = [int(item) for item in (data.get("question_ids") or [])]
        snapshots = data.get("question_snapshots") or []
        snapshot_ids = {
            int(item["id"])
            for item in snapshots
            if isinstance(item, dict) and isinstance(item.get("id"), int)
        }
        references += len(question_ids)
        for question_id in question_ids:
            if question_id in snapshot_ids:
                continue
            missing_snapshot_references += 1
            alias = aliases.get(question_id)
            if alias is not None and alias.get("snapshot_complete") is True:
                alias_hydrations += 1
            elif question_id in canonical_ids:
                canonical_hydrations += 1
            else:
                unresolved.append((str(snapshot.id), question_id))
    if unresolved:
        raise CatalogMigrationError(
            "Snapshotless Firestore sessions contain unresolvable legacy question IDs: "
            + repr(unresolved[:10])
        )
    return {
        "sessions": sessions,
        "question_references": references,
        "missing_snapshot_references": missing_snapshot_references,
        "alias_hydrations": alias_hydrations,
        "canonical_hydrations": canonical_hydrations,
        "unresolved_references": 0,
    }


def _chunks(values: Sequence[Any], size: int) -> Iterator[tuple[int, Sequence[Any]]]:
    for start in range(0, len(values), size):
        yield start, values[start : start + size]


def apply_release(
    client: Any,
    plan: CatalogPlan,
    *,
    prefix: str,
    batch_size: int = DEFAULT_BATCH_SIZE,
    run_id: str | None = None,
    source_preflight_sha256: str | None = None,
    source_preflight_backend: str | None = None,
    expected_current_release: Any = _EXPECTED_CURRENT_UNSET,
    rollback: bool = False,
) -> dict[str, Any]:
    if batch_size < 1 or batch_size >= MAX_BATCH_WRITES:
        raise CatalogMigrationError("Batch size must be between 1 and 399")
    if not isinstance(source_preflight_sha256, str) or not re.fullmatch(
        r"[0-9a-f]{64}", source_preflight_sha256
    ):
        raise CatalogMigrationError("A verified live-source row hash is required")
    if source_preflight_backend != "postgresql":
        raise CatalogMigrationError(
            "Production publication requires a row-verified PostgreSQL source"
        )
    expected_current = _validate_expected_current_release(
        expected_current_release
    )
    pointer_ref = client.collection(f"{prefix}_catalog_meta").document("current")
    pointer_observation = _observe_pointer(pointer_ref)
    if run_id is None and rollback:
        expected_label = expected_current or "none"
        suffix = hashlib.sha256(expected_label.encode("utf-8")).hexdigest()[:12]
        run_id = f"rollback-{plan.release_id}-{suffix}"
    run_id = run_id or plan.release_id
    if not run_id or "/" in run_id or len(run_id.encode("utf-8")) > 512:
        raise CatalogMigrationError("Migration run ID is invalid")
    run_ref = client.collection(f"{prefix}_catalog_migration_runs").document(run_id)
    existing_run = _snapshot_data(run_ref.get())
    next_index = 0
    created = 0
    matched = 0
    batches = 0
    if existing_run is not None:
        if (
            existing_run.get("release_id") != plan.release_id
            or existing_run.get("manifest_root_sha256") != plan.manifest_root_sha256
        ):
            raise CatalogMigrationError("Migration run ID belongs to another release")
        if (
            existing_run.get("source_preflight_sha256")
            not in {None, source_preflight_sha256}
            or existing_run.get("source_preflight_backend")
            not in {None, source_preflight_backend}
        ):
            raise CatalogMigrationError("Migration run source preflight differs")
        if (
            existing_run.get("expected_current_release", _EXPECTED_CURRENT_UNSET)
            != expected_current
            or existing_run.get("rollback_mode", _EXPECTED_CURRENT_UNSET)
            is not rollback
        ):
            raise CatalogMigrationError(
                "Migration run pointer precondition or mode differs"
            )
        next_index = int(existing_run.get("next_write_index", 0))
        created = int(existing_run.get("created_count", 0))
        matched = int(existing_run.get("matching_count", 0))
        batches = int(existing_run.get("committed_batch_count", 0))

    # A process can stop after the pointer transaction commits but before the
    # separate audit write. An exact target pointer plus the matching verifying
    # run is the only case where the original expected-current value may differ
    # from the pointer observed by the retry.
    recovering_published_run = bool(
        existing_run is not None
        and existing_run.get("status") in {"verifying", "complete"}
        and pointer_observation.data == plan.pointer_document
    )
    if not recovering_published_run:
        if pointer_observation.release_id != expected_current:
            raise CatalogMigrationError(
                "Current catalog release differs from --expected-current-release"
            )
        if (
            pointer_observation.release_id == plan.release_id
            and pointer_observation.data != plan.pointer_document
        ):
            raise CatalogMigrationError(
                "Current pointer names this release but its verified metadata differs"
            )
        if existing_run is not None and (
            "observed_pointer_revision" not in existing_run
            or existing_run.get("observed_pointer_revision")
            != pointer_observation.revision_token
        ):
            raise CatalogMigrationError(
                "Current catalog pointer revision changed since this run began"
            )

    documents = list(plan.publish_documents)
    release_ref = _release_reference(client, prefix, plan.release_id)
    release_before_apply = _snapshot_data(release_ref.get())
    if (
        release_before_apply is not None
        and canonical_json_bytes(release_before_apply)
        != canonical_json_bytes(plan.release_document)
    ):
        raise CatalogMigrationError("Existing immutable release manifest conflicts")

    if recovering_published_run:
        verification = verify_release(
            client, plan, prefix=prefix, require_pointer=True
        )
        hydration = verify_user_state_hydration(client, plan, prefix=prefix)
        was_incomplete = existing_run.get("status") == "verifying"
        if was_incomplete:
            batch = client.batch()
            batch.set(
                run_ref,
                {
                    **copy.deepcopy(existing_run),
                    "status": "complete",
                    "verified_release_document_count": verification[
                        "verified_release_documents"
                    ],
                    "hydration_audit": hydration,
                    "previous_release_id": expected_current,
                    "pointer_transaction_committed": True,
                    "pointer_changed": True,
                    "recovered_after_pointer_commit": True,
                    "committed_batch_count": batches + 1,
                },
            )
            batch.commit()
            batches += 1
        return {
            "release_id": plan.release_id,
            "created_count": created,
            "matching_count": matched,
            "batch_count": batches,
            "verified": True,
            "pointer_published": True,
            "pointer_changed": False,
            "previous_release_id": expected_current,
            "rollback_mode": rollback,
            "recovered_after_pointer_commit": was_incomplete,
            "user_state_hydration": hydration,
        }

    target_is_current = pointer_observation.release_id == plan.release_id
    resumable_forward_run = (
        existing_run is not None
        and existing_run.get("status") in {"applying", "verifying"}
        and existing_run.get("rollback_mode") is False
    )
    if rollback:
        if target_is_current:
            raise CatalogMigrationError(
                "Rollback target is already the current catalog release"
            )
        if release_before_apply is None:
            raise CatalogMigrationError(
                "Rollback requires an existing verified immutable release"
            )
    elif (
        release_before_apply is not None
        and not target_is_current
        and not resumable_forward_run
    ):
        raise CatalogMigrationError(
            "Selecting an already-published non-current release requires --rollback"
        )

    if next_index < 0 or next_index > len(documents):
        raise CatalogMigrationError("Migration checkpoint is outside the release")
    release_created = False
    if not rollback:
        for start, chunk in _chunks(documents[next_index:], batch_size):
            absolute_start = next_index + start
            batch = client.batch()
            for document in chunk:
                wrote = _safe_create_if_missing_or_equal(
                    reference=_entity_reference(
                        client, prefix, plan.release_id, document
                    ),
                    data=document.data,
                    batch=batch,
                    label=f"{document.kind}/{document.document_id}",
                )
                created += int(wrote)
                matched += int(not wrote)
            checkpoint = absolute_start + len(chunk)
            batch.set(
                run_ref,
                {
                    "schema_version": SCHEMA_VERSION,
                    "run_id": run_id,
                    "release_id": plan.release_id,
                    "manifest_root_sha256": plan.manifest_root_sha256,
                    "status": "applying",
                    "next_write_index": checkpoint,
                    "planned_document_count": len(documents),
                    "created_count": created,
                    "matching_count": matched,
                    "committed_batch_count": batches + 1,
                    "database_writes_performed": True,
                    "source_preflight_sha256": source_preflight_sha256,
                    "source_preflight_backend": source_preflight_backend,
                    "expected_current_release": expected_current,
                    "observed_pointer_revision": pointer_observation.revision_token,
                    "rollback_mode": False,
                },
            )
            batch.commit()
            batches += 1

        batch = client.batch()
        release_created = _safe_create_if_missing_or_equal(
            reference=release_ref,
            data=plan.release_document,
            batch=batch,
            label=f"catalog_releases/{plan.release_id}",
        )
        batch.set(
            run_ref,
            {
                "schema_version": SCHEMA_VERSION,
                "run_id": run_id,
                "release_id": plan.release_id,
                "manifest_root_sha256": plan.manifest_root_sha256,
                "status": "verifying",
                "next_write_index": len(documents),
                "planned_document_count": len(documents),
                "created_count": created + int(release_created),
                "matching_count": matched + int(not release_created),
                "committed_batch_count": batches + 1,
                "database_writes_performed": True,
                "source_preflight_sha256": source_preflight_sha256,
                "source_preflight_backend": source_preflight_backend,
                "expected_current_release": expected_current,
                "observed_pointer_revision": pointer_observation.revision_token,
                "rollback_mode": False,
            },
        )
        batch.commit()
        batches += 1

    verification = verify_release(
        client, plan, prefix=prefix, require_pointer=False
    )
    hydration = verify_user_state_hydration(client, plan, prefix=prefix)

    if rollback:
        matched = max(matched, len(documents) + 1)
        batch = client.batch()
        batch.set(
            run_ref,
            {
                "schema_version": SCHEMA_VERSION,
                "run_id": run_id,
                "release_id": plan.release_id,
                "manifest_root_sha256": plan.manifest_root_sha256,
                "status": "verifying",
                "next_write_index": len(documents),
                "planned_document_count": len(documents),
                "created_count": 0,
                "matching_count": matched,
                "committed_batch_count": batches + 1,
                "database_writes_performed": True,
                "source_preflight_sha256": source_preflight_sha256,
                "source_preflight_backend": source_preflight_backend,
                "expected_current_release": expected_current,
                "observed_pointer_revision": pointer_observation.revision_token,
                "rollback_mode": True,
            },
        )
        batch.commit()
        batches += 1

    # The one mutable control pointer is published only after exact remote
    # verification. The transaction compares both the data and the Firestore
    # revision observed before any writes, preventing stale delayed publishers
    # (and existing-pointer ABA changes) from reverting a newer release. A
    # missing pointer has no Firestore tombstone revision, so operators must
    # never delete it; its nonexistence is protected transactionally within the
    # initial publication attempt.
    pointer_changed = _publish_pointer_cas(
        client,
        pointer_ref,
        plan.pointer_document,
        pointer_observation,
    )

    # This audit write occurs after the pointer transaction. It is not part of
    # the catalog read path and cannot make a partial release visible.
    batch = client.batch()
    batch.set(
        run_ref,
        {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "release_id": plan.release_id,
            "manifest_root_sha256": plan.manifest_root_sha256,
            "status": "complete",
            "next_write_index": len(documents),
            "planned_document_count": len(documents),
            "created_count": created + int(release_created),
            "matching_count": matched + int(not release_created),
            "committed_batch_count": batches + 1,
            "verified_release_document_count": verification[
                "verified_release_documents"
            ],
            "hydration_audit": hydration,
            "database_writes_performed": True,
            "source_preflight_sha256": source_preflight_sha256,
            "source_preflight_backend": source_preflight_backend,
            "expected_current_release": expected_current,
            "previous_release_id": pointer_observation.release_id,
            "observed_pointer_revision": pointer_observation.revision_token,
            "rollback_mode": rollback,
            "pointer_transaction_committed": True,
            "pointer_changed": pointer_changed,
        },
    )
    batch.commit()
    batches += 1
    verify_release(client, plan, prefix=prefix, require_pointer=True)
    return {
        "release_id": plan.release_id,
        "created_count": created + int(release_created),
        "matching_count": matched + int(not release_created),
        "batch_count": batches,
        "verified": True,
        "pointer_published": True,
        "pointer_changed": pointer_changed,
        "previous_release_id": pointer_observation.release_id,
        "rollback_mode": rollback,
        "user_state_hydration": hydration,
    }


def firestore_target_summary(*, database_id: str, prefix: str) -> dict[str, Any]:
    from app.config import settings

    emulator = bool(os.environ.get("FIRESTORE_EMULATOR_HOST", "").strip())
    project_id = settings.firebase_project_id.strip()
    if emulator and not project_id:
        project_id = "gatepath-local"
    confirmation = (
        f"{project_id}|{database_id}|{prefix}" if project_id else None
    )
    return {
        "project_id": project_id or None,
        "database_id": database_id,
        "collection_prefix": prefix,
        "emulator": emulator,
        "confirmation": confirmation,
    }


def create_firestore_client(*, database_id: str, allow_emulator: bool = False) -> Any:
    """Create an Admin client without printing credentials or project URLs."""

    emulator = bool(os.environ.get("FIRESTORE_EMULATOR_HOST", "").strip())
    if emulator and not allow_emulator:
        raise CatalogMigrationError(
            "Remote catalog modes refuse FIRESTORE_EMULATOR_HOST unless the "
            "explicit test-only override is supplied"
        )
    from app import firebase_auth
    from app.config import settings

    if emulator:
        from google.auth.credentials import AnonymousCredentials
        from google.cloud import firestore

        return firestore.Client(
            project=settings.firebase_project_id.strip() or "gatepath-local",
            database=database_id,
            credentials=AnonymousCredentials(),
        )
    from firebase_admin import firestore

    return firestore.client(
        app=firebase_auth.get_firebase_admin_app(),
        database_id=database_id,
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-snapshot",
        type=Path,
        default=BACKEND_DIR / "data" / "firestore_legacy_catalog_snapshot.json",
    )
    parser.add_argument(
        "--archive",
        type=Path,
        default=BACKEND_DIR / "data" / "gate_cs_pyq_practice_1996_2025.json",
    )
    parser.add_argument(
        "--allowlist",
        type=Path,
        default=(
            BACKEND_DIR
            / "data"
            / "gate_cs_pyq_practice_1996_2025.allowlist.json"
        ),
    )
    parser.add_argument(
        "--visibility-plan",
        type=Path,
        default=BACKEND_DIR / "data" / "pyq_legacy_collision_cleanup_plan.json",
    )
    parser.add_argument("--manifest-out", type=Path)
    parser.add_argument(
        "--expected-manifest",
        type=Path,
        default=BACKEND_DIR / "data" / "firestore_catalog_release_manifest.json",
        help="Frozen dry-run manifest required by remote modes",
    )
    parser.add_argument(
        "--snapshot-from-sqlite",
        type=Path,
        help="Export a read-only SQLite catalog snapshot and exit",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--verify-only", action="store_true")
    parser.add_argument(
        "--confirm-release",
        help="Required with --apply; must exactly equal the dry-run release ID",
    )
    parser.add_argument(
        "--expected-current-release",
        help=(
            "Required with --apply; current pointer release ID, or 'none' when "
            "no catalog has been published"
        ),
    )
    parser.add_argument(
        "--rollback",
        action="store_true",
        help="Explicitly repoint to an already-published verified release",
    )
    parser.add_argument("--collection-prefix", default="gatepath")
    parser.add_argument("--database-id", default="(default)")
    parser.add_argument(
        "--confirm-firestore-target",
        help=(
            "Required with --apply; exact project|database|prefix shown by dry-run"
        ),
    )
    parser.add_argument(
        "--allow-firestore-emulator",
        action="store_true",
        help="Test-only override for remote modes when FIRESTORE_EMULATOR_HOST is set",
    )
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--shard-bytes", type=int, default=DEFAULT_SHARD_BYTES)
    parser.add_argument("--run-id")
    parser.add_argument(
        "--verify-source-database",
        action="store_true",
        help="Read DATABASE_URL and require exact row-level equality with the snapshot",
    )
    return parser.parse_args(argv)


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _guard_snapshot_output(args: argparse.Namespace) -> None:
    output = args.source_snapshot.resolve()
    protected = {
        args.snapshot_from_sqlite.resolve(),
        args.archive.resolve(),
        args.allowlist.resolve(),
        args.visibility_plan.resolve(),
    }
    data_dir = BACKEND_DIR / "data"
    for pattern in ("gate_cs_pyq_*", "pyq_*"):
        protected.update(path.resolve() for path in data_dir.glob(pattern))
    if output in protected:
        raise CatalogMigrationError(
            "Snapshot output would overwrite a source database or reviewed PYQ artifact"
        )
    if output.parent == data_dir.resolve() and not output.name.startswith(
        "firestore_legacy_catalog_snapshot"
    ):
        raise CatalogMigrationError(
            "Catalog data-directory snapshots must use the dedicated "
            "firestore_legacy_catalog_snapshot*.json name"
        )


def _guard_manifest_output(args: argparse.Namespace) -> None:
    if args.manifest_out is None:
        return
    output = args.manifest_out.resolve()
    protected = {
        args.source_snapshot.resolve(),
        args.archive.resolve(),
        args.allowlist.resolve(),
        args.visibility_plan.resolve(),
    }
    data_dir = BACKEND_DIR / "data"
    for pattern in ("gate_cs_pyq_*", "pyq_*"):
        protected.update(path.resolve() for path in data_dir.glob(pattern))
    if output in protected:
        raise CatalogMigrationError(
            "Manifest output would overwrite a catalog source or reviewed PYQ artifact"
        )
    if output.parent == data_dir.resolve() and not output.name.startswith(
        "firestore_catalog_release_manifest"
    ):
        raise CatalogMigrationError(
            "Catalog data-directory manifests must use the dedicated "
            "firestore_catalog_release_manifest*.json name"
        )


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.snapshot_from_sqlite is not None:
        if args.apply or args.verify_only:
            raise CatalogMigrationError(
                "Snapshot export cannot be combined with Firestore modes"
            )
        _guard_snapshot_output(args)
        snapshot = export_sqlite_snapshot(args.snapshot_from_sqlite)
        _write_json(args.source_snapshot, snapshot)
        print(
            json.dumps(
                {
                    "mode": "snapshot-export",
                    "database_writes_performed": False,
                    "output": _portable_path(args.source_snapshot),
                    "snapshot_version": snapshot["snapshot_version"],
                    "counts": snapshot["counts"],
                },
                indent=2,
            )
        )
        return 0

    plan = build_catalog_plan(
        snapshot_path=args.source_snapshot,
        archive_path=args.archive,
        allowlist_path=args.allowlist,
        visibility_path=args.visibility_plan,
        shard_bytes=args.shard_bytes,
    )
    if args.apply and args.confirm_release != plan.release_id:
        raise CatalogMigrationError(
            "--apply requires --confirm-release with the exact dry-run release ID"
        )
    if args.apply and args.expected_current_release is None:
        raise CatalogMigrationError(
            "--apply requires --expected-current-release (use 'none' if absent)"
        )
    if args.rollback and not args.apply:
        raise CatalogMigrationError("--rollback can only be used with --apply")
    if args.allow_firestore_emulator and not (args.apply or args.verify_only):
        raise CatalogMigrationError(
            "--allow-firestore-emulator is only valid with a remote mode"
        )
    if (args.apply or args.verify_only) and args.manifest_out is not None:
        raise CatalogMigrationError(
            "Remote modes cannot rewrite the frozen dry-run manifest"
        )
    if args.apply or args.verify_only:
        expected_manifest = _load_object(args.expected_manifest)
        if expected_manifest != plan.public_manifest():
            raise CatalogMigrationError(
                "Frozen Firestore catalog manifest differs from the rebuilt plan"
            )
    if args.manifest_out is not None:
        _guard_manifest_output(args)
        _write_json(args.manifest_out, plan.public_manifest())

    target = firestore_target_summary(
        database_id=args.database_id,
        prefix=args.collection_prefix,
    )
    if (
        (args.apply or args.verify_only)
        and target["emulator"]
        and not args.allow_firestore_emulator
    ):
        raise CatalogMigrationError(
            "Remote catalog modes refuse FIRESTORE_EMULATOR_HOST unless "
            "--allow-firestore-emulator is explicitly supplied for testing"
        )
    if args.apply:
        if target["confirmation"] is None:
            raise CatalogMigrationError(
                "--apply requires a configured Firebase project ID"
            )
        if args.confirm_firestore_target != target["confirmation"]:
            raise CatalogMigrationError(
                "--apply requires --confirm-firestore-target with the exact "
                "project|database|prefix shown by dry-run"
            )

    source_preflight_sha256: str | None = None
    source_preflight_backend: str | None = None
    if args.verify_source_database or args.apply:
        source_preflight_sha256, source_preflight_backend = asyncio.run(
            verify_configured_source_database(
                _load_object(args.source_snapshot)
            )
        )
        if args.apply and source_preflight_backend != "postgresql":
            raise CatalogMigrationError(
                "--apply requires DATABASE_URL to point to the row-verified "
                "PostgreSQL/Neon source; local SQLite verification is review-only"
            )

    if not args.apply and not args.verify_only:
        print(
            json.dumps(
                {
                    "mode": "dry-run",
                    "database_writes_performed": False,
                    "release_id": plan.release_id,
                    "manifest_root_sha256": plan.manifest_root_sha256,
                    "counts": plan.counts,
                    "source_database_verified": source_preflight_sha256 is not None,
                    "source_preflight_sha256": source_preflight_sha256,
                    "source_preflight_backend": source_preflight_backend,
                    "firestore_target": target,
                },
                indent=2,
            )
        )
        return 0

    client = create_firestore_client(
        database_id=args.database_id,
        allow_emulator=args.allow_firestore_emulator,
    )
    if args.verify_only:
        report = verify_release(
            client, plan, prefix=args.collection_prefix, require_pointer=True
        )
        report["user_state_hydration"] = verify_user_state_hydration(
            client, plan, prefix=args.collection_prefix
        )
        report["mode"] = "verify-only"
        report["database_writes_performed"] = False
    else:
        expected_current_release = (
            None
            if args.expected_current_release.casefold() == "none"
            else args.expected_current_release
        )
        report = apply_release(
            client,
            plan,
            prefix=args.collection_prefix,
            batch_size=args.batch_size,
            run_id=args.run_id,
            source_preflight_sha256=source_preflight_sha256,
            source_preflight_backend=source_preflight_backend,
            expected_current_release=expected_current_release,
            rollback=args.rollback,
        )
        report["mode"] = "apply"
        report["database_writes_performed"] = True
    report["firestore_target"] = target
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CatalogMigrationError as exc:
        print(f"catalog migration blocked: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
