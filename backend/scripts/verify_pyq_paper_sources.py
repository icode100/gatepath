"""Build a strict, staging-only source-verification gate for 39 GATE CS papers.

This verifier proves local file identity and source authority separately.  A
paper is ``verified`` only when either:

* a first-party GATE/IIT index and independently acquired official artifact
  are present and that artifact is byte-identical to the bound local source;
  or
* at least two independently acquired republications from distinct domains
  are byte-identical to the local source and agree on page/item structure.

URLs, authority labels, visually similar papers, single mirrors, and answer
keys never satisfy the gate on their own.  The emitted artifact is review-only:
it cannot write a database, promote content, or make a question practice-ready.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

from pypdf import PdfReader


REPO_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_DIR / "backend"
BUILD_DIR = REPO_DIR / "tmp" / "pyq" / "build"
DEFAULT_MANIFEST = BACKEND_DIR / "data" / "pyq_source_manifest.json"
DEFAULT_CANONICAL = BUILD_DIR / "canonical_pyq_archive.json"
DEFAULT_PROVENANCE = BUILD_DIR / "original_pdf_provenance.json"
DEFAULT_EVIDENCE = BACKEND_DIR / "data" / "pyq_paper_source_evidence.json"
DEFAULT_OUTPUT = BUILD_DIR / "pyq_paper_source_verification.json"

SCHEMA_VERSION = "1.0-staging-paper-source-verification"
EXPECTED_PAPERS = 39
EXPECTED_ITEMS = 2712
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
OFFICIAL_HOSTS = {
    "gate.iitb.ac.in",
    "gate.iitk.ac.in",
    "gate.iitm.ac.in",
    "gate2025.iitr.ac.in",
    "gate2027.iitm.ac.in",
}
METHOD_PRIMARY = "primary_official_byte_identity"
METHOD_SECONDARY = "cross_validated_republication"


class SourceVerificationError(ValueError):
    """Raised when an input binding or evidence declaration is unsafe."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceVerificationError(f"Cannot read JSON input {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SourceVerificationError(f"{path}: expected a JSON object")
    return value


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
    path = path.resolve()
    return {
        "path": _relative(path),
        "sha256": _sha256_file(path),
        "bytes": path.stat().st_size,
    }


def _validate_embedded_hash(value: Mapping[str, Any], *, label: str) -> None:
    expected = value.get("artifact_sha256")
    if expected is None:
        return
    if not isinstance(expected, str) or HASH_RE.fullmatch(expected) is None:
        raise SourceVerificationError(f"{label}: malformed artifact_sha256")
    core = {key: child for key, child in value.items() if key != "artifact_sha256"}
    if _canonical_json_sha256(core) != expected:
        raise SourceVerificationError(f"{label}: embedded artifact hash mismatch")


def _url_host(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    parsed = urlparse(value.strip())
    return (parsed.hostname or "").casefold()


def _is_https(value: Any) -> bool:
    return isinstance(value, str) and urlparse(value).scheme.casefold() == "https"


def _is_official_index(value: Any) -> bool:
    return _is_https(value) and _url_host(value) in OFFICIAL_HOSTS


def _inspect_pdf(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "exists": path.is_file(),
        "valid_pdf": False,
        "sha256": None,
        "bytes": None,
        "pages": None,
    }
    if not path.is_file():
        return result
    result["bytes"] = path.stat().st_size
    result["sha256"] = _sha256_file(path)
    try:
        with path.open("rb") as stream:
            if stream.read(5) != b"%PDF-":
                return result
        result["pages"] = len(PdfReader(path, strict=False).pages)
        result["valid_pdf"] = True
    except Exception:  # pypdf may surface several parser-specific exceptions.
        return result
    return result


def _list_of_dicts(value: Any, *, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise SourceVerificationError(f"{label}: expected an array of objects")
    return value


def _unique_by_id(rows: Sequence[dict[str, Any]], *, field: str, label: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        identity = str(row.get(field) or "").strip()
        if not identity or identity in result:
            raise SourceVerificationError(f"{label}: empty or duplicate {field}={identity!r}")
        result[identity] = row
    return result


def _group_items(
    rows: Sequence[dict[str, Any]],
    *,
    paper_field: str,
    ordinal_field: str,
    label: str,
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[str, int]] = set()
    for row in rows:
        paper_id = str(row.get(paper_field) or "").strip()
        ordinal = row.get(ordinal_field)
        key = (paper_id, ordinal) if isinstance(ordinal, int) else None
        if not paper_id or key is None or ordinal < 1 or key in seen:
            raise SourceVerificationError(f"{label}: invalid or duplicate item {key}")
        seen.add(key)
        grouped[paper_id].append(row)
    for paper_id, paper_rows in grouped.items():
        actual = sorted(int(row[ordinal_field]) for row in paper_rows)
        if actual != list(range(1, len(paper_rows) + 1)):
            raise SourceVerificationError(f"{label}: {paper_id} ordinals are not contiguous")
    return grouped


def _resolve_source_path(value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (REPO_DIR / path).resolve()


def _validate_top_level_guards(evidence: Mapping[str, Any]) -> None:
    for field in (
        "production_import_authorized",
        "database_write_authorized",
        "promotion_authorized",
    ):
        if evidence.get(field) is not False:
            raise SourceVerificationError(f"Evidence catalog requires {field}=false")


def _inspect_evidence_entry(
    entry: Mapping[str, Any],
    *,
    local_sha256: str,
    local_pages: int,
    expected_item_count: int,
) -> dict[str, Any]:
    paper_id = str(entry.get("paper_id") or "")
    evidence_id = str(entry.get("evidence_id") or "")
    authority = str(entry.get("authority") or "")
    if authority not in {"primary_official", "secondary_republication"}:
        raise SourceVerificationError(
            f"{paper_id}/{evidence_id}: unsupported evidence authority {authority!r}"
        )
    artifact_raw = str(entry.get("artifact_path") or "")
    if not artifact_raw:
        raise SourceVerificationError(f"{paper_id}/{evidence_id}: artifact_path is required")
    artifact = _resolve_source_path(artifact_raw)
    declared_sha = str(entry.get("artifact_sha256") or "").casefold()
    declared_bytes = entry.get("artifact_bytes")
    declared_pages = entry.get("artifact_pages")
    if HASH_RE.fullmatch(declared_sha) is None:
        raise SourceVerificationError(f"{paper_id}/{evidence_id}: invalid declared SHA-256")
    inspected = _inspect_pdf(artifact)
    if not inspected["exists"]:
        raise SourceVerificationError(f"{paper_id}/{evidence_id}: evidence artifact missing")
    if not inspected["valid_pdf"]:
        raise SourceVerificationError(f"{paper_id}/{evidence_id}: evidence artifact is not a valid PDF")
    if (
        inspected["sha256"] != declared_sha
        or inspected["bytes"] != declared_bytes
        or inspected["pages"] != declared_pages
    ):
        raise SourceVerificationError(
            f"{paper_id}/{evidence_id}: evidence artifact declaration drifted"
        )
    source_url = entry.get("source_url")
    index_url = entry.get("index_url")
    source_domain = str(entry.get("source_domain") or "").casefold()
    if source_domain != _url_host(source_url):
        raise SourceVerificationError(
            f"{paper_id}/{evidence_id}: source_domain does not match source_url"
        )
    independently_acquired = entry.get("independently_acquired") is True
    item_count = entry.get("observed_item_count")
    byte_identical = inspected["sha256"] == local_sha256
    page_structure_agrees = inspected["pages"] == local_pages
    item_structure_agrees = item_count == expected_item_count
    official_index_confirmed = _is_official_index(index_url)
    official_source_confirmed = _is_https(source_url) and source_domain in OFFICIAL_HOSTS
    qualifies_primary = bool(
        authority == "primary_official"
        and independently_acquired
        and official_index_confirmed
        and official_source_confirmed
        and byte_identical
        and page_structure_agrees
        and item_structure_agrees
    )
    qualifies_secondary = bool(
        authority == "secondary_republication"
        and independently_acquired
        and _is_https(source_url)
        and byte_identical
        and page_structure_agrees
        and item_structure_agrees
    )
    return {
        "evidence_id": evidence_id,
        "authority": authority,
        "source_url": source_url,
        "index_url": index_url,
        "source_domain": source_domain,
        "independently_acquired": independently_acquired,
        "acquisition_method": entry.get("acquisition_method"),
        "acquisition_date": entry.get("acquisition_date"),
        "acquisition_record": entry.get("acquisition_record"),
        "structure_review": entry.get("structure_review"),
        "artifact": {
            "declared_path": artifact_raw.replace("\\", "/"),
            "absolute_path": str(artifact),
            "sha256": inspected["sha256"],
            "bytes": inspected["bytes"],
            "pages": inspected["pages"],
            "valid_pdf": inspected["valid_pdf"],
        },
        "observed_item_count": item_count,
        "byte_identical_to_bound_source": byte_identical,
        "page_structure_agrees": page_structure_agrees,
        "item_structure_agrees": item_structure_agrees,
        "official_index_confirmed": official_index_confirmed,
        "official_source_confirmed": official_source_confirmed,
        "qualifies_primary_official_byte_identity": qualifies_primary,
        "qualifies_cross_validated_republication_candidate": qualifies_secondary,
    }


def decide_verification(
    *,
    local_integrity_ok: bool,
    counts_ok: bool,
    evidence: Sequence[Mapping[str, Any]],
    manifest_authority: str,
) -> tuple[str, str, list[str], list[str]]:
    """Return a fail-closed decision and stable blocker/review-flag lists."""

    official = [
        row
        for row in evidence
        if row.get("qualifies_primary_official_byte_identity") is True
    ]
    secondary = [
        row
        for row in evidence
        if row.get("qualifies_cross_validated_republication_candidate") is True
    ]
    secondary_domains = {
        str(row.get("source_domain") or "").casefold() for row in secondary
    }
    has_cross_validation = len(secondary) >= 2 and len(secondary_domains) >= 2
    has_official_candidate = any(row.get("authority") == "primary_official" for row in evidence)
    method = (
        METHOD_PRIMARY
        if official or has_official_candidate or manifest_authority == "primary_official"
        else METHOD_SECONDARY
    )
    blockers: list[str] = []
    flags: list[str] = []
    if not local_integrity_ok:
        blockers.append("bound_local_source_integrity_failed")
    else:
        flags.append("bound_local_source_integrity_verified")
    if not counts_ok:
        blockers.append("manifest_canonical_provenance_count_mismatch")
    else:
        flags.append("manifest_canonical_provenance_counts_agree")
    if not local_integrity_ok or not counts_ok:
        return "rejected", method, sorted(blockers), sorted(flags)
    if official:
        flags.extend(
            [
                "official_index_confirmed",
                "independent_official_artifact_byte_identical",
                "page_and_item_structure_agree",
            ]
        )
        return "verified", METHOD_PRIMARY, [], sorted(set(flags))
    if has_cross_validation:
        flags.extend(
            [
                "two_independent_republication_domains_confirmed",
                "republished_artifacts_byte_identical",
                "page_and_item_structure_agree",
            ]
        )
        return "verified", METHOD_SECONDARY, [], sorted(set(flags))

    if has_official_candidate:
        if any(not row.get("byte_identical_to_bound_source") for row in evidence if row.get("authority") == "primary_official"):
            blockers.append("official_artifact_not_byte_identical_to_bound_source")
        if any(not row.get("page_structure_agrees") for row in evidence if row.get("authority") == "primary_official"):
            blockers.append("official_artifact_page_structure_differs")
        if any(not row.get("item_structure_agrees") for row in evidence if row.get("authority") == "primary_official"):
            blockers.append("official_artifact_item_structure_differs")
        blockers.append("no_qualifying_official_byte_identity_evidence")
    else:
        blockers.append("no_independently_acquired_official_artifact")
    if not has_cross_validation:
        blockers.append("fewer_than_two_qualifying_independent_republication_domains")
    flags.append("source_authority_requires_manual_review")
    return "review", method, sorted(set(blockers)), sorted(set(flags))


def build_source_verification(
    *,
    manifest_path: Path = DEFAULT_MANIFEST,
    canonical_path: Path = DEFAULT_CANONICAL,
    provenance_path: Path = DEFAULT_PROVENANCE,
    evidence_path: Path = DEFAULT_EVIDENCE,
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest_path = manifest_path.resolve()
    canonical_path = canonical_path.resolve()
    provenance_path = provenance_path.resolve()
    evidence_path = evidence_path.resolve()
    manifest = _read_json(manifest_path)
    canonical = _read_json(canonical_path)
    provenance = _read_json(provenance_path)
    evidence_catalog = _read_json(evidence_path)
    _validate_embedded_hash(provenance, label="original PDF provenance")
    _validate_top_level_guards(evidence_catalog)

    manifest_rows = _list_of_dicts(manifest.get("papers"), label="manifest papers")
    canonical_papers = _list_of_dicts(canonical.get("papers"), label="canonical papers")
    canonical_items = _list_of_dicts(canonical.get("questions"), label="canonical questions")
    provenance_papers = _list_of_dicts(provenance.get("papers"), label="provenance papers")
    provenance_items = _list_of_dicts(provenance.get("items"), label="provenance items")
    evidence_rows = _list_of_dicts(evidence_catalog.get("entries"), label="source evidence")
    if len(manifest_rows) != EXPECTED_PAPERS:
        raise SourceVerificationError(
            f"Manifest has {len(manifest_rows)} papers, expected {EXPECTED_PAPERS}"
        )
    if len(canonical_items) != EXPECTED_ITEMS or len(provenance_items) != EXPECTED_ITEMS:
        raise SourceVerificationError(
            "Canonical/provenance inputs must each contain exactly 2,712 parent slots"
        )

    manifest_by_id = _unique_by_id(manifest_rows, field="id", label="manifest")
    canonical_papers_by_id = _unique_by_id(canonical_papers, field="id", label="canonical papers")
    provenance_papers_by_id = _unique_by_id(provenance_papers, field="paper_id", label="provenance papers")
    expected_ids = set(manifest_by_id)
    if set(canonical_papers_by_id) != expected_ids or set(provenance_papers_by_id) != expected_ids:
        raise SourceVerificationError("Manifest/canonical/provenance paper identities differ")
    canonical_by_paper = _group_items(
        canonical_items,
        paper_field="source_paper_id",
        ordinal_field="ordinal",
        label="canonical",
    )
    provenance_by_paper = _group_items(
        provenance_items,
        paper_field="source_paper_id",
        ordinal_field="canonical_ordinal",
        label="provenance",
    )
    if set(canonical_by_paper) != expected_ids or set(provenance_by_paper) != expected_ids:
        raise SourceVerificationError("Canonical/provenance item paper identities differ")

    evidence_by_paper: dict[str, list[dict[str, Any]]] = defaultdict(list)
    evidence_ids: set[str] = set()
    for row in evidence_rows:
        paper_id = str(row.get("paper_id") or "")
        evidence_id = str(row.get("evidence_id") or "")
        if paper_id not in expected_ids or not evidence_id or evidence_id in evidence_ids:
            raise SourceVerificationError(
                f"Evidence catalog has invalid paper/evidence identity {paper_id}/{evidence_id}"
            )
        evidence_ids.add(evidence_id)
        evidence_by_paper[paper_id].append(row)

    paper_records: list[dict[str, Any]] = []
    for paper_id, manifest_row in manifest_by_id.items():
        canonical_paper = canonical_papers_by_id[paper_id]
        provenance_paper = provenance_papers_by_id[paper_id]
        canonical_rows = canonical_by_paper[paper_id]
        provenance_rows = provenance_by_paper[paper_id]
        source_identities = {
            (
                str(row.get("source_path") or ""),
                str(row.get("source_pdf_sha256") or "").casefold(),
            )
            for row in provenance_rows
        }
        if len(source_identities) != 1:
            raise SourceVerificationError(f"{paper_id}: provenance source identity is not unique")
        source_path_raw, provenance_source_hash = next(iter(source_identities))
        source_path = _resolve_source_path(source_path_raw)
        local = _inspect_pdf(source_path)
        manifest_sha = str(manifest_row.get("local_sha256") or "").casefold()
        local_integrity_ok = bool(
            local["valid_pdf"]
            and HASH_RE.fullmatch(manifest_sha)
            and local["sha256"] == manifest_sha
            and local["bytes"] == manifest_row.get("local_bytes")
            and local["pages"] == manifest_row.get("local_page_count")
            and provenance_source_hash == manifest_sha
            and provenance_paper.get("source_pdf_sha256") == manifest_sha
            and provenance_paper.get("source_page_count") == local["pages"]
            and canonical_paper.get("source_pdf_sha256") == manifest_sha
        )
        expected_count = int(manifest_row.get("expected_item_count") or 0)
        observed_count = manifest_row.get("observed_item_count")
        canonical_count = len(canonical_rows)
        provenance_count = len(provenance_rows)
        counts_ok = bool(
            expected_count > 0
            and observed_count == expected_count
            and canonical_paper.get("expected_item_count") == expected_count
            and provenance_paper.get("item_count") == expected_count
            and canonical_count == expected_count
            and provenance_count == expected_count
        )
        inspected_evidence = [
            _inspect_evidence_entry(
                row,
                local_sha256=str(local.get("sha256") or ""),
                local_pages=int(local.get("pages") or 0),
                expected_item_count=expected_count,
            )
            for row in evidence_by_paper.get(paper_id, [])
        ]
        decision, method, blockers, flags = decide_verification(
            local_integrity_ok=local_integrity_ok,
            counts_ok=counts_ok,
            evidence=inspected_evidence,
            manifest_authority=str(manifest_row.get("source_authority") or ""),
        )
        paper_records.append(
            {
                "source_paper_id": paper_id,
                "year": manifest_row.get("year"),
                "session": manifest_row.get("session"),
                "decision": decision,
                "method": method,
                "local_source": {
                    "manifest_declared_path": manifest_row.get("local_file"),
                    "provenance_path": source_path_raw,
                    "absolute_path": str(source_path),
                    "sha256": local.get("sha256"),
                    "bytes": local.get("bytes"),
                    "pages": local.get("pages"),
                    "valid_pdf": local.get("valid_pdf"),
                    "identity_matches_manifest_and_provenance": local_integrity_ok,
                },
                "counts": {
                    "expected_item_count": expected_count,
                    "manifest_observed_item_count": observed_count,
                    "canonical_item_count": canonical_count,
                    "provenance_item_count": provenance_count,
                    "counts_agree": counts_ok,
                },
                "provenance_binding": {
                    "source_pdf_sha256": provenance_paper.get("source_pdf_sha256"),
                    "source_page_count": provenance_paper.get("source_page_count"),
                    "item_count": provenance_paper.get("item_count"),
                    "unresolved_count": provenance_paper.get("unresolved_count"),
                },
                "evidence": inspected_evidence,
                "blockers": blockers,
                "review_flags": flags,
                "staging_guard": {
                    "production_import_authorized": False,
                    "database_write_authorized": False,
                    "promotion_authorized": False,
                    "practice_eligible": False,
                },
            }
        )

    decision_counts = Counter(row["decision"] for row in paper_records)
    method_counts = Counter(row["method"] for row in paper_records)
    input_bindings = {
        "source_manifest": _binding(manifest_path),
        "canonical_archive": _binding(canonical_path),
        "original_pdf_provenance": _binding(provenance_path),
        "source_evidence_catalog": _binding(evidence_path),
    }
    artifact_core = {
        "schema_version": SCHEMA_VERSION,
        "scope": "Strict source verification for the 39-paper GATE CS 1996-2025 staging inventory",
        "staging_guard": {
            "production_import_authorized": False,
            "database_write_authorized": False,
            "promotion_authorized": False,
            "practice_eligible": False,
        },
        "verification_policy": {
            "official": "Official index plus an independently acquired official artifact that is byte-identical to the bound local PDF and agrees on page/item structure.",
            "secondary": "At least two independently acquired, byte-identical artifacts from distinct domains with matching page/item structure.",
            "url_only_or_single_republisher_is_sufficient": False,
            "answer_key_can_verify_question_paper_identity": False,
        },
        "input_bindings": input_bindings,
        "invariants": {
            "expected_paper_count": EXPECTED_PAPERS,
            "actual_paper_count": len(paper_records),
            "expected_parent_item_count": EXPECTED_ITEMS,
            "canonical_parent_item_count": len(canonical_items),
            "provenance_parent_item_count": len(provenance_items),
            "all_papers_have_false_staging_guards": all(
                not any(row["staging_guard"].values()) for row in paper_records
            ),
        },
        "decision_counts": dict(sorted(decision_counts.items())),
        "method_counts": dict(sorted(method_counts.items())),
        "papers": paper_records,
    }
    artifact = {
        **artifact_core,
        "artifact_sha256": _canonical_json_sha256(artifact_core),
    }
    report_core = {
        "schema_version": SCHEMA_VERSION,
        "source_artifact_sha256": artifact["artifact_sha256"],
        "staging_guard": dict(artifact["staging_guard"]),
        "input_bindings": input_bindings,
        "summary": {
            "paper_count": len(paper_records),
            "verified_count": decision_counts.get("verified", 0),
            "review_count": decision_counts.get("review", 0),
            "rejected_count": decision_counts.get("rejected", 0),
            "primary_official_byte_identity_count": sum(
                row["decision"] == "verified" and row["method"] == METHOD_PRIMARY
                for row in paper_records
            ),
            "cross_validated_republication_count": sum(
                row["decision"] == "verified" and row["method"] == METHOD_SECONDARY
                for row in paper_records
            ),
            "bound_source_bytes": sum(int(row["local_source"]["bytes"] or 0) for row in paper_records),
        },
        "papers": [
            {
                "source_paper_id": row["source_paper_id"],
                "decision": row["decision"],
                "method": row["method"],
                "source_sha256": row["local_source"]["sha256"],
                "source_bytes": row["local_source"]["bytes"],
                "source_pages": row["local_source"]["pages"],
                "expected_item_count": row["counts"]["expected_item_count"],
                "observed_item_count": row["counts"]["manifest_observed_item_count"],
                "canonical_item_count": row["counts"]["canonical_item_count"],
                "provenance_item_count": row["counts"]["provenance_item_count"],
                "qualifying_evidence_ids": [
                    evidence["evidence_id"]
                    for evidence in row["evidence"]
                    if evidence["qualifies_primary_official_byte_identity"]
                    or evidence["qualifies_cross_validated_republication_candidate"]
                ],
                "blockers": row["blockers"],
                "review_flags": row["review_flags"],
            }
            for row in paper_records
        ],
    }
    report = {**report_core, "artifact_sha256": _canonical_json_sha256(report_core)}
    return artifact, report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--canonical", type=Path, default=DEFAULT_CANONICAL)
    parser.add_argument("--provenance", type=Path, default=DEFAULT_PROVENANCE)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    artifact, report = build_source_verification(
        manifest_path=args.manifest,
        canonical_path=args.canonical,
        provenance_path=args.provenance,
        evidence_path=args.evidence,
    )
    output = args.output.resolve()
    report_path = (
        args.report.resolve()
        if args.report is not None
        else output.with_suffix(".report.json")
    )
    _write_json(output, artifact)
    _write_json(report_path, report)
    summary = report["summary"]
    print(
        "Verified source gate: "
        f"{summary['verified_count']} verified / {summary['review_count']} review / "
        f"{summary['rejected_count']} rejected across {summary['paper_count']} papers."
    )
    print(f"Artifact: {output}")
    print(f"Report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
