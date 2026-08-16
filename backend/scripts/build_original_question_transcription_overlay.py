"""Build a deterministic, staging-only original-PDF transcription overlay.

This tool never opens a database and never imports or promotes a question.  It
joins the reviewed 39-paper/2,712-slot canonical inventory to the independently
hashed original-PDF provenance index.  Text is emitted only when the exact
page/boundary extraction reproduces the provenance block hash.  Page-only OCR
or rendered-image locators remain review records, and missing locators remain
unresolved.

GateOverflow and ExamSIDE candidate bodies are used only as in-memory
cross-checks.  Their text and explanations are never copied to the output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable

from pypdf import PdfReader


REPO_DIR = Path(__file__).resolve().parents[2]
BUILD_DIR = REPO_DIR / "tmp" / "pyq" / "build"
DEFAULT_ARCHIVE = BUILD_DIR / "canonical_pyq_archive.json"
DEFAULT_CANDIDATES = BUILD_DIR / "canonical_pyq_candidates_structured.json"
DEFAULT_PROVENANCE = BUILD_DIR / "original_pdf_provenance.json"
DEFAULT_MANIFEST = REPO_DIR / "backend" / "data" / "pyq_source_manifest.json"
DEFAULT_LOCATOR_OVERRIDES = (
    REPO_DIR / "backend" / "data" / "pyq_original_locator_overrides.json"
)
DEFAULT_OUTPUT = BUILD_DIR / "original_question_transcription_overlay.json"

SCHEMA_VERSION = "1.0-staging-original-question-transcription-overlay"
EXPECTED_PAPERS = 39
EXPECTED_SLOTS = 2712
STATUSES = {"exact", "review", "unresolved"}
OBJECTIVE_TYPES = {"mcq", "msq"}
OPTION_IDS = ("A", "B", "C", "D")
FORBIDDEN_OUTPUT_KEYS = {"practice_eligible", "solution", "solution_md", "explanation"}
HASH_RE = re.compile(r"[0-9a-f]{64}")
PAGE_FOOTER_RE = re.compile(r"(?im)^\s*Page\s+\d+\s+of\s+\d+\s*$")
VISUAL_REFERENCE_RE = re.compile(
    r"(?i)\b(?:figure|diagram|circuit|graph|table|image|shown\s+(?:above|below)|"
    r"following\s+(?:figure|diagram|circuit|graph|table))\b"
)
BROKEN_GLYPH_RE = re.compile(r"[\uE000-\uF8FF\uFFFD]|#{2,}")
INLINE_OPTION_RE = re.compile(r"(?<![A-Za-z0-9])\(([A-Da-d])\)[ \t]*")
LINE_OPTION_RE = re.compile(r"(?im)^\s*([A-D])[.)][ \t]+")
LETTERED_SUBPART_RE = re.compile(
    r"(?im)(?:^|\n)[ \t]*(?:\(([a-h])\)|([a-h])[.)])[ \t]+"
)
LEGACY_SUBPART_YEARS = set(range(1996, 2003))


class OverlayBuildError(ValueError):
    """Raised when an input identity or source transcription is unsafe."""


@dataclass(slots=True)
class PdfSource:
    path: Path
    sha256: str
    reader: PdfReader
    page_text: dict[int, str]


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return _sha256_text(encoded)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OverlayBuildError(f"Cannot read JSON input {path}: {exc}") from exc


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "")
    value = value.replace("\u00ad", "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [" ".join(line.split()) for line in value.split("\n")]
    return "\n".join(line for line in lines if line).strip()


def _comparison_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").casefold()
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def _input_binding(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(REPO_DIR)).replace("\\", "/")
        if path.is_relative_to(REPO_DIR)
        else str(path),
        "sha256": _sha256_file(path),
        "bytes": path.stat().st_size,
    }


def _validate_embedded_artifact_hash(payload: dict[str, Any], *, label: str) -> None:
    expected = payload.get("artifact_sha256")
    if expected is None:
        return
    if not isinstance(expected, str) or not HASH_RE.fullmatch(expected):
        raise OverlayBuildError(f"{label}: malformed artifact_sha256")
    core = {key: value for key, value in payload.items() if key != "artifact_sha256"}
    if _canonical_json_sha256(core) != expected:
        raise OverlayBuildError(f"{label}: embedded artifact_sha256 mismatch")


def _slot_key(row: dict[str, Any], *, ordinal_key: str) -> tuple[str, int]:
    paper_id = str(row.get("source_paper_id") or row.get("paper_id") or "").strip()
    ordinal = row.get(ordinal_key)
    if not paper_id or not isinstance(ordinal, int) or ordinal < 1:
        raise OverlayBuildError(f"Invalid slot identity: {paper_id!r}/{ordinal!r}")
    return paper_id, ordinal


def _unique_map(
    rows: Any, *, ordinal_key: str, label: str
) -> dict[tuple[str, int], dict[str, Any]]:
    if not isinstance(rows, list):
        raise OverlayBuildError(f"{label}: item list is missing")
    result: dict[tuple[str, int], dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise OverlayBuildError(f"{label}: item is not an object")
        key = _slot_key(row, ordinal_key=ordinal_key)
        if key in result:
            raise OverlayBuildError(f"{label}: duplicate slot {key}")
        result[key] = row
    return result


def _validate_inputs(
    archive: dict[str, Any],
    candidates: dict[str, Any],
    provenance: dict[str, Any],
    manifest: dict[str, Any],
    *,
    manifest_path: Path,
) -> tuple[
    dict[tuple[str, int], dict[str, Any]],
    dict[tuple[str, int], dict[str, Any]],
    dict[tuple[str, int], dict[str, Any]],
    dict[str, dict[str, Any]],
]:
    if len(archive.get("papers") or []) != EXPECTED_PAPERS:
        raise OverlayBuildError("Canonical archive must contain exactly 39 papers")
    archive_map = _unique_map(
        archive.get("questions"), ordinal_key="ordinal", label="canonical archive"
    )
    candidate_map = _unique_map(
        candidates.get("questions"), ordinal_key="ordinal", label="candidate artifact"
    )
    provenance_map = _unique_map(
        provenance.get("items"),
        ordinal_key="canonical_ordinal",
        label="original PDF provenance",
    )
    if not (
        len(archive_map)
        == len(candidate_map)
        == len(provenance_map)
        == EXPECTED_SLOTS
    ):
        raise OverlayBuildError("All staging inputs must expose exactly 2,712 slots")
    if set(archive_map) != set(candidate_map) or set(archive_map) != set(provenance_map):
        raise OverlayBuildError("Canonical, candidate, and provenance slot identities differ")
    papers = manifest.get("papers")
    if not isinstance(papers, list) or len(papers) != EXPECTED_PAPERS:
        raise OverlayBuildError("Source manifest must contain exactly 39 papers")
    manifest_map = {str(row.get("id")): row for row in papers if isinstance(row, dict)}
    if len(manifest_map) != EXPECTED_PAPERS:
        raise OverlayBuildError("Source manifest contains duplicate or invalid paper IDs")
    if provenance.get("source_manifest_sha256") != _sha256_file(manifest_path):
        raise OverlayBuildError("Provenance is not bound to the supplied source manifest")
    identity = provenance.get("canonical_identity") or {}
    if identity != {"paper_count": EXPECTED_PAPERS, "item_count": EXPECTED_SLOTS}:
        raise OverlayBuildError("Provenance canonical identity is not 39/2712")
    _validate_embedded_artifact_hash(provenance, label="original PDF provenance")
    for key, record in provenance_map.items():
        manifest_paper = manifest_map.get(key[0])
        if manifest_paper is None:
            raise OverlayBuildError(f"Provenance references unknown paper {key[0]}")
        expected_sha = str(manifest_paper.get("local_sha256") or "").casefold()
        if record.get("source_pdf_sha256") != expected_sha:
            raise OverlayBuildError(f"{key}: provenance/source-manifest PDF hash mismatch")
        archive_label = str(archive_map[key].get("item_label") or "")
        if str(record.get("item_label") or "") != archive_label:
            raise OverlayBuildError(f"{key}: provenance item label mismatch")
        page_count = manifest_paper.get("local_page_count")
        if not isinstance(page_count, int) or page_count < 1:
            raise OverlayBuildError(f"{key[0]}: manifest PDF page count is invalid")
        source_pages = record.get("source_pages") or []
        if not isinstance(source_pages, list) or any(
            not isinstance(page, int) or not 1 <= page <= page_count
            for page in source_pages
        ):
            raise OverlayBuildError(f"{key}: provenance source page is outside the PDF")
        boundary = record.get("boundary")
        if boundary is not None:
            if not isinstance(boundary, dict):
                raise OverlayBuildError(f"{key}: malformed provenance boundary")
            start_page = boundary.get("start_page")
            end_page = boundary.get("end_page")
            if (
                not isinstance(start_page, int)
                or not isinstance(end_page, int)
                or not 1 <= start_page <= end_page <= page_count
            ):
                raise OverlayBuildError(f"{key}: provenance boundary is outside the PDF")
    provenance_papers = provenance.get("papers")
    if provenance_papers is not None:
        if not isinstance(provenance_papers, list) or len(provenance_papers) != EXPECTED_PAPERS:
            raise OverlayBuildError("Provenance paper summary is not exactly 39 papers")
        provenance_paper_map = {
            str(row.get("paper_id")): row
            for row in provenance_papers
            if isinstance(row, dict)
        }
        if set(provenance_paper_map) != set(manifest_map):
            raise OverlayBuildError("Provenance/manifest paper identities differ")
        for paper_id, paper in provenance_paper_map.items():
            manifest_paper = manifest_map[paper_id]
            if paper.get("source_pdf_sha256") != manifest_paper.get("local_sha256"):
                raise OverlayBuildError(f"{paper_id}: provenance paper PDF hash mismatch")
            if paper.get("source_page_count") != manifest_paper.get("local_page_count"):
                raise OverlayBuildError(f"{paper_id}: provenance paper page count mismatch")
    return archive_map, candidate_map, provenance_map, manifest_map


def _locator_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    # The committed locator catalog groups slot locators by paper so a single
    # rendered-page checksum can safely cover every printed label reviewed on
    # that page.  Flatten that normalized representation for the slot-level
    # validation below; never infer a page or render hash from list order.
    papers = payload.get("papers")
    if isinstance(papers, list):
        rows: list[dict[str, Any]] = []
        for paper in papers:
            if not isinstance(paper, dict):
                raise OverlayBuildError("Locator override paper must be an object")
            paper_id = str(paper.get("paper_id") or "").strip()
            source_sha = str(paper.get("source_pdf_sha256") or "").casefold()
            page_evidence = paper.get("page_evidence")
            locators = paper.get("locators")
            if not paper_id or not HASH_RE.fullmatch(source_sha):
                raise OverlayBuildError("Locator override paper identity is incomplete")
            if not isinstance(page_evidence, list) or not isinstance(locators, list):
                raise OverlayBuildError(
                    f"{paper_id}: locator override pages/locators are missing"
                )
            evidence_by_page: dict[int, dict[str, Any]] = {}
            for evidence in page_evidence:
                if not isinstance(evidence, dict) or not isinstance(
                    evidence.get("page"), int
                ):
                    raise OverlayBuildError(
                        f"{paper_id}: rendered-page evidence is malformed"
                    )
                page = int(evidence["page"])
                if page in evidence_by_page:
                    raise OverlayBuildError(
                        f"{paper_id}: duplicate rendered-page evidence for page {page}"
                    )
                evidence_by_page[page] = evidence
            for locator in locators:
                if not isinstance(locator, dict):
                    raise OverlayBuildError(
                        f"{paper_id}: slot locator must be an object"
                    )
                page = locator.get("source_page")
                evidence = evidence_by_page.get(page) if isinstance(page, int) else None
                if evidence is None:
                    raise OverlayBuildError(
                        f"{paper_id}: locator page {page!r} has no rendered evidence"
                    )
                rows.append(
                    {
                        **locator,
                        "source_paper_id": paper_id,
                        "source_pdf_sha256": source_sha,
                        "review_required": paper.get("review_required") is True,
                        "evidence_method": evidence.get("evidence_method"),
                        "visual_spot_check": evidence.get("visual_spot_check") is True,
                        "rendered_page_evidence": {
                            "page": page,
                            "sha256": evidence.get("sha256"),
                            "format": evidence.get("format"),
                            "dpi": evidence.get("dpi"),
                            "color_mode": evidence.get("color_mode"),
                        },
                    }
                )
        declared_count = payload.get("locator_count")
        if declared_count is not None and declared_count != len(rows):
            raise OverlayBuildError(
                "Locator override count does not match the flattened slot inventory"
            )
        unresolved = payload.get("unresolved_locators")
        if isinstance(unresolved, list) and unresolved:
            raise OverlayBuildError("Locator override catalog still has unresolved slots")
        return rows
    for name in ("overrides", "locators", "items"):
        rows = payload.get(name)
        if isinstance(rows, list):
            return rows
    if all(isinstance(value, dict) for value in payload.values()):
        return [value for value in payload.values() if isinstance(value, dict)]
    raise OverlayBuildError("Locator override artifact has no explicit locator list")


def _rendered_locator(row: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    evidence = row.get("rendered_page_evidence")
    if isinstance(evidence, dict):
        digest = evidence.get("sha256")
        spec = {key: evidence.get(key) for key in ("format", "dpi", "color_mode")}
    else:
        digest = row.get("rendered_page_sha256") or row.get("rendered_sha256")
        spec = row.get("render_specification") or row.get("render_spec") or {}
    if not isinstance(digest, str) or not HASH_RE.fullmatch(digest):
        raise OverlayBuildError("Locator override rendered-page SHA-256 is missing")
    if not isinstance(spec, dict):
        raise OverlayBuildError("Locator override render specification is missing")
    required = {"format", "dpi", "color_mode"}
    if not required.issubset(spec) or not isinstance(spec.get("dpi"), int):
        raise OverlayBuildError("Locator override render specification is incomplete")
    return digest, {key: spec[key] for key in sorted(required)}


def _load_locator_overrides(
    path: Path | None,
    *,
    provenance: dict[str, Any],
    provenance_map: dict[tuple[str, int], dict[str, Any]],
    manifest_map: dict[str, dict[str, Any]],
    source_manifest_sha256: str,
) -> tuple[dict[tuple[str, int], dict[str, Any]], dict[str, Any] | None]:
    if path is None or not path.is_file():
        return {}, None
    payload = _read_json(path)
    if not isinstance(payload, dict):
        raise OverlayBuildError("Locator override artifact must be a JSON object")
    _validate_embedded_artifact_hash(payload, label="locator overrides")
    declared_manifest = payload.get("source_manifest_sha256")
    if declared_manifest is not None and declared_manifest != source_manifest_sha256:
        raise OverlayBuildError("Locator overrides target a different source manifest")
    declared_provenance = payload.get("provenance_artifact_sha256")
    if declared_provenance is not None and declared_provenance != provenance.get("artifact_sha256"):
        raise OverlayBuildError("Locator overrides target a different provenance artifact")

    result: dict[tuple[str, int], dict[str, Any]] = {}
    for row in _locator_rows(payload):
        key = _slot_key(row, ordinal_key="canonical_ordinal" if "canonical_ordinal" in row else "ordinal")
        if key in result:
            raise OverlayBuildError(f"Duplicate locator override {key}")
        base = provenance_map.get(key)
        paper = manifest_map.get(key[0])
        if base is None or paper is None:
            raise OverlayBuildError(f"Locator override references unknown slot {key}")
        if str(row.get("item_label") or "") != str(base.get("item_label") or ""):
            raise OverlayBuildError(f"{key}: locator override item label mismatch")
        source_sha = str(row.get("source_pdf_sha256") or "").casefold()
        if source_sha != str(paper.get("local_sha256") or "").casefold():
            raise OverlayBuildError(f"{key}: locator override PDF hash mismatch")
        page = row.get("source_page")
        page_count = int(paper.get("local_page_count") or 0)
        if not isinstance(page, int) or not 1 <= page <= page_count:
            raise OverlayBuildError(f"{key}: locator override page is outside the PDF")
        if row.get("review_required") is not True:
            raise OverlayBuildError(f"{key}: locator override must remain review-required")
        method = row.get("evidence_method")
        if not isinstance(method, str) or not method.strip():
            raise OverlayBuildError(f"{key}: locator override evidence method is missing")
        rendered_sha, render_spec = _rendered_locator(row)
        base_render = {
            (entry.get("page"), entry.get("sha256")): {
                key: entry.get(key) for key in ("format", "dpi", "color_mode")
            }
            for entry in base.get("rendered_page_evidence") or []
            if isinstance(entry, dict)
        }
        matching_spec = base_render.get((page, rendered_sha))
        if matching_spec is None:
            raise OverlayBuildError(
                f"{key}: provenance has not incorporated the checksum-bound locator override"
            )
        if matching_spec != render_spec:
            raise OverlayBuildError(f"{key}: locator/provenance render specification mismatch")
        result[key] = {
            "source_page": page,
            "evidence_method": method.strip(),
            "rendered_page_sha256": rendered_sha,
            "render_specification": render_spec,
        }
    return result, _input_binding(path)


def _resolve_pdf_path(record: dict[str, Any]) -> Path:
    raw = record.get("source_path")
    if not isinstance(raw, str) or not raw.strip():
        raise OverlayBuildError("Provenance record has no source_path")
    path = Path(raw)
    return path if path.is_absolute() else REPO_DIR / path


def _page_raw(source: PdfSource, page: int) -> str:
    cached = source.page_text.get(page)
    if cached is not None:
        return cached
    if not 1 <= page <= len(source.reader.pages):
        raise OverlayBuildError(f"{source.path}: page {page} is outside the PDF")
    pdf_page = source.reader.pages[page - 1]
    try:
        raw = pdf_page.extract_text(extraction_mode="layout") or ""
    except Exception:
        raw = pdf_page.extract_text() or ""
    source.page_text[page] = raw
    return raw


def _open_pdf(
    record: dict[str, Any], cache: dict[Path, PdfSource]
) -> PdfSource:
    path = _resolve_pdf_path(record)
    expected = str(record.get("source_pdf_sha256") or "").casefold()
    source = cache.get(path)
    if source is not None:
        if source.sha256 != expected:
            raise OverlayBuildError(f"Cached source PDF hash binding mismatch: {path}")
        return source
    if not path.is_file():
        raise OverlayBuildError(f"Missing source PDF {path}")
    actual = _sha256_file(path)
    if actual != expected:
        raise OverlayBuildError(f"Source PDF hash mismatch: {path}")
    source = PdfSource(path=path, sha256=actual, reader=PdfReader(path), page_text={})
    cache[path] = source
    return source


def _verify_all_source_pdfs(
    provenance_map: dict[tuple[str, int], dict[str, Any]],
    manifest_map: dict[str, dict[str, Any]],
    cache: dict[Path, PdfSource],
) -> dict[str, Any]:
    """Verify every paper's on-disk hash and page count before transcribing."""

    representative: dict[str, dict[str, Any]] = {}
    for (paper_id, _ordinal), record in provenance_map.items():
        representative.setdefault(paper_id, record)
    if set(representative) != set(manifest_map):
        raise OverlayBuildError("Cannot bind every manifest paper to a source PDF")

    verified_paths: set[Path] = set()
    for paper_id in sorted(manifest_map):
        source = _open_pdf(representative[paper_id], cache)
        expected_pages = manifest_map[paper_id].get("local_page_count")
        if len(source.reader.pages) != expected_pages:
            raise OverlayBuildError(
                f"{paper_id}: source PDF page count mismatch "
                f"({len(source.reader.pages)} != {expected_pages})"
            )
        verified_paths.add(source.path)
    return {
        "paper_count": len(representative),
        "unique_pdf_count": len(verified_paths),
        "all_hashes_verified_from_disk": True,
        "all_page_counts_verified_from_disk": True,
    }


