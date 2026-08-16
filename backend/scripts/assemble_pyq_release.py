"""Assemble the checksum-bound, expanded GATE CSE PYQ staging release.

The upstream extraction pipeline deliberately emits several independent,
review-first artifacts.  This module is the single deterministic join point:
it verifies every available lineage hash, merges only evidence whose status is
strong enough for that field, and expands the audited 1996-2002 descriptive
parents into independently gradable archive records.

The generated archive is compatible with :mod:`app.pyq_archive`, but remains
staging-only: every ``practice_eligible`` value is false and this command never
opens a database.  The companion report distinguishes source-record release
readiness from the stricter auto-gradable practice gate.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlparse


REPO_DIR = Path(__file__).resolve().parents[2]
BUILD_DIR = REPO_DIR / "tmp" / "pyq" / "build"
DEFAULT_CANONICAL = BUILD_DIR / "canonical_pyq_archive.json"
DEFAULT_CANONICAL_REPORT = BUILD_DIR / "canonical_pyq_archive.report.json"
DEFAULT_RAW_CANDIDATES = BUILD_DIR / "canonical_pyq_candidates.json"
DEFAULT_CANDIDATES = BUILD_DIR / "canonical_pyq_candidates_structured.json"
DEFAULT_CANDIDATE_REPORT = BUILD_DIR / "canonical_pyq_candidates.report.json"
DEFAULT_PROVENANCE = BUILD_DIR / "original_pdf_provenance.json"
DEFAULT_OVERLAY = BUILD_DIR / "original_question_transcription_overlay.json"
DEFAULT_ANSWER_INDEX = (
    REPO_DIR
    / "tmp"
    / "pyq"
    / "reference"
    / "answer-keys"
    / "pyq_answer_key_index.json"
)
DEFAULT_LEGACY_AUDIT = (
    REPO_DIR / "backend" / "data" / "legacy_pyq_subparts_1996_2002.json"
)
DEFAULT_MANIFEST = REPO_DIR / "backend" / "data" / "pyq_source_manifest.json"
DEFAULT_TOPIC_POLICY = REPO_DIR / "backend" / "data" / "pyq_topic_aliases.json"
DEFAULT_SLOT_POLICY = (
    REPO_DIR / "backend" / "data" / "pyq_slot_classification_overrides.json"
)
DEFAULT_LEGACY_CHILD_POLICY = (
    REPO_DIR / "backend" / "data" / "pyq_legacy_child_classifications.json"
)
DEFAULT_TOPIC_INVENTORY = (
    REPO_DIR / "backend" / "data" / "question_bank_manifest.json"
)
DEFAULT_MATCHER = BUILD_DIR / "pyq_transcription_matches.json"
DEFAULT_CONTENT_LEDGER = BUILD_DIR / "verified_pyq_content.json"
DEFAULT_FIGURE_ASSETS = BUILD_DIR / "pyq_figure_assets.json"
DEFAULT_SOURCE_VERIFICATION = BUILD_DIR / "pyq_paper_source_verification.json"
DEFAULT_CLASSIFICATION_REVIEW_BASE = (
    REPO_DIR / "backend" / "data" / "pyq_classification_review_base.json"
)
DEFAULT_CLASSIFICATION_REVIEW_OVERRIDES = (
    REPO_DIR / "backend" / "data" / "pyq_classification_review_overrides.json"
)
DEFAULT_OUTPUT = BUILD_DIR / "final_pyq_release.json"
DEFAULT_REPORT = BUILD_DIR / "final_pyq_release.report.json"

SCHEMA_VERSION = "1.0"
REPORT_SCHEMA_VERSION = "1.0-staging-final-pyq-release"
EXPECTED_PAPER_COUNT = 39
EXPECTED_PARENT_SLOT_COUNT = 2712
EXPECTED_EXPANDED_RECORD_COUNT = 2873
EXPECTED_FINAL_CLASSIFICATION_COUNTS = {
    "mapped": 2791,
    "out_of_syllabus": 67,
    "review": 15,
}
LEGACY_PAPER_IDS = {f"gate-cs-{year}" for year in range(1996, 2003)}
OBJECTIVE_TYPES = {"mcq", "msq", "nat"}
VERIFIED_ANSWER_STATUSES = {"official", "secondary_two_source_agreement"}
FATAL_ANSWER_CONFLICT_KINDS = {
    "official_claim_conflict",
    "secondary_claim_conflict",
}
HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class ReleaseAssemblyError(ValueError):
    """Raised when staging evidence cannot be joined without guessing."""


_OPTION_PARSER: Any | None = None


def _option_parser() -> Any:
    """Load the repository's strict option parser without duplicating policy."""

    global _OPTION_PARSER
    if _OPTION_PARSER is not None:
        return _OPTION_PARSER
    path = Path(__file__).with_name("structure_pyq_options.py")
    spec = importlib.util.spec_from_file_location("pyq_release_option_parser", path)
    if spec is None or spec.loader is None:
        raise ReleaseAssemblyError(f"Cannot load strict option parser from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _OPTION_PARSER = module
    return module


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseAssemblyError(f"Cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReleaseAssemblyError(f"{path}: expected a JSON object")
    return value


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ReleaseAssemblyError(f"Cannot hash {path}: {exc}") from exc
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def _require_hash(value: Any, *, context: str) -> str:
    normalized = str(value or "").casefold()
    if not HASH_RE.fullmatch(normalized):
        raise ReleaseAssemblyError(f"{context}: missing or malformed SHA-256")
    return normalized


def _slug(value: str) -> str:
    folded = (
        unicodedata.normalize("NFKD", value)
        .encode("ascii", "ignore")
        .decode("ascii")
        .casefold()
    )
    return re.sub(r"[^a-z0-9]+", "-", folded).strip("-")


def _validate_embedded_hash(
    payload: Mapping[str, Any],
    *,
    field: str,
    context: str,
) -> None:
    expected = _require_hash(payload.get(field), context=f"{context}.{field}")
    core = {key: value for key, value in payload.items() if key != field}
    if _canonical_sha256(core) != expected:
        raise ReleaseAssemblyError(f"{context}: embedded {field} does not reproduce")


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_DIR).as_posix()
    except ValueError:
        return str(path.resolve())


def _binding(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    try:
        size = resolved.stat().st_size
    except OSError as exc:
        raise ReleaseAssemblyError(f"Cannot stat {resolved}: {exc}") from exc
    return {
        "path": _relative(resolved),
        "sha256": _sha256_file(resolved),
        "bytes": size,
    }


def _binding_sha(value: Any, *, context: str) -> str:
    if not isinstance(value, Mapping):
        raise ReleaseAssemblyError(f"{context}: input binding is missing")
    return _require_hash(value.get("sha256"), context=f"{context}.sha256")


def _assert_binding(
    bindings: Mapping[str, Any],
    key: str,
    path: Path,
    *,
    context: str,
) -> None:
    expected = _sha256_file(path)
    observed = _binding_sha(bindings.get(key), context=f"{context}.{key}")
    if observed != expected:
        raise ReleaseAssemblyError(
            f"{context}.{key}: stale input hash ({observed} != {expected})"
        )


def _assert_flat_binding(
    bindings: Mapping[str, Any],
    key: str,
    path: Path,
    *,
    context: str,
) -> None:
    observed = _require_hash(bindings.get(key), context=f"{context}.{key}")
    expected = _sha256_file(path)
    if observed != expected:
        raise ReleaseAssemblyError(
            f"{context}.{key}: stale input hash ({observed} != {expected})"
        )


def _assert_staging_guard(
    payload: Mapping[str, Any],
    *,
    context: str,
    required_false: Sequence[str],
) -> None:
    for field in required_false:
        if payload.get(field) is not False:
            raise ReleaseAssemblyError(f"{context}.{field} must be false")


def _slot_key(
    row: Mapping[str, Any],
    *,
    ordinal_key: str,
    context: str,
) -> tuple[str, int]:
    paper_id = str(row.get("source_paper_id") or "")
    ordinal = row.get(ordinal_key)
    if not paper_id or not isinstance(ordinal, int) or ordinal < 1:
        raise ReleaseAssemblyError(
            f"{context}: invalid slot identity {paper_id!r}/{ordinal!r}"
        )
    return paper_id, ordinal


def _unique_map(
    rows: Any,
    *,
    ordinal_key: str,
    context: str,
) -> dict[tuple[str, int], dict[str, Any]]:
    if not isinstance(rows, list):
        raise ReleaseAssemblyError(f"{context}: expected a list")
    result: dict[tuple[str, int], dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ReleaseAssemblyError(f"{context}: non-object row")
        key = _slot_key(row, ordinal_key=ordinal_key, context=context)
        if key in result:
            raise ReleaseAssemblyError(f"{context}: duplicate slot {key}")
        result[key] = row
    return result


def _validate_identity_sets(
    canonical: Mapping[tuple[str, int], Mapping[str, Any]],
    *others: tuple[str, Mapping[tuple[str, int], Mapping[str, Any]]],
) -> None:
    expected = set(canonical)
    for name, mapping in others:
        if set(mapping) != expected:
            missing = sorted(expected - set(mapping))
            extra = sorted(set(mapping) - expected)
            raise ReleaseAssemblyError(
                f"{name}: canonical identity mismatch; missing={missing[:5]}, "
                f"extra={extra[:5]}"
            )
        for key, row in mapping.items():
            if row.get("item_label") != canonical[key].get("item_label"):
                raise ReleaseAssemblyError(f"{name}: item label mismatch at {key}")


def _validate_canonical_report(
    *,
    canonical: Mapping[str, Any],
    report: Mapping[str, Any],
    manifest_path: Path,
    expected_paper_count: int,
    expected_parent_count: int,
) -> None:
    if report.get("artifact_version") != canonical.get("artifact_version"):
        raise ReleaseAssemblyError("canonical report artifact version is stale")
    invariants = report.get("invariants")
    if not isinstance(invariants, Mapping):
        raise ReleaseAssemblyError("canonical report invariants are missing")
    if invariants.get("actual_paper_count") != expected_paper_count:
        raise ReleaseAssemblyError("canonical report paper count is stale")
    if invariants.get("actual_item_count") != expected_parent_count:
        raise ReleaseAssemblyError("canonical report slot count is stale")
    inputs = report.get("inputs")
    if not isinstance(inputs, Mapping):
        raise ReleaseAssemblyError("canonical report inputs are missing")
    manifest_binding = inputs.get("manifest")
    observed = _binding_sha(manifest_binding, context="canonical report manifest")
    if observed != _sha256_file(manifest_path):
        raise ReleaseAssemblyError("canonical report is bound to a stale manifest")


def _validate_candidate_lineage(
    *,
    raw_candidates_path: Path,
    candidates: Mapping[str, Any],
    candidate_report: Mapping[str, Any],
    topic_policy_path: Path,
    slot_policy_path: Path,
    expected_paper_count: int,
    expected_parent_count: int,
) -> None:
    _assert_staging_guard(
        candidates,
        context="structured candidates",
        required_false=("database_writes_performed", "automatic_promotion_allowed"),
    )
    if candidates.get("paper_count") != expected_paper_count:
        raise ReleaseAssemblyError("structured candidate paper count is stale")
    if candidates.get("slot_count") != expected_parent_count:
        raise ReleaseAssemblyError("structured candidate slot count is stale")
    observed = _require_hash(
        candidates.get("input_artifact_sha256"),
        context="structured candidates.input_artifact_sha256",
    )
    expected = _sha256_file(raw_candidates_path)
    if observed != expected:
        raise ReleaseAssemblyError("structured candidates are bound to a stale raw artifact")

    if candidate_report.get("paper_count") != expected_paper_count:
        raise ReleaseAssemblyError("candidate report paper count is stale")
    if candidate_report.get("slot_count") != expected_parent_count:
        raise ReleaseAssemblyError("candidate report slot count is stale")
    classification = (
        (candidate_report.get("reconciliation") or {}).get("classification") or {}
    )
    if not isinstance(classification, Mapping):
        raise ReleaseAssemblyError("candidate classification report is missing")
    if classification.get("policy_sha256") != _sha256_file(topic_policy_path):
        raise ReleaseAssemblyError("candidate topic classification policy is stale")
    if classification.get("slot_policy_sha256") != _sha256_file(slot_policy_path):
        raise ReleaseAssemblyError("candidate slot classification policy is stale")
    after = classification.get("after") or {}
    if after.get("unresolved_conflicts") not in {0, None}:
        raise ReleaseAssemblyError("candidate classifications contain unresolved conflicts")


def _validate_answer_index(
    answer_index: Mapping[str, Any],
    *,
    manifest_path: Path,
    canonical_keys: set[tuple[str, int]],
) -> dict[tuple[str, int], dict[str, Any]]:
    _assert_staging_guard(
        answer_index,
        context="answer index",
        required_false=("production_import_authorized", "practice_promotion_authorized"),
    )
    core = {key: value for key, value in answer_index.items() if key != "artifact_version"}
    if _canonical_sha256(core) != _require_hash(
        answer_index.get("artifact_version"), context="answer index artifact_version"
    ):
        raise ReleaseAssemblyError("answer index artifact_version does not reproduce")
    if answer_index.get("manifest_sha256") != _sha256_file(manifest_path):
        raise ReleaseAssemblyError("answer index is bound to a stale manifest")

    conflicts = answer_index.get("conflicts") or []
    fatal = [
        row
        for row in conflicts
        if isinstance(row, Mapping)
        and row.get("kind") in FATAL_ANSWER_CONFLICT_KINDS
    ]
    if fatal:
        raise ReleaseAssemblyError(
            f"answer index contains unresolved authoritative conflicts: {fatal[:3]}"
        )

    resolutions = _unique_map(
        answer_index.get("resolutions") or [],
        ordinal_key="canonical_ordinal",
        context="answer resolutions",
    )
    if not set(resolutions).issubset(canonical_keys):
        raise ReleaseAssemblyError("answer resolutions contain unknown canonical slots")
    for key, resolution in resolutions.items():
        status = resolution.get("status")
        if status in {"official_conflict", "secondary_conflict"}:
            raise ReleaseAssemblyError(f"{key}: unresolved answer conflict")
        if status in VERIFIED_ANSWER_STATUSES and resolution.get("selected_answer") is None:
            raise ReleaseAssemblyError(f"{key}: verified resolution has no selected answer")
    return resolutions


def _validate_matcher(
    matcher: Mapping[str, Any],
    *,
    matcher_path: Path,
) -> dict[tuple[str, int], dict[str, Any]]:
    if (
        matcher.get("schema_version")
        != "1.0-staging-high-confidence-transcription-matches"
    ):
        raise ReleaseAssemblyError("transcription matcher schema version drifted")
    _assert_staging_guard(
        matcher,
        context="transcription matcher",
        required_false=(
            "database_writes_performed",
            "production_import_authorized",
            "automatic_promotion_allowed",
        ),
    )
    _validate_embedded_hash(
        matcher,
        field="artifact_sha256",
        context="transcription matcher",
    )
    bindings = matcher.get("input_bindings")
    if not isinstance(bindings, Mapping):
        raise ReleaseAssemblyError("transcription matcher input bindings are missing")
    for key, value in sorted(bindings.items()):
        if value is None:
            continue
        values = value if isinstance(value, list) else [value]
        if not values:
            raise ReleaseAssemblyError(f"matcher binding {key!r} is empty")
        for index, current in enumerate(values):
            suffix = f"[{index}]" if isinstance(value, list) else ""
            context = f"matcher binding {key}{suffix}"
            if not isinstance(current, Mapping):
                raise ReleaseAssemblyError(f"{context} is malformed")
            raw_path = current.get("path")
            if not isinstance(raw_path, str) or not raw_path.strip():
                raise ReleaseAssemblyError(f"{context} has no path")
            candidate = Path(raw_path)
            if not candidate.is_absolute():
                candidate = REPO_DIR / candidate
            observed = _binding_sha(current, context=context)
            if observed != _sha256_file(candidate):
                raise ReleaseAssemblyError(f"{context} is stale")
            expected_bytes = current.get("bytes")
            if not isinstance(expected_bytes, int) or expected_bytes < 0:
                raise ReleaseAssemblyError(f"{context} byte count is malformed")
            try:
                actual_bytes = candidate.stat().st_size
            except OSError as exc:
                raise ReleaseAssemblyError(f"Cannot stat {candidate}: {exc}") from exc
            if actual_bytes != expected_bytes:
                raise ReleaseAssemblyError(f"{context} byte count is stale")

    matches: dict[tuple[str, int], dict[str, Any]] = {}
    for row in matcher.get("matches") or []:
        if not isinstance(row, dict):
            raise ReleaseAssemblyError("matcher contains a non-object match")
        key = _slot_key(row, ordinal_key="canonical_ordinal", context="matcher")
        if key in matches:
            raise ReleaseAssemblyError(f"matcher contains duplicate match {key}")
        if row.get("match_status") != "exact_proposed_review":
            raise ReleaseAssemblyError(f"matcher {key}: unexpected match status")
        if row.get("manual_review_required") is not True:
            raise ReleaseAssemblyError(f"matcher {key}: review proposal lost its guard")
        matches[key] = row
    return matches


def _validate_recursive_input_bindings(
    bindings: Mapping[str, Any], *, context: str
) -> None:
    """Validate every scalar or list-valued path/SHA/byte binding."""

    for key, value in sorted(bindings.items()):
        values = value if isinstance(value, list) else [value]
        if not values:
            raise ReleaseAssemblyError(f"{context} binding {key!r} is empty")
        for index, current in enumerate(values):
            suffix = f"[{index}]" if isinstance(value, list) else ""
            current_context = f"{context} binding {key}{suffix}"
            if not isinstance(current, Mapping):
                raise ReleaseAssemblyError(f"{current_context} is malformed")
            raw_path = current.get("path")
            if not isinstance(raw_path, str) or not raw_path.strip():
                raise ReleaseAssemblyError(f"{current_context} has no path")
            candidate = Path(raw_path)
            if not candidate.is_absolute():
                candidate = REPO_DIR / candidate
            if _binding_sha(current, context=current_context) != _sha256_file(candidate):
                raise ReleaseAssemblyError(f"{current_context} is stale")
            expected_bytes = current.get("bytes")
            if not isinstance(expected_bytes, int) or expected_bytes < 0:
                raise ReleaseAssemblyError(f"{current_context} byte count is malformed")
            try:
                actual_bytes = candidate.stat().st_size
            except OSError as exc:
                raise ReleaseAssemblyError(f"Cannot stat {candidate}: {exc}") from exc
            if actual_bytes != expected_bytes:
                raise ReleaseAssemblyError(f"{current_context} byte count is stale")


def _validate_content_evidence(
    field: Mapping[str, Any],
    *,
    key: tuple[str, int],
    field_name: str,
    provenance: Mapping[str, Any],
) -> None:
    method = field.get("verification_method")
    if method not in {
        "checksum_bound_original_text_block",
        "mutually_unique_cross_source_original_page",
    }:
        raise ReleaseAssemblyError(
            f"content ledger {key}/{field_name}: invalid verification method"
        )
    evidence = field.get("evidence")
    if not isinstance(evidence, Mapping):
        raise ReleaseAssemblyError(
            f"content ledger {key}/{field_name}: verification evidence is missing"
        )
    if evidence.get("source_pdf_sha256") != provenance.get("source_pdf_sha256"):
        raise ReleaseAssemblyError(
            f"content ledger {key}/{field_name}: source PDF evidence drifted"
        )
    if evidence.get("source_pages") != provenance.get("source_pages"):
        raise ReleaseAssemblyError(
            f"content ledger {key}/{field_name}: source pages drifted"
        )
    if method == "checksum_bound_original_text_block":
        if evidence.get("text_block_sha256") != provenance.get("text_block_sha256"):
            raise ReleaseAssemblyError(
                f"content ledger {key}/{field_name}: text block drifted"
            )
        page_hashes = evidence.get("page_text_sha256")
        if not isinstance(page_hashes, list) or not page_hashes:
            raise ReleaseAssemblyError(
                f"content ledger {key}/{field_name}: page-text evidence is missing"
            )
        for row in page_hashes:
            if not isinstance(row, Mapping) or not isinstance(row.get("page"), int):
                raise ReleaseAssemblyError(
                    f"content ledger {key}/{field_name}: page-text evidence is malformed"
                )
            _require_hash(
                row.get("sha256"),
                context=f"content ledger {key}/{field_name} page text",
            )
    else:
        for hash_key in (
            "examside_raw_response_sha256",
            "gateoverflow_body_sha256",
            "gateoverflow_page_text_sha256",
        ):
            _require_hash(
                evidence.get(hash_key),
                context=f"content ledger {key}/{field_name} {hash_key}",
            )
        claims = evidence.get("official_resolution_claim_ids")
        if not isinstance(claims, list) or not claims:
            raise ReleaseAssemblyError(
                f"content ledger {key}/{field_name}: official answer lineage missing"
            )
        if float(evidence.get("gateoverflow_text_similarity") or 0) < 0.95:
            raise ReleaseAssemblyError(
                f"content ledger {key}/{field_name}: similarity floor failed"
            )
        renders = evidence.get("rendered_page_evidence")
        if renders is not None:
            if not isinstance(renders, list) or not renders:
                raise ReleaseAssemblyError(
                    f"content ledger {key}/{field_name}: rendered evidence is missing"
                )
            for row in renders:
                if not isinstance(row, Mapping) or not isinstance(row.get("page"), int):
                    raise ReleaseAssemblyError(
                        f"content ledger {key}/{field_name}: rendered evidence is malformed"
                    )
                _require_hash(
                    row.get("sha256"),
                    context=f"content ledger {key}/{field_name} render",
                )
            if evidence.get("text_block_sha256") is not None or evidence.get(
                "text_similarity"
            ) is not None:
                raise ReleaseAssemblyError(
                    f"content ledger {key}/{field_name}: page evidence mixed contracts"
                )
        else:
            if evidence.get("text_block_sha256") != provenance.get("text_block_sha256"):
                raise ReleaseAssemblyError(
                    f"content ledger {key}/{field_name}: text block drifted"
                )
            if float(evidence.get("text_similarity") or 0) < 0.95:
                raise ReleaseAssemblyError(
                    f"content ledger {key}/{field_name}: similarity floor failed"
                )


def _validate_content_field(
    field: Any,
    *,
    key: tuple[str, int],
    field_name: str,
    provenance: Mapping[str, Any],
    allowed_statuses: set[str],
) -> None:
    if not isinstance(field, Mapping):
        raise ReleaseAssemblyError(f"content ledger {key}/{field_name} is malformed")
    status = field.get("status")
    if status not in allowed_statuses:
        raise ReleaseAssemblyError(
            f"content ledger {key}/{field_name}: invalid status {status!r}"
        )
    blockers = field.get("blockers")
    if not isinstance(blockers, list) or any(
        not isinstance(value, str) or not value for value in blockers
    ):
        raise ReleaseAssemblyError(
            f"content ledger {key}/{field_name}: blockers are malformed"
        )
    if blockers != sorted(set(blockers)):
        raise ReleaseAssemblyError(
            f"content ledger {key}/{field_name}: blockers are not deterministic"
        )
    if status == "verified":
        content = field.get("content")
        if field_name == "stem":
            if (
                not isinstance(content, str)
                or not content.strip()
                or content != content.strip()
                or field.get("content_sha256") != _sha256_text(content)
            ):
                raise ReleaseAssemblyError(
                    f"content ledger {key}/stem: verified content hash drifted"
                )
        else:
            if not isinstance(content, list) or len(content) < 2:
                raise ReleaseAssemblyError(
                    f"content ledger {key}/options: verified content is incomplete"
                )
            normalized = _normalized_options(content)
            if content != normalized or field.get("content_sha256") != _canonical_sha256(
                content
            ):
                raise ReleaseAssemblyError(
                    f"content ledger {key}/options: verified content hash drifted"
                )
        if blockers:
            raise ReleaseAssemblyError(
                f"content ledger {key}/{field_name}: verified content has blockers"
            )
        _validate_content_evidence(
            field,
            key=key,
            field_name=field_name,
            provenance=provenance,
        )
        return
    if any(
        field.get(name) is not None
        for name in ("content", "content_sha256", "verification_method", "evidence")
    ):
        raise ReleaseAssemblyError(
            f"content ledger {key}/{field_name}: unverified content was retained"
        )
    if status in {"review", "missing"} and not blockers:
        raise ReleaseAssemblyError(
            f"content ledger {key}/{field_name}: unverified status has no blocker"
        )
    if status == "not_applicable" and blockers:
        raise ReleaseAssemblyError(
            f"content ledger {key}/{field_name}: N/A options have blockers"
        )


def _validate_content_ledger(
    ledger: Mapping[str, Any],
    *,
    candidates_path: Path,
    provenance_path: Path,
    overlay_path: Path,
    answer_index_path: Path,
    figure_assets_path: Path,
    canonical_map: Mapping[tuple[str, int], Mapping[str, Any]],
    provenance_map: Mapping[tuple[str, int], Mapping[str, Any]],
    expected_paper_count: int,
    expected_parent_count: int,
) -> dict[tuple[str, int], dict[str, Any]]:
    if ledger.get("schema_version") != "1.0-staging-pyq-content-verification":
        raise ReleaseAssemblyError("content verification ledger schema drifted")
    _assert_staging_guard(
        ledger,
        context="content verification ledger",
        required_false=(
            "database_writes_performed",
            "production_import_authorized",
            "automatic_promotion_allowed",
        ),
    )
    if ledger.get("practice_eligible_count") != 0:
        raise ReleaseAssemblyError("content verification ledger attempted promotion")
    _validate_embedded_hash(
        ledger, field="artifact_sha256", context="content verification ledger"
    )
    identity = ledger.get("canonical_identity")
    if not isinstance(identity, Mapping) or identity != {
        "paper_count": expected_paper_count,
        "parent_slot_count": expected_parent_count,
    }:
        raise ReleaseAssemblyError("content verification ledger identity drifted")
    policy = ledger.get("verification_policy")
    required_true = (
        "exact_original_text_block_allowed",
        "cross_source_requires_mutual_unique_match",
        "cross_source_requires_original_text_block",
        "cross_source_requires_official_answer_type_marks",
        "cross_source_requires_gateoverflow_and_examside_agreement",
        "canonical_page_options_require_exact_examside_agreement",
    )
    required_false = (
        "cross_source_latex_code_html_visual_auto_acceptance",
        "matcher_cross_source_option_auto_acceptance",
        "third_party_explanations_consumed",
    )
    if not isinstance(policy, Mapping) or any(
        policy.get(name) is not True for name in required_true
    ) or any(policy.get(name) is not False for name in required_false):
        raise ReleaseAssemblyError("content verification ledger policy drifted")
    if float(policy.get("cross_source_minimum_original_similarity") or 0) < 0.95 or float(
        policy.get("cross_source_minimum_gateoverflow_similarity") or 0
    ) < 0.95:
        raise ReleaseAssemblyError("content verification similarity floor drifted")
    bindings = ledger.get("input_bindings")
    if not isinstance(bindings, Mapping):
        raise ReleaseAssemblyError("content verification bindings are missing")
    _validate_recursive_input_bindings(bindings, context="content verification")
    for key, path in (
        ("structured_candidates", candidates_path),
        ("original_pdf_provenance", provenance_path),
        ("original_transcription_overlay", overlay_path),
        ("official_answer_index", answer_index_path),
        ("original_pdf_figure_assets", figure_assets_path),
    ):
        _assert_binding(bindings, key, path, context="content verification ledger")

    rows = _unique_map(
        ledger.get("items"),
        ordinal_key="canonical_ordinal",
        context="content verification ledger",
    )
    if set(rows) != set(canonical_map):
        raise ReleaseAssemblyError("content verification ledger coverage drifted")
    for key, row in rows.items():
        canonical = canonical_map[key]
        if row.get("item_label") != canonical.get("item_label"):
            raise ReleaseAssemblyError(f"content ledger {key}: item label drifted")
        _validate_content_field(
            row.get("stem"),
            key=key,
            field_name="stem",
            provenance=provenance_map[key],
            allowed_statuses={"verified", "review", "missing"},
        )
        _validate_content_field(
            row.get("options"),
            key=key,
            field_name="options",
            provenance=provenance_map[key],
            allowed_statuses={"verified", "review", "missing", "not_applicable"},
        )
        assets = row.get("asset_blockers")
        blockers = row.get("blockers")
        if (
            not isinstance(assets, list)
            or assets != sorted(set(assets))
            or not isinstance(blockers, list)
            or blockers
            != sorted(
                set(
                    list(row["stem"]["blockers"])
                    + list(row["options"]["blockers"])
                    + assets
                )
            )
        ):
            raise ReleaseAssemblyError(f"content ledger {key}: blocker union drifted")
        figure = row.get("figure_evidence")
        if not isinstance(figure, Mapping) or figure.get("status") not in {
            "not_required",
            "asset_ready",
            "review_required",
            "missing",
        }:
            raise ReleaseAssemblyError(f"content ledger {key}: figure evidence malformed")
        if figure.get("source_pdf_sha256") != provenance_map[key].get(
            "source_pdf_sha256"
        ) or figure.get("source_pages") != provenance_map[key].get("source_pages"):
            raise ReleaseAssemblyError(f"content ledger {key}: figure lineage drifted")
        asset_count = figure.get("asset_count")
        asset_hashes = figure.get("asset_sha256")
        if (
            not isinstance(asset_count, int)
            or asset_count < 0
            or not isinstance(asset_hashes, list)
        ):
            raise ReleaseAssemblyError(f"content ledger {key}: figure assets malformed")
        for digest in asset_hashes:
            _require_hash(digest, context=f"content ledger {key} figure asset")
        if figure.get("status") == "asset_ready" and (
            asset_count < 1 or len(asset_hashes) < 1 or assets
        ):
            raise ReleaseAssemblyError(f"content ledger {key}: ready figure is blocked")
        if figure.get("status") == "not_required" and asset_count != 0:
            raise ReleaseAssemblyError(
                f"content ledger {key}: non-required figure carries assets"
            )
    return rows


def _validated_figure_asset(
    raw: Any,
    *,
    paper_id: str,
    source_pdf_sha256: str,
    source_pages: Sequence[int],
    seen_assets: dict[str, str],
) -> dict[str, str]:
    context = f"figure asset {paper_id}"
    if not isinstance(raw, Mapping):
        raise ReleaseAssemblyError(f"{context}: asset row is malformed")
    asset_id = raw.get("asset_id")
    if not isinstance(asset_id, str) or not re.fullmatch(
        r"pyq-figure-[0-9a-f]{20}", asset_id
    ):
        raise ReleaseAssemblyError(f"{context}: asset id is malformed")
    relative_path = raw.get("relative_path")
    if (
        not isinstance(relative_path, str)
        or not relative_path
        or "\\" in relative_path
    ):
        raise ReleaseAssemblyError(f"{context}/{asset_id}: path is malformed")
    relative = Path(relative_path)
    expected_prefix = Path("tmp") / "pyq" / "build" / "figure-assets" / paper_id
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or tuple(relative.parts[: len(expected_prefix.parts)])
        != tuple(expected_prefix.parts)
        or relative.suffix.casefold() != ".png"
    ):
        raise ReleaseAssemblyError(
            f"{context}/{asset_id}: path is outside the paper figure directory"
        )
    asset_path = (REPO_DIR / relative).resolve()
    asset_root = (REPO_DIR / expected_prefix).resolve()
    if not asset_path.is_relative_to(asset_root) or not asset_path.is_file():
        raise ReleaseAssemblyError(f"{context}/{asset_id}: asset file is missing")
    digest = _require_hash(raw.get("sha256"), context=f"{context}/{asset_id}")
    if _sha256_file(asset_path) != digest:
        raise ReleaseAssemblyError(f"{context}/{asset_id}: asset hash drifted")
    expected_bytes = raw.get("bytes")
    if not isinstance(expected_bytes, int) or expected_bytes < 1:
        raise ReleaseAssemblyError(f"{context}/{asset_id}: byte count is malformed")
    if asset_path.stat().st_size != expected_bytes:
        raise ReleaseAssemblyError(f"{context}/{asset_id}: byte count drifted")
    if raw.get("media_type") != "image/png":
        raise ReleaseAssemblyError(f"{context}/{asset_id}: media type is not PNG")
    if raw.get("source_pdf_sha256") != source_pdf_sha256:
        raise ReleaseAssemblyError(f"{context}/{asset_id}: source PDF drifted")
    source_page = raw.get("source_page")
    if not isinstance(source_page, int) or source_page not in source_pages:
        raise ReleaseAssemblyError(f"{context}/{asset_id}: source page drifted")
    _require_hash(
        raw.get("source_page_render_sha256"),
        context=f"{context}/{asset_id} source render",
    )
    width = raw.get("pixel_width")
    height = raw.get("pixel_height")
    if not isinstance(width, int) or width < 1 or not isinstance(height, int) or height < 1:
        raise ReleaseAssemblyError(f"{context}/{asset_id}: pixel dimensions are invalid")
    for name in ("crop_box_pixels", "crop_box_pdf_points"):
        box = raw.get(name)
        if (
            not isinstance(box, list)
            or len(box) != 4
            or any(not isinstance(value, (int, float)) for value in box)
            or box[2] <= box[0]
            or box[3] <= box[1]
        ):
            raise ReleaseAssemblyError(f"{context}/{asset_id}: {name} is invalid")
    dpi = raw.get("render_dpi")
    if not isinstance(dpi, int) or dpi < 72:
        raise ReleaseAssemblyError(f"{context}/{asset_id}: render DPI is invalid")
    role = raw.get("asset_role")
    if (
        not isinstance(role, str)
        or len(role) > 48
        or not re.fullmatch(r"[a-z0-9]+(?:_[a-z0-9]+)*", role)
    ):
        raise ReleaseAssemblyError(f"{context}/{asset_id}: asset role is malformed")
    alt = raw.get("alt_text")
    caption = raw.get("caption")
    visual_kind = raw.get("visual_kind")
    if any(
        not isinstance(value, str) or not value.strip() or value != value.strip()
        for value in (alt, caption, visual_kind)
    ):
        raise ReleaseAssemblyError(f"{context}/{asset_id}: accessible description is missing")
    if raw.get("review_status") != "visually_reviewed_exact_bounds":
        raise ReleaseAssemblyError(f"{context}/{asset_id}: crop was not visually reviewed")
    if raw.get("origin") != "checksum_bound_original_question_paper_pdf_crop":
        raise ReleaseAssemblyError(f"{context}/{asset_id}: asset is not an original crop")
    identity = _canonical_sha256(dict(raw))
    prior = seen_assets.setdefault(asset_id, identity)
    if prior != identity:
        raise ReleaseAssemblyError(f"{context}/{asset_id}: asset id is ambiguous")
    return {"kind": role, "path": relative_path, "alt": alt, "sha256": digest}


def _figure_prompt_hashes(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        normalized = " ".join(
            unicodedata.normalize("NFKC", value).replace("\u00ad", "").split()
        )
        if not normalized:
            continue
        digest = _sha256_text(normalized)
        if digest not in result:
            result.append(digest)
    return result


def _validate_figure_asset_index(
    artifact: Mapping[str, Any],
    *,
    canonical_path: Path,
    provenance_path: Path,
    overlay_path: Path,
    legacy_path: Path,
    manifest_path: Path,
    canonical_map: Mapping[tuple[str, int], Mapping[str, Any]],
    provenance_map: Mapping[tuple[str, int], Mapping[str, Any]],
    child_map: Mapping[tuple[str, int, str], Mapping[str, Any]],
    paper_by_id: Mapping[str, Mapping[str, Any]],
    expected_paper_count: int,
    expected_parent_count: int,
) -> dict[tuple[str, int, str | None], dict[str, Any]]:
    if artifact.get("schema_version") != "1.0-staging-original-pdf-figure-assets":
        raise ReleaseAssemblyError("figure asset index schema drifted")
    _assert_staging_guard(
        artifact,
        context="figure asset index",
        required_false=(
            "database_writes_performed",
            "production_import_authorized",
            "automatic_promotion_allowed",
        ),
    )
    if artifact.get("practice_eligible_count") != 0:
        raise ReleaseAssemblyError("figure asset index attempted promotion")
    _validate_embedded_hash(artifact, field="artifact_sha256", context="figure asset index")
    expected_identity = {
        "paper_count": expected_paper_count,
        "canonical_parent_count": expected_parent_count,
        "expanded_legacy_child_count": len(child_map),
        "audited_record_count": expected_parent_count + len(child_map),
    }
    if artifact.get("identity") != expected_identity:
        raise ReleaseAssemblyError("figure asset index identity drifted")
    bindings = artifact.get("input_bindings")
    if not isinstance(bindings, Mapping):
        raise ReleaseAssemblyError("figure asset index bindings are missing")
    _validate_recursive_input_bindings(bindings, context="figure asset index")
    for name, path in (
        ("source_manifest", manifest_path),
        ("canonical_archive", canonical_path),
        ("original_pdf_provenance", provenance_path),
        ("original_transcription_overlay", overlay_path),
        ("legacy_subpart_audit", legacy_path),
    ):
        _assert_binding(bindings, name, path, context="figure asset index")

    source_files = artifact.get("source_files")
    if not isinstance(source_files, list) or len(source_files) != expected_paper_count:
        raise ReleaseAssemblyError("figure asset source-file coverage drifted")
    source_file_map: dict[str, Mapping[str, Any]] = {}
    for row in source_files:
        if not isinstance(row, Mapping):
            raise ReleaseAssemblyError("figure asset source-file row is malformed")
        paper_id = row.get("paper_id")
        if not isinstance(paper_id, str) or paper_id in source_file_map:
            raise ReleaseAssemblyError("figure asset source-file ids are duplicated")
        source_file_map[paper_id] = row
    if set(source_file_map) != set(paper_by_id):
        raise ReleaseAssemblyError("figure asset source-file paper set drifted")
    for paper_id, row in source_file_map.items():
        if row.get("source_pdf_sha256") != paper_by_id[paper_id].get("source_pdf_sha256"):
            raise ReleaseAssemblyError(f"{paper_id}: figure source PDF drifted")
        if not isinstance(row.get("source_page_count"), int) or row["source_page_count"] < 1:
            raise ReleaseAssemblyError(f"{paper_id}: figure source page count is invalid")

    raw_items = artifact.get("items")
    if not isinstance(raw_items, list) or len(raw_items) != expected_identity["audited_record_count"]:
        raise ReleaseAssemblyError("figure asset item coverage drifted")
    expected_keys: set[tuple[str, int, str | None]] = {
        (paper_id, ordinal, None) for paper_id, ordinal in canonical_map
    } | set(child_map)
    result: dict[tuple[str, int, str | None], dict[str, Any]] = {}
    seen_assets: dict[str, str] = {}
    for row in raw_items:
        if not isinstance(row, Mapping):
            raise ReleaseAssemblyError("figure asset item row is malformed")
        paper_id = row.get("source_paper_id")
        ordinal = row.get("canonical_ordinal")
        child_label = row.get("child_item_label")
        if (
            not isinstance(paper_id, str)
            or not isinstance(ordinal, int)
            or (child_label is not None and not isinstance(child_label, str))
        ):
            raise ReleaseAssemblyError("figure asset item key is malformed")
        key = paper_id, ordinal, child_label
        if key in result or key not in expected_keys:
            raise ReleaseAssemblyError(f"figure asset key is duplicated or unexpected: {key}")
        parent_key = paper_id, ordinal
        provenance = provenance_map[parent_key]
        if child_label is None:
            expected_label = canonical_map[parent_key].get("item_label")
            expected_kind = "canonical_parent"
            expected_pages = list(provenance.get("source_pages") or [])
        else:
            expected_label = child_label
            expected_kind = "expanded_legacy_child"
            expected_pages = list(child_map[(paper_id, ordinal, child_label)].get("source_pages") or [])
        if row.get("item_label") != expected_label or row.get("record_kind") != expected_kind:
            raise ReleaseAssemblyError(f"figure asset {key}: identity drifted")
        if row.get("source_pdf_sha256") != provenance.get("source_pdf_sha256"):
            raise ReleaseAssemblyError(f"figure asset {key}: source PDF drifted")
        source_pages = row.get("source_pages")
        if source_pages != sorted(set(expected_pages)):
            raise ReleaseAssemblyError(f"figure asset {key}: source pages drifted")
        prompt_hashes = row.get("prompt_text_sha256")
        if (
            not isinstance(prompt_hashes, list)
            or len(prompt_hashes) != len(set(prompt_hashes))
            or any(not isinstance(value, str) or not HASH_RE.fullmatch(value) for value in prompt_hashes)
        ):
            raise ReleaseAssemblyError(f"figure asset {key}: prompt hashes are malformed")
        if child_label is not None:
            child = child_map[(paper_id, ordinal, child_label)]
            shared = child.get("shared_context")
            shared = shared if isinstance(shared, Mapping) else {}
            expected_prompt_hashes = _figure_prompt_hashes(
                (
                    shared.get("canonical_parent_question"),
                    shared.get("additional_shared_text"),
                    child.get("prompt_text"),
                )
            )
            if prompt_hashes != expected_prompt_hashes:
                raise ReleaseAssemblyError(
                    f"figure asset {key}: normalized child prompt hashes drifted"
                )
        status = row.get("dependence_status")
        assessment = row.get("dependence_assessment")
        if status not in {"not_required", "asset_ready", "review_required", "missing"}:
            raise ReleaseAssemblyError(f"figure asset {key}: status is invalid")
        if assessment not in {"confirmed", "potential", "not_detected"}:
            raise ReleaseAssemblyError(f"figure asset {key}: assessment is invalid")
        if status == "not_required" and assessment != "not_detected":
            raise ReleaseAssemblyError(f"figure asset {key}: no-asset assessment drifted")
        if status in {"asset_ready", "missing"} and assessment != "confirmed":
            raise ReleaseAssemblyError(f"figure asset {key}: confirmed assessment is missing")
        signals = row.get("detection_signals")
        review_flags = row.get("review_flags")
        for values, name in ((signals, "signals"), (review_flags, "review flags")):
            if (
                not isinstance(values, list)
                or values != sorted(set(values))
                or any(not isinstance(value, str) or not value for value in values)
            ):
                raise ReleaseAssemblyError(f"figure asset {key}: {name} are malformed")
        if row.get("production_import_authorized") is not False:
            raise ReleaseAssemblyError(f"figure asset {key}: production promotion attempted")
        raw_assets = row.get("assets")
        if not isinstance(raw_assets, list):
            raise ReleaseAssemblyError(f"figure asset {key}: assets are malformed")
        normalized_assets = [
            _validated_figure_asset(
                raw,
                paper_id=paper_id,
                source_pdf_sha256=str(provenance["source_pdf_sha256"]),
                source_pages=source_pages,
                seen_assets=seen_assets,
            )
            for raw in raw_assets
        ]
        if len({asset["sha256"] for asset in normalized_assets}) != len(normalized_assets):
            raise ReleaseAssemblyError(f"figure asset {key}: assets are duplicated")
        if status == "asset_ready" and (not normalized_assets or review_flags):
            raise ReleaseAssemblyError(f"figure asset {key}: ready assets are incomplete")
        if status != "asset_ready" and normalized_assets:
            raise ReleaseAssemblyError(f"figure asset {key}: unready assets were attached")
        if status == "not_required" and review_flags:
            raise ReleaseAssemblyError(f"figure asset {key}: non-required row has review flags")
        if status in {"review_required", "missing"} and not review_flags:
            raise ReleaseAssemblyError(f"figure asset {key}: blocked row lacks a review flag")
        release_flags = list(review_flags)
        if status == "review_required":
            release_flags.append("figure_asset_review_required")
        elif status == "missing":
            release_flags.append("figure_asset_missing")
        result[key] = {
            "status": status,
            "assessment": assessment,
            "source_pdf_sha256": row["source_pdf_sha256"],
            "source_pages": source_pages,
            "assets": normalized_assets,
            "asset_sha256": sorted(asset["sha256"] for asset in normalized_assets),
            "review_flags": sorted(set(release_flags)),
        }
    if set(result) != expected_keys:
        raise ReleaseAssemblyError("figure asset exact parent/child coverage drifted")
    return result


def _validate_content_figure_alignment(
    content_rows: Mapping[tuple[str, int], Mapping[str, Any]],
    figure_rows: Mapping[tuple[str, int, str | None], Mapping[str, Any]],
) -> None:
    for key, content in content_rows.items():
        figure = figure_rows[(key[0], key[1], None)]
        evidence = content["figure_evidence"]
        if (
            evidence.get("status") != figure["status"]
            or evidence.get("assessment") != figure["assessment"]
            or evidence.get("source_pdf_sha256") != figure["source_pdf_sha256"]
            or evidence.get("source_pages") != figure["source_pages"]
            or evidence.get("asset_count") != len(figure["assets"])
            or sorted(evidence.get("asset_sha256") or []) != figure["asset_sha256"]
        ):
            raise ReleaseAssemblyError(f"content/figure evidence drifted at {key}")


def _validate_bound_source_file(raw: Any, *, context: str) -> tuple[Path, str, int, int]:
    if not isinstance(raw, Mapping):
        raise ReleaseAssemblyError(f"{context}: file evidence is malformed")
    absolute_path = raw.get("absolute_path")
    declared_path = raw.get("declared_path") or raw.get("manifest_declared_path")
    candidates: list[Path] = []
    if isinstance(absolute_path, str) and absolute_path:
        candidates.append(Path(absolute_path))
    if isinstance(declared_path, str) and declared_path:
        declared = Path(declared_path)
        candidates.append(declared if declared.is_absolute() else REPO_DIR / declared)
    path = next((candidate.resolve() for candidate in candidates if candidate.is_file()), None)
    if path is None:
        raise ReleaseAssemblyError(f"{context}: checksum-bound file is missing")
    digest = _require_hash(raw.get("sha256"), context=f"{context} SHA-256")
    if _sha256_file(path) != digest:
        raise ReleaseAssemblyError(f"{context}: file hash drifted")
    size = raw.get("bytes")
    pages = raw.get("pages")
    if not isinstance(size, int) or size < 1 or path.stat().st_size != size:
        raise ReleaseAssemblyError(f"{context}: file byte count drifted")
    if not isinstance(pages, int) or pages < 1 or raw.get("valid_pdf") is not True:
        raise ReleaseAssemblyError(f"{context}: PDF structure is invalid")
    return path, digest, size, pages


def _validate_paper_source_verification(
    artifact: Mapping[str, Any],
    *,
    manifest_path: Path,
    canonical_path: Path,
    provenance_path: Path,
    paper_by_id: Mapping[str, Mapping[str, Any]],
    canonical_map: Mapping[tuple[str, int], Mapping[str, Any]],
    provenance_map: Mapping[tuple[str, int], Mapping[str, Any]],
    expected_paper_count: int,
    expected_parent_count: int,
) -> dict[str, dict[str, Any]]:
    if artifact.get("schema_version") != "1.0-staging-paper-source-verification":
        raise ReleaseAssemblyError("paper source verification schema drifted")
    guard = artifact.get("staging_guard")
    if not isinstance(guard, Mapping) or guard != {
        "production_import_authorized": False,
        "database_write_authorized": False,
        "promotion_authorized": False,
        "practice_eligible": False,
    }:
        raise ReleaseAssemblyError("paper source verification staging guard drifted")
    _validate_embedded_hash(
        artifact, field="artifact_sha256", context="paper source verification"
    )
    policy = artifact.get("verification_policy")
    if (
        not isinstance(policy, Mapping)
        or not isinstance(policy.get("official"), str)
        or not isinstance(policy.get("secondary"), str)
        or policy.get("url_only_or_single_republisher_is_sufficient") is not False
        or policy.get("answer_key_can_verify_question_paper_identity") is not False
    ):
        raise ReleaseAssemblyError("paper source verification policy drifted")
    bindings = artifact.get("input_bindings")
    if not isinstance(bindings, Mapping):
        raise ReleaseAssemblyError("paper source verification bindings are missing")
    _validate_recursive_input_bindings(bindings, context="paper source verification")
    for name, path in (
        ("source_manifest", manifest_path),
        ("canonical_archive", canonical_path),
        ("original_pdf_provenance", provenance_path),
    ):
        _assert_binding(bindings, name, path, context="paper source verification")
    invariants = artifact.get("invariants")
    if not isinstance(invariants, Mapping) or invariants != {
        "expected_paper_count": expected_paper_count,
        "actual_paper_count": expected_paper_count,
        "expected_parent_item_count": expected_parent_count,
        "canonical_parent_item_count": expected_parent_count,
        "provenance_parent_item_count": expected_parent_count,
        "all_papers_have_false_staging_guards": True,
    }:
        raise ReleaseAssemblyError("paper source verification invariants drifted")
    rows = artifact.get("papers")
    if not isinstance(rows, list) or len(rows) != expected_paper_count:
        raise ReleaseAssemblyError("paper source verification coverage drifted")
    canonical_counts = Counter(paper_id for paper_id, _ in canonical_map)
    provenance_counts = Counter(paper_id for paper_id, _ in provenance_map)
    result: dict[str, dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise ReleaseAssemblyError("paper source verification row is malformed")
        paper_id = raw.get("source_paper_id")
        if not isinstance(paper_id, str) or paper_id in result or paper_id not in paper_by_id:
            raise ReleaseAssemblyError("paper source verification id is invalid")
        paper = paper_by_id[paper_id]
        context = f"paper source verification {paper_id}"
        if raw.get("year") != paper.get("year") or raw.get("session") != paper.get(
            "session_label"
        ):
            raise ReleaseAssemblyError(f"{context}: paper identity drifted")
        row_guard = raw.get("staging_guard")
        if not isinstance(row_guard, Mapping) or any(row_guard.values()):
            raise ReleaseAssemblyError(f"{context}: staging promotion attempted")
        local_path, local_sha, local_bytes, local_pages = _validate_bound_source_file(
            raw.get("local_source"), context=f"{context} local source"
        )
        local = raw["local_source"]
        if (
            local.get("identity_matches_manifest_and_provenance") is not True
            or local_sha != paper.get("source_pdf_sha256")
        ):
            raise ReleaseAssemblyError(f"{context}: local source identity drifted")
        expected_count = canonical_counts[paper_id]
        counts = raw.get("counts")
        if not isinstance(counts, Mapping) or counts != {
            "expected_item_count": paper.get("expected_item_count"),
            "manifest_observed_item_count": paper.get("expected_item_count"),
            "canonical_item_count": expected_count,
            "provenance_item_count": provenance_counts[paper_id],
            "counts_agree": True,
        }:
            raise ReleaseAssemblyError(f"{context}: item counts drifted")
        provenance_binding = raw.get("provenance_binding")
        if (
            not isinstance(provenance_binding, Mapping)
            or provenance_binding.get("source_pdf_sha256") != local_sha
            or provenance_binding.get("source_page_count") != local_pages
            or provenance_binding.get("item_count") != provenance_counts[paper_id]
            or provenance_binding.get("unresolved_count") != 0
        ):
            raise ReleaseAssemblyError(f"{context}: provenance binding drifted")
        blockers = raw.get("blockers")
        review_flags = raw.get("review_flags")
        for values, name in ((blockers, "blockers"), (review_flags, "review flags")):
            if (
                not isinstance(values, list)
                or values != sorted(set(values))
                or any(not isinstance(value, str) or not value for value in values)
            ):
                raise ReleaseAssemblyError(f"{context}: {name} are malformed")
        decision = raw.get("decision")
        method = raw.get("method")
        if decision not in {"verified", "review", "rejected"} or method not in {
            "primary_official_byte_identity",
            "cross_validated_republication",
        }:
            raise ReleaseAssemblyError(f"{context}: decision or method is invalid")
        evidence_rows = raw.get("evidence")
        if not isinstance(evidence_rows, list):
            raise ReleaseAssemblyError(f"{context}: evidence list is malformed")
        qualifying_primary: list[Mapping[str, Any]] = []
        qualifying_secondary: list[Mapping[str, Any]] = []
        secondary_domains: set[str] = set()
        for evidence in evidence_rows:
            if not isinstance(evidence, Mapping):
                raise ReleaseAssemblyError(f"{context}: evidence row is malformed")
            domain = evidence.get("source_domain")
            source_url = evidence.get("source_url")
            if (
                not isinstance(domain, str)
                or not domain
                or not isinstance(source_url, str)
                or urlparse(source_url).scheme != "https"
                or urlparse(source_url).hostname != domain
            ):
                raise ReleaseAssemblyError(f"{context}: evidence URL/domain is invalid")
            _, evidence_sha, evidence_bytes, evidence_pages = _validate_bound_source_file(
                evidence.get("artifact"),
                context=f"{context}/{evidence.get('evidence_id')}",
            )
            byte_identical = evidence_sha == local_sha and evidence_bytes == local_bytes
            if evidence.get("byte_identical_to_bound_source") is not byte_identical:
                raise ReleaseAssemblyError(f"{context}: byte-identity claim drifted")
            if evidence.get("page_structure_agrees") is True and evidence_pages != local_pages:
                raise ReleaseAssemblyError(f"{context}: page-structure claim drifted")
            if evidence.get("item_structure_agrees") is True and evidence.get(
                "observed_item_count"
            ) != expected_count:
                raise ReleaseAssemblyError(f"{context}: item-structure claim drifted")
            if evidence.get("qualifies_primary_official_byte_identity") is True:
                if (
                    evidence.get("authority") != "primary_official"
                    or evidence.get("independently_acquired") is not True
                    or not byte_identical
                    or evidence.get("page_structure_agrees") is not True
                    or evidence.get("item_structure_agrees") is not True
                    or evidence.get("official_index_confirmed") is not True
                    or evidence.get("official_source_confirmed") is not True
                ):
                    raise ReleaseAssemblyError(f"{context}: official evidence is incomplete")
                qualifying_primary.append(evidence)
            if evidence.get("qualifies_cross_validated_republication_candidate") is True:
                if (
                    evidence.get("independently_acquired") is not True
                    or not byte_identical
                    or evidence.get("page_structure_agrees") is not True
                    or evidence.get("item_structure_agrees") is not True
                ):
                    raise ReleaseAssemblyError(
                        f"{context}: secondary identity evidence is incomplete"
                    )
                qualifying_secondary.append(evidence)
                secondary_domains.add(domain)
        if decision == "verified":
            if blockers:
                raise ReleaseAssemblyError(f"{context}: verified paper has blockers")
            if method == "primary_official_byte_identity" and not qualifying_primary:
                raise ReleaseAssemblyError(f"{context}: official byte identity is unproven")
            if method == "cross_validated_republication" and (
                len(qualifying_secondary) < 2 or len(secondary_domains) < 2
            ):
                raise ReleaseAssemblyError(f"{context}: two-source identity is unproven")
        elif not blockers:
            raise ReleaseAssemblyError(f"{context}: unverified paper lacks blockers")
        result[paper_id] = dict(raw)
    if set(result) != set(paper_by_id):
        raise ReleaseAssemblyError("paper source verification paper set drifted")
    observed_decisions = dict(
        sorted(Counter(str(row["decision"]) for row in result.values()).items())
    )
    observed_methods = dict(
        sorted(Counter(str(row["method"]) for row in result.values()).items())
    )
    if artifact.get("decision_counts") != observed_decisions:
        raise ReleaseAssemblyError("paper source verification decision counts drifted")
    if artifact.get("method_counts") != observed_methods:
        raise ReleaseAssemblyError("paper source verification method counts drifted")
    return result


def _release_canonical_parent_ordinal(item: Mapping[str, Any]) -> int:
    values: set[int] = set()
    for reference in item.get("source_references") or []:
        if not isinstance(reference, Mapping) or reference.get("kind") != "canonical_parent_slot":
            continue
        match = re.search(
            r"canonical_parent_ordinal=(\d+)", str(reference.get("note") or "")
        )
        if match:
            values.add(int(match.group(1)))
    if len(values) > 1:
        raise ReleaseAssemblyError(
            f"{item.get('source_paper_id')}#{item.get('ordinal')}: conflicting parent ordinals"
        )
    return next(iter(values), int(item["ordinal"]))


def _classification_projection(items: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "source_paper_id": item["source_paper_id"],
            "canonical_parent_ordinal": _release_canonical_parent_ordinal(item),
            "final_release_ordinal": item["ordinal"],
            "item_label": item["item_label"],
            "parent_item_label": item.get("parent_item_label"),
            "subject_code": item.get("subject_code"),
            "topic_slug": item.get("topic_slug"),
            "syllabus_status": item.get("syllabus_status"),
            "classification_status": item.get("classification_status"),
        }
        for item in items
    ]


def _classification_inventory(raw: Mapping[str, Any]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    courses = raw.get("courses")
    if not isinstance(courses, Mapping):
        raise ReleaseAssemblyError("classification topic inventory is malformed")
    for course, data in courses.items():
        topics = data.get("by_topic") if isinstance(data, Mapping) else None
        if not isinstance(topics, Mapping):
            raise ReleaseAssemblyError(f"classification inventory {course}: topics missing")
        result[str(course)] = {
            re.sub(r"[^a-z0-9]+", "-", str(name).casefold()).strip("-")
            for name in topics
        }
    return result


def _classification_review_row(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source_paper_id": item["source_paper_id"],
        "canonical_parent_ordinal": _release_canonical_parent_ordinal(item),
        "item_label": item["item_label"],
        "ordinal": item["ordinal"],
        "parent_item_label": item.get("parent_item_label"),
        "source_page": item.get("source_page"),
        "subject_code": item.get("subject_code"),
        "topic_slug": item.get("topic_slug"),
        "syllabus_status": item.get("syllabus_status"),
        "classification_status": item.get("classification_status"),
        "review_flags": list(item.get("review_flags") or []),
    }


def _validate_classification_review_base(
    artifact: Mapping[str, Any],
    *,
    canonical_path: Path,
    legacy_path: Path,
    child_policy_path: Path,
    parent_policy_path: Path,
    inventory_path: Path,
    content_ledger_path: Path,
    provenance_path: Path,
    base_items: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if artifact.get("schema_version") != "1.0-staging-pyq-classification-review-base":
        raise ReleaseAssemblyError("classification review base schema drifted")
    if artifact.get("source_role") != "immutable_pre_override_classification_projection":
        raise ReleaseAssemblyError("classification review base source role drifted")
    _assert_staging_guard(
        artifact,
        context="classification review base",
        required_false=(
            "database_writes_performed",
            "production_import_authorized",
            "automatic_promotion_allowed",
        ),
    )
    _validate_embedded_hash(
        artifact, field="artifact_sha256", context="classification review base"
    )
    artifact_sha256 = _require_hash(
        artifact.get("artifact_sha256"),
        context="classification review base artifact",
    )
    bindings = artifact.get("input_bindings")
    if not isinstance(bindings, Mapping):
        raise ReleaseAssemblyError("classification review base bindings are missing")
    _validate_recursive_input_bindings(bindings, context="classification review base")
    for name, path in (
        ("canonical_archive", canonical_path),
        ("legacy_subpart_audit", legacy_path),
        ("legacy_child_policy", child_policy_path),
        ("base_parent_policy", parent_policy_path),
        ("topic_inventory", inventory_path),
        ("content_verification_ledger", content_ledger_path),
        ("original_pdf_provenance", provenance_path),
    ):
        _assert_binding(bindings, name, path, context="classification review base")

    projection = _classification_projection(base_items)
    projection_sha256 = _canonical_sha256(projection)
    if artifact.get("classification_projection") != projection:
        raise ReleaseAssemblyError(
            "classification review base projection differs from pre-override release"
        )
    if artifact.get("classification_projection_sha256") != projection_sha256:
        raise ReleaseAssemblyError("classification review base projection hash drifted")
    review_items = [
        item
        for item in base_items
        if item.get("classification_status") == "review_required"
    ]
    review_rows = [_classification_review_row(item) for item in review_items]
    frozen_rows = artifact.get("review_rows")
    if not isinstance(frozen_rows, list) or len(frozen_rows) != len(review_rows):
        raise ReleaseAssemblyError(
            "classification review base rows differ from pre-override release"
        )
    # The projection above is the byte-exact classification contract.  Review
    # flags are deliberately excluded from that projection because unrelated
    # content/source/figure gates evolve independently between evidence passes.
    # The frozen flags remain checksum-bound historical context for the review
    # decision, but must not force the current release to discard newer blockers.
    for index, (frozen, current) in enumerate(zip(frozen_rows, review_rows, strict=True)):
        if not isinstance(frozen, Mapping):
            raise ReleaseAssemblyError(
                f"classification review base row {index} is malformed"
            )
        expected = {name: value for name, value in current.items() if name != "review_flags"}
        observed = {name: frozen.get(name) for name in expected}
        if observed != expected or set(frozen) != set(current):
            fields = sorted(
                name
                for name in set(frozen) | set(current)
                if name != "review_flags" and frozen.get(name) != current.get(name)
            )
            raise ReleaseAssemblyError(
                "classification review base rows differ from pre-override release: "
                f"row {index} fields {fields}"
            )
        frozen_flags = frozen.get("review_flags")
        if not isinstance(frozen_flags, list) or (
            "classification_review_required" not in frozen_flags
        ):
            raise ReleaseAssemblyError(
                f"classification review base row {index} lacks its prior review gate"
            )
    keys = sorted(
        f"{item['source_paper_id']}#{_release_canonical_parent_ordinal(item)}"
        for item in review_items
    )
    identity = {
        "expected_count": len(review_rows),
        "classification_projection_sha256": projection_sha256,
        "review_key_sha256": _canonical_sha256(keys),
    }
    if artifact.get("base_review_identity") != identity:
        raise ReleaseAssemblyError("classification review base identity drifted")
    if artifact.get("counts") != {
        "expanded_records": len(base_items),
        "review_rows": len(review_rows),
    }:
        raise ReleaseAssemblyError("classification review base counts drifted")
    return {**identity, "artifact_sha256": artifact_sha256}


def _validate_classification_review_overrides(
    artifact: Mapping[str, Any],
    *,
    classification_base_path: Path,
    classification_base_identity: Mapping[str, Any],
    canonical_path: Path,
    legacy_path: Path,
    child_policy_path: Path,
    parent_policy_path: Path,
    inventory_path: Path,
    content_ledger_path: Path,
    provenance_path: Path,
    base_items: Sequence[Mapping[str, Any]],
    paper_by_id: Mapping[str, Mapping[str, Any]],
    inventory_raw: Mapping[str, Any],
) -> dict[tuple[str, int, str, str | None], dict[str, Any]]:
    if artifact.get("schema_version") != "1.0-staging-pyq-classification-review-overrides":
        raise ReleaseAssemblyError("classification review override schema drifted")
    _assert_staging_guard(
        artifact,
        context="classification review overrides",
        required_false=(
            "database_writes_performed",
            "production_import_authorized",
            "automatic_promotion_allowed",
        ),
    )
    if artifact.get("practice_eligible_count") != 0:
        raise ReleaseAssemblyError("classification review overrides attempted promotion")
    _validate_embedded_hash(
        artifact, field="artifact_sha256", context="classification review overrides"
    )
    policy = artifact.get("policy")
    if not isinstance(policy, Mapping) or policy != {
        "allowed_decisions": ["map", "out_of_syllabus", "review"],
        "map_requires_single_inventory_course_topic": True,
        "out_of_syllabus_requires_original_evidence": True,
        "compound_or_insufficient_evidence_remains_review": True,
        "third_party_content_is_not_evidence": True,
        "base_policy_is_comparison_only": True,
        "expanded_children_require_explicit_child_identity": True,
    }:
        raise ReleaseAssemblyError("classification review override policy drifted")
    bindings = artifact.get("input_bindings")
    if not isinstance(bindings, Mapping):
        raise ReleaseAssemblyError("classification review override bindings are missing")
    _validate_recursive_input_bindings(bindings, context="classification review overrides")
    for name, path in (
        ("classification_review_base", classification_base_path),
        ("canonical_archive", canonical_path),
        ("legacy_subpart_audit", legacy_path),
        ("legacy_child_policy", child_policy_path),
        ("base_parent_policy", parent_policy_path),
        ("topic_inventory", inventory_path),
        ("content_verification_ledger", content_ledger_path),
        ("original_pdf_provenance", provenance_path),
    ):
        _assert_binding(bindings, name, path, context="classification review overrides")

    expected_base_identity = {
        key: classification_base_identity[key]
        for key in (
            "expected_count",
            "classification_projection_sha256",
            "review_key_sha256",
        )
    }
    if artifact.get("base_review_identity") != expected_base_identity:
        raise ReleaseAssemblyError(
            "classification override/base projection identity drifted"
        )

    review_rows = [
        item for item in base_items if item.get("classification_status") == "review_required"
    ]
    review_by_key: dict[tuple[str, int, str, str | None], Mapping[str, Any]] = {}
    string_keys: list[str] = []
    for item in review_rows:
        parent_ordinal = _release_canonical_parent_ordinal(item)
        child_label = str(item["item_label"]) if item.get("parent_item_label") else None
        key = (
            str(item["source_paper_id"]),
            parent_ordinal,
            str(item["item_label"]),
            child_label,
        )
        if key in review_by_key:
            raise ReleaseAssemblyError(f"classification base review key duplicated: {key}")
        review_by_key[key] = item
        string_keys.append(f"{key[0]}#{key[1]}")
    identity = artifact.get("base_review_identity")
    if not isinstance(identity, Mapping) or identity != {
        "expected_count": len(review_rows),
        "classification_projection_sha256": _canonical_sha256(
            _classification_projection(base_items)
        ),
        "review_key_sha256": _canonical_sha256(sorted(string_keys)),
    }:
        raise ReleaseAssemblyError("classification base review identity drifted")

    inventory = _classification_inventory(inventory_raw)
    decisions = artifact.get("decisions")
    if not isinstance(decisions, list) or len(decisions) != len(review_rows):
        raise ReleaseAssemblyError("classification review decision coverage drifted")
    result: dict[tuple[str, int, str, str | None], dict[str, Any]] = {}
    evidence_counts: Counter[str] = Counter()
    decision_counts: Counter[str] = Counter()
    for raw in decisions:
        if not isinstance(raw, Mapping):
            raise ReleaseAssemblyError("classification review decision is malformed")
        key = (
            str(raw.get("source_paper_id") or ""),
            int(raw.get("canonical_parent_ordinal") or 0),
            str(raw.get("item_label") or ""),
            raw.get("child_item_label"),
        )
        if key in result or key not in review_by_key:
            raise ReleaseAssemblyError(f"classification review key is unexpected: {key}")
        item = review_by_key[key]
        if raw.get("parent_item_label") != item.get("parent_item_label"):
            raise ReleaseAssemblyError(f"classification review {key}: parent label drifted")
        prior = raw.get("prior_classification")
        if not isinstance(prior, Mapping) or any(
            prior.get(name) != expected
            for name, expected in (
                ("final_release_ordinal", item.get("ordinal")),
                ("classification_status", item.get("classification_status")),
                ("syllabus_status", item.get("syllabus_status")),
                ("course", item.get("subject_code")),
                ("topic", item.get("topic_slug")),
            )
        ):
            raise ReleaseAssemblyError(f"classification review {key}: prior state drifted")
        if not isinstance(prior.get("review_flags"), list) or (
            "classification_review_required" not in prior["review_flags"]
        ):
            raise ReleaseAssemblyError(f"classification review {key}: prior gate is missing")
        decision = raw.get("decision")
        course = raw.get("course")
        topic = raw.get("topic")
        if decision == "map":
            if course not in inventory or topic not in inventory[str(course)]:
                raise ReleaseAssemblyError(f"classification review {key}: map is non-canonical")
        elif decision in {"out_of_syllabus", "review"}:
            if course is not None or topic is not None:
                raise ReleaseAssemblyError(
                    f"classification review {key}: non-map carries course/topic"
                )
        else:
            raise ReleaseAssemblyError(f"classification review {key}: decision is invalid")
        reason_code = raw.get("reason_code")
        reason = raw.get("reason")
        if any(not isinstance(value, str) or not value.strip() for value in (reason_code, reason)):
            raise ReleaseAssemblyError(f"classification review {key}: rationale is missing")
        evidence = raw.get("evidence")
        if not isinstance(evidence, Mapping):
            raise ReleaseAssemblyError(f"classification review {key}: evidence is missing")
        evidence_kind = evidence.get("kind")
        if evidence_kind not in {
            "checksum_bound_original_page_text_review",
            "checksum_bound_original_pdf_page_ocr_index",
            "checksum_bound_original_pdf_page_rapidocr",
            "checksum_bound_original_pdf_page_rapidocr_cache",
            "checksum_bound_original_text_block",
        }:
            raise ReleaseAssemblyError(f"classification review {key}: evidence kind is invalid")
        if evidence.get("source_pdf_sha256") != paper_by_id[key[0]].get(
            "source_pdf_sha256"
        ):
            raise ReleaseAssemblyError(f"classification review {key}: source PDF drifted")
        pages = evidence.get("source_pages")
        excerpt = evidence.get("excerpt")
        if (
            not isinstance(pages, list)
            or not pages
            or any(not isinstance(page, int) or page < 1 for page in pages)
            or not isinstance(excerpt, str)
            or not excerpt
            or evidence.get("excerpt_sha256") != _sha256_text(excerpt)
        ):
            raise ReleaseAssemblyError(f"classification review {key}: evidence hash drifted")
        if evidence_kind in {
            "checksum_bound_original_page_text_review",
            "checksum_bound_original_text_block",
        }:
            _require_hash(
                evidence.get("text_block_sha256"),
                context=f"classification review {key} text block",
            )
            rendered = evidence.get("rendered_page_evidence")
            if not isinstance(rendered, list):
                raise ReleaseAssemblyError(f"classification review {key}: renders malformed")
            for row in rendered:
                if not isinstance(row, Mapping):
                    raise ReleaseAssemblyError(f"classification review {key}: render malformed")
                _require_hash(
                    row.get("sha256") or row.get("rendered_page_sha256"),
                    context=f"classification review {key} render",
                )
        else:
            for name in ("page_ocr_text_sha256", "rendered_page_sha256"):
                _require_hash(
                    evidence.get(name), context=f"classification review {key} {name}"
                )
            if evidence_kind == "checksum_bound_original_pdf_page_rapidocr":
                _require_hash(
                    evidence.get("ocr_artifact_sha256"),
                    context=f"classification review {key} OCR artifact",
                )
        if decision != "review" and evidence.get(
            "question_boundary_status"
        ) == "page_level_locator_conflict":
            raise ReleaseAssemblyError(
                f"classification review {key}: ambiguous evidence was finalized"
            )
        expected_decision_hash = _canonical_sha256(
            {
                "identity": {
                    "source_paper_id": key[0],
                    "canonical_parent_ordinal": key[1],
                    "item_label": key[2],
                    "child_item_label": key[3],
                },
                "decision": decision,
                "course": course,
                "topic": topic,
                "reason_code": reason_code,
                "reason": reason,
                "evidence_sha256": evidence["excerpt_sha256"],
            }
        )
        if raw.get("decision_evidence_sha256") != expected_decision_hash:
            raise ReleaseAssemblyError(f"classification review {key}: decision hash drifted")
        result[key] = dict(raw)
        decision_counts[str(decision)] += 1
        evidence_counts[str(evidence_kind)] += 1
    if set(result) != set(review_by_key):
        raise ReleaseAssemblyError("classification review keys do not cover base reviews")
    counts = artifact.get("counts")
    if not isinstance(counts, Mapping) or counts != {
        "total": len(result),
        "by_decision": dict(sorted(decision_counts.items())),
        "by_evidence_kind": dict(sorted(evidence_counts.items())),
    }:
        raise ReleaseAssemblyError("classification review counts drifted")
    return result


def _apply_classification_review_overrides(
    items: list[dict[str, Any]],
    decisions: Mapping[tuple[str, int, str, str | None], Mapping[str, Any]],
    *,
    artifact_sha256: str,
) -> None:
    for item in items:
        if item.get("classification_status") != "review_required":
            continue
        child_label = str(item["item_label"]) if item.get("parent_item_label") else None
        key = (
            str(item["source_paper_id"]),
            _release_canonical_parent_ordinal(item),
            str(item["item_label"]),
            child_label,
        )
        decision = decisions[key]
        outcome = decision["decision"]
        flags = set(str(flag) for flag in item.get("review_flags") or [])
        if outcome == "map":
            item["subject_code"] = decision["course"]
            item["topic_slug"] = decision["topic"]
            item["syllabus_status"] = "in_syllabus"
            item["classification_status"] = "verified"
            flags.discard("classification_review_required")
        elif outcome == "out_of_syllabus":
            item["subject_code"] = None
            item["topic_slug"] = None
            item["syllabus_status"] = "out_of_syllabus"
            item["classification_status"] = "out_of_syllabus"
            flags.discard("classification_review_required")
        else:
            item["subject_code"] = None
            item["topic_slug"] = None
            item["syllabus_status"] = "review_required"
            item["classification_status"] = "review_required"
            flags.add("classification_review_required")
        item["review_flags"] = sorted(flags)
        references = list(item.get("source_references") or [])
        references.append(
            {
                "kind": "classification_review_override",
                "url": None,
                "sha256": artifact_sha256,
                "note": (
                    f"canonical_parent_ordinal={key[1]}; decision={outcome}; "
                    f"decision_evidence_sha256={decision['decision_evidence_sha256']}"
                ),
            }
        )
        item["source_references"] = _dedupe_references(references)
        item["content_sha256"] = _content_sha256(item)


def _original_reference(
    *,
    paper: Mapping[str, Any],
    provenance: Mapping[str, Any],
    canonical_parent_ordinal: int,
    source_pages: Sequence[int] | None = None,
    item_label: str | None = None,
) -> dict[str, Any]:
    pages = list(source_pages or provenance.get("source_pages") or [])
    text_hash = provenance.get("text_block_sha256")
    note_parts = [f"canonical_parent_ordinal={canonical_parent_ordinal}"]
    if item_label:
        note_parts.append(f"item_label={item_label}")
    if pages:
        note_parts.append("source_pages=" + ",".join(str(page) for page in pages))
    if isinstance(text_hash, str):
        note_parts.append(f"text_block_sha256={text_hash}")
    return {
        "kind": "original_pdf_item",
        "url": paper.get("source_url"),
        "sha256": provenance.get("source_pdf_sha256"),
        "note": "; ".join(note_parts),
    }


def _dedupe_references(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in rows:
        row = {
            "kind": raw.get("kind"),
            "url": raw.get("url"),
            "sha256": raw.get("sha256"),
            "note": raw.get("note"),
        }
        identity = json.dumps(row, sort_keys=True, separators=(",", ":"))
        if identity not in seen:
            result.append(row)
            seen.add(identity)
    return result


def _normalized_answer(
    selected: Any,
    *,
    question_type: str,
) -> tuple[Any | None, list[str]]:
    if not isinstance(selected, Mapping):
        return None, ["verified_answer_shape_invalid"]
    kind = selected.get("kind")
    if kind == "options":
        options = selected.get("options")
        if not isinstance(options, list) or not options:
            return None, ["verified_answer_shape_invalid"]
        normalized = [str(value).strip().upper() for value in options]
        if question_type == "mcq" and len(normalized) == 1:
            return normalized[0], []
        if question_type == "msq":
            return sorted(set(normalized)), []
        return selected, ["verified_answer_type_mismatch"]
    if kind == "numeric_ranges":
        ranges = selected.get("ranges")
        if question_type != "nat" or not isinstance(ranges, list) or len(ranges) != 1:
            return selected, ["verified_answer_type_mismatch"]
        current = ranges[0]
        if not isinstance(current, Mapping):
            return selected, ["verified_answer_shape_invalid"]
        try:
            return {
                "min": float(current["minimum"]),
                "max": float(current["maximum"]),
            }, []
        except (KeyError, TypeError, ValueError):
            return selected, ["verified_answer_shape_invalid"]
    if kind == "marks_to_all":
        return None, ["marks_to_all_not_auto_scorable"]
    if kind == "options_any_of":
        return copy.deepcopy(selected), ["alternative_answers_not_auto_scorable"]
    return copy.deepcopy(selected), ["verified_answer_shape_unsupported"]


def _community_value(value: Any, *, question_type: str) -> Any | None:
    """Normalize a secondary answer claim without weakening type semantics."""

    if question_type == "mcq":
        if isinstance(value, str) and re.fullmatch(r"[A-D]", value.strip().upper()):
            return value.strip().upper()
        return None
    if question_type == "msq":
        raw = value if isinstance(value, list) else [value]
        if not raw:
            return None
        normalized = [str(current).strip().upper() for current in raw]
        if any(re.fullmatch(r"[A-D]", current) is None for current in normalized):
            return None
        return sorted(set(normalized))
    if question_type == "nat":
        if isinstance(value, bool):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if number != number or number in {float("inf"), float("-inf")}:
            return None
        return {"min": number, "max": number}
    return None


def _community_claim_reference(
    candidate_row: Mapping[str, Any],
    *,
    source: str,
    normalized_value: Any,
) -> dict[str, Any]:
    snapshots = candidate_row.get("secondary_snapshots")
    snapshots = snapshots if isinstance(snapshots, Mapping) else {}
    snapshot = snapshots.get(source)
    if not isinstance(snapshot, Mapping):
        raise ReleaseAssemblyError(
            f"community answer claim source {source!r} has no bound snapshot"
        )
    if source == "gateoverflow":
        body = snapshot.get("question_body_text")
        if (
            not isinstance(body, str)
            or snapshot.get("question_body_sha256") != _sha256_text(body)
        ):
            raise ReleaseAssemblyError("GateOverflow community claim text hash drifted")
        digest = _require_hash(
            snapshot.get("page_text_sha256"),
            context="GateOverflow community claim page",
        )
        url = None
        evidence = (
            f"question_body_sha256={snapshot.get('question_body_sha256')}; "
            f"page_text_sha256={digest}"
        )
    elif source == "examside":
        digest = _require_hash(
            snapshot.get("raw_response_sha256"),
            context="ExamSIDE community claim response",
        )
        source_id = snapshot.get("source_id")
        url = snapshot.get("source_url")
        if (
            not isinstance(source_id, str)
            or not source_id.strip()
            or not isinstance(url, str)
            or not url.startswith(("https://", "http://"))
        ):
            raise ReleaseAssemblyError("ExamSIDE community claim identity is incomplete")
        evidence = f"source_id={source_id}; raw_response_sha256={digest}"
    else:
        raise ReleaseAssemblyError(f"unsupported community answer source {source!r}")
    return {
        "kind": "community_answer_claim",
        "url": url,
        "sha256": digest,
        "note": (
            f"source={source}; authority=secondary_community_candidate; "
            f"normalized_value={json.dumps(normalized_value, sort_keys=True)}; {evidence}"
        ),
    }


def _community_candidate_answer(
    *,
    canonical: Mapping[str, Any],
    candidate_row: Mapping[str, Any],
    item_type: str,
    marks: Any,
) -> tuple[Any | None, list[str], list[dict[str, Any]]]:
    """Return a two-source answer only when every corroboration guard holds."""

    candidate = candidate_row.get("candidate")
    candidate = candidate if isinstance(candidate, Mapping) else {}
    if candidate.get("answer_status") != "community_corroborated_candidate":
        return None, [], []
    if (
        candidate_row.get("reconciliation_status") != "exact"
        or candidate_row.get("withheld_reasons")
        or candidate_row.get("candidate_review_reasons")
    ):
        return None, ["community_answer_reconciliation_not_exact"], []
    if item_type not in OBJECTIVE_TYPES:
        return None, ["community_answer_type_invalid"], []
    canonical_type = str(canonical.get("item_type") or "unknown").casefold()
    if canonical_type not in {"unknown", item_type}:
        raise ReleaseAssemblyError("community answer conflicts with canonical item type")
    candidate_marks = candidate.get("marks")
    if candidate_marks not in {1, 2, 1.0, 2.0}:
        return None, ["community_answer_marks_invalid"], []
    if marks is not None and float(marks) != float(candidate_marks):
        raise ReleaseAssemblyError("community answer marks conflict with canonical marks")

    promotion = candidate_row.get("promotion_review")
    answer_evidence = (
        promotion.get("answer_evidence") if isinstance(promotion, Mapping) else None
    )
    if not isinstance(answer_evidence, Mapping) or answer_evidence.get(
        "requirements_met"
    ) is not True:
        return None, ["community_answer_evidence_gate_failed"], []

    claims = candidate.get("answer_claims")
    if not isinstance(claims, list):
        return None, ["community_answer_claims_missing"], []
    by_source: dict[str, Any] = {}
    for claim in claims:
        if not isinstance(claim, Mapping):
            raise ReleaseAssemblyError("community answer contains a malformed claim")
        source = str(claim.get("source") or "").casefold()
        if (
            not source
            or source in by_source
            or claim.get("authority") != "secondary_community_candidate"
        ):
            raise ReleaseAssemblyError("community answer sources are duplicated or invalid")
        by_source[source] = _community_value(claim.get("value"), question_type=item_type)
    if len(by_source) < 2:
        return None, ["community_answer_independent_sources_missing"], []
    if any(value is None for value in by_source.values()):
        return None, ["community_answer_shape_invalid"], []
    normalized_claims = {
        _canonical_sha256(value): value for value in by_source.values()
    }
    if len(normalized_claims) != 1:
        raise ReleaseAssemblyError("community answer claims conflict")
    accepted = next(iter(normalized_claims.values()))
    candidate_answer = _community_value(
        candidate.get("answer"), question_type=item_type
    )
    if candidate_answer is None:
        return None, ["community_answer_shape_invalid"], []
    if _canonical_sha256(candidate_answer) != _canonical_sha256(accepted):
        raise ReleaseAssemblyError("community candidate answer conflicts with its claims")

    independent = answer_evidence.get("independent_community_sources")
    independent_sources = (
        {str(value).casefold() for value in independent}
        if isinstance(independent, list)
        else set()
    )
    if independent_sources != set(by_source):
        raise ReleaseAssemblyError("community answer source inventory conflicts")

    snapshots = candidate_row.get("secondary_snapshots")
    examside = snapshots.get("examside") if isinstance(snapshots, Mapping) else None
    if not isinstance(examside, Mapping):
        raise ReleaseAssemblyError("community answer lacks its ExamSIDE snapshot")
    examside_type = str(examside.get("question_type") or "").casefold()
    if examside_type != item_type or examside.get("marks") != candidate_marks:
        raise ReleaseAssemblyError("community answer type/marks conflict with ExamSIDE")
    references = [
        _community_claim_reference(
            candidate_row, source=source, normalized_value=accepted
        )
        for source in sorted(by_source)
    ]
    return accepted, [], references


def _classification(
    candidate_row: Mapping[str, Any],
    canonical: Mapping[str, Any],
) -> tuple[str | None, str | None, str, str, list[str]]:
    candidate = candidate_row.get("candidate")
    candidate = candidate if isinstance(candidate, Mapping) else {}
    outcome = candidate.get("classification_outcome")
    course = candidate.get("course") or canonical.get("subject_code")
    topic = candidate.get("topic") or canonical.get("topic_slug")
    if outcome == "mapped" and course and topic:
        return str(course), str(topic), "in_syllabus", "verified", []
    if outcome == "out_of_syllabus":
        return (
            str(course) if course else None,
            str(topic) if topic else None,
            "out_of_syllabus",
            "out_of_syllabus",
            [],
        )
    return (
        str(course) if course else None,
        str(topic) if topic else None,
        "review_required",
        "review_required",
        ["classification_review_required"],
    )


def _matcher_content(row: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not isinstance(row, Mapping):
        return {}
    content = row.get("proposed_review_content")
    return content if isinstance(content, Mapping) else {}


def _normalized_options(value: Any) -> list[Any]:
    if not isinstance(value, list):
        return []
    normalized: list[Any] = []
    for index, option in enumerate(value):
        if isinstance(option, str):
            normalized.append(option)
            continue
        if not isinstance(option, Mapping):
            raise ReleaseAssemblyError(f"option {index + 1}: unsupported value")
        identifier = option.get(
            "id",
            option.get(
                "label",
                option.get("key", option.get("identifier", chr(ord("A") + index))),
            ),
        )
        text = option.get(
            "text",
            option.get(
                "value",
                option.get(
                    "option", option.get("content_text", option.get("content_html"))
                ),
            ),
        )
        if text is None:
            raise ReleaseAssemblyError(f"option {index + 1}: text is missing")
        normalized.append({"id": str(identifier).strip().upper(), "text": str(text).strip()})
    return normalized


def _late_exact_secondary_options(
    candidate_row: Mapping[str, Any],
    *,
    item_type: str,
) -> tuple[str | None, list[Any]]:
    """Parse exact-labelled secondary text after official type resolution.

    Upstream option structuring intentionally refuses an unknown question type.
    Official keys may establish that type later.  Re-running the same strict
    parser here recovers a review-only option proposal without weakening any
    source-authority or promotion guard.
    """

    if item_type not in {"mcq", "msq"}:
        return None, []
    snapshots = candidate_row.get("secondary_snapshots")
    snapshots = snapshots if isinstance(snapshots, Mapping) else {}
    gateoverflow = snapshots.get("gateoverflow")
    if not isinstance(gateoverflow, Mapping):
        return None, []
    body = gateoverflow.get("question_body_text")
    if not isinstance(body, str) or not body.strip():
        return None, []
    expected_hash = gateoverflow.get("question_body_sha256")
    if expected_hash != _sha256_text(body):
        raise ReleaseAssemblyError("exact GateOverflow snapshot text hash drifted")
    parsed = _option_parser().parse_explicit_four_choices(body)
    if parsed.get("status") != "exact":
        return None, []
    stem = parsed.get("stem")
    stem = stem.strip() if isinstance(stem, str) and stem.strip() else None
    return stem, _normalized_options(parsed.get("options"))


def _transcription(
    *,
    canonical: Mapping[str, Any],
    candidate_row: Mapping[str, Any],
    overlay: Mapping[str, Any],
    matcher_row: Mapping[str, Any] | None,
    resolved_item_type: str,
) -> tuple[str | None, list[Any], str, list[str]]:
    canonical_text = canonical.get("question_md")
    canonical_text = (
        canonical_text.strip()
        if isinstance(canonical_text, str) and canonical_text.strip()
        else None
    )
    canonical_options = canonical.get("options")
    options = _normalized_options(canonical_options)
    status = str(canonical.get("transcription_status") or "missing")
    flags: list[str] = []

    proposed = overlay.get("proposed_overlay")
    proposed = proposed if isinstance(proposed, Mapping) else {}
    overlay_exact = overlay.get("status") == "exact"
    overlay_text = proposed.get("question_text")
    overlay_text = (
        overlay_text.strip()
        if isinstance(overlay_text, str) and overlay_text.strip()
        else None
    )
    overlay_options = proposed.get("options")
    overlay_options = overlay_options if isinstance(overlay_options, list) else []
    if overlay_exact and overlay_text:
        expected = proposed.get("question_text_sha256")
        if expected != _sha256_text(overlay_text):
            raise ReleaseAssemblyError("exact transcription overlay text hash drifted")
        if canonical_text and status == "verified" and canonical_text != overlay_text:
            flags.append("verified_transcription_sources_disagree")
            status = "review_required"
        else:
            canonical_text = overlay_text
            status = "verified"
    if overlay_exact and overlay_options:
        expected = proposed.get("options_sha256")
        if expected != _canonical_sha256(overlay_options):
            raise ReleaseAssemblyError("exact transcription overlay option hash drifted")
        options = _normalized_options(overlay_options)

    candidate = candidate_row.get("candidate")
    candidate = candidate if isinstance(candidate, Mapping) else {}
    if canonical_text is None:
        matcher_content = _matcher_content(matcher_row)
        matcher_text = matcher_content.get("question_text") or matcher_content.get("question")
        if isinstance(matcher_text, str) and matcher_text.strip():
            canonical_text = matcher_text.strip()
            status = "review_required"
            flags.append("matcher_transcription_review_only")
        else:
            candidate_text = candidate.get("question_text")
            if isinstance(candidate_text, str) and candidate_text.strip():
                canonical_text = candidate_text.strip()
                status = "review_required"
                flags.append("secondary_transcription_review_only")
    if not options:
        matcher_options = _matcher_content(matcher_row).get("options")
        if isinstance(matcher_options, list) and matcher_options:
            options = _normalized_options(matcher_options)
            flags.append("matcher_options_review_only")
            status = "review_required"
        else:
            candidate_options = candidate.get("options")
            if isinstance(candidate_options, list) and candidate_options:
                options = _normalized_options(candidate_options)
                flags.append("secondary_options_review_only")
                if not overlay_exact:
                    status = "review_required"
    if not options:
        parsed_stem, parsed_options = _late_exact_secondary_options(
            candidate_row, item_type=resolved_item_type
        )
        if parsed_options:
            options = parsed_options
            flags.append("secondary_options_review_only")
            if canonical_text is None and parsed_stem:
                canonical_text = parsed_stem
                flags.append("secondary_transcription_review_only")
            if not overlay_exact:
                status = "review_required"
    if canonical_text is None:
        status = "missing"
        flags.append("question_text_missing")
    elif status not in {"verified", "review_required"}:
        status = "review_required"
    return canonical_text, options, status, flags


def _content_ledger_transcription(
    *,
    key: tuple[str, int],
    question: str | None,
    options: list[Any],
    prior_status: str,
    resolved_item_type: str,
    ledger_row: Mapping[str, Any],
    ledger_artifact_sha256: str,
) -> tuple[str | None, list[Any], str, list[str], dict[str, Any], str | None]:
    """Apply the ledger as the sole authority for transcription readiness."""

    ledger_type = str(ledger_row.get("item_type") or "unknown").casefold()
    stem = ledger_row["stem"]
    option_field = ledger_row["options"]
    stem_status = stem["status"]
    option_status = option_field["status"]
    type_refined_by_official = ledger_type not in {"unknown", resolved_item_type}
    if type_refined_by_official and option_status == "verified":
        raise ReleaseAssemblyError(
            f"content ledger {key}: item type {ledger_type!r} != {resolved_item_type!r}"
        )
    method: str | None = None
    if stem_status == "verified":
        verified_question = str(stem["content"])
        if prior_status == "verified" and question and question != verified_question:
            raise ReleaseAssemblyError(
                f"content ledger {key}: verified stem conflicts with upstream text"
            )
        question = verified_question
        method = str(stem["verification_method"])
    if option_status == "verified":
        options = _normalized_options(option_field["content"])
    elif option_status == "not_applicable":
        if (
            resolved_item_type not in {"nat", "descriptive", "composite"}
            and not type_refined_by_official
        ):
            raise ReleaseAssemblyError(
                f"content ledger {key}: options are N/A for {resolved_item_type}"
            )
        options = []
    elif resolved_item_type not in {"mcq", "msq", "unknown"}:
        if ledger_type != "unknown" and not type_refined_by_official:
            raise ReleaseAssemblyError(
                f"content ledger {key}: unexpected option review for {resolved_item_type}"
            )
        options = []

    asset_blockers = list(ledger_row.get("asset_blockers") or [])
    fully_verified = (
        stem_status == "verified"
        and (
            option_status == "verified"
            if resolved_item_type in {"mcq", "msq"}
            else option_status == "not_applicable"
        )
        and not asset_blockers
    )
    if fully_verified:
        status = "verified"
        flags: list[str] = []
    else:
        status = "missing" if stem_status == "missing" else "review_required"
        flags = sorted(set(str(value) for value in ledger_row.get("blockers") or []))
        if type_refined_by_official:
            flags.append("content_ledger_type_refined_by_official_answer")
            flags = sorted(set(flags))
        if not flags:
            flags.append("content_verification_not_complete")
    reference = {
        "kind": "verified_content_ledger",
        "url": None,
        "sha256": ledger_artifact_sha256,
        "note": (
            f"canonical_ordinal={key[1]}; stem_status={stem_status}; "
            f"stem_method={stem.get('verification_method')}; "
            f"options_status={option_status}; "
            f"options_method={option_field.get('verification_method')}; "
            f"figure_status={ledger_row['figure_evidence'].get('status')}"
        ),
    }
    extraction_method = f"content_ledger_{method}" if method else None
    return question, options, status, flags, reference, extraction_method


def _answer(
    *,
    canonical: Mapping[str, Any],
    candidate_row: Mapping[str, Any],
    resolution: Mapping[str, Any] | None,
) -> tuple[str, float | None, Any | None, str, list[str], list[dict[str, Any]]]:
    candidate = candidate_row.get("candidate")
    candidate = candidate if isinstance(candidate, Mapping) else {}
    item_type = str(candidate.get("item_type") or canonical.get("item_type") or "unknown").casefold()
    marks = canonical.get("marks")
    if marks is None:
        marks = candidate.get("marks")
    accepted = None
    answer_status = "not_applicable" if item_type == "descriptive" else "unresolved"
    flags: list[str] = []
    references: list[dict[str, Any]] = []
    if resolution is None or resolution.get("status") not in VERIFIED_ANSWER_STATUSES:
        community_answer, community_flags, community_references = (
            _community_candidate_answer(
                canonical=canonical,
                candidate_row=candidate_row,
                item_type=item_type,
                marks=marks,
            )
        )
        flags.extend(community_flags)
        if community_answer is not None:
            return (
                item_type,
                marks,
                community_answer,
                "community_verified",
                flags,
                community_references,
            )
        if item_type in OBJECTIVE_TYPES:
            flags.append("objective_answer_not_verified")
        return item_type, marks, accepted, answer_status, flags, references

    selected_type = str(resolution.get("selected_question_type") or "").casefold()
    if selected_type in OBJECTIVE_TYPES:
        item_type = selected_type
    selected_marks = resolution.get("selected_marks")
    if selected_marks is not None:
        marks = selected_marks
    accepted, answer_flags = _normalized_answer(
        resolution.get("selected_answer"), question_type=item_type
    )
    flags.extend(answer_flags)
    answer_status = (
        "official"
        if resolution.get("status") == "official"
        else "community_verified"
    )
    references.append(
        {
            "kind": "verified_answer_key",
            "url": None,
            "sha256": None,
            "note": (
                f"status={resolution.get('status')}; claim_ids="
                + ",".join(str(value) for value in resolution.get("supporting_claim_ids") or [])
            ),
        }
    )
    return item_type, marks, accepted, answer_status, flags, references


def _content_sha256(item: Mapping[str, Any]) -> str:
    payload = {
        key: item.get(key)
        for key in (
            "source_paper_id",
            "item_label",
            "ordinal",
            "legacy_source_ordinals",
            "parent_item_label",
            "source_page",
            "marks",
            "item_type",
            "question_md",
            "options",
            "accepted_answers",
            "solution_md",
            "subject_code",
            "topic_slug",
            "syllabus_status",
            "transcription_status",
            "answer_status",
            "classification_status",
            "practice_eligible",
            "review_flags",
            "assets",
            "source_references",
            "extraction_method",
            "extraction_confidence",
        )
    }
    return _canonical_sha256(payload)


def _release_blockers(item: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    if not item.get("question_md"):
        blockers.append("question_text_missing")
    if item.get("transcription_status") != "verified":
        blockers.append("transcription_not_verified")
    if item.get("source_page") is None:
        blockers.append("original_source_page_missing")
    references = item.get("source_references") or []
    if not any(
        isinstance(reference, Mapping)
        and reference.get("kind") == "original_pdf_item"
        and isinstance(reference.get("sha256"), str)
        and HASH_RE.fullmatch(str(reference.get("sha256")).casefold())
        for reference in references
    ):
        blockers.append("original_item_reference_missing")
    item_type = item.get("item_type")
    if item_type == "unknown":
        blockers.append("item_type_unresolved")
    if item.get("marks") is None:
        blockers.append("marks_missing")
    if item.get("classification_status") not in {"verified", "out_of_syllabus"}:
        blockers.append("classification_not_verified")
    if item.get("syllabus_status") not in {"in_syllabus", "out_of_syllabus"}:
        blockers.append("syllabus_status_not_final")
    if not item.get("subject_code") or not item.get("topic_slug"):
        blockers.append("course_or_topic_missing")
    if item_type in OBJECTIVE_TYPES:
        if item.get("answer_status") not in {"official", "community_verified"}:
            blockers.append("objective_answer_not_verified")
        if item.get("accepted_answers") is None:
            blockers.append("objective_answer_missing")
        options = item.get("options") or []
        if item_type in {"mcq", "msq"} and len(options) < 2:
            blockers.append("objective_options_missing")
        if item_type == "nat" and options:
            blockers.append("nat_has_options")
    blockers.extend(str(flag) for flag in item.get("review_flags") or [])
    return sorted(set(blockers))


def _auto_gradable_blockers(
    item: Mapping[str, Any],
    paper: Mapping[str, Any],
    release_blockers: Sequence[str],
) -> list[str]:
    blockers = list(release_blockers)
    if item.get("item_type") not in OBJECTIVE_TYPES:
        blockers.append("not_auto_gradable_item_type")
    if item.get("syllabus_status") != "in_syllabus":
        blockers.append("not_in_current_syllabus")
    if not item.get("solution_md"):
        blockers.append("solution_missing")
    if item.get("marks") not in {1, 2, 1.0, 2.0}:
        blockers.append("marks_not_one_or_two")
    if paper.get("source_status") != "verified":
        blockers.append("paper_source_not_explicitly_promoted")
    return sorted(set(blockers))


def _parent_record(
    *,
    canonical: Mapping[str, Any],
    candidate_row: Mapping[str, Any],
    provenance: Mapping[str, Any],
    overlay: Mapping[str, Any],
    resolution: Mapping[str, Any] | None,
    matcher_row: Mapping[str, Any] | None,
    content_ledger_row: Mapping[str, Any],
    content_ledger_artifact_sha256: str,
    figure_decision: Mapping[str, Any],
    figure_artifact_sha256: str,
    paper: Mapping[str, Any],
    ordinal: int,
    legacy_expanded: bool,
) -> dict[str, Any]:
    course, topic, syllabus_status, classification_status, classification_flags = (
        _classification(candidate_row, canonical)
    )
    item_type, marks, accepted, answer_status, answer_flags, answer_refs = _answer(
        canonical=canonical,
        candidate_row=candidate_row,
        resolution=resolution,
    )
    question, options, prior_transcription_status, _ = _transcription(
        canonical=canonical,
        candidate_row=candidate_row,
        overlay=overlay,
        matcher_row=matcher_row,
        resolved_item_type=item_type,
    )
    (
        question,
        options,
        transcription_status,
        transcription_flags,
        content_reference,
        content_extraction_method,
    ) = _content_ledger_transcription(
        key=(str(canonical["source_paper_id"]), int(canonical["ordinal"])),
        question=question,
        options=options,
        prior_status=prior_transcription_status,
        resolved_item_type=item_type,
        ledger_row=content_ledger_row,
        ledger_artifact_sha256=content_ledger_artifact_sha256,
    )
    source_pages = list(provenance.get("source_pages") or [])
    flags = sorted(
        set(
            transcription_flags
            + classification_flags
            + answer_flags
            + list(figure_decision.get("review_flags") or [])
        )
    )
    references = list(canonical.get("source_references") or [])
    references.append(
        _original_reference(
            paper=paper,
            provenance=provenance,
            canonical_parent_ordinal=int(canonical["ordinal"]),
            source_pages=source_pages,
            item_label=str(canonical.get("item_label") or ""),
        )
    )
    references.extend(answer_refs)
    references.append(content_reference)
    references.append(
        {
            "kind": "verified_figure_asset_index",
            "url": None,
            "sha256": figure_artifact_sha256,
            "note": (
                f"canonical_ordinal={canonical['ordinal']}; "
                f"child_item_label=null; status={figure_decision['status']}; "
                "asset_sha256=" + ",".join(figure_decision["asset_sha256"])
            ),
        }
    )
    if matcher_row is not None:
        references.append(
            {
                "kind": "review_transcription_match",
                "url": None,
                "sha256": None,
                "note": "manual_review_required=true; match_status=exact_proposed_review",
            }
        )
    if legacy_expanded:
        references.append(
            {
                "kind": "canonical_parent_slot",
                "url": None,
                "sha256": None,
                "note": (
                    f"canonical_parent_ordinal={canonical['ordinal']}; "
                    f"parent_item_label={canonical.get('item_label')}"
                ),
            }
        )
    item = {
        "source_paper_id": canonical["source_paper_id"],
        "item_label": canonical["item_label"],
        "ordinal": ordinal,
        "legacy_source_ordinals": (
            []
            if legacy_expanded
            else list(canonical.get("legacy_source_ordinals") or [])
        ),
        "parent_item_label": canonical.get("parent_item_label"),
        "source_page": source_pages[0] if source_pages else canonical.get("source_page"),
        "marks": float(marks) if marks is not None else None,
        "item_type": item_type,
        "question_md": question,
        "options": options,
        "accepted_answers": accepted,
        "solution_md": canonical.get("solution_md"),
        "subject_code": course,
        "topic_slug": topic,
        "syllabus_status": syllabus_status,
        "transcription_status": transcription_status,
        "answer_status": answer_status,
        "classification_status": classification_status,
        "practice_eligible": False,
        "review_flags": sorted(set(flags)),
        "assets": copy.deepcopy(figure_decision.get("assets") or []),
        "source_references": _dedupe_references(references),
        "extraction_method": (
            content_extraction_method
            or canonical.get("extraction_method")
            or "staging_evidence_merge"
        ),
        "extraction_confidence": (
            1.0
            if transcription_status == "verified"
            else canonical.get("extraction_confidence")
        ),
    }
    item["content_sha256"] = _content_sha256(item)
    return item


def _verified_text(value: Any, expected_hash: Any, *, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReleaseAssemblyError(f"{context}: exact child text is missing")
    text = value.strip()
    if _sha256_text(text) != _require_hash(expected_hash, context=f"{context} hash"):
        raise ReleaseAssemblyError(f"{context}: exact child text hash drifted")
    return text


def _child_record(
    *,
    parent: Mapping[str, Any],
    decision: Mapping[str, Any],
    child: Mapping[str, Any],
    provenance: Mapping[str, Any],
    overlay: Mapping[str, Any],
    overlay_artifact_sha256: str,
    child_classification: Mapping[str, Any],
    figure_decision: Mapping[str, Any],
    figure_artifact_sha256: str,
    paper: Mapping[str, Any],
    ordinal: int,
) -> dict[str, Any]:
    context = f"{parent['source_paper_id']}#{parent['ordinal']}/{child.get('child_item_label')}"
    if child.get("materialization_status") != "exact":
        raise ReleaseAssemblyError(f"{context}: child content is not exact")
    prompt = _verified_text(
        child.get("prompt_text"), child.get("prompt_text_sha256"), context=context
    )
    evidence = child.get("prompt_evidence")
    if not isinstance(evidence, Mapping):
        raise ReleaseAssemblyError(f"{context}: prompt evidence is missing")
    prompt_source = child.get("prompt_source")
    overlay_sources = {
        "original_transcription_overlay_child",
        "bounded_nested_span_in_overlay_child",
        "bounded_roman_span_in_overlay_parent",
    }
    if prompt_source in overlay_sources:
        if evidence.get("overlay_artifact_sha256") != overlay_artifact_sha256:
            raise ReleaseAssemblyError(
                f"{context}: prompt uses a stale transcription overlay"
            )
    if prompt_source == "original_transcription_overlay_child":
        # The audited prompt may normalize a checksum-bound source child span.
        # Both hashes must therefore be valid, but need not be byte-identical.
        _require_hash(
            evidence.get("source_child_text_sha256"),
            context=f"{context} source child span",
        )
        parent_block_hash = provenance.get("text_block_sha256")
        if (
            parent_block_hash
            and evidence.get("source_text_block_sha256") != parent_block_hash
        ):
            raise ReleaseAssemblyError(f"{context}: parent text-block evidence drifted")
    elif prompt_source in {
        "bounded_nested_span_in_overlay_child",
        "bounded_roman_span_in_overlay_parent",
    }:
        span_hash_key = (
            "ancestor_text_sha256"
            if prompt_source == "bounded_nested_span_in_overlay_child"
            else "parent_prompt_sha256"
        )
        _require_hash(evidence.get(span_hash_key), context=f"{context} source span")
        start = evidence.get("start_offset")
        end = evidence.get("end_offset")
        if (
            not isinstance(start, int)
            or not isinstance(end, int)
            or start < 0
            or end <= start
        ):
            raise ReleaseAssemblyError(f"{context}: bounded source span is invalid")
    elif prompt_source == "manual_visual_transcription_from_checksum_bound_complete_scan":
        _require_hash(
            evidence.get("source_pdf_sha256"),
            context=f"{context} visual source PDF",
        )
        source_url = evidence.get("source_url")
        if not isinstance(source_url, str) or not source_url.startswith(("https://", "http://")):
            raise ReleaseAssemblyError(f"{context}: visual source URL is missing")
        evidence_pages = evidence.get("source_pages")
        page_count = evidence.get("source_page_count")
        if (
            not isinstance(evidence_pages, list)
            or not evidence_pages
            or any(not isinstance(page, int) or page < 1 for page in evidence_pages)
            or not isinstance(page_count, int)
            or page_count < max(evidence_pages or [1])
        ):
            raise ReleaseAssemblyError(f"{context}: visual source pages drifted")
        if evidence.get("visual_transcription_required") is not True:
            raise ReleaseAssemblyError(f"{context}: visual transcription guard is missing")
        visual_renders = evidence.get("rendered_page_evidence")
        if not isinstance(visual_renders, list) or not visual_renders:
            raise ReleaseAssemblyError(f"{context}: visual render evidence is missing")
        for rendered_page in visual_renders:
            if not isinstance(rendered_page, Mapping):
                raise ReleaseAssemblyError(f"{context}: visual render evidence is malformed")
            _require_hash(
                rendered_page.get("rendered_page_sha256")
                or rendered_page.get("sha256"),
                context=f"{context} visual render",
            )
    else:
        raise ReleaseAssemblyError(f"{context}: unknown child prompt evidence mode")

    shared = child.get("shared_context")
    if not isinstance(shared, Mapping):
        raise ReleaseAssemblyError(f"{context}: shared context is missing")
    if (
        shared.get("source_paper_id") != parent.get("source_paper_id")
        or shared.get("canonical_parent_ordinal") != parent.get("ordinal")
        or shared.get("parent_item_label") != parent.get("item_label")
    ):
        raise ReleaseAssemblyError(f"{context}: shared context names another parent")
    canonical_parent_text = str(parent.get("question_md") or "").strip()
    if shared.get("canonical_parent_question_sha256") != _sha256_text(
        canonical_parent_text
    ):
        raise ReleaseAssemblyError(f"{context}: canonical parent question drifted")
    additional = str(shared.get("additional_shared_text") or "").strip()
    if shared.get("additional_shared_text_sha256") != _sha256_text(additional):
        raise ReleaseAssemblyError(f"{context}: additional shared context drifted")
    pieces: list[str] = []
    for text in (canonical_parent_text, additional, prompt):
        if text and text not in pieces:
            pieces.append(text)
    question = "\n\n".join(pieces)
    if not question:
        raise ReleaseAssemblyError(f"{context}: composed child question is empty")

    source_pages = child.get("source_pages")
    if not isinstance(source_pages, list) or not source_pages:
        raise ReleaseAssemblyError(f"{context}: child source pages are missing")
    rendered = child.get("rendered_page_evidence")
    if not isinstance(rendered, list) or not rendered:
        raise ReleaseAssemblyError(f"{context}: rendered evidence is missing")
    rendered_pages = [entry.get("page") for entry in rendered if isinstance(entry, Mapping)]
    if sorted(set(rendered_pages)) != sorted(set(source_pages)):
        raise ReleaseAssemblyError(f"{context}: rendered child pages are incomplete")
    for entry in rendered:
        if not isinstance(entry, Mapping):
            raise ReleaseAssemblyError(f"{context}: malformed rendered evidence")
        _require_hash(entry.get("rendered_page_sha256"), context=f"{context} render")

    classification_outcome = child_classification.get("decision")
    if classification_outcome == "map":
        course = str(child_classification["canonical_course"])
        topic = str(child_classification["canonical_topic"])
        syllabus_status = "in_syllabus"
        classification_status = "verified"
    elif classification_outcome == "out_of_syllabus":
        course = None
        topic = None
        syllabus_status = "out_of_syllabus"
        classification_status = "out_of_syllabus"
    else:
        raise ReleaseAssemblyError(f"{context}: child classification is not final")
    references = list(parent.get("source_references") or [])
    references.extend(
        [
            _original_reference(
                paper=paper,
                provenance=provenance,
                canonical_parent_ordinal=int(parent["ordinal"]),
                source_pages=source_pages,
                item_label=str(child.get("child_item_label") or ""),
            ),
            {
                "kind": "canonical_parent_slot",
                "url": None,
                "sha256": None,
                "note": (
                    f"canonical_parent_ordinal={parent['ordinal']}; "
                    f"parent_item_label={parent.get('item_label')}"
                ),
            },
            {
                "kind": "child_topic_classification",
                "url": None,
                "sha256": None,
                "note": (
                    f"decision={classification_outcome}; "
                    f"reason_code={child_classification.get('reason_code')}; "
                    f"evidence_sha256={child_classification.get('evidence_sha256')}"
                ),
            },
            {
                "kind": "verified_figure_asset_index",
                "url": None,
                "sha256": figure_artifact_sha256,
                "note": (
                    f"canonical_ordinal={parent['ordinal']}; "
                    f"child_item_label={child['child_item_label']}; "
                    f"status={figure_decision['status']}; "
                    "asset_sha256=" + ",".join(figure_decision["asset_sha256"])
                ),
            },
        ]
    )
    flags = sorted(
        set(
            [str(flag) for flag in child.get("review_flags") or []]
            + list(figure_decision.get("review_flags") or [])
        )
    )
    item = {
        "source_paper_id": parent["source_paper_id"],
        "item_label": child["child_item_label"],
        "ordinal": ordinal,
        "legacy_source_ordinals": [],
        "parent_item_label": parent["item_label"],
        "source_page": source_pages[0],
        "marks": (
            float(child["marks"]) if child.get("marks") is not None else None
        ),
        "item_type": "descriptive",
        "question_md": question,
        "options": [],
        "accepted_answers": None,
        "solution_md": None,
        "subject_code": course,
        "topic_slug": topic,
        "syllabus_status": syllabus_status,
        "transcription_status": "verified",
        "answer_status": "not_applicable",
        "classification_status": classification_status,
        "practice_eligible": False,
        "review_flags": flags,
        "assets": copy.deepcopy(figure_decision.get("assets") or []),
        "source_references": _dedupe_references(references),
        "extraction_method": "audited_legacy_child_exact",
        "extraction_confidence": 1.0,
    }
    item["content_sha256"] = _content_sha256(item)
    return item


def _legacy_decisions(
    audit: Mapping[str, Any],
    *,
    canonical_path: Path,
    provenance_path: Path,
    manifest_path: Path,
    overlay_path: Path,
    expected_legacy_paper_ids: set[str],
) -> tuple[dict[tuple[str, int], dict[str, Any]], dict[str, int]]:
    _assert_staging_guard(
        audit,
        context="legacy subpart audit",
        required_false=(
            "database_writes_performed",
            "production_import_authorized",
            "automatic_promotion_allowed",
        ),
    )
    _validate_embedded_hash(
        audit, field="artifact_sha256", context="legacy subpart audit"
    )
    bindings = audit.get("input_bindings")
    if not isinstance(bindings, Mapping):
        raise ReleaseAssemblyError("legacy subpart audit input bindings are missing")
    for key, path in (
        ("canonical_archive_sha256", canonical_path),
        ("original_pdf_provenance_sha256", provenance_path),
        ("source_manifest_sha256", manifest_path),
        ("original_question_transcription_overlay_sha256", overlay_path),
    ):
        _assert_flat_binding(
            bindings,
            key,
            path,
            context="legacy subpart audit",
        )

    papers = audit.get("papers")
    if not isinstance(papers, list):
        raise ReleaseAssemblyError("legacy subpart audit papers are missing")
    observed_papers = {
        str(row.get("paper_id")) for row in papers if isinstance(row, Mapping)
    }
    if observed_papers != expected_legacy_paper_ids:
        raise ReleaseAssemblyError(
            "legacy subpart audit paper coverage mismatch: "
            f"{sorted(observed_papers)} != {sorted(expected_legacy_paper_ids)}"
        )
    decisions: dict[tuple[str, int], dict[str, Any]] = {}
    expanded_counts: dict[str, int] = {}
    for paper in papers:
        if not isinstance(paper, dict):
            raise ReleaseAssemblyError("legacy subpart audit contains a malformed paper")
        paper_id = str(paper["paper_id"])
        final_count = paper.get("final_split_database_record_count")
        if not isinstance(final_count, int) or final_count < 1:
            raise ReleaseAssemblyError(f"{paper_id}: expanded record count is unresolved")
        if paper.get("residual_review_row_count") != 0:
            raise ReleaseAssemblyError(f"{paper_id}: legacy split audit still has reviews")
        expanded_counts[paper_id] = final_count
        for row in paper.get("decisions") or []:
            if not isinstance(row, dict):
                raise ReleaseAssemblyError(f"{paper_id}: malformed split decision")
            ordinal = row.get("parent_canonical_ordinal")
            if not isinstance(ordinal, int) or ordinal < 1:
                raise ReleaseAssemblyError(f"{paper_id}: malformed parent ordinal")
            key = paper_id, ordinal
            if key in decisions:
                raise ReleaseAssemblyError(f"legacy subpart audit duplicates {key}")
            if row.get("decision") not in {"split", "no_split"}:
                raise ReleaseAssemblyError(f"{key}: split decision is not final")
            if row.get("review_required") is not False:
                raise ReleaseAssemblyError(f"{key}: split decision remains review-only")
            labels = row.get("child_labels")
            records = row.get("child_records")
            if row.get("decision") == "split":
                if not isinstance(labels, list) or len(labels) < 2:
                    raise ReleaseAssemblyError(f"{key}: split child labels are incomplete")
                if not isinstance(records, list) or len(records) != len(labels):
                    raise ReleaseAssemblyError(f"{key}: split child records are incomplete")
                observed_labels = [record.get("child_item_label") for record in records]
                observed_orders = [record.get("child_order") for record in records]
                if observed_labels != labels or observed_orders != list(
                    range(1, len(records) + 1)
                ):
                    raise ReleaseAssemblyError(f"{key}: child order/identity is ambiguous")
                prompt_hashes = [record.get("prompt_text_sha256") for record in records]
                if len(set(prompt_hashes)) != len(prompt_hashes):
                    raise ReleaseAssemblyError(f"{key}: child prompt content is ambiguous")
            elif records not in (None, []) or labels:
                raise ReleaseAssemblyError(f"{key}: no_split decision contains child records")
            decisions[key] = row
    return decisions, expanded_counts


def _canonical_topic_inventory(raw: Mapping[str, Any]) -> dict[str, set[str]]:
    courses = raw.get("courses")
    if not isinstance(courses, Mapping) or not courses:
        raise ReleaseAssemblyError("canonical topic inventory is missing")
    result: dict[str, set[str]] = {}
    for raw_code, raw_course in courses.items():
        topics = raw_course.get("by_topic") if isinstance(raw_course, Mapping) else None
        if not isinstance(topics, Mapping) or not topics:
            raise ReleaseAssemblyError(f"topic inventory course {raw_code!r} has no topics")
        result[str(raw_code)] = {_slug(str(topic)) for topic in topics}
    return result


def _legacy_child_evidence(
    child: Mapping[str, Any],
    *,
    key: tuple[str, int, str],
) -> tuple[str, str]:
    prompt = child.get("prompt_text")
    prompt_hash = child.get("prompt_text_sha256")
    if (
        not isinstance(prompt, str)
        or not prompt.strip()
        or prompt_hash != _sha256_text(prompt)
    ):
        raise ReleaseAssemblyError(f"{key}: child classification prompt hash drifted")
    shared = child.get("shared_context")
    if not isinstance(shared, Mapping):
        raise ReleaseAssemblyError(f"{key}: child classification shared context is missing")
    shared_text = shared.get("additional_shared_text") or ""
    if not isinstance(shared_text, str):
        raise ReleaseAssemblyError(f"{key}: child shared text is malformed")
    if shared_text and shared.get("additional_shared_text_sha256") != _sha256_text(
        shared_text
    ):
        raise ReleaseAssemblyError(f"{key}: child shared-text hash drifted")
    source_pages = child.get("source_pages")
    if (
        not isinstance(source_pages, list)
        or not source_pages
        or any(not isinstance(page, int) or page < 1 for page in source_pages)
    ):
        raise ReleaseAssemblyError(f"{key}: child classification source pages are invalid")
    render_hashes: list[str] = []
    for rendered in child.get("rendered_page_evidence") or []:
        digest = rendered.get("rendered_page_sha256") if isinstance(rendered, Mapping) else None
        render_hashes.append(_require_hash(digest, context=f"{key} rendered page"))
    if not render_hashes:
        raise ReleaseAssemblyError(f"{key}: child classification render evidence is missing")
    payload = {
        "paper_id": key[0],
        "parent_canonical_ordinal": key[1],
        "child_item_label": key[2],
        "prompt_text_sha256": prompt_hash,
        "prompt_source": child.get("prompt_source"),
        "prompt_evidence_sha256": _canonical_sha256(
            child.get("prompt_evidence") or {}
        ),
        "shared_context_sha256": _canonical_sha256(shared),
        "source_pages": source_pages,
        "rendered_page_sha256": render_hashes,
    }
    excerpt = " ".join(
        (f"{prompt} Context: {shared_text}" if shared_text else prompt).split()
    )[:320]
    return _canonical_sha256(payload), excerpt


def _validate_legacy_child_policy(
    policy: Mapping[str, Any],
    *,
    policy_path: Path,
    audit_path: Path,
    inventory_path: Path,
    decisions: Mapping[tuple[str, int], Mapping[str, Any]],
) -> dict[tuple[str, int, str], dict[str, Any]]:
    if policy.get("schema_version") != "1.0":
        raise ReleaseAssemblyError("legacy child classification schema drifted")
    if not isinstance(policy.get("policy_version"), str) or not str(
        policy.get("policy_version")
    ).strip():
        raise ReleaseAssemblyError("legacy child classification policy version is missing")
    _assert_staging_guard(
        policy,
        context="legacy child classification policy",
        required_false=("database_writes_performed", "production_import_authorized"),
    )
    scope = policy.get("scope")
    if not isinstance(scope, Mapping):
        raise ReleaseAssemblyError("legacy child classification scope is missing")
    if scope.get("legacy_subpart_audit_sha256") != _sha256_file(audit_path):
        raise ReleaseAssemblyError("legacy child classifications use a stale subpart audit")
    if scope.get("canonical_inventory_sha256") != _sha256_file(inventory_path):
        raise ReleaseAssemblyError("legacy child classifications use a stale topic inventory")
    classification_policy = policy.get("classification_policy")
    if classification_policy is not None:
        if not isinstance(classification_policy, Mapping):
            raise ReleaseAssemblyError("legacy child classification policy is malformed")
        if classification_policy.get("every_child_is_an_explicit_decision") is not True:
            raise ReleaseAssemblyError("legacy child classification is not child-explicit")
        if classification_policy.get("runtime_parent_inheritance_allowed") is not False:
            raise ReleaseAssemblyError("legacy child classification allows parent inheritance")

    source_children: dict[tuple[str, int, str], Mapping[str, Any]] = {}
    split_parent_count = 0
    for (paper_id, parent_ordinal), parent in decisions.items():
        records = parent.get("child_records") or []
        if records:
            split_parent_count += 1
        for child in records:
            if not isinstance(child, Mapping):
                raise ReleaseAssemblyError(f"{paper_id}#{parent_ordinal}: malformed child")
            label = child.get("child_item_label")
            if not isinstance(label, str) or not label.strip():
                raise ReleaseAssemblyError(f"{paper_id}#{parent_ordinal}: child label missing")
            key = paper_id, parent_ordinal, label.strip()
            if key in source_children:
                raise ReleaseAssemblyError(f"duplicate materialized child {key}")
            source_children[key] = child
    if scope.get("materialized_child_count") != len(source_children):
        raise ReleaseAssemblyError("legacy child classification child count drifted")
    if scope.get("split_parent_count") != split_parent_count:
        raise ReleaseAssemblyError("legacy child classification parent count drifted")

    inventory = _canonical_topic_inventory(_read_json(inventory_path))
    result: dict[tuple[str, int, str], dict[str, Any]] = {}
    outcomes: Counter[str] = Counter()
    rows = policy.get("child_decisions")
    if not isinstance(rows, list):
        raise ReleaseAssemblyError("legacy child classification decisions are missing")
    for row in rows:
        if not isinstance(row, dict):
            raise ReleaseAssemblyError("legacy child classification has a malformed row")
        paper_id = str(row.get("paper_id") or "")
        ordinal = row.get("parent_canonical_ordinal")
        label = row.get("child_item_label")
        if (
            not paper_id
            or not isinstance(ordinal, int)
            or ordinal < 1
            or not isinstance(label, str)
            or not label.strip()
        ):
            raise ReleaseAssemblyError("legacy child classification key is malformed")
        key = paper_id, ordinal, label.strip()
        child = source_children.get(key)
        if child is None or key in result:
            raise ReleaseAssemblyError(f"duplicate or unknown child classification {key}")
        evidence_hash, excerpt = _legacy_child_evidence(child, key=key)
        if (
            row.get("prompt_text_sha256") != child.get("prompt_text_sha256")
            or row.get("evidence_sha256") != evidence_hash
            or row.get("evidence_excerpt") != excerpt
        ):
            raise ReleaseAssemblyError(f"{key}: child classification evidence drifted")
        outcome = row.get("decision")
        course = row.get("canonical_course")
        topic = row.get("canonical_topic")
        if outcome == "map":
            if course not in inventory or topic not in inventory[course]:
                raise ReleaseAssemblyError(
                    f"{key}: child topic {course}/{topic} is outside canonical inventory"
                )
        elif outcome == "out_of_syllabus":
            if course is not None or topic is not None:
                raise ReleaseAssemblyError(f"{key}: out-of-syllabus child carries a topic")
        elif outcome == "review":
            raise ReleaseAssemblyError(f"{key}: child classification remains review-only")
        else:
            raise ReleaseAssemblyError(f"{key}: invalid child classification decision")
        reason_code = row.get("reason_code")
        reason = row.get("reason")
        comparison = row.get("parent_comparison")
        if (
            not isinstance(reason_code, str)
            or not reason_code.strip()
            or not isinstance(reason, str)
            or not reason.strip()
            or comparison
            not in {"same_as_parent", "differs_from_parent", "parent_unresolved"}
        ):
            raise ReleaseAssemblyError(f"{key}: child classification rationale is incomplete")
        result[key] = row
        outcomes[str(outcome)] += 1
    if set(result) != set(source_children):
        missing = sorted(set(source_children) - set(result))
        extra = sorted(set(result) - set(source_children))
        raise ReleaseAssemblyError(
            f"child classification coverage mismatch; missing={missing[:5]}, extra={extra[:5]}"
        )
    expected_summary = {
        "mapped": outcomes["map"],
        "out_of_syllabus": outcomes["out_of_syllabus"],
        "review": outcomes["review"],
    }
    if policy.get("summary") != expected_summary:
        raise ReleaseAssemblyError("legacy child classification summary drifted")
    return result


def assemble_release(
    *,
    canonical_path: Path = DEFAULT_CANONICAL,
    canonical_report_path: Path = DEFAULT_CANONICAL_REPORT,
    raw_candidates_path: Path = DEFAULT_RAW_CANDIDATES,
    candidates_path: Path = DEFAULT_CANDIDATES,
    candidate_report_path: Path = DEFAULT_CANDIDATE_REPORT,
    provenance_path: Path = DEFAULT_PROVENANCE,
    overlay_path: Path = DEFAULT_OVERLAY,
    answer_index_path: Path = DEFAULT_ANSWER_INDEX,
    legacy_audit_path: Path = DEFAULT_LEGACY_AUDIT,
    manifest_path: Path = DEFAULT_MANIFEST,
    topic_policy_path: Path = DEFAULT_TOPIC_POLICY,
    slot_policy_path: Path = DEFAULT_SLOT_POLICY,
    legacy_child_policy_path: Path = DEFAULT_LEGACY_CHILD_POLICY,
    topic_inventory_path: Path = DEFAULT_TOPIC_INVENTORY,
    content_ledger_path: Path = DEFAULT_CONTENT_LEDGER,
    figure_assets_path: Path = DEFAULT_FIGURE_ASSETS,
    source_verification_path: Path = DEFAULT_SOURCE_VERIFICATION,
    classification_review_base_path: Path | None = DEFAULT_CLASSIFICATION_REVIEW_BASE,
    classification_review_path: Path | None = DEFAULT_CLASSIFICATION_REVIEW_OVERRIDES,
    matcher_path: Path | None = None,
    expected_paper_count: int = EXPECTED_PAPER_COUNT,
    expected_parent_count: int = EXPECTED_PARENT_SLOT_COUNT,
    expected_expanded_count: int = EXPECTED_EXPANDED_RECORD_COUNT,
    expected_legacy_paper_ids: set[str] | None = None,
    expected_classification_counts: Mapping[str, int] | None = (
        EXPECTED_FINAL_CLASSIFICATION_COUNTS
    ),
) -> tuple[dict[str, Any], dict[str, Any]]:
    paths = {
        "canonical_archive": canonical_path.resolve(),
        "canonical_report": canonical_report_path.resolve(),
        "raw_candidates": raw_candidates_path.resolve(),
        "structured_candidates": candidates_path.resolve(),
        "candidate_report": candidate_report_path.resolve(),
        "original_pdf_provenance": provenance_path.resolve(),
        "original_transcription_overlay": overlay_path.resolve(),
        "answer_key_index": answer_index_path.resolve(),
        "legacy_subpart_audit": legacy_audit_path.resolve(),
        "source_manifest": manifest_path.resolve(),
        "topic_policy": topic_policy_path.resolve(),
        "slot_policy": slot_policy_path.resolve(),
        "legacy_child_policy": legacy_child_policy_path.resolve(),
        "topic_inventory": topic_inventory_path.resolve(),
        "content_verification_ledger": content_ledger_path.resolve(),
        "figure_asset_index": figure_assets_path.resolve(),
        "paper_source_verification": source_verification_path.resolve(),
    }
    if classification_review_path is not None:
        if classification_review_base_path is None:
            raise ReleaseAssemblyError(
                "classification review base is required with review overrides"
            )
        paths["classification_review_base"] = (
            classification_review_base_path.resolve()
        )
        paths["classification_review_overrides"] = classification_review_path.resolve()
    if matcher_path is not None:
        paths["transcription_matcher"] = matcher_path.resolve()
    inputs = {name: _read_json(path) for name, path in paths.items()}

    canonical = inputs["canonical_archive"]
    canonical_report = inputs["canonical_report"]
    raw_candidates = inputs["raw_candidates"]
    candidates = inputs["structured_candidates"]
    candidate_report = inputs["candidate_report"]
    provenance = inputs["original_pdf_provenance"]
    overlay = inputs["original_transcription_overlay"]
    answer_index = inputs["answer_key_index"]
    legacy_audit = inputs["legacy_subpart_audit"]
    legacy_child_policy = inputs["legacy_child_policy"]
    content_ledger = inputs["content_verification_ledger"]
    figure_assets = inputs["figure_asset_index"]
    source_verification = inputs["paper_source_verification"]
    classification_review_base = inputs.get("classification_review_base")
    classification_review = inputs.get("classification_review_overrides")
    topic_inventory = inputs["topic_inventory"]
    manifest = inputs["source_manifest"]

    papers = canonical.get("papers")
    if not isinstance(papers, list) or len(papers) != expected_paper_count:
        raise ReleaseAssemblyError("canonical archive does not contain the expected papers")
    paper_by_id = {
        str(paper.get("id")): paper for paper in papers if isinstance(paper, dict)
    }
    if len(paper_by_id) != expected_paper_count:
        raise ReleaseAssemblyError("canonical archive paper ids are missing or duplicated")
    manifest_ids = {
        str(paper.get("id"))
        for paper in manifest.get("papers") or []
        if isinstance(paper, Mapping)
    }
    if manifest_ids != set(paper_by_id):
        raise ReleaseAssemblyError("canonical archive paper set is stale against manifest")

    canonical_map = _unique_map(
        canonical.get("questions"), ordinal_key="ordinal", context="canonical archive"
    )
    if len(canonical_map) != expected_parent_count:
        raise ReleaseAssemblyError("canonical archive parent-slot count is stale")
    candidate_map = _unique_map(
        candidates.get("questions"),
        ordinal_key="ordinal",
        context="structured candidates",
    )
    provenance_map = _unique_map(
        provenance.get("items"),
        ordinal_key="canonical_ordinal",
        context="original PDF provenance",
    )
    overlay_map = _unique_map(
        overlay.get("items"),
        ordinal_key="canonical_ordinal",
        context="transcription overlay",
    )
    _validate_identity_sets(
        canonical_map,
        ("structured candidates", candidate_map),
        ("original PDF provenance", provenance_map),
        ("transcription overlay", overlay_map),
    )

    _validate_canonical_report(
        canonical=canonical,
        report=canonical_report,
        manifest_path=paths["source_manifest"],
        expected_paper_count=expected_paper_count,
        expected_parent_count=expected_parent_count,
    )
    _assert_staging_guard(
        raw_candidates,
        context="raw candidates",
        required_false=("database_writes_performed", "automatic_promotion_allowed"),
    )
    _validate_candidate_lineage(
        raw_candidates_path=paths["raw_candidates"],
        candidates=candidates,
        candidate_report=candidate_report,
        topic_policy_path=paths["topic_policy"],
        slot_policy_path=paths["slot_policy"],
        expected_paper_count=expected_paper_count,
        expected_parent_count=expected_parent_count,
    )

    _assert_staging_guard(
        provenance,
        context="original PDF provenance",
        required_false=("production_import_authorized",),
    )
    _validate_embedded_hash(
        provenance, field="artifact_sha256", context="original PDF provenance"
    )
    if provenance.get("source_manifest_sha256") != _sha256_file(
        paths["source_manifest"]
    ):
        raise ReleaseAssemblyError("original PDF provenance uses a stale manifest")

    _assert_staging_guard(
        overlay,
        context="transcription overlay",
        required_false=(
            "database_writes_performed",
            "production_import_authorized",
            "automatic_promotion_allowed",
        ),
    )
    _validate_embedded_hash(
        overlay, field="artifact_sha256", context="transcription overlay"
    )
    overlay_bindings = overlay.get("input_bindings")
    if not isinstance(overlay_bindings, Mapping):
        raise ReleaseAssemblyError("transcription overlay input bindings are missing")
    for key, path_key in (
        ("canonical_archive", "canonical_archive"),
        ("canonical_candidates", "structured_candidates"),
        ("original_pdf_provenance", "original_pdf_provenance"),
        ("source_manifest", "source_manifest"),
    ):
        _assert_binding(
            overlay_bindings,
            key,
            paths[path_key],
            context="transcription overlay",
        )

    resolutions = _validate_answer_index(
        answer_index,
        manifest_path=paths["source_manifest"],
        canonical_keys=set(canonical_map),
    )
    matcher_map: dict[tuple[str, int], dict[str, Any]] = {}
    matcher = inputs.get("transcription_matcher")
    if matcher is not None:
        matcher_map = _validate_matcher(
            matcher, matcher_path=paths["transcription_matcher"]
        )
        if not set(matcher_map).issubset(canonical_map):
            raise ReleaseAssemblyError("matcher proposes content for unknown canonical slots")
        for key, row in matcher_map.items():
            if row.get("item_label") != canonical_map[key].get("item_label"):
                raise ReleaseAssemblyError(f"matcher item label mismatch at {key}")

    content_ledger_map = _validate_content_ledger(
        content_ledger,
        candidates_path=paths["structured_candidates"],
        provenance_path=paths["original_pdf_provenance"],
        overlay_path=paths["original_transcription_overlay"],
        answer_index_path=paths["answer_key_index"],
        figure_assets_path=paths["figure_asset_index"],
        canonical_map=canonical_map,
        provenance_map=provenance_map,
        expected_paper_count=expected_paper_count,
        expected_parent_count=expected_parent_count,
    )
    content_ledger_artifact_sha256 = _require_hash(
        content_ledger.get("artifact_sha256"),
        context="content verification ledger artifact",
    )

    legacy_ids = (
        set(expected_legacy_paper_ids)
        if expected_legacy_paper_ids is not None
        else set(LEGACY_PAPER_IDS)
    )
    decisions, expanded_counts = _legacy_decisions(
        legacy_audit,
        canonical_path=paths["canonical_archive"],
        provenance_path=paths["original_pdf_provenance"],
        manifest_path=paths["source_manifest"],
        overlay_path=paths["original_transcription_overlay"],
        expected_legacy_paper_ids=legacy_ids,
    )
    child_classifications = _validate_legacy_child_policy(
        legacy_child_policy,
        policy_path=paths["legacy_child_policy"],
        audit_path=paths["legacy_subpart_audit"],
        inventory_path=paths["topic_inventory"],
        decisions=decisions,
    )
    legacy_children: dict[tuple[str, int, str], Mapping[str, Any]] = {}
    for (paper_id, parent_ordinal), decision in decisions.items():
        if decision.get("decision") != "split":
            continue
        for child in decision.get("child_records") or []:
            if not isinstance(child, Mapping):
                raise ReleaseAssemblyError(
                    f"{paper_id}#{parent_ordinal}: legacy child row is malformed"
                )
            child_label = child.get("child_item_label")
            if not isinstance(child_label, str):
                raise ReleaseAssemblyError(
                    f"{paper_id}#{parent_ordinal}: legacy child label is missing"
                )
            child_key = paper_id, parent_ordinal, child_label
            if child_key in legacy_children:
                raise ReleaseAssemblyError(f"legacy child key is duplicated: {child_key}")
            legacy_children[child_key] = child
    figure_rows = _validate_figure_asset_index(
        figure_assets,
        canonical_path=paths["canonical_archive"],
        provenance_path=paths["original_pdf_provenance"],
        overlay_path=paths["original_transcription_overlay"],
        legacy_path=paths["legacy_subpart_audit"],
        manifest_path=paths["source_manifest"],
        canonical_map=canonical_map,
        provenance_map=provenance_map,
        child_map=legacy_children,
        paper_by_id=paper_by_id,
        expected_paper_count=expected_paper_count,
        expected_parent_count=expected_parent_count,
    )
    _validate_content_figure_alignment(content_ledger_map, figure_rows)
    figure_artifact_sha256 = _require_hash(
        figure_assets.get("artifact_sha256"), context="figure asset index artifact"
    )
    source_decisions = _validate_paper_source_verification(
        source_verification,
        manifest_path=paths["source_manifest"],
        canonical_path=paths["canonical_archive"],
        provenance_path=paths["original_pdf_provenance"],
        paper_by_id=paper_by_id,
        canonical_map=canonical_map,
        provenance_map=provenance_map,
        expected_paper_count=expected_paper_count,
        expected_parent_count=expected_parent_count,
    )
    source_verification_artifact_sha256 = _require_hash(
        source_verification.get("artifact_sha256"),
        context="paper source verification artifact",
    )

    expected_descriptive_parents = {
        key
        for key, item in canonical_map.items()
        if key[0] in legacy_ids
        and str(item.get("item_type") or "").casefold() == "descriptive"
    }
    if set(decisions) != expected_descriptive_parents:
        missing = sorted(expected_descriptive_parents - set(decisions))
        extra = sorted(set(decisions) - expected_descriptive_parents)
        raise ReleaseAssemblyError(
            f"legacy descriptive-parent coverage mismatch; missing={missing[:5]}, "
            f"extra={extra[:5]}"
        )

    final_papers: list[dict[str, Any]] = []
    for paper in papers:
        current = copy.deepcopy(paper)
        paper_id = str(current["id"])
        source_decision = source_decisions[paper_id]
        current["source_status"] = {
            "verified": "verified",
            "review": "review_required",
            "rejected": "rejected",
        }[str(source_decision["decision"])]
        source_note = (
            "Source verification "
            f"decision={source_decision['decision']}; method={source_decision['method']}; "
            f"artifact_sha256={source_verification_artifact_sha256}."
        )
        current["notes"] = " ".join(
            value
            for value in (str(current.get("notes") or "").strip(), source_note)
            if value
        )
        if paper_id in expanded_counts:
            before = current["expected_item_count"]
            after = expanded_counts[paper_id]
            current["expected_item_count"] = after
            suffix = (
                f"Expanded from {before} canonical parent slots to {after} "
                "audited archive records; staging-only."
            )
            current["notes"] = " ".join(
                value for value in (str(current.get("notes") or "").strip(), suffix) if value
            )
        final_papers.append(current)
    final_paper_by_id = {paper["id"]: paper for paper in final_papers}

    final_questions: list[dict[str, Any]] = []
    per_paper_parent_count = Counter(key[0] for key in canonical_map)
    per_paper_final_count: Counter[str] = Counter()
    for paper in final_papers:
        paper_id = str(paper["id"])
        parent_rows = [
            canonical_map[(paper_id, ordinal)]
            for ordinal in range(1, per_paper_parent_count[paper_id] + 1)
        ]
        final_ordinal = 0
        for parent in parent_rows:
            key = paper_id, int(parent["ordinal"])
            decision = decisions.get(key)
            if decision and decision.get("parent_item_label") != parent.get("item_label"):
                raise ReleaseAssemblyError(f"{key}: legacy parent label drifted")
            if decision and decision.get("decision") == "split":
                seen_questions: set[str] = set()
                for child in decision["child_records"]:
                    final_ordinal += 1
                    child_key = key[0], key[1], str(child["child_item_label"])
                    item = _child_record(
                        parent=parent,
                        decision=decision,
                        child=child,
                        provenance=provenance_map[key],
                        overlay=overlay_map[key],
                        overlay_artifact_sha256=str(overlay["artifact_sha256"]),
                        child_classification=child_classifications[child_key],
                        figure_decision=figure_rows[child_key],
                        figure_artifact_sha256=figure_artifact_sha256,
                        paper=paper,
                        ordinal=final_ordinal,
                    )
                    normalized = " ".join(str(item["question_md"]).split()).casefold()
                    if normalized in seen_questions:
                        raise ReleaseAssemblyError(f"{key}: composed child questions are ambiguous")
                    seen_questions.add(normalized)
                    final_questions.append(item)
                continue
            final_ordinal += 1
            final_questions.append(
                _parent_record(
                    canonical=parent,
                    candidate_row=candidate_map[key],
                    provenance=provenance_map[key],
                    overlay=overlay_map[key],
                    resolution=resolutions.get(key),
                    matcher_row=matcher_map.get(key),
                    content_ledger_row=content_ledger_map[key],
                    content_ledger_artifact_sha256=content_ledger_artifact_sha256,
                    figure_decision=figure_rows[(key[0], key[1], None)],
                    figure_artifact_sha256=figure_artifact_sha256,
                    paper=paper,
                    ordinal=final_ordinal,
                    legacy_expanded=paper_id in legacy_ids,
                )
            )
        per_paper_final_count[paper_id] = final_ordinal
        if final_ordinal != paper["expected_item_count"]:
            raise ReleaseAssemblyError(
                f"{paper_id}: expanded count {final_ordinal} does not match audited "
                f"count {paper['expected_item_count']}"
            )

    if len(final_questions) != expected_expanded_count:
        raise ReleaseAssemblyError(
            f"expanded corpus count {len(final_questions)} != {expected_expanded_count}"
        )
    identities = {(item["source_paper_id"], item["ordinal"]) for item in final_questions}
    labels = {(item["source_paper_id"], str(item["item_label"]).casefold()) for item in final_questions}
    if len(identities) != len(final_questions) or len(labels) != len(final_questions):
        raise ReleaseAssemblyError("expanded corpus identities are not unique")
    if any(item.get("practice_eligible") is not False for item in final_questions):
        raise ReleaseAssemblyError("staging assembler attempted practice promotion")

    classification_review_decisions: dict[
        tuple[str, int, str, str | None], dict[str, Any]
    ] = {}
    if classification_review is None:
        if any(
            item.get("classification_status") == "review_required"
            for item in final_questions
        ):
            raise ReleaseAssemblyError(
                "classification review overrides are required for unresolved base rows"
            )
    else:
        if not isinstance(classification_review_base, Mapping):
            raise ReleaseAssemblyError("classification review base is missing")
        classification_review_base_identity = _validate_classification_review_base(
            classification_review_base,
            canonical_path=paths["canonical_archive"],
            legacy_path=paths["legacy_subpart_audit"],
            child_policy_path=paths["legacy_child_policy"],
            parent_policy_path=paths["slot_policy"],
            inventory_path=paths["topic_inventory"],
            content_ledger_path=paths["content_verification_ledger"],
            provenance_path=paths["original_pdf_provenance"],
            base_items=final_questions,
        )
        classification_review_decisions = _validate_classification_review_overrides(
            classification_review,
            classification_base_path=paths["classification_review_base"],
            classification_base_identity=classification_review_base_identity,
            canonical_path=paths["canonical_archive"],
            legacy_path=paths["legacy_subpart_audit"],
            child_policy_path=paths["legacy_child_policy"],
            parent_policy_path=paths["slot_policy"],
            inventory_path=paths["topic_inventory"],
            content_ledger_path=paths["content_verification_ledger"],
            provenance_path=paths["original_pdf_provenance"],
            base_items=final_questions,
            paper_by_id=paper_by_id,
            inventory_raw=topic_inventory,
        )
        classification_review_artifact_sha256 = _require_hash(
            classification_review.get("artifact_sha256"),
            context="classification review override artifact",
        )
        _apply_classification_review_overrides(
            final_questions,
            classification_review_decisions,
            artifact_sha256=classification_review_artifact_sha256,
        )

    classification_counts: Counter[str] = Counter()
    for item in final_questions:
        status = item.get("classification_status")
        if status == "verified":
            classification_counts["mapped"] += 1
        elif status == "out_of_syllabus":
            classification_counts["out_of_syllabus"] += 1
        else:
            classification_counts["review"] += 1
    observed_classification_counts = {
        key: classification_counts[key]
        for key in ("mapped", "out_of_syllabus", "review")
    }
    classification_counts_exact = expected_classification_counts is None or (
        observed_classification_counts == dict(expected_classification_counts)
    )
    if not classification_counts_exact:
        raise ReleaseAssemblyError(
            "final classification counts drifted: "
            f"{observed_classification_counts} != {dict(expected_classification_counts)}"
        )

    answer_evidence_counts = Counter(
        str(item.get("answer_status") or "unknown") for item in final_questions
    )
    community_verified_by_year: Counter[int] = Counter()
    for item in final_questions:
        if item.get("answer_status") == "community_verified":
            year = final_paper_by_id[item["source_paper_id"]].get("year")
            if not isinstance(year, int):
                raise ReleaseAssemblyError(
                    f"{item['source_paper_id']}: paper year is missing"
                )
            community_verified_by_year[year] += 1

    content_verification_counts = {
        "parent_slots": len(content_ledger_map),
        "stems": dict(
            sorted(
                Counter(
                    str(row["stem"]["status"])
                    for row in content_ledger_map.values()
                ).items()
            )
        ),
        "options": dict(
            sorted(
                Counter(
                    str(row["options"]["status"])
                    for row in content_ledger_map.values()
                ).items()
            )
        ),
        "figures": dict(
            sorted(
                Counter(
                    str(row["figure_evidence"]["status"])
                    for row in content_ledger_map.values()
                ).items()
            )
        ),
        "asset_blocked_parent_slots": sum(
            bool(row.get("asset_blockers")) for row in content_ledger_map.values()
        ),
    }
    figure_asset_counts = {
        "audited_records": len(figure_rows),
        "parents": dict(
            sorted(
                Counter(
                    row["status"]
                    for key, row in figure_rows.items()
                    if key[2] is None
                ).items()
            )
        ),
        "expanded_children": dict(
            sorted(
                Counter(
                    row["status"]
                    for key, row in figure_rows.items()
                    if key[2] is not None
                ).items()
            )
        ),
        "attached_asset_references": sum(
            len(item.get("assets") or []) for item in final_questions
        ),
        "attached_unique_asset_sha256": len(
            {
                asset["sha256"]
                for item in final_questions
                for asset in item.get("assets") or []
            }
        ),
    }
    paper_source_verification_counts = {
        "decisions": dict(
            sorted(
                Counter(
                    str(row["decision"]) for row in source_decisions.values()
                ).items()
            )
        ),
        "methods": dict(
            sorted(
                Counter(
                    str(row["method"]) for row in source_decisions.values()
                ).items()
            )
        ),
        "verified_paper_ids": sorted(
            paper_id
            for paper_id, row in source_decisions.items()
            if row["decision"] == "verified"
        ),
    }
    classification_review_override_counts = {
        "total": len(classification_review_decisions),
        "by_decision": dict(
            sorted(
                Counter(
                    str(row["decision"])
                    for row in classification_review_decisions.values()
                ).items()
            )
        ),
        "remaining_review": sum(
            row["decision"] == "review"
            for row in classification_review_decisions.values()
        ),
    }

    input_bindings = {name: _binding(path) for name, path in sorted(paths.items())}
    version_basis = {
        "schema": REPORT_SCHEMA_VERSION,
        "inputs": {name: value["sha256"] for name, value in input_bindings.items()},
        "parent_slots": expected_parent_count,
        "expanded_records": expected_expanded_count,
    }
    artifact_version = "gate-cs-1996-2025-expanded-" + _canonical_sha256(
        version_basis
    )[:16]
    artifact = {
        "schema_version": SCHEMA_VERSION,
        "artifact_version": artifact_version,
        "papers": final_papers,
        "questions": final_questions,
    }

    blocker_counts: Counter[str] = Counter()
    auto_blocker_counts: Counter[str] = Counter()
    paper_reports: list[dict[str, Any]] = []
    release_ready = 0
    auto_ready = 0
    rows_by_paper: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in final_questions:
        rows_by_paper[item["source_paper_id"]].append(item)
        blockers = _release_blockers(item)
        blocker_counts.update(blockers)
        if not blockers:
            release_ready += 1
        auto_blockers = _auto_gradable_blockers(
            item, final_paper_by_id[item["source_paper_id"]], blockers
        )
        auto_blocker_counts.update(auto_blockers)
        if not auto_blockers:
            auto_ready += 1
    for paper in final_papers:
        rows = rows_by_paper[paper["id"]]
        current_blockers = Counter()
        current_auto = Counter()
        ready = 0
        auto = 0
        for item in rows:
            blockers = _release_blockers(item)
            current_blockers.update(blockers)
            ready += int(not blockers)
            auto_blockers = _auto_gradable_blockers(item, paper, blockers)
            current_auto.update(auto_blockers)
            auto += int(not auto_blockers)
        paper_reports.append(
            {
                "paper_id": paper["id"],
                "source_status": paper["source_status"],
                "source_verification_decision": source_decisions[paper["id"]][
                    "decision"
                ],
                "canonical_parent_slots": per_paper_parent_count[paper["id"]],
                "expanded_archive_records": len(rows),
                "release_ready": ready,
                "archive_only": len(rows) - ready,
                "auto_gradable_ready": auto,
                "community_verified_answers": sum(
                    item.get("answer_status") == "community_verified" for item in rows
                ),
                "release_blockers": dict(sorted(current_blockers.items())),
                "auto_gradable_blockers": dict(sorted(current_auto.items())),
            }
        )

    report_core = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "artifact_version": artifact_version,
        "artifact_sha256": _canonical_sha256(artifact),
        "source_role": "checksum_bound_staging_release_only",
        "database_writes_performed": False,
        "production_import_authorized": False,
        "automatic_promotion_allowed": False,
        "input_bindings": input_bindings,
        "counts": {
            "papers": len(final_papers),
            "canonical_parent_slots": expected_parent_count,
            "expanded_archive_records": len(final_questions),
            "legacy_expansion_delta": len(final_questions) - expected_parent_count,
            "archival_complete": len(final_questions),
            "release_ready": release_ready,
            "archive_only": len(final_questions) - release_ready,
            "auto_gradable_ready": auto_ready,
            "practice_eligible": 0,
        },
        "classification_counts": observed_classification_counts,
        "answer_evidence_counts": dict(sorted(answer_evidence_counts.items())),
        "community_verified_answers_by_year": {
            str(year): count
            for year, count in sorted(community_verified_by_year.items())
        },
        "content_verification_counts": content_verification_counts,
        "figure_asset_counts": figure_asset_counts,
        "paper_source_verification_counts": paper_source_verification_counts,
        "classification_review_override_counts": (
            classification_review_override_counts
        ),
        "release_blockers": dict(sorted(blocker_counts.items())),
        "auto_gradable_blockers": dict(sorted(auto_blocker_counts.items())),
        "papers": paper_reports,
        "invariants": {
            "paper_count_exact": len(final_papers) == expected_paper_count,
            "parent_slot_count_exact": len(canonical_map) == expected_parent_count,
            "expanded_record_count_exact": len(final_questions)
            == expected_expanded_count,
            "all_ordinals_contiguous": all(
                [item["ordinal"] for item in rows_by_paper[paper["id"]]]
                == list(range(1, paper["expected_item_count"] + 1))
                for paper in final_papers
            ),
            "all_records_archived": sum(per_paper_final_count.values())
            == expected_expanded_count,
            "practice_promotion_disabled": all(
                item["practice_eligible"] is False for item in final_questions
            ),
            "database_writes_disabled": True,
            "classification_counts_exact": classification_counts_exact,
            "figure_parent_child_coverage_exact": len(figure_rows)
            == expected_parent_count + len(legacy_children),
            "figure_assets_only_attached_from_ready_rows": all(
                not row["assets"] or row["status"] == "asset_ready"
                for row in figure_rows.values()
            ),
        },
    }
    if not all(report_core["invariants"].values()):
        raise ReleaseAssemblyError(
            f"final release invariants failed: {report_core['invariants']}"
        )
    report = {
        **report_core,
        "report_sha256": _canonical_sha256(report_core),
    }
    return artifact, report


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canonical", type=Path, default=DEFAULT_CANONICAL)
    parser.add_argument("--canonical-report", type=Path, default=DEFAULT_CANONICAL_REPORT)
    parser.add_argument("--raw-candidates", type=Path, default=DEFAULT_RAW_CANDIDATES)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--candidate-report", type=Path, default=DEFAULT_CANDIDATE_REPORT)
    parser.add_argument("--provenance", type=Path, default=DEFAULT_PROVENANCE)
    parser.add_argument("--overlay", type=Path, default=DEFAULT_OVERLAY)
    parser.add_argument("--answer-index", type=Path, default=DEFAULT_ANSWER_INDEX)
    parser.add_argument("--legacy-audit", type=Path, default=DEFAULT_LEGACY_AUDIT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--topic-policy", type=Path, default=DEFAULT_TOPIC_POLICY)
    parser.add_argument("--slot-policy", type=Path, default=DEFAULT_SLOT_POLICY)
    parser.add_argument(
        "--legacy-child-policy", type=Path, default=DEFAULT_LEGACY_CHILD_POLICY
    )
    parser.add_argument("--topic-inventory", type=Path, default=DEFAULT_TOPIC_INVENTORY)
    parser.add_argument(
        "--content-ledger", type=Path, default=DEFAULT_CONTENT_LEDGER
    )
    parser.add_argument(
        "--figure-assets", type=Path, default=DEFAULT_FIGURE_ASSETS
    )
    parser.add_argument(
        "--source-verification", type=Path, default=DEFAULT_SOURCE_VERIFICATION
    )
    parser.add_argument(
        "--classification-review-base",
        type=Path,
        default=DEFAULT_CLASSIFICATION_REVIEW_BASE,
    )
    parser.add_argument(
        "--classification-review",
        type=Path,
        default=DEFAULT_CLASSIFICATION_REVIEW_OVERRIDES,
    )
    parser.add_argument(
        "--matcher",
        type=Path,
        default=DEFAULT_MATCHER,
        help="Optional review-only high-confidence matcher artifact.",
    )
    parser.add_argument("--without-matcher", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    matcher_path = None
    if not args.without_matcher and args.matcher.exists():
        matcher_path = args.matcher
    artifact, report = assemble_release(
        canonical_path=args.canonical,
        canonical_report_path=args.canonical_report,
        raw_candidates_path=args.raw_candidates,
        candidates_path=args.candidates,
        candidate_report_path=args.candidate_report,
        provenance_path=args.provenance,
        overlay_path=args.overlay,
        answer_index_path=args.answer_index,
        legacy_audit_path=args.legacy_audit,
        manifest_path=args.manifest,
        topic_policy_path=args.topic_policy,
        slot_policy_path=args.slot_policy,
        legacy_child_policy_path=args.legacy_child_policy,
        topic_inventory_path=args.topic_inventory,
        content_ledger_path=args.content_ledger,
        figure_assets_path=args.figure_assets,
        source_verification_path=args.source_verification,
        classification_review_base_path=args.classification_review_base,
        classification_review_path=args.classification_review,
        matcher_path=matcher_path,
    )
    _write_json(args.output.resolve(), artifact)
    _write_json(args.report.resolve(), report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
