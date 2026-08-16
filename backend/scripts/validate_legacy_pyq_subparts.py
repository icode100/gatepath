"""Validate the explicit 1996-2002 legacy descriptive-subpart audit.

This validator is read-only.  It proves that every canonical descriptive parent
in the seven legacy papers has exactly one checksum-bound visual decision and
that aggregate split counts can be reproduced without touching the database.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


REPO_DIR = Path(__file__).resolve().parents[2]
DEFAULT_AUDIT = REPO_DIR / "backend" / "data" / "legacy_pyq_subparts_1996_2002.json"
DEFAULT_ARCHIVE = REPO_DIR / "tmp" / "pyq" / "build" / "canonical_pyq_archive.json"
DEFAULT_PROVENANCE = REPO_DIR / "tmp" / "pyq" / "build" / "original_pdf_provenance.json"
DEFAULT_OVERLAY = (
    REPO_DIR / "tmp" / "pyq" / "build" / "original_question_transcription_overlay.json"
)
DEFAULT_MANIFEST = REPO_DIR / "backend" / "data" / "pyq_source_manifest.json"

PAPER_IDS = {f"gate-cs-{year}" for year in range(1996, 2003)}
DECISIONS = {"split", "no_split", "review"}
HASH_RE = re.compile(r"[0-9a-f]{64}")
FORBIDDEN_KEYS = {"practice_eligible", "solution", "solution_md", "explanation"}


class LegacySubpartAuditError(ValueError):
    """Raised when the audited data cannot be reproduced safely."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LegacySubpartAuditError(f"Cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise LegacySubpartAuditError(f"{path}: expected a JSON object")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _clean_prompt(value: str) -> str:
    result = value.strip()
    result = re.sub(
        r"\nJoin All India Mock GATE.*?http://forum\.gatementor\.com\s*",
        "\n",
        result,
        flags=re.DOTALL,
    ).strip()
    for marker in (
        "\nSECTION – B",
        "\nSECTION - B",
        "\nSECTION – A",
        "\nSECTION - A",
    ):
        if marker in result:
            result = result.split(marker, 1)[0].rstrip()
    return re.sub(r"\n\s*\(c\)\s*$", "", result).rstrip()


def _validate_embedded_hash(payload: dict[str, Any]) -> None:
    expected = payload.get("artifact_sha256")
    if not isinstance(expected, str) or not HASH_RE.fullmatch(expected):
        raise LegacySubpartAuditError("Audit artifact_sha256 is missing or malformed")
    core = {key: value for key, value in payload.items() if key != "artifact_sha256"}
    if _canonical_sha256(core) != expected:
        raise LegacySubpartAuditError("Audit artifact_sha256 does not reproduce")