def _extract_original_block(
    record: dict[str, Any], cache: dict[Path, PdfSource]
) -> str | None:
    boundary = record.get("boundary")
    expected_hash = record.get("text_block_sha256")
    if boundary is None or expected_hash is None:
        return None
    if not isinstance(boundary, dict) or not isinstance(expected_hash, str):
        raise OverlayBuildError("Malformed provenance block boundary")
    source = _open_pdf(record, cache)
    start_page = boundary.get("start_page")
    end_page = boundary.get("end_page")
    start_offset = boundary.get("start_offset")
    end_offset = boundary.get("end_offset")
    if not all(isinstance(value, int) for value in (start_page, end_page, start_offset, end_offset)):
        raise OverlayBuildError("Provenance block boundary must contain integer offsets")
    if start_page > end_page:
        raise OverlayBuildError("Provenance block boundary is reversed")
    chunks: list[str] = []
    page_hashes = {
        entry.get("page"): entry.get("sha256")
        for entry in record.get("page_text_sha256") or []
        if isinstance(entry, dict)
    }
    for page in range(start_page, end_page + 1):
        raw = _page_raw(source, page)
        normalized_page = _normalize_text(raw)
        if page in page_hashes and page_hashes[page] != (
            _sha256_text(normalized_page) if normalized_page else None
        ):
            raise OverlayBuildError(
                f"{record.get('source_paper_id')}/{record.get('item_label')}: page text hash mismatch"
            )
        start = start_offset if page == start_page else 0
        end = end_offset if page == end_page else len(raw)
        if start < 0 or end < start or end > len(raw):
            raise OverlayBuildError("Provenance block offsets fall outside extracted page text")
        chunk = raw[start:end]
        if page not in page_hashes and _normalize_text(chunk):
            raise OverlayBuildError(
                f"{record.get('source_paper_id')}/{record.get('item_label')}: "
                "block uses an unhashed non-empty page"
            )
        chunks.append(chunk)
    block = _normalize_text("\n".join(chunks))
    if _sha256_text(block) != expected_hash:
        raise OverlayBuildError(
            f"{record.get('source_paper_id')}/{record.get('item_label')}: original block hash mismatch"
        )
    return block


