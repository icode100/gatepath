"""Build a fail-closed, staging-only PYQ content verification ledger.

The ledger assigns an independent status to the stem and option set of every
canonical parent slot.  It accepts either an exact, checksum-bound original
PDF transcription or a mutually unique secondary transcription that is also
bound to the original PDF page and passes stricter cross-source gates.

No explanation or solution text is read or emitted.  The module never opens a
database and cannot make a question practice eligible or authorize promotion.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping


REPO_DIR = Path(__file__).resolve().parents[2]
BUILD_DIR = REPO_DIR / "tmp" / "pyq" / "build"
REFERENCE_DIR = REPO_DIR / "tmp" / "pyq" / "reference"
DEFAULT_CANDIDATES = BUILD_DIR / "canonical_pyq_candidates_structured.json"
DEFAULT_PROVENANCE = BUILD_DIR / "original_pdf_provenance.json"
DEFAULT_OVERLAY = BUILD_DIR / "original_question_transcription_overlay.json"
DEFAULT_MATCHES = BUILD_DIR / "pyq_transcription_matches.json"
DEFAULT_ANSWERS = (
    REFERENCE_DIR / "answer-keys" / "pyq_answer_key_index.json"
)
DEFAULT_EXAMSIDE = (
    REFERENCE_DIR / "examside" / "examside_reference_index.jsonl"
)
DEFAULT_GATEOVERFLOW = REFERENCE_DIR / "extracted" / "question_locator_index.jsonl"
DEFAULT_GATEOVERFLOW_PAGES = REFERENCE_DIR / "extracted"
DEFAULT_FIGURES = BUILD_DIR / "pyq_figure_assets.json"
DEFAULT_OUTPUT = BUILD_DIR / "verified_pyq_content.json"

SCHEMA_VERSION = "1.0-staging-pyq-content-verification"
EXPECTED_PARENT_SLOTS = 2712
EXPECTED_PAPERS = 39
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
OBJECTIVE_TYPES = {"mcq", "msq"}
NON_OPTION_TYPES = {"nat", "descriptive"}
ACTIVE_HTML_RE = re.compile(
    r"<\s*(?:script|iframe|object|embed)\b|\son[a-z]+\s*=|javascript\s*:",
    re.IGNORECASE,
)
ANY_HTML_TAG_RE = re.compile(r"<\s*/?\s*[a-z][^>]*>", re.IGNORECASE)
TEX_OR_MATH_RE = re.compile(
    r"\$|\\(?:begin|end|frac|sqrt|sum|prod|int|left|right|overline|"
    r"mathbf|mathrm|text|times|cdot|leq|geq|neq|infty|epsilon|lambda|"
    r"alpha|beta|theta|rightarrow|to|in|cup|cap)\b|[∑√∫∞≤≥≠∈∪∩→]"
)
CODE_RE = re.compile(
    r"(?im)^\s*#\s*include\b|\b(?:typedef|struct|scanf|printf|malloc|"
    r"int\s+main|void\s+\w+\s*\()\b|->|\{\s*$|;\s*$"
)
VISUAL_REFERENCE_RE = re.compile(
    r"(?i)\b(?:figure|diagram|circuit|image|shown\s+(?:above|below)|"
    r"following\s+(?:figure|diagram|circuit))\b"
)
BROKEN_GLYPH_RE = re.compile(r"[\uE000-\uF8FF\uFFFD]|#{2,}")
FORBIDDEN_OUTPUT_KEYS = {
    "solution",
    "solution_md",
    "explanation",
    "explanation_html",
    "correct_answer",
    "practice_eligible",
}


class ContentVerificationError(ValueError):
    """Raised when a source or lineage invariant does not reproduce."""


_MATCHER: Any | None = None


def _matcher_module() -> Any:
    global _MATCHER
    if _MATCHER is not None:
        return _MATCHER
    path = Path(__file__).with_name("match_pyq_transcription_candidates.py")
    spec = importlib.util.spec_from_file_location("pyq_content_matcher", path)
    if spec is None or spec.loader is None:
        raise ContentVerificationError(f"Cannot load matcher helpers from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    _MATCHER = module
    return module


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
        raise ContentVerificationError(f"Cannot hash {path}: {exc}") from exc
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContentVerificationError(f"Cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContentVerificationError(f"{path}: expected an object")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise ContentVerificationError(f"Cannot read JSONL {path}: {exc}") from exc
    result: list[dict[str, Any]] = []
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ContentVerificationError(f"{path}:{number}: invalid JSON") from exc
        if not isinstance(row, dict):
            raise ContentVerificationError(f"{path}:{number}: row is not an object")
        result.append(row)
    return result


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_DIR).as_posix()
    except ValueError:
        return str(path.resolve())


def _binding(path: Path) -> dict[str, Any]:
    return {
        "path": _relative(path),
        "sha256": _sha256_file(path),
        "bytes": path.stat().st_size,
    }


def _require_hash(value: Any, *, context: str) -> str:
    normalized = str(value or "").casefold()
    if HASH_RE.fullmatch(normalized) is None:
        raise ContentVerificationError(f"{context}: malformed SHA-256")
    return normalized


def _validate_embedded_hash(payload: Mapping[str, Any], *, context: str) -> None:
    value = payload.get("artifact_sha256")
    if value is None:
        return
    expected = _require_hash(value, context=f"{context}.artifact_sha256")
    core = {key: child for key, child in payload.items() if key != "artifact_sha256"}
    if _canonical_sha256(core) != expected:
        raise ContentVerificationError(f"{context}: embedded hash mismatch")


def _slot_key(
    row: Mapping[str, Any], *, ordinal_key: str = "canonical_ordinal"
) -> tuple[str, int]:
    paper_id = str(row.get("source_paper_id") or row.get("paper_id") or "").strip()
    ordinal = row.get(ordinal_key)
    if not paper_id or not isinstance(ordinal, int) or ordinal < 1:
        raise ContentVerificationError(f"Invalid slot identity {paper_id!r}/{ordinal!r}")
    return paper_id, ordinal


def _unique_slots(
    rows: Any, *, ordinal_key: str, context: str
) -> dict[tuple[str, int], dict[str, Any]]:
    if not isinstance(rows, list):
        raise ContentVerificationError(f"{context}: missing row list")
    result: dict[tuple[str, int], dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ContentVerificationError(f"{context}: non-object row")
        key = _slot_key(row, ordinal_key=ordinal_key)
        if key in result:
            raise ContentVerificationError(f"{context}: duplicate slot {key}")
        result[key] = row
    return result


def _safe_output(value: Any, *, path: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key in FORBIDDEN_OUTPUT_KEYS:
                raise ContentVerificationError(f"Forbidden output field {path}.{key}")
            _safe_output(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _safe_output(child, path=f"{path}[{index}]")


def _ambiguity_reasons(text: str) -> list[str]:
    """Return risks that make third-party typography unsafe to promote."""

    reasons: list[str] = []
    if ACTIVE_HTML_RE.search(text) or ANY_HTML_TAG_RE.search(text):
        reasons.append("html_or_embedded_markup")
    if TEX_OR_MATH_RE.search(text):
        reasons.append("formula_or_latex_requires_visual_review")
    if CODE_RE.search(text):
        reasons.append("code_layout_requires_visual_review")
    if VISUAL_REFERENCE_RE.search(text):
        reasons.append("prompt_depends_on_visual_asset")
    if BROKEN_GLYPH_RE.search(text):
        reasons.append("broken_or_private_glyph")
    if "[image:" in text.casefold():
        reasons.append("remote_visual_asset_not_copied")
    return sorted(set(reasons))


def _normalized_options(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, str]] = []
    for row in value:
        if not isinstance(row, Mapping):
            return []
        identifier = str(
            row.get("id") or row.get("identifier") or row.get("source_identifier") or ""
        ).strip().upper()
        text = str(row.get("text") or row.get("content") or "").strip()
        if identifier not in {"A", "B", "C", "D"} or not text:
            return []
        result.append({"id": identifier, "text": text})
    if [row["id"] for row in result] != ["A", "B", "C", "D"]:
        return []
    if len({row["text"] for row in result}) != 4:
        return []
    return result


def _verified_field(
    *, content: Any, content_hash: str, method: str, evidence: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "status": "verified",
        "content": content,
        "content_sha256": content_hash,
        "verification_method": method,
        "evidence": dict(evidence),
        "blockers": [],
    }


def _unverified_field(status: str, blockers: Iterable[str]) -> dict[str, Any]:
    if status not in {"review", "missing", "not_applicable"}:
        raise ContentVerificationError(f"Invalid field status {status!r}")
    return {
        "status": status,
        "content": None,
        "content_sha256": None,
        "verification_method": None,
        "evidence": None,
        "blockers": sorted(set(blockers)),
    }


def _gateoverflow_page_index(
    directory: Path,
) -> tuple[dict[tuple[str, int], str], list[dict[str, Any]]]:
    result: dict[tuple[str, int], str] = {}
    bindings: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.pages.jsonl")):
        bindings.append(_binding(path))
        for row in _read_jsonl(path):
            volume = str(row.get("volume") or "")
            page = row.get("page")
            digest = _require_hash(
                row.get("text_sha256"), context=f"{path.name}:{page}.text_sha256"
            )
            text = row.get("text")
            if not isinstance(text, str) or _sha256_text(text) != digest:
                raise ContentVerificationError(f"{path.name}:{page}: page text drifted")
            key = (volume, int(page))
            if not volume or key in result:
                raise ContentVerificationError(f"Duplicate GateOverflow page {key}")
            text_path = directory / str(row.get("text_path") or "")
            if not text_path.is_file() or _sha256_file(text_path) != digest:
                raise ContentVerificationError(
                    f"{path.name}:{page}: extracted page file hash drifted"
                )
            result[key] = digest
    if not result:
        raise ContentVerificationError("No GateOverflow page indexes found")
    return result, bindings


def _gateoverflow_rows(
    path: Path,
) -> dict[tuple[str, int, str], dict[str, Any]]:
    result: dict[tuple[str, int, str], dict[str, Any]] = {}
    for row in _read_jsonl(path):
        key = (
            str(row.get("volume") or ""),
            int(row.get("source_page") or 0),
            str(row.get("book_id") or ""),
        )
        # A few index headings are intentionally unresolved and have no book
        # id.  They cannot back a canonical snapshot and are ignored here.
        if not all(key):
            continue
        if key in result:
            raise ContentVerificationError(f"Invalid/duplicate GateOverflow locator {key}")
        result[key] = row
    return result


def _examside_rows(path: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl(path):
        question = row.get("question") if isinstance(row.get("question"), Mapping) else {}
        source_id = str(question.get("source_id") or "").strip()
        if not source_id or source_id in result:
            raise ContentVerificationError(f"Duplicate ExamSIDE source id {source_id!r}")
        provenance = row.get("provenance") if isinstance(row.get("provenance"), Mapping) else {}
        _require_hash(
            provenance.get("question_raw_sha256"),
            context=f"ExamSIDE {source_id}.question_raw_sha256",
        )
        result[source_id] = row
    return result


def _answer_map(payload: Mapping[str, Any]) -> dict[tuple[str, int], dict[str, Any]]:
    return _unique_slots(
        payload.get("resolutions"), ordinal_key="canonical_ordinal", context="answers"
    )


def _figure_parent_map(
    payload: Mapping[str, Any],
) -> dict[tuple[str, int], dict[str, Any]]:
    _validate_embedded_hash(payload, context="figure assets")
    if (
        payload.get("database_writes_performed") is not False
        or payload.get("production_import_authorized") is not False
        or payload.get("automatic_promotion_allowed") is not False
        or payload.get("practice_eligible_count") != 0
    ):
        raise ContentVerificationError("Figure asset staging invariants failed")
    result: dict[tuple[str, int], dict[str, Any]] = {}
    for row in payload.get("items") or []:
        if not isinstance(row, dict) or row.get("child_item_label") is not None:
            continue
        key = _slot_key(row, ordinal_key="canonical_ordinal")
        if key in result:
            raise ContentVerificationError(f"Figure index duplicate parent {key}")
        if row.get("dependence_status") not in {
            "not_required",
            "asset_ready",
            "review_required",
            "missing",
        }:
            raise ContentVerificationError(f"Figure index invalid status at {key}")
        result[key] = row
    if len(result) != EXPECTED_PARENT_SLOTS:
        raise ContentVerificationError(
            f"Figure index has {len(result)} parents, expected {EXPECTED_PARENT_SLOTS}"
        )
    return result


def _validate_gateoverflow_snapshot(
    candidate_row: Mapping[str, Any],
    *,
    pages: Mapping[tuple[str, int], str],
    locators: Mapping[tuple[str, int, str], Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    snapshots = candidate_row.get("secondary_snapshots")
    snapshot = snapshots.get("gateoverflow") if isinstance(snapshots, Mapping) else None
    if not isinstance(snapshot, Mapping):
        return None
    volume = str(snapshot.get("volume") or "")
    page = int(snapshot.get("book_page") or 0)
    book_id = str(snapshot.get("book_id") or "")
    if not volume or page < 1 or not book_id:
        return None
    locator = locators.get((volume, page, book_id))
    if locator is None:
        raise ContentVerificationError(
            f"GateOverflow snapshot has no source locator {(volume, page, book_id)}"
        )
    expected_page_hash = _require_hash(
        snapshot.get("page_text_sha256"), context="GateOverflow snapshot page hash"
    )
    if pages.get((volume, page)) != expected_page_hash:
        raise ContentVerificationError("GateOverflow snapshot page hash drifted")
    body = snapshot.get("question_body_text")
    body_hash = _require_hash(
        snapshot.get("question_body_sha256"), context="GateOverflow snapshot body hash"
    )
    if not isinstance(body, str) or _sha256_text(body) != body_hash:
        raise ContentVerificationError("GateOverflow snapshot body hash drifted")
    if (
        str(locator.get("item_label") or "")
        != str(snapshot.get("source_item_label") or "")
        or str(locator.get("heading") or "") != str(snapshot.get("heading") or "")
    ):
        raise ContentVerificationError("GateOverflow snapshot locator identity drifted")
    return snapshot


def _exact_overlay_content(
    *,
    key: tuple[str, int],
    candidate_row: Mapping[str, Any],
    overlay_row: Mapping[str, Any],
    provenance_row: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    if overlay_row.get("status") != "exact":
        return None, []
    original = overlay_row.get("original_source_evidence")
    if not isinstance(original, Mapping):
        raise ContentVerificationError(f"{key}: exact overlay lacks source evidence")
    # Canonical-complete scan rows may be page-bound but have no safe text
    # boundary.  They are evaluated independently by the cross-source page
    # gate below; an upstream `exact` label alone is not enough here.
    if original.get("evidence_status") != "exact_text_block":
        return None, []
    for field in ("source_pdf_sha256", "text_block_sha256", "source_pages"):
        if original.get(field) != provenance_row.get(field):
            raise ContentVerificationError(f"{key}: overlay/provenance {field} drifted")
    proposed = overlay_row.get("proposed_overlay")
    proposed = proposed if isinstance(proposed, Mapping) else {}
    candidate = candidate_row.get("candidate")
    candidate = candidate if isinstance(candidate, Mapping) else {}
    text = proposed.get("question_text") or candidate.get("question_text")
    if not isinstance(text, str) or not text.strip():
        raise ContentVerificationError(f"{key}: exact overlay has no stem")
    text = text.strip()
    expected_text_hash = proposed.get("question_text_sha256") or candidate.get(
        "question_text_sha256"
    )
    if expected_text_hash != _sha256_text(text):
        raise ContentVerificationError(f"{key}: exact stem hash drifted")
    options_source = proposed.get("options") or candidate.get("options")
    options = _normalized_options(options_source)
    if proposed.get("options"):
        expected = proposed.get("options_sha256")
        if expected != _canonical_sha256(proposed["options"]):
            raise ContentVerificationError(f"{key}: exact overlay options hash drifted")
    return (
        {
            "text": text,
            "text_sha256": _sha256_text(text),
            "evidence": {
                "source_pdf_sha256": original["source_pdf_sha256"],
                "source_pages": list(original["source_pages"]),
                "text_block_sha256": original["text_block_sha256"],
                "page_text_sha256": list(original.get("page_text_sha256") or []),
            },
        },
        options,
    )


def _collapsed(value: str) -> str:
    return " ".join(value.split())


def _balanced_latex(value: str) -> bool:
    if value.count("$$") % 2:
        return False
    without_display = value.replace("$$", "")
    if without_display.count("$") % 2:
        return False
    return value.count("{") == value.count("}")


def _canonical_page_cross_source_gate(
    *,
    key: tuple[str, int],
    candidate_row: Mapping[str, Any],
    overlay_row: Mapping[str, Any],
    provenance_row: Mapping[str, Any],
    answer_row: Mapping[str, Any] | None,
    examside: Mapping[str, Mapping[str, Any]],
    gateoverflow_pages: Mapping[tuple[str, int], str],
    gateoverflow_locators: Mapping[tuple[str, int, str], Mapping[str, Any]],
    examside_usage: Mapping[str, int],
    gateoverflow_usage: Mapping[tuple[str, int, str], int],
) -> tuple[dict[str, Any] | None, list[dict[str, str]], list[str]]:
    """Verify a canonical-complete scan using two unique secondary joins."""

    reasons: list[str] = []
    original = overlay_row.get("original_source_evidence")
    original = original if isinstance(original, Mapping) else {}
    if (
        overlay_row.get("status") != "exact"
        or overlay_row.get("status_reason") != "canonical_slot_already_complete"
        or original.get("evidence_status") != "rendered_page_review_required"
    ):
        return None, [], ["not_a_canonical_complete_page_bound_candidate"]
    if candidate_row.get("reconciliation_status") != "exact":
        reasons.append("canonical_reconciliation_not_exact")
    candidate = candidate_row.get("candidate")
    candidate = candidate if isinstance(candidate, Mapping) else {}
    text = str(candidate.get("question_text") or "").strip()
    if not text or candidate.get("question_text_sha256") != _sha256_text(text):
        raise ContentVerificationError(f"{key}: canonical-complete stem hash drifted")
    hard_risks = [
        reason
        for reason in _ambiguity_reasons(text)
        if reason
        not in {
            "formula_or_latex_requires_visual_review",
            "code_layout_requires_visual_review",
        }
    ]
    reasons.extend(hard_risks)
    if CODE_RE.search(text):
        reasons.append("code_layout_requires_visual_review")
    if TEX_OR_MATH_RE.search(text) and not _balanced_latex(text):
        reasons.append("formula_delimiters_or_braces_unbalanced")

    if original.get("source_pdf_sha256") != provenance_row.get("source_pdf_sha256"):
        reasons.append("source_pdf_hash_lineage_drift")
    if original.get("source_pages") != provenance_row.get("source_pages"):
        reasons.append("source_page_lineage_drift")
    rendered = original.get("rendered_page_evidence") or []
    if not rendered or rendered != provenance_row.get("rendered_page_evidence"):
        reasons.append("rendered_page_hash_lineage_missing_or_drifted")
    else:
        for page in rendered:
            if not isinstance(page, Mapping) or HASH_RE.fullmatch(
                str(page.get("sha256") or "")
            ) is None:
                reasons.append("rendered_page_hash_malformed")

    go = _validate_gateoverflow_snapshot(
        candidate_row, pages=gateoverflow_pages, locators=gateoverflow_locators
    )
    if go is None:
        reasons.append("gateoverflow_snapshot_missing")
        go_similarity = 0.0
    else:
        go_key = (
            str(go.get("volume") or ""),
            int(go.get("book_page") or 0),
            str(go.get("book_id") or ""),
        )
        if gateoverflow_usage.get(go_key) != 1:
            reasons.append("gateoverflow_join_not_unique")
        go_similarity = _matcher_module()._text_similarity(
            text, str(go.get("question_body_text") or "")
        )[0]
        if go_similarity < 0.95:
            reasons.append("gateoverflow_text_similarity_below_0_95")

    snapshots = candidate_row.get("secondary_snapshots")
    examside_snapshot = (
        snapshots.get("examside") if isinstance(snapshots, Mapping) else None
    )
    examside_text = ""
    examside_options: list[dict[str, str]] = []
    source_id = ""
    if not isinstance(examside_snapshot, Mapping):
        reasons.append("examside_snapshot_missing")
    else:
        source_id = str(examside_snapshot.get("source_id") or "")
        if examside_usage.get(source_id) != 1:
            reasons.append("examside_join_not_unique")
        source_row = examside.get(source_id)
        if source_row is None:
            reasons.append("examside_source_missing")
        else:
            source_provenance = source_row.get("provenance")
            source_provenance = (
                source_provenance if isinstance(source_provenance, Mapping) else {}
            )
            if source_provenance.get("question_raw_sha256") != examside_snapshot.get(
                "raw_response_sha256"
            ):
                raise ContentVerificationError(f"{key}: ExamSIDE raw hash drifted")
            source_question = source_row.get("question")
            source_question = (
                source_question if isinstance(source_question, Mapping) else {}
            )
            sanitized, flags = _matcher_module()._candidate_content(source_question)
            if flags or examside_snapshot.get("remote_assets"):
                reasons.extend(flags or ["remote_visual_asset_not_copied"])
            examside_text = str(sanitized.get("question_text") or "").strip()
            snapshot_text = str(examside_snapshot.get("question_text") or "").strip()
            if _collapsed(examside_text) != _collapsed(snapshot_text):
                reasons.append("examside_snapshot_text_representation_drift")
            text_score = _matcher_module()._text_similarity(text, examside_text)[0]
            if text_score < 0.98:
                reasons.append("examside_text_similarity_below_0_98")
            if (TEX_OR_MATH_RE.search(text) or CODE_RE.search(text)) and _collapsed(
                text
            ) != _collapsed(examside_text):
                reasons.append("formula_or_code_not_exact_across_sources")
            examside_options = _normalized_options(sanitized.get("options"))

    if answer_row is None or answer_row.get("status") != "official":
        reasons.append("official_answer_resolution_missing")
    elif (
        str(answer_row.get("selected_question_type") or "").casefold()
        != str(candidate.get("item_type") or "").casefold()
        or answer_row.get("selected_marks") != candidate.get("marks")
    ):
        reasons.append("official_type_or_marks_drift")

    reasons = sorted(set(reasons))
    if reasons:
        return None, [], reasons
    stem = {
        "text": text,
        "text_sha256": _sha256_text(text),
        "evidence": {
            "source_pdf_sha256": original["source_pdf_sha256"],
            "source_pages": list(original["source_pages"]),
            "rendered_page_evidence": list(rendered),
            "examside_source_id": source_id,
            "examside_raw_response_sha256": examside_snapshot[
                "raw_response_sha256"
            ],
            "gateoverflow_body_sha256": go["question_body_sha256"],
            "gateoverflow_page_text_sha256": go["page_text_sha256"],
            "gateoverflow_text_similarity": go_similarity,
            "official_resolution_claim_ids": sorted(
                str(value) for value in answer_row.get("claim_ids") or []
            ),
        },
    }
    canonical_options = _normalized_options(candidate.get("options"))
    verified_options: list[dict[str, str]] = []
    if canonical_options and examside_options and canonical_options == examside_options:
        verified_options = canonical_options
    return stem, verified_options, []


def _cross_source_gate(
    *,
    key: tuple[str, int],
    candidate_row: Mapping[str, Any],
    overlay_row: Mapping[str, Any],
    provenance_row: Mapping[str, Any],
    match_row: Mapping[str, Any],
    answer_row: Mapping[str, Any] | None,
    examside: Mapping[str, Mapping[str, Any]],
    gateoverflow_pages: Mapping[tuple[str, int], str],
    gateoverflow_locators: Mapping[tuple[str, int, str], Mapping[str, Any]],
) -> tuple[dict[str, Any] | None, list[str]]:
    """Verify a cross-source stem or return explicit fail-closed reasons."""

    reasons: list[str] = []
    if (
        match_row.get("match_status") != "exact_proposed_review"
        or match_row.get("manual_review_required") is not True
    ):
        reasons.append("matcher_guard_or_status_invalid")
    if match_row.get("review_flags"):
        reasons.extend(str(value) for value in match_row.get("review_flags") or [])
    evidence = match_row.get("evidence")
    evidence = evidence if isinstance(evidence, Mapping) else {}
    original = evidence.get("original_text_evidence")
    original = original if isinstance(original, Mapping) else {}
    if original.get("kind") != "original_pdf_text_block":
        reasons.append("page_ocr_not_precise_enough_for_automatic_transcription")
    if float(evidence.get("text_similarity") or 0) < 0.95:
        reasons.append("original_text_similarity_below_0_95")
    if float(evidence.get("existing_secondary_text_similarity") or 0) < 0.95:
        reasons.append("gateoverflow_text_similarity_below_0_95")
    if float(evidence.get("topic_similarity") or 0) < 0.90:
        reasons.append("topic_similarity_below_0_90")
    if evidence.get("official_answer_agreement") is not True:
        reasons.append("official_answer_agreement_missing")

    candidate = candidate_row.get("candidate")
    candidate = candidate if isinstance(candidate, Mapping) else {}
    if candidate.get("classification_outcome") != "mapped":
        reasons.append("canonical_classification_not_mapped")
    if (
        evidence.get("canonical_course") != candidate.get("course")
        or evidence.get("canonical_topic") != candidate.get("topic")
    ):
        reasons.append("canonical_classification_drift")
    snapshot = _validate_gateoverflow_snapshot(
        candidate_row, pages=gateoverflow_pages, locators=gateoverflow_locators
    )
    if snapshot is None:
        reasons.append("gateoverflow_snapshot_missing")

    content = match_row.get("proposed_review_content")
    content = content if isinstance(content, Mapping) else {}
    text = content.get("question_text")
    if not isinstance(text, str) or not text.strip():
        reasons.append("matched_stem_missing")
        text = ""
    elif content.get("question_text_sha256") != _sha256_text(text):
        raise ContentVerificationError(f"{key}: matcher stem hash drifted")
    reasons.extend(_ambiguity_reasons(text))

    source_id = str(evidence.get("examside_source_id") or "")
    source_row = examside.get(source_id)
    if source_row is None:
        reasons.append("examside_source_missing")
    else:
        source_provenance = source_row.get("provenance")
        source_provenance = (
            source_provenance if isinstance(source_provenance, Mapping) else {}
        )
        if source_provenance.get("question_raw_sha256") != evidence.get(
            "examside_raw_response_sha256"
        ):
            raise ContentVerificationError(f"{key}: ExamSIDE raw hash drifted")
        source_question = source_row.get("question")
        source_question = source_question if isinstance(source_question, Mapping) else {}
        sanitized, flags = _matcher_module()._candidate_content(source_question)
        if flags:
            reasons.extend(flags)
        if sanitized.get("question_text") != text:
            raise ContentVerificationError(f"{key}: matcher/ExamSIDE content drifted")

    if answer_row is None or answer_row.get("status") != "official":
        reasons.append("official_answer_resolution_missing")
    else:
        claims = set(str(value) for value in answer_row.get("claim_ids") or [])
        match_claims = set(
            str(value) for value in evidence.get("official_resolution_claim_ids") or []
        )
        if not match_claims or not match_claims.issubset(claims):
            reasons.append("official_answer_claim_lineage_drift")
        if (
            answer_row.get("selected_question_type") != evidence.get("question_type")
            or answer_row.get("selected_marks") != evidence.get("marks")
        ):
            reasons.append("official_type_or_marks_drift")

    overlay_original = overlay_row.get("original_source_evidence")
    overlay_original = overlay_original if isinstance(overlay_original, Mapping) else {}
    for field in ("source_pdf_sha256", "text_block_sha256", "source_pages"):
        if original.get(field) != overlay_original.get(field):
            reasons.append(f"original_{field}_lineage_drift")
        if original.get(field) != provenance_row.get(field):
            reasons.append(f"provenance_{field}_lineage_drift")
    if snapshot is not None and text:
        go_similarity = _matcher_module()._text_similarity(
            text, str(snapshot.get("question_body_text") or "")
        )[0]
        if go_similarity < 0.95:
            reasons.append("recomputed_gateoverflow_similarity_below_0_95")

    reasons = sorted(set(reasons))
    if reasons:
        return None, reasons
    return (
        {
            "text": text.strip(),
            "text_sha256": _sha256_text(text.strip()),
            "evidence": {
                "source_pdf_sha256": original["source_pdf_sha256"],
                "source_pages": list(original["source_pages"]),
                "text_block_sha256": original["text_block_sha256"],
                "examside_source_id": source_id,
                "examside_raw_response_sha256": evidence[
                    "examside_raw_response_sha256"
                ],
                "gateoverflow_body_sha256": snapshot["question_body_sha256"],
                "gateoverflow_page_text_sha256": snapshot["page_text_sha256"],
                "official_resolution_claim_ids": sorted(
                    str(value)
                    for value in evidence.get("official_resolution_claim_ids") or []
                ),
                "text_similarity": evidence["text_similarity"],
                "gateoverflow_text_similarity": evidence[
                    "existing_secondary_text_similarity"
                ],
            },
        },
        [],
    )


def _review_candidate_present(
    *,
    candidate: Mapping[str, Any],
    overlay: Mapping[str, Any],
    match: Mapping[str, Any] | None,
    field: str,
) -> bool:
    proposed = overlay.get("proposed_overlay")
    proposed = proposed if isinstance(proposed, Mapping) else {}
    matcher_content = match.get("proposed_review_content") if match else None
    matcher_content = matcher_content if isinstance(matcher_content, Mapping) else {}
    if field == "stem":
        return any(
            isinstance(value, str) and bool(value.strip())
            for value in (
                proposed.get("question_text"),
                candidate.get("question_text"),
                matcher_content.get("question_text"),
            )
        )
    return any(
        isinstance(value, list) and bool(value)
        for value in (
            proposed.get("options"),
            candidate.get("options"),
            matcher_content.get("options"),
        )
    )


def _asset_blockers(
    *,
    candidate: Mapping[str, Any],
    overlay: Mapping[str, Any],
    provenance: Mapping[str, Any],
    match: Mapping[str, Any] | None,
    figure: Mapping[str, Any],
) -> list[str]:
    values: set[str] = set()
    flags = list(overlay.get("review_flags") or []) + list(
        provenance.get("review_flags") or []
    )
    if match:
        flags.extend(match.get("review_flags") or [])
    for flag in flags:
        text = str(flag)
        if any(token in text.casefold() for token in ("image", "visual", "diagram", "asset")):
            values.add(text)
    text_candidates = [candidate.get("question_text")]
    proposed = overlay.get("proposed_overlay")
    if isinstance(proposed, Mapping):
        text_candidates.append(proposed.get("question_text"))
    if match and isinstance(match.get("proposed_review_content"), Mapping):
        text_candidates.append(match["proposed_review_content"].get("question_text"))
    if any(
        isinstance(text, str) and VISUAL_REFERENCE_RE.search(text)
        for text in text_candidates
    ):
        values.add("prompt_level_visual_reference")
    if overlay.get("status_reason") == "source_text_contains_visual_or_layout_risk":
        values.add("source_text_contains_visual_or_layout_risk")
    dependence_status = figure.get("dependence_status")
    if dependence_status == "review_required":
        values.add("original_pdf_figure_review_required")
    elif dependence_status == "missing":
        values.add("original_pdf_figure_asset_missing")
    elif dependence_status == "asset_ready":
        # The figure index has already verified and attached an original-PDF
        # crop for this exact canonical slot.  Prompt-level visual signals are
        # therefore satisfied dependencies, not missing-asset blockers.  Any
        # formula/transcription/layout ambiguity remains independently on the
        # stem field and is not weakened here.
        return []
    return sorted(values)


SATISFIED_BY_ATTACHED_ORIGINAL_ASSET = {
    "figure_or_table_review_required",
    "prompt_depends_on_visual_asset",
    "prompt_level_visual_reference",
    "remote_visual_asset_not_copied",
    "upstream_visual_or_missing_content_signal",
}


def _clear_satisfied_asset_dependencies(
    field: dict[str, Any], *, figure: Mapping[str, Any]
) -> None:
    """Clear only dependency blockers satisfied by an exact attached crop."""

    if figure.get("dependence_status") != "asset_ready":
        return
    field["blockers"] = sorted(
        set(field.get("blockers") or []) - SATISFIED_BY_ATTACHED_ORIGINAL_ASSET
    )


def _count_statuses(items: Iterable[Mapping[str, Any]], field: str) -> dict[str, int]:
    counts = Counter(str(item[field]["status"]) for item in items)
    return dict(sorted(counts.items()))


def build_verification(
    *,
    candidates_path: Path = DEFAULT_CANDIDATES,
    provenance_path: Path = DEFAULT_PROVENANCE,
    overlay_path: Path = DEFAULT_OVERLAY,
    matches_path: Path = DEFAULT_MATCHES,
    answers_path: Path = DEFAULT_ANSWERS,
    examside_path: Path = DEFAULT_EXAMSIDE,
    gateoverflow_path: Path = DEFAULT_GATEOVERFLOW,
    gateoverflow_pages_dir: Path = DEFAULT_GATEOVERFLOW_PAGES,
    figures_path: Path = DEFAULT_FIGURES,
) -> tuple[dict[str, Any], dict[str, Any]]:
    candidates_payload = _read_json(candidates_path)
    provenance_payload = _read_json(provenance_path)
    overlay_payload = _read_json(overlay_path)
    matches_payload = _read_json(matches_path)
    answers_payload = _read_json(answers_path)
    figures_payload = _read_json(figures_path)
    for name, payload in (
        ("provenance", provenance_payload),
        ("overlay", overlay_payload),
        ("matcher", matches_payload),
    ):
        _validate_embedded_hash(payload, context=name)
    if (
        candidates_payload.get("slot_count") != EXPECTED_PARENT_SLOTS
        or provenance_payload.get("practice_eligible_count") != 0
        or provenance_payload.get("production_import_authorized") is not False
        or overlay_payload.get("database_writes_performed") is not False
        or overlay_payload.get("production_import_authorized") is not False
        or overlay_payload.get("automatic_promotion_allowed") is not False
        or matches_payload.get("database_writes_performed") is not False
        or matches_payload.get("production_import_authorized") is not False
        or matches_payload.get("automatic_promotion_allowed") is not False
    ):
        raise ContentVerificationError("Staging/no-promotion input invariants failed")
    matcher_policy = matches_payload.get("matching_policy")
    if not isinstance(matcher_policy, Mapping) or not all(
        matcher_policy.get(key) is True
        for key in (
            "requires_same_paper",
            "requires_official_answer_type_marks",
            "requires_verified_course_topic",
            "requires_original_pdf_text_or_checksum_bound_ocr",
            "requires_mutual_unique_best",
        )
    ):
        raise ContentVerificationError("Matcher mutual-evidence policy drifted")
    if float(matcher_policy.get("minimum_margin") or 0) < 0.08:
        raise ContentVerificationError("Matcher margin is below the accepted floor")

    candidates = _unique_slots(
        candidates_payload.get("questions"), ordinal_key="ordinal", context="candidates"
    )
    provenance = _unique_slots(
        provenance_payload.get("items"),
        ordinal_key="canonical_ordinal",
        context="provenance",
    )
    overlays = _unique_slots(
        overlay_payload.get("items"),
        ordinal_key="canonical_ordinal",
        context="overlay",
    )
    matches = _unique_slots(
        matches_payload.get("matches"),
        ordinal_key="canonical_ordinal",
        context="matches",
    )
    answers = _answer_map(answers_payload)
    figures = _figure_parent_map(figures_payload)
    canonical_keys = set(candidates)
    if (
        len(canonical_keys) != EXPECTED_PARENT_SLOTS
        or set(provenance) != canonical_keys
        or set(overlays) != canonical_keys
        or not set(matches).issubset(canonical_keys)
        or set(figures) != canonical_keys
    ):
        raise ContentVerificationError("Canonical parent-slot identity drifted")
    if len({key[0] for key in canonical_keys}) != EXPECTED_PAPERS:
        raise ContentVerificationError("Canonical paper count drifted")

    examside = _examside_rows(examside_path)
    gateoverflow_pages, gateoverflow_page_bindings = _gateoverflow_page_index(
        gateoverflow_pages_dir
    )
    gateoverflow_locators = _gateoverflow_rows(gateoverflow_path)

    examside_usage: Counter[str] = Counter()
    gateoverflow_usage: Counter[tuple[str, int, str]] = Counter()
    for row in candidates.values():
        snapshots = row.get("secondary_snapshots")
        if not isinstance(snapshots, Mapping):
            continue
        examside_snapshot = snapshots.get("examside")
        if isinstance(examside_snapshot, Mapping):
            source_id = str(examside_snapshot.get("source_id") or "")
            if source_id:
                examside_usage[source_id] += 1
        go = snapshots.get("gateoverflow")
        if isinstance(go, Mapping):
            go_key = (
                str(go.get("volume") or ""),
                int(go.get("book_page") or 0),
                str(go.get("book_id") or ""),
            )
            if all(go_key):
                gateoverflow_usage[go_key] += 1

    items: list[dict[str, Any]] = []
    cross_source_verified: list[tuple[str, int]] = []
    blocker_counts: Counter[str] = Counter()
    for key in sorted(canonical_keys):
        candidate_row = candidates[key]
        overlay_row = overlays[key]
        provenance_row = provenance[key]
        match_row = matches.get(key)
        if (
            str(candidate_row.get("item_label")) != str(overlay_row.get("item_label"))
            or str(candidate_row.get("item_label")) != str(provenance_row.get("item_label"))
            or (match_row and str(candidate_row.get("item_label")) != str(match_row.get("item_label")))
        ):
            raise ContentVerificationError(f"{key}: item label drifted")
        candidate = candidate_row.get("candidate")
        candidate = candidate if isinstance(candidate, Mapping) else {}
        exact_stem, exact_options = _exact_overlay_content(
            key=key,
            candidate_row=candidate_row,
            overlay_row=overlay_row,
            provenance_row=provenance_row,
        )
        page_stem: dict[str, Any] | None = None
        page_options: list[dict[str, str]] = []
        page_reasons: list[str] = []
        if exact_stem is None and overlay_row.get("status") == "exact":
            page_stem, page_options, page_reasons = _canonical_page_cross_source_gate(
                key=key,
                candidate_row=candidate_row,
                overlay_row=overlay_row,
                provenance_row=provenance_row,
                answer_row=answers.get(key),
                examside=examside,
                gateoverflow_pages=gateoverflow_pages,
                gateoverflow_locators=gateoverflow_locators,
                examside_usage=examside_usage,
                gateoverflow_usage=gateoverflow_usage,
            )
        cross_stem: dict[str, Any] | None = None
        cross_reasons: list[str] = []
        if exact_stem is None and page_stem is None and match_row is not None:
            cross_stem, cross_reasons = _cross_source_gate(
                key=key,
                candidate_row=candidate_row,
                overlay_row=overlay_row,
                provenance_row=provenance_row,
                match_row=match_row,
                answer_row=answers.get(key),
                examside=examside,
                gateoverflow_pages=gateoverflow_pages,
                gateoverflow_locators=gateoverflow_locators,
            )

        if exact_stem is not None:
            stem = _verified_field(
                content=exact_stem["text"],
                content_hash=exact_stem["text_sha256"],
                method="checksum_bound_original_text_block",
                evidence=exact_stem["evidence"],
            )
        elif page_stem is not None:
            stem = _verified_field(
                content=page_stem["text"],
                content_hash=page_stem["text_sha256"],
                method="mutually_unique_cross_source_original_page",
                evidence=page_stem["evidence"],
            )
            cross_source_verified.append(key)
        elif cross_stem is not None:
            stem = _verified_field(
                content=cross_stem["text"],
                content_hash=cross_stem["text_sha256"],
                method="mutually_unique_cross_source_original_page",
                evidence=cross_stem["evidence"],
            )
            cross_source_verified.append(key)
        else:
            present = _review_candidate_present(
                candidate=candidate,
                overlay=overlay_row,
                match=match_row,
                field="stem",
            )
            reasons = (
                list(overlay_row.get("review_flags") or [])
                + page_reasons
                + cross_reasons
            )
            reasons.append(str(overlay_row.get("status_reason") or "stem_not_verified"))
            if not present:
                reasons.append("no_safe_stem_candidate")
            stem = _unverified_field("review" if present else "missing", reasons)

        item_type = str(candidate.get("item_type") or "unknown").casefold()
        if item_type in OBJECTIVE_TYPES:
            if exact_stem is not None and exact_options:
                options = _verified_field(
                    content=exact_options,
                    content_hash=_canonical_sha256(exact_options),
                    method="checksum_bound_original_text_block",
                    evidence=exact_stem["evidence"],
                )
            elif page_stem is not None and page_options:
                options = _verified_field(
                    content=page_options,
                    content_hash=_canonical_sha256(page_options),
                    method="mutually_unique_cross_source_original_page",
                    evidence=page_stem["evidence"],
                )
            else:
                present = _review_candidate_present(
                    candidate=candidate,
                    overlay=overlay_row,
                    match=match_row,
                    field="options",
                )
                option_reasons = ["objective_options_not_checksum_verified"]
                if match_row and isinstance(
                    match_row.get("proposed_review_content"), Mapping
                ) and match_row["proposed_review_content"].get("options"):
                    option_reasons.append(
                        "single_secondary_option_text_not_promoted"
                    )
                if not present:
                    option_reasons.append("no_safe_option_candidate")
                options = _unverified_field(
                    "review" if present else "missing", option_reasons
                )
        elif item_type in NON_OPTION_TYPES:
            options = _unverified_field("not_applicable", [])
        else:
            options = _unverified_field(
                "review", ["question_type_unknown_or_options_applicability_unresolved"]
            )

        figure = figures[key]
        _clear_satisfied_asset_dependencies(stem, figure=figure)
        _clear_satisfied_asset_dependencies(options, figure=figure)
        asset_blockers = _asset_blockers(
            candidate=candidate,
            overlay=overlay_row,
            provenance=provenance_row,
            match=match_row,
            figure=figure,
        )
        figure_evidence = {
            "status": figure.get("dependence_status"),
            "assessment": figure.get("dependence_assessment"),
            "source_pdf_sha256": figure.get("source_pdf_sha256"),
            "source_pages": list(figure.get("source_pages") or []),
            "asset_count": len(figure.get("assets") or []),
            "asset_sha256": sorted(
                str(asset.get("sha256"))
                for asset in figure.get("assets") or []
                if isinstance(asset, Mapping) and asset.get("sha256")
            ),
        }
        blockers = sorted(
            set(stem["blockers"] + options["blockers"] + asset_blockers)
        )
        blocker_counts.update(blockers)
        items.append(
            {
                "source_paper_id": key[0],
                "canonical_ordinal": key[1],
                "item_label": candidate_row.get("item_label"),
                "item_type": item_type,
                "course": candidate.get("course"),
                "topic": candidate.get("topic"),
                "stem": stem,
                "options": options,
                "figure_evidence": figure_evidence,
                "asset_blockers": asset_blockers,
                "blockers": blockers,
            }
        )

    if len(items) != EXPECTED_PARENT_SLOTS:
        raise ContentVerificationError("Verification ledger lost canonical slots")
    input_bindings = {
        "structured_candidates": _binding(candidates_path),
        "original_pdf_provenance": _binding(provenance_path),
        "original_transcription_overlay": _binding(overlay_path),
        "transcription_matches": _binding(matches_path),
        "official_answer_index": _binding(answers_path),
        "examside_sanitized_index": _binding(examside_path),
        "gateoverflow_question_index": _binding(gateoverflow_path),
        "gateoverflow_page_indexes": gateoverflow_page_bindings,
        "original_pdf_figure_assets": _binding(figures_path),
    }
    artifact_core = {
        "schema_version": SCHEMA_VERSION,
        "source_role": "staging_content_verification_ledger_only",
        "database_writes_performed": False,
        "production_import_authorized": False,
        "automatic_promotion_allowed": False,
        "practice_eligible_count": 0,
        "canonical_identity": {
            "paper_count": EXPECTED_PAPERS,
            "parent_slot_count": EXPECTED_PARENT_SLOTS,
        },
        "input_bindings": input_bindings,
        "verification_policy": {
            "exact_original_text_block_allowed": True,
            "cross_source_requires_mutual_unique_match": True,
            "cross_source_requires_original_text_block": True,
            "cross_source_requires_official_answer_type_marks": True,
            "cross_source_requires_gateoverflow_and_examside_agreement": True,
            "cross_source_minimum_original_similarity": 0.95,
            "cross_source_minimum_gateoverflow_similarity": 0.95,
            "cross_source_latex_code_html_visual_auto_acceptance": False,
            "matcher_cross_source_option_auto_acceptance": False,
            "canonical_page_options_require_exact_examside_agreement": True,
            "third_party_explanations_consumed": False,
        },
        "items": items,
    }
    _safe_output(artifact_core)
    artifact = {
        **artifact_core,
        "artifact_sha256": _canonical_sha256(artifact_core),
    }

    by_paper: dict[str, dict[str, Any]] = {}
    for paper_id in sorted({item["source_paper_id"] for item in items}):
        rows = [item for item in items if item["source_paper_id"] == paper_id]
        by_paper[paper_id] = {
            "parent_slots": len(rows),
            "stems": _count_statuses(rows, "stem"),
            "options": _count_statuses(rows, "options"),
            "asset_blocked_slots": sum(bool(row["asset_blockers"]) for row in rows),
            "figure_statuses": dict(
                sorted(
                    Counter(
                        str(row["figure_evidence"]["status"]) for row in rows
                    ).items()
                )
            ),
            "cross_source_verified_stems": sum(
                row["stem"]["verification_method"]
                == "mutually_unique_cross_source_original_page"
                for row in rows
            ),
        }
    report = {
        "schema_version": SCHEMA_VERSION,
        "artifact_sha256": artifact["artifact_sha256"],
        "summary": {
            "paper_count": EXPECTED_PAPERS,
            "parent_slot_count": len(items),
            "input_overlay_exact_slots": sum(
                row.get("status") == "exact" for row in overlays.values()
            ),
            "stems": _count_statuses(items, "stem"),
            "options": _count_statuses(items, "options"),
            "base_exact_verified_stems": sum(
                row["stem"]["verification_method"]
                == "checksum_bound_original_text_block"
                for row in items
            ),
            "new_cross_source_verified_stems": len(cross_source_verified),
            "new_cross_source_verified_options": sum(
                row["options"]["verification_method"]
                == "mutually_unique_cross_source_original_page"
                for row in items
            ),
            "asset_blocked_slots": sum(bool(row["asset_blockers"]) for row in items),
            "figure_statuses": dict(
                sorted(
                    Counter(
                        str(row["figure_evidence"]["status"]) for row in items
                    ).items()
                )
            ),
        },
        "cross_source_verified_slots": [
            {"source_paper_id": paper, "canonical_ordinal": ordinal}
            for paper, ordinal in cross_source_verified
        ],
        "blocker_counts": dict(sorted(blocker_counts.items())),
        "papers": by_paper,
        "invariants": {
            "all_parent_slots_present_once": len(items) == EXPECTED_PARENT_SLOTS
            and len(
                {
                    (item["source_paper_id"], item["canonical_ordinal"])
                    for item in items
                }
            )
            == EXPECTED_PARENT_SLOTS,
            "verified_stem_hashes_reproduce": all(
                row["stem"]["status"] != "verified"
                or row["stem"]["content_sha256"]
                == _sha256_text(row["stem"]["content"])
                for row in items
            ),
            "verified_options_hashes_reproduce": all(
                row["options"]["status"] != "verified"
                or row["options"]["content_sha256"]
                == _canonical_sha256(row["options"]["content"])
                for row in items
            ),
            "cross_source_verified_content_has_no_ambiguity": all(
                not _ambiguity_reasons(row["stem"]["content"])
                for row in items
                if row["stem"]["verification_method"]
                == "mutually_unique_cross_source_original_page"
            ),
            "no_database_or_promotion": artifact["database_writes_performed"] is False
            and artifact["production_import_authorized"] is False
            and artifact["automatic_promotion_allowed"] is False
            and artifact["practice_eligible_count"] == 0,
            "no_third_party_explanations": artifact["verification_policy"]
            ["third_party_explanations_consumed"]
            is False,
        },
    }
    if not all(report["invariants"].values()):
        raise ContentVerificationError(
            f"Content verification invariants failed: {report['invariants']}"
        )
    return artifact, report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--provenance", type=Path, default=DEFAULT_PROVENANCE)
    parser.add_argument("--overlay", type=Path, default=DEFAULT_OVERLAY)
    parser.add_argument("--matches", type=Path, default=DEFAULT_MATCHES)
    parser.add_argument("--answers", type=Path, default=DEFAULT_ANSWERS)
    parser.add_argument("--examside", type=Path, default=DEFAULT_EXAMSIDE)
    parser.add_argument("--gateoverflow", type=Path, default=DEFAULT_GATEOVERFLOW)
    parser.add_argument(
        "--gateoverflow-pages", type=Path, default=DEFAULT_GATEOVERFLOW_PAGES
    )
    parser.add_argument("--figures", type=Path, default=DEFAULT_FIGURES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    artifact, report = build_verification(
        candidates_path=args.candidates.resolve(),
        provenance_path=args.provenance.resolve(),
        overlay_path=args.overlay.resolve(),
        matches_path=args.matches.resolve(),
        answers_path=args.answers.resolve(),
        examside_path=args.examside.resolve(),
        gateoverflow_path=args.gateoverflow.resolve(),
        gateoverflow_pages_dir=args.gateoverflow_pages.resolve(),
        figures_path=args.figures.resolve(),
    )
    output = args.output.resolve()
    report_path = (
        args.report.resolve()
        if args.report
        else output.with_name(f"{output.stem}.report.json")
    )
    _write_json(output, artifact)
    _write_json(report_path, report)
    print(
        json.dumps(
            {
                **report["summary"],
                "output": str(output),
                "report": str(report_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