def _reject_forbidden(value: Any, path: str = "root") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_KEYS:
                raise LegacySubpartAuditError(f"Forbidden field {path}.{key}")
            _reject_forbidden(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_forbidden(child, f"{path}[{index}]")


def _unique_map(
    rows: Any,
    *,
    paper_key: str,
    ordinal_key: str,
    label: str,
) -> dict[tuple[str, int], dict[str, Any]]:
    if not isinstance(rows, list):
        raise LegacySubpartAuditError(f"{label}: expected a list")
    result: dict[tuple[str, int], dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise LegacySubpartAuditError(f"{label}: non-object row")
        paper_id = str(row.get(paper_key) or "")
        ordinal = row.get(ordinal_key)
        if not paper_id or not isinstance(ordinal, int) or ordinal < 1:
            raise LegacySubpartAuditError(f"{label}: invalid slot {paper_id}/{ordinal}")
        key = (paper_id, ordinal)
        if key in result:
            raise LegacySubpartAuditError(f"{label}: duplicate slot {key}")
        result[key] = row
    return result


def validate_audit(
    *,
    audit_path: Path = DEFAULT_AUDIT,
    archive_path: Path = DEFAULT_ARCHIVE,
    provenance_path: Path = DEFAULT_PROVENANCE,
    overlay_path: Path = DEFAULT_OVERLAY,
    manifest_path: Path = DEFAULT_MANIFEST,
) -> dict[str, Any]:
    audit = _read_json(audit_path)
    archive = _read_json(archive_path)
    provenance = _read_json(provenance_path)
    overlay = _read_json(overlay_path)
    manifest = _read_json(manifest_path)
    _validate_embedded_hash(audit)
    _reject_forbidden(audit)

    if audit.get("database_writes_performed") is not False:
        raise LegacySubpartAuditError("Audit must remain database-write-free")
    if audit.get("production_import_authorized") is not False:
        raise LegacySubpartAuditError("Audit must not authorize production import")
    if audit.get("automatic_promotion_allowed") is not False:
        raise LegacySubpartAuditError("Audit must not allow automatic promotion")
    bindings = audit.get("input_bindings") or {}
    expected_bindings = {
        "canonical_archive_sha256": _sha256_file(archive_path),
        "original_pdf_provenance_sha256": _sha256_file(provenance_path),
        "original_question_transcription_overlay_sha256": _sha256_file(overlay_path),
        "source_manifest_sha256": _sha256_file(manifest_path),
    }
    for key, expected in expected_bindings.items():
        if bindings.get(key) != expected:
            raise LegacySubpartAuditError(f"Input binding mismatch: {key}")

    manifest_rows = manifest.get("papers") or []
    manifest_map = {
        str(row.get("id")): row for row in manifest_rows if isinstance(row, dict)
    }
    archive_rows = archive.get("questions") or []
    archive_map = _unique_map(
        archive_rows,
        paper_key="source_paper_id",
        ordinal_key="ordinal",
        label="canonical archive",
    )
    provenance_map = _unique_map(
        provenance.get("items"),
        paper_key="source_paper_id",
        ordinal_key="canonical_ordinal",
        label="original PDF provenance",
    )
    overlay_map = _unique_map(
        overlay.get("items"),
        paper_key="source_paper_id",
        ordinal_key="canonical_ordinal",
        label="original transcription overlay",
    )
    expected_parents = {
        key: row
        for key, row in archive_map.items()
        if key[0] in PAPER_IDS and str(row.get("item_type") or "").casefold() == "descriptive"
    }

    papers = audit.get("papers")
    if not isinstance(papers, list) or {
        str(row.get("paper_id")) for row in papers if isinstance(row, dict)
    } != PAPER_IDS:
        raise LegacySubpartAuditError("Audit must contain exactly the seven 1996-2002 papers")

    audited_parents: dict[tuple[str, int], dict[str, Any]] = {}
    paper_reports: list[dict[str, Any]] = []
    for paper in papers:
        if not isinstance(paper, dict):
            raise LegacySubpartAuditError("Audit paper row is not an object")
        paper_id = str(paper.get("paper_id") or "")
        manifest_paper = manifest_map.get(paper_id)
        if manifest_paper is None:
            raise LegacySubpartAuditError(f"Unknown audit paper {paper_id}")
        if paper.get("source_pdf_sha256") != manifest_paper.get("local_sha256"):
            raise LegacySubpartAuditError(f"{paper_id}: source PDF SHA mismatch")
        if paper.get("source_page_count") != manifest_paper.get("local_page_count"):
            raise LegacySubpartAuditError(f"{paper_id}: source PDF page count mismatch")
        decisions = paper.get("decisions")
        if not isinstance(decisions, list):
            raise LegacySubpartAuditError(f"{paper_id}: decisions are missing")

        record_count = 0
        review_count = 0
        split_count = 0
        materialized_child_count = 0
        for row in decisions:
            if not isinstance(row, dict):
                raise LegacySubpartAuditError(f"{paper_id}: decision row is not an object")
            ordinal = row.get("parent_canonical_ordinal")
            if not isinstance(ordinal, int):
                raise LegacySubpartAuditError(f"{paper_id}: invalid parent ordinal")
            key = (paper_id, ordinal)
            if key in audited_parents:
                raise LegacySubpartAuditError(f"Duplicate audited parent {key}")
            parent = expected_parents.get(key)
            source = provenance_map.get(key)
            if parent is None or source is None:
                raise LegacySubpartAuditError(f"Unknown descriptive parent {key}")
            if row.get("parent_item_label") != parent.get("item_label"):
                raise LegacySubpartAuditError(f"{key}: parent item label mismatch")
            source_pages = row.get("source_pages")
            provenance_pages = row.get("provenance_source_pages")
            if not isinstance(source_pages, list) or not source_pages:
                raise LegacySubpartAuditError(f"{key}: audited source pages are missing")
            if provenance_pages != source.get("source_pages"):
                raise LegacySubpartAuditError(f"{key}: provenance source-page binding mismatch")
            if row.get("provenance_locator_match") != (source_pages == provenance_pages):
                raise LegacySubpartAuditError(f"{key}: provenance locator-match flag is incorrect")

            decision = row.get("decision")
            children = row.get("child_labels")
            if decision not in DECISIONS or not isinstance(children, list):
                raise LegacySubpartAuditError(f"{key}: invalid decision or child labels")
            if len(children) != len(set(children)):
                raise LegacySubpartAuditError(f"{key}: duplicate child label")
            prefix = f"{parent.get('item_label')}("
            if any(not isinstance(child, str) or not child.startswith(prefix) for child in children):
                raise LegacySubpartAuditError(f"{key}: child label does not name its parent")
            if decision == "split" and len(children) < 2:
                raise LegacySubpartAuditError(f"{key}: split requires at least two leaf children")
            if decision == "no_split" and children:
                raise LegacySubpartAuditError(f"{key}: no_split cannot name children")
            if decision == "review" and row.get("review_required") is not True:
                raise LegacySubpartAuditError(f"{key}: review decision must remain review-required")
            if decision != "review" and row.get("review_required") is not False:
                raise LegacySubpartAuditError(f"{key}: final decision has inconsistent review flag")

            expected_count = len(children) if decision == "split" else 1
            if row.get("record_count_after_decision") != expected_count:
                raise LegacySubpartAuditError(f"{key}: record count does not follow decision")
            evidence = row.get("evidence_pages")
            if not isinstance(evidence, list):
                raise LegacySubpartAuditError(f"{key}: rendered evidence is missing")
            evidence_pages = [entry.get("page") for entry in evidence if isinstance(entry, dict)]
            if evidence_pages != row.get("source_pages"):
                raise LegacySubpartAuditError(f"{key}: rendered evidence pages are incomplete")
            for entry in evidence:
                digest = entry.get("rendered_page_sha256")
                spec = entry.get("render_specification")
                if not isinstance(digest, str) or not HASH_RE.fullmatch(digest):
                    raise LegacySubpartAuditError(f"{key}: rendered-page SHA is malformed")
                if not isinstance(spec, dict) or not {
                    "renderer",
                    "format",
                    "dpi",
                    "color_mode",
                }.issubset(spec):
                    raise LegacySubpartAuditError(f"{key}: render specification is incomplete")
            corroborating = row.get("corroborating_sources", [])
            if not isinstance(corroborating, list):
                raise LegacySubpartAuditError(f"{key}: corroborating sources must be a list")
            if row.get("primary_source_defect") and not corroborating:
                raise LegacySubpartAuditError(
                    f"{key}: a claimed primary-source defect requires corroborating evidence"
                )
            for secondary in corroborating:
                if not isinstance(secondary, dict):
                    raise LegacySubpartAuditError(f"{key}: malformed corroborating source")
                if not str(secondary.get("source_url") or "").startswith("https://"):
                    raise LegacySubpartAuditError(f"{key}: corroborating source URL is invalid")
                digest = secondary.get("source_pdf_sha256")
                render_digest = secondary.get("rendered_page_sha256")
                page_count = secondary.get("source_page_count")
                page = secondary.get("source_page")
                if not isinstance(digest, str) or not HASH_RE.fullmatch(digest):
                    raise LegacySubpartAuditError(f"{key}: corroborating PDF SHA is malformed")
                if not isinstance(render_digest, str) or not HASH_RE.fullmatch(render_digest):
                    raise LegacySubpartAuditError(f"{key}: corroborating render SHA is malformed")
                if (
                    not isinstance(page_count, int)
                    or not isinstance(page, int)
                    or page_count < 1
                    or not 1 <= page <= page_count
                ):
                    raise LegacySubpartAuditError(f"{key}: corroborating page binding is invalid")
                secondary_spec = secondary.get("render_specification")
                if not isinstance(secondary_spec, dict) or not {
                    "renderer",
                    "format",
                    "color_mode",
                }.issubset(secondary_spec):
                    raise LegacySubpartAuditError(
                        f"{key}: corroborating render specification is incomplete"
                    )

            child_records = row.get("child_records")
            if not isinstance(child_records, list):
                raise LegacySubpartAuditError(f"{key}: materialization child records are missing")
            if decision == "split":
                split_count += 1
                if [child.get("child_item_label") for child in child_records] != children:
                    raise LegacySubpartAuditError(f"{key}: child materialization order mismatch")
            elif child_records:
                raise LegacySubpartAuditError(f"{key}: non-split parent cannot materialize children")

            overlay_item = overlay_map.get(key) or {}
            inventory = overlay_item.get("legacy_subpart_inventory") or {}
            inventory_children = {
                child.get("source_subpart_label"): child
                for child in inventory.get("children", [])
                if isinstance(child, dict)
            }
            for index, child in enumerate(child_records, start=1):
                if not isinstance(child, dict):
                    raise LegacySubpartAuditError(f"{key}: materialized child is not an object")
                child_label = child.get("child_item_label")
                if child.get("child_order") != index:
                    raise LegacySubpartAuditError(f"{key}/{child_label}: child order is invalid")
                if child.get("question_type") != "descriptive":
                    raise LegacySubpartAuditError(f"{key}/{child_label}: question type is invalid")
                prompt = child.get("prompt_text")
                if not isinstance(prompt, str) or not prompt.strip():
                    raise LegacySubpartAuditError(f"{key}/{child_label}: exact prompt is missing")
                if child.get("prompt_text_sha256") != _sha256_text(prompt):
                    raise LegacySubpartAuditError(f"{key}/{child_label}: prompt SHA does not reproduce")
                if child.get("materialization_status") != "exact":
                    raise LegacySubpartAuditError(f"{key}/{child_label}: child is not expansion-ready")
                if child.get("review_flags") != []:
                    raise LegacySubpartAuditError(
                        f"{key}/{child_label}: exact child retains unresolved review flags"
                    )
                archive_notes = child.get("archive_notes")
                if not isinstance(archive_notes, list) or any(
                    not isinstance(note, str) or "review_required" in note
                    for note in archive_notes
                ):
                    raise LegacySubpartAuditError(
                        f"{key}/{child_label}: archive notes are malformed or blocking"
                    )
                if child.get("source_pages") != source_pages:
                    raise LegacySubpartAuditError(f"{key}/{child_label}: source pages changed")
                if child.get("rendered_page_evidence") != evidence:
                    raise LegacySubpartAuditError(f"{key}/{child_label}: render evidence changed")
                marks = child.get("marks")
                if marks is not None and (not isinstance(marks, int) or marks < 0):
                    raise LegacySubpartAuditError(f"{key}/{child_label}: marks are invalid")
                if not isinstance(child.get("marks_status"), str):
                    raise LegacySubpartAuditError(f"{key}/{child_label}: marks status is missing")
                if marks is None and child.get("marks_status") not in {
                    "not_determinable_from_bounded_child_span",
                    "visible_only_as_parent_aggregate",
                }:
                    raise LegacySubpartAuditError(
                        f"{key}/{child_label}: null marks lack an explicit evidence status"
                    )
                if marks is not None and child.get("marks_status") != "exact_visible":
                    raise LegacySubpartAuditError(
                        f"{key}/{child_label}: visible marks have inconsistent status"
                    )
                if "parent_aggregate_marks" in child and (
                    not isinstance(child["parent_aggregate_marks"], int)
                    or child["parent_aggregate_marks"] < 1
                ):
                    raise LegacySubpartAuditError(
                        f"{key}/{child_label}: parent aggregate marks are invalid"
                    )

                context = child.get("shared_context")
                if not isinstance(context, dict):
                    raise LegacySubpartAuditError(f"{key}/{child_label}: shared context is missing")
                expected_context = {
                    "source_paper_id": paper_id,
                    "canonical_parent_ordinal": ordinal,
                    "parent_item_label": parent.get("item_label"),
                    "canonical_parent_question_sha256": _sha256_text(
                        str(parent.get("question_md") or "")
                    ),
                }
                if context.get("strategy") != "preserve_pre_expansion_parent_question":
                    raise LegacySubpartAuditError(f"{key}/{child_label}: context strategy is unsafe")
                for field, expected_value in expected_context.items():
                    if context.get(field) != expected_value:
                        raise LegacySubpartAuditError(
                            f"{key}/{child_label}: shared context mismatch for {field}"
                        )
                shared_text = context.get("additional_shared_text")
                if shared_text is not None and (
                    not isinstance(shared_text, str)
                    or context.get("additional_shared_text_sha256") != _sha256_text(shared_text)
                ):
                    raise LegacySubpartAuditError(f"{key}/{child_label}: shared-text SHA mismatch")
                shared_evidence = context.get("additional_shared_text_evidence")
                if not str(parent.get("question_md") or "").strip() and (
                    not shared_text or not isinstance(shared_evidence, dict)
                ):
                    raise LegacySubpartAuditError(
                        f"{key}/{child_label}: empty parent requires source-bound shared context"
                    )
                if shared_evidence is not None:
                    if not isinstance(shared_evidence, dict):
                        raise LegacySubpartAuditError(
                            f"{key}/{child_label}: shared-context evidence is malformed"
                        )
                    shared_pages = shared_evidence.get("source_pages")
                    shared_renders = shared_evidence.get("rendered_page_evidence")
                    if (
                        not isinstance(shared_pages, list)
                        or not shared_pages
                        or not isinstance(shared_renders, list)
                        or [render.get("page") for render in shared_renders]
                        != shared_pages
                    ):
                        raise LegacySubpartAuditError(
                            f"{key}/{child_label}: shared-context page evidence is incomplete"
                        )
                    for render in shared_renders:
                        digest = render.get("sha256")
                        if (
                            not isinstance(digest, str)
                            or not HASH_RE.fullmatch(digest)
                            or not (
                                (
                                    isinstance(render.get("width_px"), int)
                                    and isinstance(render.get("height_px"), int)
                                )
                                or isinstance(render.get("dpi"), int)
                            )
                        ):
                            raise LegacySubpartAuditError(
                                f"{key}/{child_label}: shared-context render evidence is invalid"
                            )

                prompt_source = child.get("prompt_source")
                prompt_evidence = child.get("prompt_evidence")
                if not isinstance(prompt_evidence, dict):
                    raise LegacySubpartAuditError(f"{key}/{child_label}: prompt evidence is missing")
                if prompt_source == "original_transcription_overlay_child":
                    source_child = inventory_children.get(child_label)
                    if source_child is None:
                        raise LegacySubpartAuditError(
                            f"{key}/{child_label}: overlay child evidence cannot be found"
                        )
                    source_text = str(source_child.get("text") or "")
                    if prompt != _clean_prompt(source_text):
                        raise LegacySubpartAuditError(
                            f"{key}/{child_label}: prompt diverges from overlay child text"
                        )
                    if prompt_evidence.get("source_child_text_sha256") != _sha256_text(source_text):
                        raise LegacySubpartAuditError(
                            f"{key}/{child_label}: overlay child SHA mismatch"
                        )
                elif prompt_source in {
                    "bounded_nested_span_in_overlay_child",
                    "bounded_roman_span_in_overlay_parent",
                }:
                    start = prompt_evidence.get("start_offset")
                    end = prompt_evidence.get("end_offset")
                    if (
                        not isinstance(start, int)
                        or not isinstance(end, int)
                        or not 0 <= start < end
                    ):
                        raise LegacySubpartAuditError(
                            f"{key}/{child_label}: bounded prompt offsets are invalid"
                        )
                    if prompt_source == "bounded_nested_span_in_overlay_child":
                        ancestor_label = prompt_evidence.get("ancestor_item_label")
                        ancestor = inventory_children.get(ancestor_label)
                        ancestor_text = str((ancestor or {}).get("text") or "")
                        if (
                            not ancestor_text
                            or prompt_evidence.get("ancestor_text_sha256")
                            != _sha256_text(ancestor_text)
                            or end > len(ancestor_text)
                            or prompt != _clean_prompt(ancestor_text[start:end])
                        ):
                            raise LegacySubpartAuditError(
                                f"{key}/{child_label}: nested bounded span does not reproduce"
                            )
                    else:
                        parent_text = str(
                            inventory.get("parent_prompt")
                            or (overlay_item.get("proposed_overlay") or {}).get("question_text")
                            or ""
                        )
                        if (
                            prompt_evidence.get("parent_prompt_sha256")
                            != _sha256_text(parent_text)
                            or end > len(parent_text)
                            or prompt != _clean_prompt(parent_text[start:end])
                        ):
                            raise LegacySubpartAuditError(
                                f"{key}/{child_label}: parent bounded span does not reproduce"
                            )
                elif prompt_source == "manual_visual_transcription_from_checksum_bound_complete_scan":
                    source_digest = prompt_evidence.get("source_pdf_sha256")
                    rendered = prompt_evidence.get("rendered_page_evidence")
                    if (
                        not isinstance(source_digest, str)
                        or not HASH_RE.fullmatch(source_digest)
                        or not isinstance(rendered, list)
                        or not rendered
                        or prompt_evidence.get("visual_transcription_required") is not True
                    ):
                        raise LegacySubpartAuditError(
                            f"{key}/{child_label}: visual transcription evidence is incomplete"
                        )
                    for rendered_page in rendered:
                        digest = rendered_page.get("sha256") if isinstance(rendered_page, dict) else None
                        if not isinstance(digest, str) or not HASH_RE.fullmatch(digest):
                            raise LegacySubpartAuditError(
                                f"{key}/{child_label}: visual render SHA is malformed"
                            )
                else:
                    raise LegacySubpartAuditError(
                        f"{key}/{child_label}: unknown prompt materialization source"
                    )
                materialized_child_count += 1
            audited_parents[key] = row
            record_count += expected_count
            review_count += int(decision == "review")

        canonical_paper_rows = [row for key, row in archive_map.items() if key[0] == paper_id]
        non_descriptive_count = sum(
            str(row.get("item_type") or "").casefold() != "descriptive"
            for row in canonical_paper_rows
        )
        final_count = None if review_count else non_descriptive_count + record_count
        expected_aggregate = {
            "canonical_slot_count": len(canonical_paper_rows),
            "canonical_descriptive_parent_count": len(decisions),
            "audited_descriptive_record_count": record_count,
            "final_split_database_record_count": final_count,
            "corpus_delta": None if final_count is None else final_count - len(canonical_paper_rows),
            "residual_review_row_count": review_count,
            "split_parent_count": split_count,
            "materialized_child_record_count": materialized_child_count,
            "expansion_ready_child_count": materialized_child_count,
        }
        for field, expected in expected_aggregate.items():
            if paper.get(field) != expected:
                raise LegacySubpartAuditError(f"{paper_id}: aggregate mismatch for {field}")
        paper_reports.append({"paper_id": paper_id, **expected_aggregate})

    if set(audited_parents) != set(expected_parents):
        missing = sorted(set(expected_parents) - set(audited_parents))
        extra = sorted(set(audited_parents) - set(expected_parents))
        raise LegacySubpartAuditError(
            f"Descriptive-parent coverage mismatch; missing={missing[:5]}, extra={extra[:5]}"
        )

    review_rows = sum(row["residual_review_row_count"] for row in paper_reports)
    split_parents = sum(row["split_parent_count"] for row in paper_reports)
    materialized_children = sum(
        row["materialized_child_record_count"] for row in paper_reports
    )
    final_total = (
        sum(row["final_split_database_record_count"] for row in paper_reports)
        if review_rows == 0
        else None
    )
    canonical_total = sum(row["canonical_slot_count"] for row in paper_reports)
    expected_summary = audit.get("summary") or {}
    reproduced_summary = {
        "paper_count": len(paper_reports),
        "descriptive_parent_count": len(audited_parents),
        "canonical_slot_count": canonical_total,
        "final_split_database_record_count": final_total,
        "corpus_delta": None if final_total is None else final_total - canonical_total,
        "residual_review_row_count": review_rows,
        "split_parent_count": split_parents,
        "materialized_child_record_count": materialized_children,
        "expansion_ready_child_count": materialized_children,
    }
    if expected_summary != reproduced_summary:
        raise LegacySubpartAuditError("Top-level audit summary does not reproduce")
    return {"summary": reproduced_summary, "papers": paper_reports}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--provenance", type=Path, default=DEFAULT_PROVENANCE)
    parser.add_argument("--overlay", type=Path, default=DEFAULT_OVERLAY)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = validate_audit(
        audit_path=args.audit,
        archive_path=args.archive,
        provenance_path=args.provenance,
        overlay_path=args.overlay,
        manifest_path=args.manifest,
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