def _strip_source_marker(block: str, source_label: str) -> tuple[str, str]:
    label = re.escape(source_label)
    patterns = [
        re.compile(rf"^\s*(Question\s+Number\s*:\s*{label})(?!\d)\s*", re.I),
        re.compile(
            rf"^\s*(Q(?:uestion)?(?:\.|\s)*(?:No\.?\s*)?{label})(?!\d)\.?\s*",
            re.I,
        ),
        re.compile(rf"^\s*({label})(?!\d)\.?\s*", re.I),
    ]
    for pattern in patterns:
        match = pattern.match(block)
        if match:
            return block[match.end() :].strip(), match.group(1).strip()
    raise OverlayBuildError(f"Hash-verified block does not start with source label {source_label!r}")


def _option_matches(text: str) -> tuple[list[re.Match[str]], str | None]:
    inline = list(INLINE_OPTION_RE.finditer(text))
    line = list(LINE_OPTION_RE.finditer(text))
    candidates = [(inline, "parenthesized"), (line, "line_letter")]
    valid = [
        (matches, scheme)
        for matches, scheme in candidates
        if tuple(match.group(1).upper() for match in matches) == OPTION_IDS
    ]
    if len(valid) != 1:
        return [], None
    return valid[0]


def _parse_options(text: str) -> dict[str, Any]:
    matches, scheme = _option_matches(text)
    if not matches:
        return {"status": "unresolved", "reasons": ["explicit_A_to_D_block_not_unique"]}
    stem = text[: matches[0].start()].strip()
    if not stem:
        return {"status": "review", "reasons": ["empty_stem_before_options"]}
    options: list[dict[str, Any]] = []
    reasons: set[str] = set()
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index < 3 else len(text)
        value = text[match.end() : end].strip()
        if not value:
            reasons.add("empty_option")
        if PAGE_FOOTER_RE.search(value):
            reasons.add("page_footer_inside_option_block")
        options.append(
            {
                "identifier": OPTION_IDS[index],
                "source_identifier": match.group(1).upper(),
                "text": value,
                "text_sha256": _sha256_text(value),
            }
        )
    normalized = [_comparison_text(option["text"]) for option in options]
    if any(not value for value in normalized):
        reasons.add("option_has_no_semantic_text")
    if len(set(normalized)) != 4:
        reasons.add("duplicate_option_text")
    return {
        "status": "exact" if not reasons else "review",
        "reasons": sorted(reasons),
        "label_scheme": scheme,
        "stem": stem,
        "stem_sha256": _sha256_text(stem),
        "options": options,
    }


