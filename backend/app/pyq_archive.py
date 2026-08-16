"""Audited, paper-scoped ingestion for GATE previous-year questions.

The archive deliberately stores every source item, including descriptive,
out-of-syllabus, image-dependent, and not-yet-keyed questions.  Only rows that
pass every explicit verification gate may be materialized into the auto-scored
``questions`` table.  Imports never retire originals or PYQs from another
paper.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Difficulty,
    PyqArchiveExecution,
    PyqArchiveImport,
    PyqSourcePaper,
    PyqSourceQuestion,
    Question,
    QuestionSource,
    QuestionType,
    Subject,
    Topic,
)
from app.question_bank import _answer, _options
from app.question_assets import (
    QuestionAssetValidationError,
    public_question_assets,
)
from app.test_catalog import rebuild_test_catalog, validate_test_catalog


SUPPORTED_SCHEMA_MAJOR = "1"
PRACTICE_TYPES = {"mcq", "msq", "nat"}
VERIFIED_ANSWER_STATUSES = {"official", "community_verified"}
BACKEND_ROOT = Path(__file__).resolve().parents[1]
LEGACY_COLLISION_EVIDENCE_PATH = (
    BACKEND_ROOT / "data" / "pyq_legacy_collision_adoptions.json"
)
# The evidence file enumerates both pre-archive rows for every reviewed
# collision.  Keeping its checksum in code makes an unreviewed registry edit a
# hard importer failure rather than silently broadening an adoption rule.
LEGACY_COLLISION_EVIDENCE_SHA256 = (
    "7e7f872fb5bbbd5e9136312733a8e2adce7ea628c0800dd5bd2393207053b3de"
)
PYQ_VISIBILITY_PLAN_PATH = (
    BACKEND_ROOT / "data" / "pyq_legacy_collision_cleanup_plan.json"
)
# Updated only after the published practice artifact, allowlist, report, and the
# complete 228-row portable-fingerprint ledger have passed disposable-database
# validation.  The plan cannot silently grow or retarget itself at runtime.
PYQ_VISIBILITY_PLAN_SHA256 = (
    "1f68544cf95a66560ba6482245cc053340e837f01cab6590d0f4c4d7c25655ed"
)
REVIEWED_VISIBILITY_ARTIFACT_SHA256 = (
    "1c34407a6b71459d5c89f837fa0f3ef00190a27740b876008d79b22cd29c9dec"
)
REVIEWED_VISIBILITY_ARTIFACT_VERSION = (
    "gate-cs-pyq-practice-0aa05b22e3bf-88c192e62efb"
)

# Narrow compatibility aliases for rows shipped before the canonical archive
# existed.  Keep this explicit and paper-scoped: broad year/session inference
# could adopt a question from the wrong multi-session paper.
EXPLICIT_LEGACY_PAPER_ALIASES: dict[str, set[str]] = {
    "gate-cs-2024-set-1": {"GATE 2024 CS1 (Session 5)"},
}


class PyqArchiveValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class _LegacyCollisionAdoption:
    source_paper_id: str
    item_label: str
    ordinal: int
    source_pdf_sha256: str
    answer_key_sha256: str
    selected_pre_adoption_fingerprint_sha256: str
    preserved_duplicate_fingerprint_sha256s: frozenset[str]
    reviewed_equivalence: dict[str, Any]


@dataclass(frozen=True, slots=True)
class _PyqVisibilityPlan:
    plan_sha256: str
    artifact_file_sha256: str
    artifact_canonical_sha256: str
    artifact_version: str
    selection_sha256: str
    archive_record_count: int
    practice_eligible_count: int
    expected_question_row_count: int
    expected_pyq_row_count: int
    expected_active_originals: int
    expected_active_pyqs_before: int
    expected_retirements: int
    expected_active_pyqs_after: int
    expected_reactivations: int
    expected_recovery_active_pyqs_before: int
    expected_recovery_active_pyqs_after: int
    keep_records: tuple[dict[str, Any], ...]
    keep_external_ids: frozenset[str]
    retire_fingerprints: frozenset[str]


class SourceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(min_length=1, max_length=48)
    url: str | None = None
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    note: str | None = None


class AssetReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(min_length=1, max_length=48)
    path: str = Field(min_length=1)
    alt: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")


class ArchivePaper(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=96)
    exam_code: str = Field(default="GATE", min_length=1, max_length=24)
    paper_code: str = Field(default="CS", min_length=1, max_length=24)
    year: int = Field(ge=1987, le=2100)
    session_label: str = Field(default="main", min_length=1, max_length=80)
    display_name: str = Field(min_length=1, max_length=180)
    expected_item_count: int = Field(ge=1)
    source_url: str | None = None
    answer_key_url: str | None = None
    source_pdf_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-fA-F]{64}$"
    )
    answer_key_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-fA-F]{64}$"
    )
    # Historical question-bank releases used short paper labels such as
    # ``CS1-2024``.  Keep those aliases in the immutable artifact so adoption
    # is explicit instead of relying on increasingly permissive heuristics.
    # They are import-only metadata and deliberately have no database column.
    source_aliases: list[str] = Field(default_factory=list)
    source_status: Literal["verified", "review_required", "rejected"] = (
        "review_required"
    )
    notes: str | None = None

    @model_validator(mode="after")
    def verified_papers_have_a_checksum(self) -> ArchivePaper:
        aliases: list[str] = []
        normalized_aliases: set[str] = set()
        for raw_alias in self.source_aliases:
            alias = " ".join(raw_alias.split())
            if not alias:
                raise ValueError("source_aliases cannot contain empty labels")
            if len(alias) > 180:
                raise ValueError("source aliases cannot exceed 180 characters")
            normalized = _normalized_source_label(alias)
            if normalized and normalized not in normalized_aliases:
                aliases.append(alias)
                normalized_aliases.add(normalized)
        self.source_aliases = aliases
        if self.source_status == "verified" and not self.source_pdf_sha256:
            raise ValueError("verified papers require source_pdf_sha256")
        return self


class ArchiveQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_paper_id: str = Field(min_length=1, max_length=96)
    item_label: str = Field(min_length=1, max_length=48)
    ordinal: int = Field(ge=1)
    # Import-only provenance numbers used by older bank releases whose
    # section ordering differs from this archive's canonical ordinals (most
    # notably the technical-first 2017 corpus).  They are never persisted as
    # the canonical source ordinal.
    legacy_source_ordinals: list[int] = Field(default_factory=list)
    parent_item_label: str | None = Field(default=None, max_length=48)
    source_page: int | None = Field(default=None, ge=1)
    marks: float | None = Field(default=None, gt=0)
    item_type: Literal[
        "mcq", "msq", "nat", "descriptive", "composite", "unknown"
    ] = "unknown"
    question_md: str | None = None
    options: list[Any] = Field(default_factory=list)
    accepted_answers: Any | None = None
    solution_md: str | None = None
    subject_code: str | None = Field(default=None, max_length=16)
    topic_slug: str | None = Field(default=None, max_length=100)
    syllabus_status: Literal[
        "in_syllabus", "out_of_syllabus", "review_required"
    ] = "review_required"
    transcription_status: Literal["verified", "review_required", "missing"] = (
        "missing"
    )
    answer_status: Literal[
        "official", "community_verified", "unresolved", "not_applicable"
    ] = "unresolved"
    classification_status: Literal[
        "verified", "review_required", "out_of_syllabus"
    ] = "review_required"
    practice_eligible: bool = False
    review_flags: list[str] = Field(default_factory=list)
    assets: list[AssetReference] = Field(default_factory=list)
    source_references: list[SourceReference] = Field(default_factory=list)
    extraction_method: str | None = Field(default=None, max_length=80)
    extraction_confidence: float | None = Field(default=None, ge=0, le=1)
    content_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-fA-F]{64}$"
    )

    @model_validator(mode="after")
    def validated_practice_gate(self) -> ArchiveQuestion:
        self.item_label = self.item_label.strip()
        self.question_md = self.question_md.strip() if self.question_md else None
        self.solution_md = self.solution_md.strip() if self.solution_md else None
        self.review_flags = list(
            dict.fromkeys(flag.strip() for flag in self.review_flags if flag.strip())
        )
        legacy_ordinals = list(dict.fromkeys(self.legacy_source_ordinals))
        if any(value < 1 for value in legacy_ordinals):
            raise ValueError("legacy_source_ordinals must be positive")
        if len(legacy_ordinals) > 8:
            raise ValueError("at most eight legacy source ordinals are allowed")
        self.legacy_source_ordinals = legacy_ordinals
        if self.transcription_status == "verified" and not self.question_md:
            raise ValueError("verified transcription requires question_md")
        if not self.practice_eligible:
            return self
        failures: list[str] = []
        if self.item_type not in PRACTICE_TYPES:
            failures.append("unsupported item_type")
        if self.transcription_status != "verified":
            failures.append("transcription is not verified")
        if self.answer_status not in VERIFIED_ANSWER_STATUSES:
            failures.append("answer is not verified")
        if self.classification_status != "verified":
            failures.append("classification is not verified")
        if self.syllabus_status != "in_syllabus":
            failures.append("item is outside or unverified against the syllabus")
        if not self.subject_code or not self.topic_slug:
            failures.append("course/topic is missing")
        if self.review_flags:
            failures.append("review_flags are present")
        if self.accepted_answers is None:
            failures.append("accepted_answers is missing")
        if not self.solution_md:
            failures.append("solution_md is missing")
        if self.marks not in {1, 2, 1.0, 2.0}:
            failures.append("auto-scored practice requires one or two marks")
        if failures:
            raise ValueError("practice_eligible item failed gates: " + "; ".join(failures))
        return self


class PyqArchiveDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    artifact_version: str = Field(min_length=1, max_length=96)
    papers: list[ArchivePaper] = Field(min_length=1)
    questions: list[ArchiveQuestion] = Field(min_length=1)


@dataclass(frozen=True, slots=True)
class PyqArchiveImportResult:
    artifact_version: str
    checksum: str
    paper_count: int
    item_count: int
    inserted_count: int
    updated_count: int
    unchanged_count: int
    materialized_count: int
    materialized_inserted_count: int
    materialized_adopted_count: int
    materialized_updated_count: int
    retired_count: int
    reactivated_count: int
    visibility_plan_sha256: str | None
    original_active_count: int
    active_pyq_count_before: int
    active_pyq_count_after: int
    retirement_approval_required: bool
    already_applied: bool
    dry_run: bool
    execution_id: int | None


@dataclass(frozen=True, slots=True)
class PyqVisibilityRecoveryResult:
    artifact_version: str
    checksum: str
    visibility_plan_sha256: str
    reactivated_count: int
    original_active_count: int
    active_pyq_count_before: int
    active_pyq_count_after: int
    dry_run: bool
    execution_id: int | None


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _normalized_source_label(value: str | None) -> str:
    """Normalize legacy paper labels without weakening paper identity.

    Historical imports used display labels with inconsistent punctuation and
    spacing (for example ``GATE 2024 CS1 (Session 5)``).  Removing only those
    presentation differences lets the audited archive adopt the existing row
    instead of adding a duplicate.  Year and question ordinal remain separate
    mandatory parts of the provenance key.
    """

    return re.sub(r"[^a-z0-9]+", "", (value or "").casefold())


def _paper_source_aliases(paper: ArchivePaper) -> set[str]:
    labels = {
        paper.id,
        paper.display_name,
        (
            f"{paper.exam_code} {paper.year} {paper.paper_code} "
            f"{paper.session_label}"
        ),
        *paper.source_aliases,
        *EXPLICIT_LEGACY_PAPER_ALIASES.get(paper.id, set()),
    }
    return {
        normalized
        for label in labels
        if (normalized := _normalized_source_label(label))
    }


def _enum_value(value: Any) -> Any:
    return value.value if isinstance(value, Enum) else value


def _canonical_json_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _portable_correct_answer(value: Any, question_type: QuestionType) -> Any:
    """Normalize a top-level integral NAT JSON number representation."""

    if (
        question_type == QuestionType.NAT
        and isinstance(value, float)
        and value.is_integer()
    ):
        return int(value)
    return value


def _legacy_candidate_payload(
    question: Question,
    *,
    subject_codes_by_id: dict[int, str],
    topic_slugs_by_id: dict[int, str],
) -> dict[str, Any]:
    """Return the portable, review-relevant identity of a legacy PYQ row.

    Database ids and timestamps are deliberately excluded.  Course/topic are
    represented by their stable public identifiers so the fingerprint remains
    valid across independently created SQLite, staging, and production
    databases while still detecting a scope change.
    """

    subject_code = subject_codes_by_id.get(question.subject_id)
    topic_slug = topic_slugs_by_id.get(question.topic_id)
    if subject_code is None or topic_slug is None:
        raise PyqArchiveValidationError(
            "Legacy collision candidate references an unknown course/topic"
        )
    return {
        "external_id": question.external_id,
        "bank_version": question.bank_version,
        # Visibility is guarded independently by exact before/after counts and
        # the retirement ledger.  Normalizing this historical field preserves
        # the reviewed fingerprint after an authorized deactivate/reactivate
        # transition; all other content and provenance remain checksum-bound.
        "is_active": True,
        "subject_code": subject_code,
        "topic_slug": topic_slug,
        "source": _enum_value(question.source),
        "year": question.year,
        "exam_session": question.exam_session,
        "source_kind": _enum_value(question.source_kind),
        "source_year": question.source_year,
        "source_paper": question.source_paper,
        "source_question_number": question.source_question_number,
        "source_paper_id": question.source_paper_id,
        "source_item_label": question.source_item_label,
        "source_page": question.source_page,
        "source_url": question.source_url,
        "answer_key_url": question.answer_key_url,
        "extraction_method": question.extraction_method,
        "extraction_confidence": question.extraction_confidence,
        "question_type": _enum_value(question.question_type),
        "difficulty": _enum_value(question.difficulty),
        "text": question.text,
        "options": question.options,
        # SQLite's JSON decoder preserves ``42`` as int while PostgreSQL JSONB
        # can return the same stored NAT answer as ``42.0``.  Their accepted
        # answer semantics are identical; normalize only that integral numeric
        # representation so the reviewed fingerprint remains portable.
        "correct_answer": _portable_correct_answer(
            question.correct_answer, question.question_type
        ),
        "numerical_tolerance": question.numerical_tolerance,
        "marks": question.marks,
        "explanation": question.explanation,
        "tags": question.tags,
        "assets": question.assets,
    }


def _legacy_candidate_fingerprint(
    question: Question,
    *,
    subject_codes_by_id: dict[int, str],
    topic_slugs_by_id: dict[int, str],
) -> str:
    payload = _legacy_candidate_payload(
        question,
        subject_codes_by_id=subject_codes_by_id,
        topic_slugs_by_id=topic_slugs_by_id,
    )
    encoded = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _portable_text_sha256s(raw: bytes) -> set[str]:
    """Return hashes for byte-identical text modulo checkout line endings."""

    lf = raw.replace(b"\r\n", b"\n")
    crlf = lf.replace(b"\n", b"\r\n")
    return {
        hashlib.sha256(candidate).hexdigest()
        for candidate in (raw, lf, crlf)
    }


def _validate_collision_evidence_binding(path: str, expected_sha256: str) -> None:
    source_path = BACKEND_ROOT / path
    if not source_path.is_file():
        raise PyqArchiveValidationError(
            f"Legacy collision evidence source is missing: {path}"
        )
    raw = source_path.read_bytes()
    actual_sha256s = (
        _portable_text_sha256s(raw)
        if source_path.suffix.lower() in {".json", ".py"}
        else {hashlib.sha256(raw).hexdigest()}
    )
    if expected_sha256 not in actual_sha256s:
        raise PyqArchiveValidationError(
            f"Legacy collision evidence source checksum drifted: {path}"
        )


@lru_cache(maxsize=1)
def _load_legacy_collision_adoptions() -> dict[
    tuple[str, int], _LegacyCollisionAdoption
]:
    try:
        raw = LEGACY_COLLISION_EVIDENCE_PATH.read_bytes()
    except OSError as exc:
        raise PyqArchiveValidationError(
            "Legacy collision adoption evidence is unavailable"
        ) from exc
    checksum = hashlib.sha256(raw).hexdigest()
    if checksum != LEGACY_COLLISION_EVIDENCE_SHA256:
        raise PyqArchiveValidationError(
            "Legacy collision adoption evidence checksum mismatch"
        )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PyqArchiveValidationError(
            "Legacy collision adoption evidence is not valid JSON"
        ) from exc
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version",
        "evidence_version",
        "source_bindings",
        "adoptions",
    } or payload["schema_version"] != "1.0":
        raise PyqArchiveValidationError(
            "Legacy collision adoption evidence has an unsupported schema"
        )
    if not isinstance(payload["source_bindings"], list):
        raise PyqArchiveValidationError(
            "Legacy collision adoption evidence source bindings are invalid"
        )
    for binding in payload["source_bindings"]:
        if not isinstance(binding, dict) or set(binding) != {"path", "sha256"}:
            raise PyqArchiveValidationError(
                "Legacy collision adoption evidence contains an invalid source binding"
            )
        path = binding["path"]
        expected_sha256 = binding["sha256"]
        if not isinstance(path, str) or not re.fullmatch(
            r"[0-9a-f]{64}", str(expected_sha256)
        ):
            raise PyqArchiveValidationError(
                "Legacy collision adoption evidence contains an invalid source checksum"
            )
        _validate_collision_evidence_binding(path, expected_sha256)

    adoptions: dict[tuple[str, int], _LegacyCollisionAdoption] = {}
    if not isinstance(payload["adoptions"], list):
        raise PyqArchiveValidationError(
            "Legacy collision adoption evidence entries are invalid"
        )
    required_entry_keys = {
        "source_paper_id",
        "item_label",
        "ordinal",
        "source_pdf_sha256",
        "answer_key_sha256",
        "selected_pre_adoption_fingerprint_sha256",
        "preserved_duplicate_fingerprint_sha256s",
        "reviewed_equivalence",
    }
    required_equivalence_keys = {
        "source_year",
        "source_question_number",
        "question_type",
        "correct_answer",
        "marks",
        "source_url",
        "answer_key_url",
    }
    for raw_entry in payload["adoptions"]:
        if not isinstance(raw_entry, dict) or set(raw_entry) != required_entry_keys:
            raise PyqArchiveValidationError(
                "Legacy collision adoption evidence contains an invalid entry"
            )
        raw_duplicate_fingerprints = raw_entry[
            "preserved_duplicate_fingerprint_sha256s"
        ]
        if not isinstance(raw_duplicate_fingerprints, list):
            raise PyqArchiveValidationError(
                "Legacy collision adoption evidence contains invalid duplicates"
            )
        hashes = [
            raw_entry["source_pdf_sha256"],
            raw_entry["answer_key_sha256"],
            raw_entry["selected_pre_adoption_fingerprint_sha256"],
            *raw_duplicate_fingerprints,
        ]
        if any(not re.fullmatch(r"[0-9a-f]{64}", str(value)) for value in hashes):
            raise PyqArchiveValidationError(
                "Legacy collision adoption evidence contains an invalid fingerprint"
            )
        duplicate_fingerprints = frozenset(raw_duplicate_fingerprints)
        if len(duplicate_fingerprints) != 1:
            raise PyqArchiveValidationError(
                "Legacy collision adoption evidence must name one preserved duplicate"
            )
        reviewed_equivalence = raw_entry["reviewed_equivalence"]
        if not isinstance(reviewed_equivalence, dict) or set(
            reviewed_equivalence
        ) != required_equivalence_keys:
            raise PyqArchiveValidationError(
                "Legacy collision adoption equivalence proof is incomplete"
            )
        adoption = _LegacyCollisionAdoption(
            source_paper_id=str(raw_entry["source_paper_id"]),
            item_label=str(raw_entry["item_label"]),
            ordinal=int(raw_entry["ordinal"]),
            source_pdf_sha256=str(raw_entry["source_pdf_sha256"]),
            answer_key_sha256=str(raw_entry["answer_key_sha256"]),
            selected_pre_adoption_fingerprint_sha256=str(
                raw_entry["selected_pre_adoption_fingerprint_sha256"]
            ),
            preserved_duplicate_fingerprint_sha256s=duplicate_fingerprints,
            reviewed_equivalence=reviewed_equivalence,
        )
        key = (adoption.source_paper_id, adoption.ordinal)
        if key in adoptions:
            raise PyqArchiveValidationError(
                "Legacy collision adoption evidence contains a duplicate key"
            )
        adoptions[key] = adoption
    return adoptions


def _read_visibility_binding(
    binding: Any,
    *,
    label: str,
    required_keys: set[str],
) -> tuple[dict[str, Any], str]:
    if not isinstance(binding, dict) or set(binding) != required_keys:
        raise PyqArchiveValidationError(
            f"PYQ visibility plan contains an invalid {label} binding"
        )
    path = binding.get("path")
    expected_file_sha256 = binding.get("file_sha256")
    if not isinstance(path, str) or not re.fullmatch(
        r"[0-9a-f]{64}", str(expected_file_sha256)
    ):
        raise PyqArchiveValidationError(
            f"PYQ visibility plan contains an invalid {label} checksum"
        )
    source_path = BACKEND_ROOT / path
    try:
        raw = source_path.read_bytes()
    except OSError as exc:
        raise PyqArchiveValidationError(
            f"PYQ visibility plan binding is unavailable: {path}"
        ) from exc
    actual_file_sha256 = hashlib.sha256(raw).hexdigest()
    if actual_file_sha256 != expected_file_sha256:
        raise PyqArchiveValidationError(
            f"PYQ visibility plan binding checksum drifted: {path}"
        )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PyqArchiveValidationError(
            f"PYQ visibility plan binding is not valid JSON: {path}"
        ) from exc
    if not isinstance(payload, dict):
        raise PyqArchiveValidationError(
            f"PYQ visibility plan binding must be an object: {path}"
        )
    return payload, actual_file_sha256


@lru_cache(maxsize=1)
def _load_pyq_visibility_plan() -> _PyqVisibilityPlan:
    try:
        raw = PYQ_VISIBILITY_PLAN_PATH.read_bytes()
    except OSError as exc:
        raise PyqArchiveValidationError(
            "PYQ visibility plan is unavailable"
        ) from exc
    # The reviewed plan was produced on Windows, while production checks it
    # out on Linux. Accept only byte-identical text modulo CRLF/LF checkout
    # conversion and preserve the single reviewed checksum in audit records.
    if PYQ_VISIBILITY_PLAN_SHA256 not in _portable_text_sha256s(raw):
        raise PyqArchiveValidationError("PYQ visibility plan checksum mismatch")
    plan_sha256 = PYQ_VISIBILITY_PLAN_SHA256
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PyqArchiveValidationError(
            "PYQ visibility plan is not valid JSON"
        ) from exc
    required_top_keys = {
        "schema_version",
        "plan_version",
        "status",
        "database_writes_performed",
        "bindings",
        "guards",
        "keep_targets",
        "retire_targets",
        "recovery",
    }
    if (
        not isinstance(payload, dict)
        or set(payload) != required_top_keys
        or payload["schema_version"] != "2.0"
        or payload["status"] != "authorized_opt_in_only"
        or payload["database_writes_performed"] is not False
    ):
        raise PyqArchiveValidationError(
            "PYQ visibility plan has an unsupported schema or authorization state"
        )

    bindings = payload["bindings"]
    if not isinstance(bindings, dict) or set(bindings) != {
        "source_archive",
        "source_archive_report",
        "promotion_artifact",
        "promotion_allowlist",
        "promotion_report",
        "collision_evidence",
        "selection_sha256",
    }:
        raise PyqArchiveValidationError("PYQ visibility plan bindings are invalid")
    selection_sha256 = bindings["selection_sha256"]
    if not re.fullmatch(r"[0-9a-f]{64}", str(selection_sha256)):
        raise PyqArchiveValidationError(
            "PYQ visibility plan selection checksum is invalid"
        )

    source_binding = bindings["source_archive"]
    source_archive, _ = _read_visibility_binding(
        source_binding,
        label="source archive",
        required_keys={"path", "file_sha256", "canonical_sha256"},
    )
    source_canonical_sha256 = _canonical_json_sha256(source_archive)
    if source_canonical_sha256 != source_binding["canonical_sha256"]:
        raise PyqArchiveValidationError(
            "PYQ visibility plan source archive binding drifted"
        )
    source_report_binding = bindings["source_archive_report"]
    source_report, _ = _read_visibility_binding(
        source_report_binding,
        label="source archive report",
        required_keys={"path", "file_sha256", "report_sha256"},
    )
    source_report_core = {
        key: value
        for key, value in source_report.items()
        if key != "report_sha256"
    }
    if (
        _canonical_json_sha256(source_report_core)
        != source_report_binding["report_sha256"]
        or source_report.get("report_sha256")
        != source_report_binding["report_sha256"]
        or source_report.get("artifact_sha256") != source_canonical_sha256
    ):
        raise PyqArchiveValidationError(
            "PYQ visibility plan source archive report binding drifted"
        )

    artifact_binding = bindings["promotion_artifact"]
    artifact, artifact_file_sha256 = _read_visibility_binding(
        artifact_binding,
        label="promotion artifact",
        required_keys={
            "path",
            "file_sha256",
            "canonical_sha256",
            "artifact_version",
        },
    )
    artifact_canonical_sha256 = _canonical_json_sha256(artifact)
    if (
        artifact_canonical_sha256 != artifact_binding["canonical_sha256"]
        or artifact.get("artifact_version") != artifact_binding["artifact_version"]
    ):
        raise PyqArchiveValidationError(
            "PYQ visibility plan promotion artifact binding drifted"
        )

    allowlist_binding = bindings["promotion_allowlist"]
    allowlist, _ = _read_visibility_binding(
        allowlist_binding,
        label="promotion allowlist",
        required_keys={"path", "file_sha256", "artifact_sha256"},
    )
    allowlist_core = {
        key: value for key, value in allowlist.items() if key != "artifact_sha256"
    }
    if (
        _canonical_json_sha256(allowlist_core)
        != allowlist_binding["artifact_sha256"]
        or allowlist.get("artifact_sha256")
        != allowlist_binding["artifact_sha256"]
        or allowlist.get("promoted_archive_artifact_sha256")
        != artifact_canonical_sha256
        or allowlist.get("source_release_artifact_sha256")
        != source_canonical_sha256
        or allowlist.get("source_release_report_sha256")
        != source_report_binding["report_sha256"]
        or allowlist.get("selection_sha256") != selection_sha256
    ):
        raise PyqArchiveValidationError(
            "PYQ visibility plan promotion allowlist binding drifted"
        )

    report_binding = bindings["promotion_report"]
    report, _ = _read_visibility_binding(
        report_binding,
        label="promotion report",
        required_keys={"path", "file_sha256", "report_sha256"},
    )
    report_core = {key: value for key, value in report.items() if key != "report_sha256"}
    if (
        _canonical_json_sha256(report_core) != report_binding["report_sha256"]
        or report.get("report_sha256") != report_binding["report_sha256"]
        or report.get("promoted_archive_artifact_sha256")
        != artifact_canonical_sha256
        or report.get("allowlist_artifact_sha256")
        != allowlist_binding["artifact_sha256"]
        or report.get("source_release_artifact_sha256")
        != source_canonical_sha256
        or report.get("source_release_report_sha256")
        != source_report_binding["report_sha256"]
        or report.get("selection_sha256") != selection_sha256
    ):
        raise PyqArchiveValidationError(
            "PYQ visibility plan promotion report binding drifted"
        )

    collision_binding = bindings["collision_evidence"]
    _, collision_file_sha256 = _read_visibility_binding(
        collision_binding,
        label="collision evidence",
        required_keys={"path", "file_sha256"},
    )
    if collision_file_sha256 != LEGACY_COLLISION_EVIDENCE_SHA256:
        raise PyqArchiveValidationError(
            "PYQ visibility plan is bound to unreviewed collision evidence"
        )

    guards = payload["guards"]
    required_guard_keys = {
        "expected_question_rows",
        "expected_pyq_rows",
        "expected_active_originals",
        "expected_active_pyqs_before",
        "expected_retirements",
        "expected_active_pyqs_after",
        "archive_record_count",
        "practice_eligible_count",
        "delete_rows",
    }
    if not isinstance(guards, dict) or set(guards) != required_guard_keys:
        raise PyqArchiveValidationError("PYQ visibility plan guards are invalid")
    integer_guard_keys = required_guard_keys - {"delete_rows"}
    if (
        guards["delete_rows"] is not False
        or any(
            not isinstance(guards[key], int) or guards[key] < 0
            for key in integer_guard_keys
        )
    ):
        raise PyqArchiveValidationError("PYQ visibility plan guards are unsafe")

    keep_targets = payload["keep_targets"]
    required_keep_keys = {
        "source_paper_id",
        "ordinal",
        "item_label",
        "source_content_sha256",
        "promoted_content_sha256",
        "external_id",
    }
    if not isinstance(keep_targets, list) or any(
        not isinstance(entry, dict) or set(entry) != required_keep_keys
        for entry in keep_targets
    ):
        raise PyqArchiveValidationError("PYQ visibility keep ledger is invalid")
    keep_records = tuple(
        sorted(
            keep_targets,
            key=lambda entry: (entry["source_paper_id"], entry["ordinal"]),
        )
    )
    keep_keys = {
        (entry["source_paper_id"], entry["ordinal"]) for entry in keep_records
    }
    keep_external_ids = frozenset(entry["external_id"] for entry in keep_records)
    if (
        len(keep_records) != guards["practice_eligible_count"]
        or len(keep_keys) != len(keep_records)
        or len(keep_external_ids) != len(keep_records)
        or any(
            entry["external_id"]
            != f"pyq:{entry['source_paper_id']}:{_slug(entry['item_label'])}"
            or not re.fullmatch(
                r"[0-9a-f]{64}", str(entry["source_content_sha256"])
            )
            or not re.fullmatch(
                r"[0-9a-f]{64}", str(entry["promoted_content_sha256"])
            )
            for entry in keep_records
        )
    ):
        raise PyqArchiveValidationError("PYQ visibility keep ledger drifted")
    allowlist_records = allowlist.get("records")
    expected_allowlist_records = [
        {
            key: entry[key]
            for key in (
                "source_paper_id",
                "ordinal",
                "item_label",
                "source_content_sha256",
            )
        }
        for entry in keep_records
    ]
    if (
        allowlist_records != expected_allowlist_records
        or _canonical_json_sha256(allowlist_records) != selection_sha256
        or allowlist.get("practice_eligible_count") != len(keep_records)
        or allowlist.get("archive_record_count") != guards["archive_record_count"]
    ):
        raise PyqArchiveValidationError(
            "PYQ visibility keep ledger does not equal the promotion allowlist"
        )
    artifact_selected = sorted(
        (
            {
                "source_paper_id": item.get("source_paper_id"),
                "ordinal": item.get("ordinal"),
                "item_label": item.get("item_label"),
                "promoted_content_sha256": item.get("content_sha256"),
            }
            for item in artifact.get("questions", [])
            if item.get("practice_eligible") is True
        ),
        key=lambda entry: (entry["source_paper_id"], entry["ordinal"]),
    )
    if (
        len(artifact.get("questions", [])) != guards["archive_record_count"]
        or artifact_selected != [
            {
                "source_paper_id": entry["source_paper_id"],
                "ordinal": entry["ordinal"],
                "item_label": entry["item_label"],
                "promoted_content_sha256": entry["promoted_content_sha256"],
            }
            for entry in keep_records
        ]
    ):
        raise PyqArchiveValidationError(
            "PYQ visibility promotion artifact does not equal the keep ledger"
        )
    source_by_key = {
        (item.get("source_paper_id"), item.get("ordinal")): item
        for item in source_archive.get("questions", [])
    }
    for entry in keep_records:
        source_item = source_by_key.get(
            (entry["source_paper_id"], entry["ordinal"])
        )
        if (
            source_item is None
            or source_item.get("item_label") != entry["item_label"]
            or source_item.get("content_sha256")
            != entry["source_content_sha256"]
        ):
            raise PyqArchiveValidationError(
                "PYQ visibility source-content ledger drifted"
            )

    retire_targets = payload["retire_targets"]
    required_retire_keys = {
        "fingerprint_sha256",
        "external_id",
        "source_paper",
        "source_year",
        "source_question_number",
    }
    if not isinstance(retire_targets, list) or any(
        not isinstance(entry, dict) or set(entry) != required_retire_keys
        for entry in retire_targets
    ):
        raise PyqArchiveValidationError("PYQ visibility retirement ledger is invalid")
    retire_fingerprints = frozenset(
        entry["fingerprint_sha256"] for entry in retire_targets
    )
    if (
        len(retire_targets) != guards["expected_retirements"]
        or len(retire_fingerprints) != len(retire_targets)
        or any(
            not re.fullmatch(r"[0-9a-f]{64}", str(value))
            for value in retire_fingerprints
        )
    ):
        raise PyqArchiveValidationError("PYQ visibility retirement ledger drifted")

    recovery = payload["recovery"]
    if not isinstance(recovery, dict) or set(recovery) != {
        "expected_active_originals",
        "expected_active_pyqs_before",
        "expected_reactivations",
        "expected_active_pyqs_after",
        "delete_rows",
    } or recovery["delete_rows"] is not False:
        raise PyqArchiveValidationError("PYQ visibility recovery guards are invalid")
    if (
        guards["expected_retirements"] != len(retire_fingerprints)
        or guards["expected_active_pyqs_before"]
        - guards["expected_retirements"]
        != guards["expected_active_pyqs_after"]
        or recovery["expected_reactivations"] != len(retire_fingerprints)
        or recovery["expected_active_pyqs_before"]
        + recovery["expected_reactivations"]
        != recovery["expected_active_pyqs_after"]
        or recovery["expected_active_originals"]
        != guards["expected_active_originals"]
        or recovery["expected_active_pyqs_before"]
        != guards["expected_active_pyqs_after"]
        or recovery["expected_active_pyqs_after"]
        != guards["expected_active_pyqs_before"]
    ):
        raise PyqArchiveValidationError("PYQ visibility count arithmetic drifted")

    return _PyqVisibilityPlan(
        plan_sha256=plan_sha256,
        artifact_file_sha256=artifact_file_sha256,
        artifact_canonical_sha256=artifact_canonical_sha256,
        artifact_version=str(artifact_binding["artifact_version"]),
        selection_sha256=str(selection_sha256),
        archive_record_count=int(guards["archive_record_count"]),
        practice_eligible_count=int(guards["practice_eligible_count"]),
        expected_question_row_count=int(guards["expected_question_rows"]),
        expected_pyq_row_count=int(guards["expected_pyq_rows"]),
        expected_active_originals=int(guards["expected_active_originals"]),
        expected_active_pyqs_before=int(guards["expected_active_pyqs_before"]),
        expected_retirements=int(guards["expected_retirements"]),
        expected_active_pyqs_after=int(guards["expected_active_pyqs_after"]),
        expected_reactivations=int(recovery["expected_reactivations"]),
        expected_recovery_active_pyqs_before=int(
            recovery["expected_active_pyqs_before"]
        ),
        expected_recovery_active_pyqs_after=int(
            recovery["expected_active_pyqs_after"]
        ),
        keep_records=keep_records,
        keep_external_ids=keep_external_ids,
        retire_fingerprints=retire_fingerprints,
    )


def _validated_pyq_visibility_plan(
    document: PyqArchiveDocument,
    checksum: str,
) -> _PyqVisibilityPlan:
    if (
        checksum != REVIEWED_VISIBILITY_ARTIFACT_SHA256
        or document.artifact_version != REVIEWED_VISIBILITY_ARTIFACT_VERSION
    ):
        raise PyqArchiveValidationError(
            "Retirement/recovery is authorized only for the exact reviewed "
            "promotion artifact"
        )
    plan = _load_pyq_visibility_plan()
    if (
        plan.artifact_file_sha256 != REVIEWED_VISIBILITY_ARTIFACT_SHA256
        or plan.artifact_version != REVIEWED_VISIBILITY_ARTIFACT_VERSION
        or len(document.questions) != plan.archive_record_count
        or sum(item.practice_eligible for item in document.questions)
        != plan.practice_eligible_count
    ):
        raise PyqArchiveValidationError(
            "Retirement/recovery is authorized only for the exact reviewed "
            "promotion artifact"
        )
    return plan


def _candidate_has_canonical_identity(
    candidate: Question,
    *,
    paper: ArchivePaper,
    item: ArchiveQuestion,
    materialized_values: dict[str, Any],
) -> bool:
    return (
        candidate.external_id == materialized_values["external_id"]
        and candidate.source_paper_id == paper.id
        and candidate.source_item_label == item.item_label
        and candidate.source_question_number == item.ordinal
    )


def _candidate_matches_canonical_scored_content(
    candidate: Question, materialized_values: dict[str, Any]
) -> bool:
    return all(
        getattr(candidate, field) == materialized_values[field]
        for field in (
            "question_type",
            "text",
            "options",
            "correct_answer",
            "marks",
        )
    )


def _select_evidence_backed_collision_candidate(
    *,
    paper: ArchivePaper,
    item: ArchiveQuestion,
    materialized_values: dict[str, Any],
    candidates: dict[int, Question],
    subject_codes_by_id: dict[int, str],
    topic_slugs_by_id: dict[int, str],
) -> Question:
    evidence = _load_legacy_collision_adoptions().get((paper.id, item.ordinal))
    label = f"{paper.id}/{item.item_label}"
    if evidence is None or evidence.item_label != item.item_label:
        raise PyqArchiveValidationError(
            f"{label}: multiple existing PYQs share the normalized source metadata"
        )
    if (
        paper.source_pdf_sha256 != evidence.source_pdf_sha256
        or paper.answer_key_sha256 != evidence.answer_key_sha256
    ):
        raise PyqArchiveValidationError(
            f"{label}: collision evidence is bound to different source artifacts"
        )
    if len(candidates) != 2:
        raise PyqArchiveValidationError(
            f"{label}: reviewed collision candidate count drifted"
        )

    aliases = _paper_source_aliases(paper)
    canonical_candidates = [
        candidate
        for candidate in candidates.values()
        if _candidate_has_canonical_identity(
            candidate,
            paper=paper,
            item=item,
            materialized_values=materialized_values,
        )
    ]
    fingerprints = {
        candidate.id: _legacy_candidate_fingerprint(
            candidate,
            subject_codes_by_id=subject_codes_by_id,
            topic_slugs_by_id=topic_slugs_by_id,
        )
        for candidate in candidates.values()
    }
    if canonical_candidates:
        if len(canonical_candidates) != 1:
            raise PyqArchiveValidationError(
                f"{label}: canonical collision identity is not unique"
            )
        selected = canonical_candidates[0]
    else:
        pre_adoption = [
            candidate
            for candidate in candidates.values()
            if fingerprints[candidate.id]
            == evidence.selected_pre_adoption_fingerprint_sha256
        ]
        if len(pre_adoption) != 1 or not _candidate_matches_canonical_scored_content(
            pre_adoption[0], materialized_values
        ):
            raise PyqArchiveValidationError(
                f"{label}: reviewed canonical collision candidate drifted"
            )
        selected = pre_adoption[0]

    preserved = [
        candidate for candidate in candidates.values() if candidate is not selected
    ]
    preserved_fingerprints = {fingerprints[candidate.id] for candidate in preserved}
    if preserved_fingerprints != evidence.preserved_duplicate_fingerprint_sha256s:
        raise PyqArchiveValidationError(
            f"{label}: preserved legacy duplicate drifted"
        )

    proof = evidence.reviewed_equivalence
    for candidate in candidates.values():
        canonical = _candidate_has_canonical_identity(
            candidate,
            paper=paper,
            item=item,
            materialized_values=materialized_values,
        )
        if (
            not canonical
            and _normalized_source_label(candidate.source_paper) not in aliases
        ):
            raise PyqArchiveValidationError(
                f"{label}: collision candidate is outside the explicit paper aliases"
            )
        if candidate.source_kind != QuestionSource.PREVIOUS_YEAR:
            raise PyqArchiveValidationError(
                f"{label}: collision candidate is not a previous-year question"
            )
        # A canonical row may carry the archive's refreshed source URLs after a
        # prior adoption.  Every pre-adoption row must match the reviewed proof
        # exactly; the preserved duplicate is therefore never silently edited.
        if canonical:
            continue
        actual_proof = {
            "source_year": candidate.source_year,
            "source_question_number": candidate.source_question_number,
            "question_type": _enum_value(candidate.question_type),
            "correct_answer": candidate.correct_answer,
            "marks": candidate.marks,
            "source_url": candidate.source_url,
            "answer_key_url": candidate.answer_key_url,
        }
        if actual_proof != proof:
            raise PyqArchiveValidationError(
                f"{label}: collision candidate failed the reviewed equivalence proof"
            )
    return selected


def _load_document(path: Path) -> tuple[PyqArchiveDocument, str]:
    raw = path.read_bytes()
    checksum = hashlib.sha256(raw).hexdigest()
    try:
        payload = json.loads(raw)
        document = PyqArchiveDocument.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise PyqArchiveValidationError(str(exc)) from exc
    if document.schema_version.split(".", 1)[0] != SUPPORTED_SCHEMA_MAJOR:
        raise PyqArchiveValidationError(
            f"Unsupported archive schema {document.schema_version!r}"
        )
    _validate_document(document)
    return document, checksum


def _content_sha256(item: ArchiveQuestion) -> str:
    """Hash the complete review-relevant source-item record.

    This is intentionally broader than a display-content checksum.  A change
    to provenance, scoring, review status, or practice eligibility is just as
    important to the immutable archive audit as a change to the visible stem.
    """

    payload = {
        "source_paper_id": item.source_paper_id,
        "item_label": item.item_label,
        "ordinal": item.ordinal,
        "legacy_source_ordinals": item.legacy_source_ordinals,
        "parent_item_label": item.parent_item_label,
        "source_page": item.source_page,
        "marks": item.marks,
        "item_type": item.item_type,
        "question_md": item.question_md,
        "options": item.options,
        "accepted_answers": item.accepted_answers,
        "solution_md": item.solution_md,
        "subject_code": item.subject_code,
        "topic_slug": item.topic_slug,
        "syllabus_status": item.syllabus_status,
        "transcription_status": item.transcription_status,
        "answer_status": item.answer_status,
        "classification_status": item.classification_status,
        "practice_eligible": item.practice_eligible,
        "review_flags": item.review_flags,
        "assets": [asset.model_dump(mode="json") for asset in item.assets],
        "source_references": [
            reference.model_dump(mode="json") for reference in item.source_references
        ],
        "extraction_method": item.extraction_method,
        "extraction_confidence": item.extraction_confidence,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_document(document: PyqArchiveDocument) -> None:
    papers_by_id: dict[str, ArchivePaper] = {}
    paper_sessions: set[tuple[str, str, int, str]] = set()
    alias_owners: dict[tuple[int, str], str] = {}
    for paper in document.papers:
        if paper.id in papers_by_id:
            raise PyqArchiveValidationError(f"Duplicate paper id {paper.id!r}")
        session_identity = (
            paper.exam_code.upper(),
            paper.paper_code.upper(),
            paper.year,
            paper.session_label.casefold(),
        )
        if session_identity in paper_sessions:
            raise PyqArchiveValidationError(
                f"Duplicate paper session {paper.year}/{paper.session_label}"
            )
        paper_sessions.add(session_identity)
        papers_by_id[paper.id] = paper
        for alias in _paper_source_aliases(paper):
            alias_key = (paper.year, alias)
            owner = alias_owners.get(alias_key)
            if owner is not None and owner != paper.id:
                raise PyqArchiveValidationError(
                    f"Ambiguous source alias {alias!r} for {owner!r} and "
                    f"{paper.id!r}"
                )
            alias_owners[alias_key] = paper.id

    questions_by_paper: dict[str, list[ArchiveQuestion]] = {
        paper_id: [] for paper_id in papers_by_id
    }
    labels: set[tuple[str, str]] = set()
    ordinals: set[tuple[str, int]] = set()
    legacy_ordinals: set[tuple[str, int]] = set()
    for item in document.questions:
        paper = papers_by_id.get(item.source_paper_id)
        if paper is None:
            raise PyqArchiveValidationError(
                f"Question {item.item_label!r} references unknown paper "
                f"{item.source_paper_id!r}"
            )
        label_key = (paper.id, item.item_label.casefold())
        ordinal_key = (paper.id, item.ordinal)
        if label_key in labels:
            raise PyqArchiveValidationError(
                f"Duplicate item label {paper.id}/{item.item_label}"
            )
        if ordinal_key in ordinals:
            raise PyqArchiveValidationError(
                f"Duplicate item ordinal {paper.id}/{item.ordinal}"
            )
        labels.add(label_key)
        ordinals.add(ordinal_key)
        effective_legacy_ordinals = item.legacy_source_ordinals or [item.ordinal]
        for legacy_ordinal in effective_legacy_ordinals:
            if legacy_ordinal > paper.expected_item_count:
                raise PyqArchiveValidationError(
                    f"Legacy source ordinal {paper.id}/{legacy_ordinal} exceeds "
                    f"the paper's audited item count {paper.expected_item_count}"
                )
            legacy_key = (paper.id, legacy_ordinal)
            if legacy_key in legacy_ordinals:
                raise PyqArchiveValidationError(
                    f"Duplicate legacy source ordinal {paper.id}/{legacy_ordinal}"
                )
            legacy_ordinals.add(legacy_key)
        questions_by_paper[paper.id].append(item)
        computed_hash = _content_sha256(item)
        if item.content_sha256 and item.content_sha256.lower() != computed_hash:
            raise PyqArchiveValidationError(
                f"Content checksum mismatch for {paper.id}/{item.item_label}"
            )
        if item.practice_eligible and paper.source_status != "verified":
            raise PyqArchiveValidationError(
                f"Practice item {paper.id}/{item.item_label} uses an unverified paper"
            )

    for paper_id, paper in papers_by_id.items():
        items = questions_by_paper[paper_id]
        if len(items) != paper.expected_item_count:
            raise PyqArchiveValidationError(
                f"Paper {paper_id} expected {paper.expected_item_count} items, "
                f"found {len(items)}"
            )
        expected_ordinals = list(range(1, paper.expected_item_count + 1))
        actual_ordinals = sorted(item.ordinal for item in items)
        if actual_ordinals != expected_ordinals:
            raise PyqArchiveValidationError(
                f"Paper {paper_id} ordinals must be contiguous 1.."
                f"{paper.expected_item_count}"
            )


def _paper_values(paper: ArchivePaper) -> dict[str, Any]:
    return {
        "exam_code": paper.exam_code.upper(),
        "paper_code": paper.paper_code.upper(),
        "year": paper.year,
        "session_label": paper.session_label,
        "display_name": paper.display_name,
        "expected_item_count": paper.expected_item_count,
        "source_url": paper.source_url,
        "answer_key_url": paper.answer_key_url,
        "source_pdf_sha256": (
            paper.source_pdf_sha256.lower() if paper.source_pdf_sha256 else None
        ),
        "answer_key_sha256": (
            paper.answer_key_sha256.lower() if paper.answer_key_sha256 else None
        ),
        "source_status": paper.source_status,
        "notes": paper.notes,
    }


def _source_question_values(item: ArchiveQuestion) -> dict[str, Any]:
    return {
        "item_label": item.item_label,
        "ordinal": item.ordinal,
        "parent_item_label": item.parent_item_label,
        "source_page": item.source_page,
        "marks": item.marks,
        "item_type": item.item_type,
        "question_md": item.question_md,
        # Preserve the audited source transcription exactly.  Strict option
        # normalization happens only at the practice-materialization gate.
        "options": item.options,
        "accepted_answers": item.accepted_answers,
        "solution_md": item.solution_md,
        "subject_code": item.subject_code.upper() if item.subject_code else None,
        "topic_slug": item.topic_slug,
        "syllabus_status": item.syllabus_status,
        "transcription_status": item.transcription_status,
        "answer_status": item.answer_status,
        "classification_status": item.classification_status,
        "practice_eligible": item.practice_eligible,
        "review_flags": list(item.review_flags),
        "assets": [asset.model_dump(mode="json") for asset in item.assets],
        "source_references": [
            reference.model_dump(mode="json") for reference in item.source_references
        ],
        "extraction_method": item.extraction_method,
        "extraction_confidence": item.extraction_confidence,
        "content_sha256": _content_sha256(item),
    }


def _changed(model: Any, values: dict[str, Any]) -> bool:
    return any(getattr(model, field) != value for field, value in values.items())


def _resolved_practice_values(
    item: ArchiveQuestion,
    paper: ArchivePaper,
    *,
    subjects_by_code: dict[str, Subject],
    topics_by_scope: dict[tuple[int, str], Topic],
) -> dict[str, Any]:
    subject = subjects_by_code.get(str(item.subject_code).upper())
    if subject is None:
        raise PyqArchiveValidationError(
            f"{paper.id}/{item.item_label}: unknown course {item.subject_code!r}"
        )
    topic = topics_by_scope.get((subject.id, _slug(str(item.topic_slug))))
    if topic is None:
        raise PyqArchiveValidationError(
            f"{paper.id}/{item.item_label}: topic {item.topic_slug!r} is not in "
            f"{subject.code}"
        )
    question_type = QuestionType(item.item_type)
    options = _options(item.options)
    if question_type != QuestionType.NAT and len(options) < 2:
        raise PyqArchiveValidationError(
            f"{paper.id}/{item.item_label}: MCQ/MSQ needs at least two options"
        )
    if question_type == QuestionType.NAT and options:
        raise PyqArchiveValidationError(
            f"{paper.id}/{item.item_label}: NAT cannot contain options"
        )
    try:
        answer = _answer(
            item.accepted_answers,
            question_type,
            {option["id"] for option in options},
        )
    except ValueError as exc:
        raise PyqArchiveValidationError(
            f"{paper.id}/{item.item_label}: {exc}"
        ) from exc
    try:
        assets = public_question_assets(item.assets, paper_id=paper.id)
    except QuestionAssetValidationError as exc:
        raise PyqArchiveValidationError(
            f"{paper.id}/{item.item_label}: invalid promoted asset: {exc}"
        ) from exc
    return {
        "external_id": f"pyq:{paper.id}:{_slug(item.item_label)}",
        # Archive-managed rows remain outside the globally authoritative bank
        # version so a normal full-bank bootstrap cannot retire them.
        "bank_version": None,
        "is_active": True,
        "subject_id": subject.id,
        "topic_id": topic.id,
        "source": QuestionSource.PREVIOUS_YEAR,
        "year": paper.year,
        "exam_session": paper.session_label,
        "source_kind": QuestionSource.PREVIOUS_YEAR,
        "source_year": paper.year,
        "source_paper": paper.id,
        "source_question_number": item.ordinal,
        "source_paper_id": paper.id,
        "source_item_label": item.item_label,
        "source_page": item.source_page,
        "source_url": paper.source_url,
        "answer_key_url": paper.answer_key_url,
        "extraction_method": item.extraction_method,
        "extraction_confidence": item.extraction_confidence,
        "question_type": question_type,
        "difficulty": Difficulty.MEDIUM,
        "text": str(item.question_md),
        "options": options,
        "correct_answer": answer,
        "numerical_tolerance": 0.01,
        "marks": int(float(item.marks or 1)),
        "explanation": str(item.solution_md),
        "tags": ["pyq", str(paper.year), paper.id, item.item_label],
        "assets": assets,
    }


async def import_pyq_archive(
    session: AsyncSession,
    path: Path,
    *,
    dry_run: bool = True,
    materialize: bool = False,
    expected_original_count: int | None = None,
    unsafe_allow_unpinned_original_count: bool = False,
    allow_retire: bool = False,
    expected_retirement_count: int | None = None,
    expected_active_pyqs_before: int | None = None,
    expected_active_pyqs_after: int | None = None,
) -> PyqArchiveImportResult:
    """Validate and apply one immutable, paper-scoped PYQ artifact.

    ``dry_run`` is the default.  Materialization is opt-in and can only touch
    previous-year rows belonging to papers declared in this artifact.
    """

    if (
        not dry_run
        and expected_original_count is None
        and not unsafe_allow_unpinned_original_count
    ):
        raise PyqArchiveValidationError(
            "Live archive applies require expected_original_count; pass the "
            "reviewed baseline or explicitly opt into the unsafe unpinned override"
        )
    guard_values = {
        "expected_original_count": expected_original_count,
        "expected_retirement_count": expected_retirement_count,
        "expected_active_pyqs_before": expected_active_pyqs_before,
        "expected_active_pyqs_after": expected_active_pyqs_after,
    }
    for name, value in guard_values.items():
        if value is not None and value < 0:
            raise PyqArchiveValidationError(f"{name} cannot be negative")
    retirement_guards = (
        expected_retirement_count,
        expected_active_pyqs_before,
        expected_active_pyqs_after,
    )
    if allow_retire and not materialize:
        raise PyqArchiveValidationError("allow_retire requires materialize=True")
    if any(value is not None for value in retirement_guards) and not allow_retire:
        raise PyqArchiveValidationError(
            "Retirement expectations require the explicit allow_retire flag"
        )
    if allow_retire and any(value is None for value in retirement_guards):
        raise PyqArchiveValidationError(
            "allow_retire requires expected_retirement_count and exact active-PYQ "
            "before/after guards"
        )

    document, checksum = _load_document(path)
    visibility_plan = (
        _validated_pyq_visibility_plan(document, checksum) if allow_retire else None
    )
    if visibility_plan is not None:
        reviewed_guards = (
            expected_original_count,
            expected_retirement_count,
            expected_active_pyqs_before,
            expected_active_pyqs_after,
        )
        required_guards = (
            visibility_plan.expected_active_originals,
            visibility_plan.expected_retirements,
            visibility_plan.expected_active_pyqs_before,
            visibility_plan.expected_active_pyqs_after,
        )
        if reviewed_guards != required_guards:
            raise PyqArchiveValidationError(
                "allow_retire guards do not equal the fingerprint-bound visibility "
                f"plan ({reviewed_guards!r} != {required_guards!r})"
            )
    previous_version_rows = list(
        (
            await session.scalars(
                select(PyqArchiveImport).where(
                    PyqArchiveImport.artifact_version == document.artifact_version
                )
            )
        ).all()
    )
    conflicting_checksums = {
        row.checksum for row in previous_version_rows if row.checksum != checksum
    }
    if conflicting_checksums:
        raise PyqArchiveValidationError(
            f"Artifact version {document.artifact_version!r} was already used with "
            "a different checksum; create a new immutable version"
        )
    exact_import = next(
        (row for row in previous_version_rows if row.checksum == checksum), None
    )

    paper_ids = [paper.id for paper in document.papers]
    existing_papers = {
        paper.id: paper
        for paper in (
            await session.scalars(
                select(PyqSourcePaper).where(PyqSourcePaper.id.in_(paper_ids))
            )
        ).all()
    }
    existing_source_questions = list(
        (
            await session.scalars(
                select(PyqSourceQuestion).where(
                    PyqSourceQuestion.source_paper_id.in_(paper_ids)
                )
            )
        ).all()
    )
    by_paper_ordinal = {
        (item.source_paper_id, item.ordinal): item
        for item in existing_source_questions
    }

    subjects = list((await session.scalars(select(Subject))).all())
    topics = list((await session.scalars(select(Topic))).all())
    subjects_by_code = {subject.code.upper(): subject for subject in subjects}
    subject_codes_by_id = {subject.id: subject.code.upper() for subject in subjects}
    topics_by_scope = {
        (topic.subject_id, _slug(topic.slug)): topic for topic in topics
    }
    topic_slugs_by_id = {topic.id: topic.slug for topic in topics}
    all_pyqs = list(
        (
            await session.scalars(
                select(Question).where(
                    Question.source_kind == QuestionSource.PREVIOUS_YEAR
                )
            )
        ).all()
    )
    linked_question_ids = {
        item.materialized_question_id
        for item in existing_source_questions
        if item.materialized_question_id is not None
    }
    paper_years = {paper.year for paper in document.papers}
    main_questions = list(
        (
            await session.scalars(
                select(Question).where(
                    or_(
                        Question.source_paper_id.in_(paper_ids),
                        Question.external_id.like("pyq:%"),
                        Question.id.in_(linked_question_ids),
                        and_(
                            Question.source_kind
                            == QuestionSource.PREVIOUS_YEAR,
                            or_(
                                Question.source_year.in_(paper_years),
                                Question.year.in_(paper_years),
                            ),
                        ),
                    )
                )
            )
        ).all()
    )
    main_by_external = {
        question.external_id: question
        for question in main_questions
        if question.external_id
    }
    main_by_id = {question.id: question for question in main_questions}
    legacy_by_provenance: dict[tuple[int, str, int], list[Question]] = {}
    for question in main_questions:
        if question.source_kind != QuestionSource.PREVIOUS_YEAR:
            continue
        source_year = (
            question.source_year
            if question.source_year is not None
            else question.year
        )
        if source_year is None or question.source_question_number is None:
            continue
        labels = {
            _normalized_source_label(question.source_paper),
            _normalized_source_label(question.exam_session),
        }
        for label in labels - {""}:
            legacy_by_provenance.setdefault(
                (source_year, label, question.source_question_number),
                [],
            ).append(question)

    # A source record may only control a previous-year row for its own paper.
    # Validate every existing link before any ORM object is changed so a
    # damaged legacy link cannot retire or overwrite generated originals.
    for source_item in existing_source_questions:
        if source_item.materialized_question_id is None:
            continue
        linked = main_by_id.get(source_item.materialized_question_id)
        if linked is None:
            continue
        if linked.source_kind != QuestionSource.PREVIOUS_YEAR:
            raise PyqArchiveValidationError(
                f"{source_item.source_paper_id}/{source_item.item_label}: "
                "materialized link targets a non-PYQ question"
            )
        if linked.source_paper_id not in {None, source_item.source_paper_id}:
            raise PyqArchiveValidationError(
                f"{source_item.source_paper_id}/{source_item.item_label}: "
                "materialized link targets another paper"
            )

    original_count = int(
        await session.scalar(
            select(func.count(Question.id)).where(
                Question.source_kind == QuestionSource.ORIGINAL,
                Question.is_active.is_(True),
            )
        )
        or 0
    )
    active_pyq_count_before = int(
        await session.scalar(
            select(func.count(Question.id)).where(
                Question.source_kind == QuestionSource.PREVIOUS_YEAR,
                Question.is_active.is_(True),
            )
        )
        or 0
    )
    if (
        expected_original_count is not None
        and original_count != expected_original_count
    ):
        raise PyqArchiveValidationError(
            "Active original-question count does not match the required baseline "
            f"({original_count} != {expected_original_count})"
        )
    if visibility_plan is not None:
        if active_pyq_count_before != visibility_plan.expected_active_pyqs_before:
            raise PyqArchiveValidationError(
                "Active PYQ count before cleanup does not match the literal reviewed "
                f"guard ({active_pyq_count_before} != "
                f"{visibility_plan.expected_active_pyqs_before})"
            )
        question_row_count = int(
            await session.scalar(select(func.count(Question.id))) or 0
        )
        if question_row_count != visibility_plan.expected_question_row_count:
            raise PyqArchiveValidationError(
                "Question-row count does not match the reviewed visibility baseline "
                f"({question_row_count} != "
                f"{visibility_plan.expected_question_row_count})"
            )
        if len(all_pyqs) != visibility_plan.expected_pyq_row_count:
            raise PyqArchiveValidationError(
                "PYQ-row count does not match the reviewed visibility baseline "
                f"({len(all_pyqs)} != {visibility_plan.expected_pyq_row_count})"
            )

    inserted = updated = unchanged = 0
    prepared_papers: list[
        tuple[ArchivePaper, dict[str, Any], PyqSourcePaper | None]
    ] = []
    for paper in document.papers:
        values = _paper_values(paper)
        existing = existing_papers.get(paper.id)
        if existing is None:
            inserted += 1
        else:
            if _changed(existing, values):
                updated += 1
            else:
                unchanged += 1
        prepared_papers.append((paper, values, existing))

    papers_by_id = {paper.id: paper for paper in document.papers}
    prepared_questions: list[
        tuple[ArchiveQuestion, dict[str, Any], PyqSourceQuestion | None]
    ] = []
    for item in document.questions:
        values = _source_question_values(item)
        existing = by_paper_ordinal.get((item.source_paper_id, item.ordinal))
        if existing is None:
            inserted += 1
        elif _changed(existing, values):
            updated += 1
        else:
            unchanged += 1
        prepared_questions.append((item, values, existing))

    # Resolve every materialization before mutating ORM objects.  A bad course,
    # topic, answer, or option therefore leaves the transaction untouched.
    resolved_materializations: dict[tuple[str, int], dict[str, Any]] = {}
    materialization_targets: dict[tuple[str, int], Question | None] = {}
    materialized_inserted = materialized_adopted = materialized_updated = 0
    linked_retirement_targets: dict[int, Question] = {}
    retirement_targets: dict[int, Question] = {}
    retired = reactivated = 0
    if materialize:
        for item, _, existing_source in prepared_questions:
            item_key = (item.source_paper_id, item.ordinal)
            linked = (
                main_by_id.get(existing_source.materialized_question_id)
                if existing_source is not None
                and existing_source.materialized_question_id is not None
                else None
            )
            if not item.practice_eligible:
                if linked is not None and linked.is_active:
                    linked_retirement_targets[linked.id] = linked
                continue

            paper = papers_by_id[item.source_paper_id]
            materialized_values = _resolved_practice_values(
                item,
                paper,
                subjects_by_code=subjects_by_code,
                topics_by_scope=topics_by_scope,
            )
            resolved_materializations[item_key] = materialized_values

            candidates: dict[int, Question] = {}
            if linked is not None:
                candidates[linked.id] = linked
            canonical = main_by_external.get(materialized_values["external_id"])
            if canonical is not None:
                candidates[canonical.id] = canonical
            for alias in _paper_source_aliases(paper):
                for legacy_ordinal in item.legacy_source_ordinals or [item.ordinal]:
                    for legacy in legacy_by_provenance.get(
                        (paper.year, alias, legacy_ordinal),
                        [],
                    ):
                        candidates[legacy.id] = legacy

            for candidate in candidates.values():
                if candidate.source_kind != QuestionSource.PREVIOUS_YEAR:
                    raise PyqArchiveValidationError(
                        f"{paper.id}/{item.item_label}: canonical identity "
                        "collides with a non-PYQ question"
                    )
                if candidate.source_paper_id not in {None, paper.id}:
                    raise PyqArchiveValidationError(
                        f"{paper.id}/{item.item_label}: canonical identity "
                        "collides with another paper"
                    )
            if len(candidates) > 1:
                target = _select_evidence_backed_collision_candidate(
                    paper=paper,
                    item=item,
                    materialized_values=materialized_values,
                    candidates=candidates,
                    subject_codes_by_id=subject_codes_by_id,
                    topic_slugs_by_id=topic_slugs_by_id,
                )
            else:
                target = next(iter(candidates.values()), None)
            materialization_targets[item_key] = target
            if target is None:
                materialized_inserted += 1
                continue

            target_is_linked = (
                existing_source is not None
                and existing_source.materialized_question_id == target.id
            )
            target_is_canonical = (
                target.external_id == materialized_values["external_id"]
                and target.source_paper_id == paper.id
                and target.source_item_label == item.item_label
                and target.source_question_number == item.ordinal
            )
            if not target_is_linked or not target_is_canonical:
                materialized_adopted += 1
            elif _changed(target, materialized_values):
                materialized_updated += 1
            if not target.is_active:
                reactivated += 1

    if visibility_plan is not None:
        reviewed_keep_keys = {
            (entry["source_paper_id"], entry["ordinal"])
            for entry in visibility_plan.keep_records
        }
        if set(resolved_materializations) != reviewed_keep_keys:
            raise PyqArchiveValidationError(
                "Resolved practice identities do not equal the reviewed keep ledger"
            )
        selected_targets = [
            materialization_targets[key] for key in sorted(reviewed_keep_keys)
        ]
        if (
            materialized_inserted
            or any(target is None for target in selected_targets)
            or len({target.id for target in selected_targets if target is not None})
            != visibility_plan.practice_eligible_count
        ):
            raise PyqArchiveValidationError(
                "Visibility cleanup requires exactly the reviewed existing keep rows; "
                "insertion or identity reuse is forbidden"
            )
        keep_targets = {
            target.id: target for target in selected_targets if target is not None
        }
        if any(not target.is_active for target in keep_targets.values()):
            raise PyqArchiveValidationError(
                "A reviewed keep row is inactive before the guarded cleanup"
            )
        candidate_retirements = {
            question.id: question
            for question in all_pyqs
            if question.is_active and question.id not in keep_targets
        }
        fingerprint_rows: dict[str, list[Question]] = {}
        for question in all_pyqs:
            fingerprint = _legacy_candidate_fingerprint(
                question,
                subject_codes_by_id=subject_codes_by_id,
                topic_slugs_by_id=topic_slugs_by_id,
            )
            fingerprint_rows.setdefault(fingerprint, []).append(question)
        ambiguous_fingerprints = {
            fingerprint
            for fingerprint in visibility_plan.retire_fingerprints
            if len(fingerprint_rows.get(fingerprint, [])) != 1
        }
        if ambiguous_fingerprints:
            raise PyqArchiveValidationError(
                "PYQ visibility retirement ledger has missing or ambiguous rows"
            )
        actual_retire_fingerprints = {
            _legacy_candidate_fingerprint(
                question,
                subject_codes_by_id=subject_codes_by_id,
                topic_slugs_by_id=topic_slugs_by_id,
            )
            for question in candidate_retirements.values()
        }
        if actual_retire_fingerprints != visibility_plan.retire_fingerprints:
            raise PyqArchiveValidationError(
                "Active non-promoted PYQs do not exactly match the reviewed "
                "retirement fingerprint ledger"
            )
        retirement_targets = candidate_retirements
        retired = len(retirement_targets)
    else:
        retirement_targets = linked_retirement_targets
        retired = len(retirement_targets)

    materialized_count = (
        materialized_inserted + materialized_adopted + materialized_updated
    )
    planned_active_pyq_count_after = (
        active_pyq_count_before + materialized_inserted + reactivated - retired
    )
    if allow_retire:
        if expected_retirement_count != retired:
            raise PyqArchiveValidationError(
                "Planned PYQ retirement count does not match the reviewed guard "
                f"({retired} != {expected_retirement_count})"
            )
        if expected_active_pyqs_before != active_pyq_count_before:
            raise PyqArchiveValidationError(
                "Active PYQ count before import does not match the reviewed guard "
                f"({active_pyq_count_before} != {expected_active_pyqs_before})"
            )
        if expected_active_pyqs_after != planned_active_pyq_count_after:
            raise PyqArchiveValidationError(
                "Planned active PYQ count after import does not match the reviewed "
                f"guard ({planned_active_pyq_count_after} != "
                f"{expected_active_pyqs_after})"
            )
    elif retired and not dry_run:
        raise PyqArchiveValidationError(
            f"Import would retire {retired} active PYQ row(s); preview the plan, "
            "then pass allow_retire with exact retirement and active-PYQ "
            "before/after guards"
        )

    if dry_run:
        return PyqArchiveImportResult(
            artifact_version=document.artifact_version,
            checksum=checksum,
            paper_count=len(document.papers),
            item_count=len(document.questions),
            inserted_count=inserted,
            updated_count=updated,
            unchanged_count=unchanged,
            materialized_count=materialized_count,
            materialized_inserted_count=materialized_inserted,
            materialized_adopted_count=materialized_adopted,
            materialized_updated_count=materialized_updated,
            retired_count=retired,
            reactivated_count=reactivated,
            visibility_plan_sha256=(
                visibility_plan.plan_sha256 if visibility_plan is not None else None
            ),
            original_active_count=original_count,
            active_pyq_count_before=active_pyq_count_before,
            active_pyq_count_after=planned_active_pyq_count_after,
            retirement_approval_required=bool(retired and not allow_retire),
            already_applied=exact_import is not None and not any(
                (inserted, updated, materialized_count, retired)
            ),
            dry_run=True,
            execution_id=None,
        )

    for paper, values, existing in prepared_papers:
        if existing is None:
            session.add(PyqSourcePaper(id=paper.id, **values))
        else:
            for field, value in values.items():
                setattr(existing, field, value)
    await session.flush()

    source_models: dict[tuple[str, int], PyqSourceQuestion] = {}
    for item, values, existing in prepared_questions:
        source_model = existing
        if source_model is None:
            source_model = PyqSourceQuestion(
                source_paper_id=item.source_paper_id,
                **values,
            )
            session.add(source_model)
        else:
            for field, value in values.items():
                setattr(source_model, field, value)
        source_models[(item.source_paper_id, item.ordinal)] = source_model
    await session.flush()

    if materialize:
        for item, _, existing_source in prepared_questions:
            item_key = (item.source_paper_id, item.ordinal)
            source_model = source_models[item_key]
            materialized_values = resolved_materializations.get(item_key)
            linked = (
                main_by_id.get(existing_source.materialized_question_id)
                if existing_source is not None
                and existing_source.materialized_question_id is not None
                else None
            )
            if materialized_values is None:
                continue

            question = materialization_targets[item_key]
            if question is None:
                question = Question(**materialized_values)
                session.add(question)
                await session.flush()
                main_by_external[question.external_id] = question
                main_by_id[question.id] = question
            elif _changed(question, materialized_values):
                for field, value in materialized_values.items():
                    setattr(question, field, value)
            source_model.materialized_question_id = question.id

        for question in retirement_targets.values():
            # Reaching this loop on a live apply means the exact reviewed
            # artifact, fingerprint ledger, and before/after guards all passed.
            question.is_active = False

    await session.flush()
    if visibility_plan is not None:
        try:
            await rebuild_test_catalog(session, commit=False)
            await session.flush()
            await validate_test_catalog(session)
        except Exception as exc:
            await session.rollback()
            raise PyqArchiveValidationError(
                "Test catalog rebuild failed inside the guarded visibility "
                "transaction"
            ) from exc
    original_count_after = int(
        await session.scalar(
            select(func.count(Question.id)).where(
                Question.source_kind == QuestionSource.ORIGINAL,
                Question.is_active.is_(True),
            )
        )
        or 0
    )
    if original_count_after != original_count:
        await session.rollback()
        raise PyqArchiveValidationError(
            "PYQ import changed the active original-question count "
            f"({original_count} -> {original_count_after})"
        )
    active_pyq_count_after = int(
        await session.scalar(
            select(func.count(Question.id)).where(
                Question.source_kind == QuestionSource.PREVIOUS_YEAR,
                Question.is_active.is_(True),
            )
        )
        or 0
    )
    if active_pyq_count_after != planned_active_pyq_count_after:
        await session.rollback()
        raise PyqArchiveValidationError(
            "Active PYQ count changed outside the reviewed plan "
            f"({planned_active_pyq_count_after} planned, "
            f"{active_pyq_count_after} observed)"
        )
    if visibility_plan is not None:
        active_pyq_external_ids = list(
            (
                await session.scalars(
                    select(Question.external_id).where(
                        Question.source_kind == QuestionSource.PREVIOUS_YEAR,
                        Question.is_active.is_(True),
                    )
                )
            ).all()
        )
        question_row_count_after = int(
            await session.scalar(select(func.count(Question.id))) or 0
        )
        pyq_row_count_after = int(
            await session.scalar(
                select(func.count(Question.id)).where(
                    Question.source_kind == QuestionSource.PREVIOUS_YEAR
                )
            )
            or 0
        )
        archive_row_count_after = int(
            await session.scalar(select(func.count(PyqSourceQuestion.id))) or 0
        )
        if (
            len(active_pyq_external_ids) != len(visibility_plan.keep_external_ids)
            or set(active_pyq_external_ids) != visibility_plan.keep_external_ids
            or None in active_pyq_external_ids
            or question_row_count_after
            != visibility_plan.expected_question_row_count
            or pyq_row_count_after != visibility_plan.expected_pyq_row_count
            or archive_row_count_after != visibility_plan.archive_record_count
            or any(question.is_active for question in retirement_targets.values())
        ):
            await session.rollback()
            raise PyqArchiveValidationError(
                "Post-cleanup visibility does not exactly equal the reviewed "
                "promotion allowlist"
            )

    archive_import = exact_import
    if exact_import is None:
        archive_import = PyqArchiveImport(
            schema_version=document.schema_version,
            artifact_version=document.artifact_version,
            checksum=checksum,
            source_path=str(path),
            paper_count=len(document.papers),
            item_count=len(document.questions),
            inserted_count=inserted,
            updated_count=updated,
            unchanged_count=unchanged,
            materialized_count=materialized_count,
            retired_count=retired,
        )
        session.add(archive_import)
        await session.flush()
    assert archive_import is not None and archive_import.id is not None
    execution = PyqArchiveExecution(
        archive_import_id=archive_import.id,
        artifact_version=document.artifact_version,
        checksum=checksum,
        execution_mode=(
            "materialize_retire"
            if visibility_plan is not None
            else ("materialize" if materialize else "archive_only")
        ),
        inserted_count=inserted,
        updated_count=updated,
        unchanged_count=unchanged,
        materialized_inserted_count=materialized_inserted,
        materialized_adopted_count=materialized_adopted,
        materialized_updated_count=materialized_updated,
        retired_count=retired,
        reactivated_count=reactivated,
        visibility_plan_sha256=(
            visibility_plan.plan_sha256 if visibility_plan is not None else None
        ),
        original_active_before=original_count,
        original_active_after=original_count_after,
        pyq_active_before=active_pyq_count_before,
        pyq_active_after=active_pyq_count_after,
        expected_original_count=expected_original_count,
        original_guard_bypassed=expected_original_count is None,
        retirement_allowed=allow_retire,
        expected_retirement_count=expected_retirement_count,
        expected_reactivation_count=None,
        expected_active_pyqs_before=expected_active_pyqs_before,
        expected_active_pyqs_after=expected_active_pyqs_after,
    )
    session.add(execution)
    await session.flush()
    execution_id = execution.id
    await session.commit()
    return PyqArchiveImportResult(
        artifact_version=document.artifact_version,
        checksum=checksum,
        paper_count=len(document.papers),
        item_count=len(document.questions),
        inserted_count=inserted,
        updated_count=updated,
        unchanged_count=unchanged,
        materialized_count=materialized_count,
        materialized_inserted_count=materialized_inserted,
        materialized_adopted_count=materialized_adopted,
        materialized_updated_count=materialized_updated,
        retired_count=retired,
        reactivated_count=reactivated,
        visibility_plan_sha256=(
            visibility_plan.plan_sha256 if visibility_plan is not None else None
        ),
        original_active_count=original_count_after,
        active_pyq_count_before=active_pyq_count_before,
        active_pyq_count_after=active_pyq_count_after,
        retirement_approval_required=False,
        already_applied=exact_import is not None and not any(
            (inserted, updated, materialized_count, retired)
        ),
        dry_run=False,
        execution_id=execution_id,
    )


async def restore_pyq_visibility(
    session: AsyncSession,
    path: Path,
    *,
    dry_run: bool = True,
    expected_original_count: int,
    expected_reactivation_count: int,
    expected_active_pyqs_before: int,
    expected_active_pyqs_after: int,
) -> PyqVisibilityRecoveryResult:
    """Reactivate only the exact rows retired by the reviewed visibility plan.

    This is intentionally a separate operation from archive import.  It never
    inserts, updates, or deletes archive/question rows and refuses to run unless
    the database is exactly at the reviewed 177-row visible state.
    """

    document, checksum = _load_document(path)
    plan = _validated_pyq_visibility_plan(document, checksum)
    supplied_guards = (
        expected_original_count,
        expected_reactivation_count,
        expected_active_pyqs_before,
        expected_active_pyqs_after,
    )
    required_guards = (
        plan.expected_active_originals,
        plan.expected_reactivations,
        plan.expected_recovery_active_pyqs_before,
        plan.expected_recovery_active_pyqs_after,
    )
    if supplied_guards != required_guards:
        raise PyqArchiveValidationError(
            "Recovery guards do not equal the fingerprint-bound visibility plan "
            f"({supplied_guards!r} != {required_guards!r})"
        )

    archive_imports = list(
        (
            await session.scalars(
                select(PyqArchiveImport).where(
                    PyqArchiveImport.artifact_version == document.artifact_version,
                    PyqArchiveImport.checksum == checksum,
                )
            )
        ).all()
    )
    if len(archive_imports) != 1:
        raise PyqArchiveValidationError(
            "Recovery requires exactly one prior import of the reviewed artifact"
        )
    archive_import = archive_imports[0]

    subjects = list((await session.scalars(select(Subject))).all())
    topics = list((await session.scalars(select(Topic))).all())
    subject_codes_by_id = {subject.id: subject.code.upper() for subject in subjects}
    topic_slugs_by_id = {topic.id: topic.slug for topic in topics}
    all_questions = list((await session.scalars(select(Question))).all())
    all_pyqs = [
        question
        for question in all_questions
        if question.source_kind == QuestionSource.PREVIOUS_YEAR
    ]
    original_count = sum(
        question.is_active
        and question.source_kind == QuestionSource.ORIGINAL
        for question in all_questions
    )
    active_pyqs = [question for question in all_pyqs if question.is_active]
    if original_count != expected_original_count:
        raise PyqArchiveValidationError(
            "Active original-question count does not match the recovery guard "
            f"({original_count} != {expected_original_count})"
        )
    if len(active_pyqs) != expected_active_pyqs_before:
        raise PyqArchiveValidationError(
            "Active PYQ count before recovery does not match the reviewed guard "
            f"({len(active_pyqs)} != {expected_active_pyqs_before})"
        )
    if (
        len(all_questions) != plan.expected_question_row_count
        or len(all_pyqs) != plan.expected_pyq_row_count
    ):
        raise PyqArchiveValidationError(
            "Question/PYQ row counts do not match the reviewed recovery baseline"
        )
    active_external_ids = [question.external_id for question in active_pyqs]
    if (
        len(active_external_ids) != len(plan.keep_external_ids)
        or set(active_external_ids) != plan.keep_external_ids
        or None in active_external_ids
    ):
        raise PyqArchiveValidationError(
            "Active PYQs before recovery do not equal the promoted keep ledger"
        )
    archive_row_count = int(
        await session.scalar(select(func.count(PyqSourceQuestion.id))) or 0
    )
    if archive_row_count != plan.archive_record_count:
        raise PyqArchiveValidationError(
            "Archive record count does not match the reviewed recovery baseline"
        )

    fingerprint_rows: dict[str, list[Question]] = {}
    for question in all_pyqs:
        fingerprint = _legacy_candidate_fingerprint(
            question,
            subject_codes_by_id=subject_codes_by_id,
            topic_slugs_by_id=topic_slugs_by_id,
        )
        fingerprint_rows.setdefault(fingerprint, []).append(question)
    restore_targets: list[Question] = []
    for fingerprint in plan.retire_fingerprints:
        matches = fingerprint_rows.get(fingerprint, [])
        if len(matches) != 1:
            raise PyqArchiveValidationError(
                "PYQ recovery ledger has a missing or ambiguous row"
            )
        target = matches[0]
        if target.is_active:
            raise PyqArchiveValidationError(
                "PYQ recovery target is already active; refusing a partial recovery"
            )
        restore_targets.append(target)
    inactive_pyqs = [question for question in all_pyqs if not question.is_active]
    if (
        len(restore_targets) != expected_reactivation_count
        or {question.id for question in restore_targets}
        != {question.id for question in inactive_pyqs}
        or len(active_pyqs) + len(restore_targets) != expected_active_pyqs_after
    ):
        raise PyqArchiveValidationError(
            "Inactive PYQs do not exactly equal the fingerprint-bound recovery ledger"
        )

    if dry_run:
        return PyqVisibilityRecoveryResult(
            artifact_version=document.artifact_version,
            checksum=checksum,
            visibility_plan_sha256=plan.plan_sha256,
            reactivated_count=len(restore_targets),
            original_active_count=original_count,
            active_pyq_count_before=len(active_pyqs),
            active_pyq_count_after=len(active_pyqs) + len(restore_targets),
            dry_run=True,
            execution_id=None,
        )

    for question in restore_targets:
        question.is_active = True
    await session.flush()
    try:
        await rebuild_test_catalog(session, commit=False)
        await session.flush()
        await validate_test_catalog(session)
    except Exception as exc:
        await session.rollback()
        raise PyqArchiveValidationError(
            "Test catalog rebuild failed inside the guarded recovery transaction"
        ) from exc
    original_count_after = int(
        await session.scalar(
            select(func.count(Question.id)).where(
                Question.source_kind == QuestionSource.ORIGINAL,
                Question.is_active.is_(True),
            )
        )
        or 0
    )
    active_pyq_count_after = int(
        await session.scalar(
            select(func.count(Question.id)).where(
                Question.source_kind == QuestionSource.PREVIOUS_YEAR,
                Question.is_active.is_(True),
            )
        )
        or 0
    )
    question_row_count_after = int(
        await session.scalar(select(func.count(Question.id))) or 0
    )
    if (
        original_count_after != original_count
        or active_pyq_count_after != expected_active_pyqs_after
        or question_row_count_after != plan.expected_question_row_count
    ):
        await session.rollback()
        raise PyqArchiveValidationError(
            "Recovery changed rows outside the exact reviewed visibility plan"
        )

    execution = PyqArchiveExecution(
        archive_import_id=archive_import.id,
        artifact_version=document.artifact_version,
        checksum=checksum,
        execution_mode="visibility_restore",
        inserted_count=0,
        updated_count=0,
        unchanged_count=0,
        materialized_inserted_count=0,
        materialized_adopted_count=0,
        materialized_updated_count=0,
        retired_count=0,
        reactivated_count=len(restore_targets),
        visibility_plan_sha256=plan.plan_sha256,
        original_active_before=original_count,
        original_active_after=original_count_after,
        pyq_active_before=len(active_pyqs),
        pyq_active_after=active_pyq_count_after,
        expected_original_count=expected_original_count,
        original_guard_bypassed=False,
        retirement_allowed=False,
        expected_retirement_count=None,
        expected_reactivation_count=expected_reactivation_count,
        expected_active_pyqs_before=expected_active_pyqs_before,
        expected_active_pyqs_after=expected_active_pyqs_after,
    )
    session.add(execution)
    await session.flush()
    execution_id = execution.id
    await session.commit()
    return PyqVisibilityRecoveryResult(
        artifact_version=document.artifact_version,
        checksum=checksum,
        visibility_plan_sha256=plan.plan_sha256,
        reactivated_count=len(restore_targets),
        original_active_count=original_count_after,
        active_pyq_count_before=len(active_pyqs),
        active_pyq_count_after=active_pyq_count_after,
        dry_run=False,
        execution_id=execution_id,
    )