def _inventory_lettered_subparts(
    *,
    body: str | None,
    archive_item: dict[str, Any],
    provenance_item: dict[str, Any],
    year: int,
) -> dict[str, Any] | None:
    """Inventory legacy descriptive subparts without materializing records.

    A parent is split only in this staging inventory.  Marker detection must
    begin at ``(a)`` and continue consecutively; any other shape fails closed.
    """

    if year not in LEGACY_SUBPART_YEARS or str(
        archive_item.get("item_type") or ""
    ).casefold() != "descriptive":
        return None
    parent_label = str(archive_item.get("item_label") or "")
    parent_ordinal = int(archive_item.get("ordinal") or 0)
    base = {
        "parent_item_label": parent_label,
        "parent_canonical_ordinal": parent_ordinal,
        "inventory_role": "staging_parent_child_review_only",
    }
    if not body:
        return {
            **base,
            "status": "review" if provenance_item.get("source_pages") else "unresolved",
            "status_reason": (
                "page_located_but_subpart_text_not_recovered"
                if provenance_item.get("source_pages")
                else "descriptive_parent_locator_unresolved"
            ),
            "parent_prompt": None,
            "children": [],
        }
    matches = list(LETTERED_SUBPART_RE.finditer(body))
    if not matches:
        return {
            **base,
            "status": "exact"
            if provenance_item.get("evidence_status") == "exact_text_block"
            else "review",
            "status_reason": "no_lettered_subparts_detected",
            "parent_prompt": body,
            "parent_prompt_sha256": _sha256_text(body),
            "children": [],
        }
    labels = [next(group for group in match.groups() if group).casefold() for match in matches]
    expected = [chr(ord("a") + index) for index in range(len(labels))]
    if labels != expected:
        return {
            **base,
            "status": "review",
            "status_reason": "lettered_subparts_not_consecutive_from_a",
            "observed_labels": labels,
            "parent_prompt": body[: matches[0].start()].strip() or None,
            "children": [],
        }
    parent_prompt = body[: matches[0].start()].strip()
    children: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        child_text = body[match.end() : end].strip()
        child_flags: list[str] = ["independent_gradability_review_required"]
        if not child_text:
            child_flags.append("empty_subpart_text")
        if BROKEN_GLYPH_RE.search(child_text):
            child_flags.append("formula_or_private_glyph_review_required")
        if VISUAL_REFERENCE_RE.search(child_text):
            child_flags.append("figure_or_table_review_required")
        child_label = labels[index]
        children.append(
            {
                "source_subpart_label": f"{parent_label}({child_label})",
                "source_marker": child_label,
                "parent_item_label": parent_label,
                "parent_canonical_ordinal": parent_ordinal,
                "independently_answerable_status": "review",
                "text": child_text,
                "text_sha256": _sha256_text(child_text),
                "status": "review" if child_flags else "exact",
                "review_flags": sorted(child_flags),
            }
        )
    # A letter marker alone cannot prove that the source intended an
    # independently gradable database record.  Keep every detected child under
    # review until a human reconciles the paper's grading structure.
    review_required = True
    return {
        **base,
        "status": "review" if review_required else "exact",
        "status_reason": (
            "lettered_subparts_require_gradability_and_visual_review"
            if review_required
            else "hash_verified_consecutive_lettered_subparts"
        ),
        "parent_prompt": parent_prompt or None,
        "parent_prompt_sha256": _sha256_text(parent_prompt) if parent_prompt else None,
        "children": children,
    }


def _candidate_cross_checks(candidate_row: dict[str, Any], original_text: str) -> list[dict[str, Any]]:
    candidate = candidate_row.get("candidate") or {}
    candidate_text = candidate.get("question_text")
    if not isinstance(candidate_text, str) or not candidate_text.strip():
        return []
    source = str(candidate.get("question_source") or "")
    if source not in {"gateoverflow_exact_label_join", "examside_exact_normalized_join"}:
        return []
    original_comparison = _comparison_text(original_text)
    candidate_comparison = _comparison_text(candidate_text)
    ratio = SequenceMatcher(None, original_comparison, candidate_comparison).ratio()
    return [
        {
            "source": "gateoverflow" if source.startswith("gateoverflow") else "examside",
            "role": "secondary_cross_check_only",
            "candidate_text_sha256": _sha256_text(candidate_text),
            "normalized_similarity": round(ratio, 6),
            "agreement": "strong" if ratio >= 0.85 else "partial" if ratio >= 0.6 else "weak",
        }
    ]


def _has_objective_gap(item: dict[str, Any]) -> bool:
    return str(item.get("item_type") or "").casefold() in OBJECTIVE_TYPES and not bool(
        item.get("options")
    )


def _transcription_review_flags(
    *,
    body: str,
    candidate_row: dict[str, Any],
    archive_item: dict[str, Any],
    option_parse: dict[str, Any] | None,
) -> list[str]:
    flags: set[str] = set()
    if BROKEN_GLYPH_RE.search(body):
        flags.add("formula_or_private_glyph_review_required")
    if VISUAL_REFERENCE_RE.search(body):
        flags.add("figure_or_table_review_required")
    if PAGE_FOOTER_RE.search(body):
        flags.add("page_layout_text_present")
    if len(_comparison_text(body)) < 12:
        flags.add("extracted_text_too_short")
    source_flags = list(archive_item.get("review_flags") or []) + list(
        candidate_row.get("candidate_review_reasons") or []
    )
    if any(
        token in str(flag).casefold()
        for flag in source_flags
        for token in ("visual_dependency", "private_use", "incomplete", "unextracted")
    ):
        flags.add("upstream_visual_or_missing_content_signal")
    if option_parse and option_parse.get("status") != "exact":
        flags.update(f"option_parse:{reason}" for reason in option_parse.get("reasons") or [])
    return sorted(flags)


def _status_for_item(
    *,
    archive_item: dict[str, Any],
    provenance_item: dict[str, Any],
    proposed: dict[str, Any],
    review_flags: Iterable[str],
) -> tuple[str, str]:
    stem_gap = not bool(archive_item.get("question_md"))
    option_gap = _has_objective_gap(archive_item)
    has_gap = stem_gap or option_gap
    if not has_gap:
        if archive_item.get("transcription_status") == "verified":
            return "exact", "canonical_slot_already_complete"
        return "review", "existing_canonical_transcription_requires_review"
    if not proposed:
        if provenance_item.get("source_pages"):
            return "review", "source_page_located_but_no_safe_transcription"
        return "unresolved", "original_source_locator_missing"
    if provenance_item.get("evidence_status") != "exact_text_block":
        return "review", "original_source_requires_rendered_page_review"
    if list(review_flags):
        return "review", "source_text_contains_visual_or_layout_risk"
    if stem_gap and not proposed.get("question_text"):
        return "review", "question_stem_not_safely_recovered"
    if option_gap and not proposed.get("options"):
        return "review", "objective_options_not_safely_recovered"
    return "exact", "hash_verified_original_pdf_transcription"


def _ensure_safe_output(value: Any, path: str = "root") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_OUTPUT_KEYS:
                raise OverlayBuildError(f"Forbidden output field {path}.{key}")
            _ensure_safe_output(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _ensure_safe_output(child, f"{path}[{index}]")


def build_overlay(
    *,
    archive_path: Path = DEFAULT_ARCHIVE,
    candidates_path: Path = DEFAULT_CANDIDATES,
    provenance_path: Path = DEFAULT_PROVENANCE,
    manifest_path: Path = DEFAULT_MANIFEST,
    locator_overrides_path: Path | None = None,
    verify_source_files: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    archive = _read_json(archive_path)
    candidates = _read_json(candidates_path)
    provenance = _read_json(provenance_path)
    manifest = _read_json(manifest_path)
    if not all(isinstance(value, dict) for value in (archive, candidates, provenance, manifest)):
        raise OverlayBuildError("All staging inputs must be JSON objects")
    archive_map, candidate_map, provenance_map, manifest_map = _validate_inputs(
        archive, candidates, provenance, manifest, manifest_path=manifest_path
    )
    overrides, override_binding = _load_locator_overrides(
        locator_overrides_path,
        provenance=provenance,
        provenance_map=provenance_map,
        manifest_map=manifest_map,
        source_manifest_sha256=_sha256_file(manifest_path),
    )
    input_bindings = {
        "canonical_archive": _input_binding(archive_path),
        "canonical_candidates": _input_binding(candidates_path),
        "original_pdf_provenance": _input_binding(provenance_path),
        "source_manifest": _input_binding(manifest_path),
        "locator_overrides": override_binding,
    }

    pdf_cache: dict[Path, PdfSource] = {}
    source_file_verification = (
        _verify_all_source_pdfs(provenance_map, manifest_map, pdf_cache)
        if verify_source_files
        else {
            "paper_count": 0,
            "unique_pdf_count": 0,
            "all_hashes_verified_from_disk": False,
            "all_page_counts_verified_from_disk": False,
            "test_fixture_bypass": True,
        }
    )
    items: list[dict[str, Any]] = []
    for key in sorted(archive_map):
        archive_item = archive_map[key]
        candidate_row = candidate_map[key]
        provenance_item = provenance_map[key]
        paper_year = int(manifest_map[key[0]].get("year") or 0)
        block = _extract_original_block(provenance_item, pdf_cache)
        proposed: dict[str, Any] = {}
        review_flags = list(provenance_item.get("review_flags") or [])
        option_parse: dict[str, Any] | None = None
        cross_checks: list[dict[str, Any]] = []
        marker_text = None
        body = ""
        if block is not None:
            body, marker_text = _strip_source_marker(
                block, str(provenance_item.get("source_label") or "")
            )
            option_parse = _parse_options(body)
            stem_gap = not bool(archive_item.get("question_md"))
            option_gap = _has_objective_gap(archive_item)
            if stem_gap:
                proposed_text = (
                    option_parse.get("stem")
                    if option_parse.get("status") in {"exact", "review"}
                    else body
                )
                if isinstance(proposed_text, str) and proposed_text.strip():
                    proposed["question_text"] = proposed_text.strip()
                    proposed["question_text_sha256"] = _sha256_text(proposed_text.strip())
            if option_gap and option_parse.get("status") == "exact":
                proposed["options"] = option_parse["options"]
                proposed["options_sha256"] = _canonical_json_sha256(option_parse["options"])
            review_flags.extend(
                _transcription_review_flags(
                    body=body,
                    candidate_row=candidate_row,
                    archive_item=archive_item,
                    option_parse=option_parse if option_gap else None,
                )
            )
            cross_checks = _candidate_cross_checks(candidate_row, body)
            if cross_checks and cross_checks[0]["agreement"] == "weak":
                review_flags.append("secondary_cross_check_weak_agreement")

        subpart_inventory = _inventory_lettered_subparts(
            body=body or None,
            archive_item=archive_item,
            provenance_item=provenance_item,
            year=paper_year,
        )

        review_flags = sorted(set(review_flags))
        status, status_reason = _status_for_item(
            archive_item=archive_item,
            provenance_item=provenance_item,
            proposed=proposed,
            review_flags=review_flags,
        )
        locator_override = overrides.get(key)
        evidence = {
            "source_pdf_sha256": provenance_item.get("source_pdf_sha256"),
            "source_pages": list(provenance_item.get("source_pages") or []),
            "source_label": provenance_item.get("source_label"),
            "matched_marker": marker_text,
            "boundary": provenance_item.get("boundary"),
            "text_block_sha256": provenance_item.get("text_block_sha256"),
            "page_text_sha256": provenance_item.get("page_text_sha256") or [],
            "rendered_page_evidence": provenance_item.get("rendered_page_evidence") or [],
            "evidence_status": provenance_item.get("evidence_status"),
            "locator_status": provenance_item.get("locator_status"),
            "locator_override": locator_override,
        }
        item = {
            "source_paper_id": key[0],
            "canonical_ordinal": key[1],
            "item_label": archive_item.get("item_label"),
            "status": status,
            "status_reason": status_reason,
            "gap_before": {
                "question_stem_missing": not bool(archive_item.get("question_md")),
                "objective_options_missing": _has_objective_gap(archive_item),
            },
            "proposed_overlay": proposed or None,
            "legacy_subpart_inventory": subpart_inventory,
            "original_source_evidence": evidence,
            "secondary_cross_checks": cross_checks,
            "review_flags": review_flags,
        }
        items.append(item)

    status_counts = Counter(item["status"] for item in items)
    if set(status_counts) - STATUSES or len(items) != EXPECTED_SLOTS:
        raise OverlayBuildError("Overlay did not assign exactly one safe status to every slot")
    paper_ids = {item["source_paper_id"] for item in items}
    if len(paper_ids) != EXPECTED_PAPERS:
        raise OverlayBuildError("Overlay does not cover exactly 39 papers")

    artifact_core = {
        "schema_version": SCHEMA_VERSION,
        "source_role": "staging_original_pdf_transcription_review_overlay_only",
        "database_writes_performed": False,
        "production_import_authorized": False,
        "automatic_promotion_allowed": False,
        "canonical_identity": {"paper_count": EXPECTED_PAPERS, "slot_count": EXPECTED_SLOTS},
        "input_bindings": input_bindings,
        "source_file_verification": source_file_verification,
        "status_vocabulary": sorted(STATUSES),
        "items": items,
    }
    _ensure_safe_output(artifact_core)
    artifact_sha256 = _canonical_json_sha256(artifact_core)
    artifact = {**artifact_core, "artifact_sha256": artifact_sha256}

    paper_counts: dict[str, Counter[str]] = defaultdict(Counter)
    legacy_subparts: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "compound_parent_count": 0,
            "lettered_subpart_count": 0,
            "subpart_inventory_review_count": 0,
            "subpart_inventory_unresolved_count": 0,
        }
    )
    for item in items:
        counts = paper_counts[item["source_paper_id"]]
        counts[item["status"]] += 1
        counts["stem_missing_before"] += int(item["gap_before"]["question_stem_missing"])
        counts["objective_options_missing_before"] += int(
            item["gap_before"]["objective_options_missing"]
        )
        proposed = item.get("proposed_overlay") or {}
        counts["stem_candidates"] += int(bool(proposed.get("question_text")))
        counts["option_candidates"] += int(bool(proposed.get("options")))
        counts["exact_stem_candidates"] += int(
            item["status"] == "exact" and bool(proposed.get("question_text"))
        )
        counts["exact_option_candidates"] += int(
            item["status"] == "exact" and bool(proposed.get("options"))
        )
        inventory = item.get("legacy_subpart_inventory")
        if isinstance(inventory, dict):
            children = inventory.get("children") or []
            legacy = legacy_subparts[item["source_paper_id"]]
            legacy["compound_parent_count"] += int(bool(children))
            legacy["lettered_subpart_count"] += len(children)
            legacy["subpart_inventory_review_count"] += int(
                inventory.get("status") == "review"
            )
            legacy["subpart_inventory_unresolved_count"] += int(
                inventory.get("status") == "unresolved"
            )
    before_stems = sum(item["gap_before"]["question_stem_missing"] for item in items)
    before_options = sum(item["gap_before"]["objective_options_missing"] for item in items)
    exact_stems = sum(
        item["status"] == "exact"
        and bool((item.get("proposed_overlay") or {}).get("question_text"))
        for item in items
    )
    exact_options = sum(
        item["status"] == "exact"
        and bool((item.get("proposed_overlay") or {}).get("options"))
        for item in items
    )
    all_stems = sum(bool((item.get("proposed_overlay") or {}).get("question_text")) for item in items)
    all_options = sum(bool((item.get("proposed_overlay") or {}).get("options")) for item in items)
    unresolved_papers = sorted(
        paper_id for paper_id, counts in paper_counts.items() if counts["unresolved"]
    )
    canonical_counts = Counter(item["source_paper_id"] for item in items)
    legacy_paper_inventory = []
    for year in sorted(LEGACY_SUBPART_YEARS):
        paper_id = f"gate-cs-{year}"
        if paper_id not in manifest_map:
            continue
        counts = legacy_subparts[paper_id]
        provisional_split_count = (
            canonical_counts[paper_id]
            - counts["compound_parent_count"]
            + counts["lettered_subpart_count"]
        )
        manifest_declared_split_count = manifest_map[paper_id].get(
            "split_database_record_count"
        )
        inventory_closed = (
            counts["subpart_inventory_unresolved_count"] == 0
            and counts["subpart_inventory_review_count"] == 0
        )
        count_matches_manifest = (
            manifest_declared_split_count is None
            or provisional_split_count == manifest_declared_split_count
        )
        closed = inventory_closed and count_matches_manifest
        legacy_paper_inventory.append(
            {
                "paper_id": paper_id,
                "canonical_slot_count": canonical_counts[paper_id],
                **counts,
                "detected_lettered_part_expansion_count": provisional_split_count,
                "provisional_split_database_record_count": provisional_split_count,
                "manifest_declared_split_database_record_count": manifest_declared_split_count,
                "manifest_count_comparison": (
                    "not_declared"
                    if manifest_declared_split_count is None
                    else "match"
                    if count_matches_manifest
                    else "mismatch_requires_review"
                ),
                "split_database_record_count": provisional_split_count if closed else None,
                "count_status": (
                    "exact"
                    if closed
                    else "unresolved"
                    if counts["subpart_inventory_unresolved_count"]
                    else "review"
                ),
                "count_status_reason": (
                    "all_children_hash_verified_and_gradability_confirmed"
                    if closed
                    else "source_parent_locator_unresolved"
                    if counts["subpart_inventory_unresolved_count"]
                    else "independent_gradability_or_manifest_count_requires_review"
                ),
            }
        )
    report = {
        "schema_version": SCHEMA_VERSION,
        "artifact_sha256": artifact_sha256,
        "paper_count": len(paper_ids),
        "slot_count": len(items),
        "status_counts": dict(sorted(status_counts.items())),
        "coverage": {
            "missing_question_stems_before": before_stems,
            "exact_question_stems_added": exact_stems,
            "review_question_stem_candidates": all_stems - exact_stems,
            "missing_question_stems_after_exact_overlay": before_stems - exact_stems,
            "missing_question_stems_after_including_review_candidates": before_stems - all_stems,
            "missing_objective_option_sets_before": before_options,
            "exact_objective_option_sets_added": exact_options,
            "review_objective_option_candidates": all_options - exact_options,
            "missing_objective_option_sets_after_exact_overlay": before_options - exact_options,
            "missing_objective_option_sets_after_including_review_candidates": before_options - all_options,
        },
        "locator_override_count": len(overrides),
        "source_file_verification": source_file_verification,
        "unresolved_papers": unresolved_papers,
        "legacy_parent_child_inventory": legacy_paper_inventory,
        "papers": [
            {"paper_id": paper_id, **dict(sorted(counts.items()))}
            for paper_id, counts in sorted(paper_counts.items())
        ],
        "visual_review_queue": [
            {
                "source_paper_id": item["source_paper_id"],
                "canonical_ordinal": item["canonical_ordinal"],
                "item_label": item["item_label"],
                "source_pages": item["original_source_evidence"]["source_pages"],
                "rendered_page_evidence": item["original_source_evidence"][
                    "rendered_page_evidence"
                ],
                "review_flags": item["review_flags"],
            }
            for item in items
            if item["status"] == "review"
            and item["original_source_evidence"]["rendered_page_evidence"]
        ][:24],
        "invariants": {
            "paper_count_is_39": len(paper_ids) == EXPECTED_PAPERS,
            "slot_count_is_2712": len(items) == EXPECTED_SLOTS,
            "unique_slot_identity": len(
                {(item["source_paper_id"], item["canonical_ordinal"]) for item in items}
            )
            == EXPECTED_SLOTS,
            "all_slots_have_closed_status": all(item["status"] in STATUSES for item in items),
            "all_outputs_staging_only": artifact["database_writes_performed"] is False
            and artifact["production_import_authorized"] is False
            and artifact["automatic_promotion_allowed"] is False,
            "no_forbidden_materialization_fields": True,
            "all_source_hashes_bound": all(
                HASH_RE.fullmatch(str(item["original_source_evidence"]["source_pdf_sha256"]))
                for item in items
            ),
            "unresolved_items_have_no_proposed_overlay": all(
                item["status"] != "unresolved" or item["proposed_overlay"] is None
                for item in items
            ),
            "all_legacy_subparts_name_their_parent": all(
                child.get("parent_item_label") == inventory.get("parent_item_label")
                and child.get("parent_canonical_ordinal")
                == inventory.get("parent_canonical_ordinal")
                for item in items
                for inventory in [item.get("legacy_subpart_inventory")]
                if isinstance(inventory, dict)
                for child in inventory.get("children") or []
            ),
        },
    }
    if not all(report["invariants"].values()):
        raise OverlayBuildError(f"Overlay invariants failed: {report['invariants']}")
    return artifact, report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--provenance", type=Path, default=DEFAULT_PROVENANCE)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--locator-overrides",
        type=Path,
        default=DEFAULT_LOCATOR_OVERRIDES if DEFAULT_LOCATOR_OVERRIDES.is_file() else None,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    artifact, report = build_overlay(
        archive_path=args.archive,
        candidates_path=args.candidates,
        provenance_path=args.provenance,
        manifest_path=args.manifest,
        locator_overrides_path=args.locator_overrides,
    )
    _write_json(args.output, artifact)
    report_path = args.output.with_suffix(".report.json")
    _write_json(report_path, report)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "report": str(report_path),
                "artifact_sha256": artifact["artifact_sha256"],
                "status_counts": report["status_counts"],
                "coverage": report["coverage"],
                "unresolved_papers": report["unresolved_papers"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
