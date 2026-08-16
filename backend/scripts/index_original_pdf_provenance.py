"""Build a review-first, per-item provenance index for original GATE PDFs.

The index is deliberately independent from database import/materialization.  It
reads the reviewed 39-paper source manifest and canonical slot builder, then
records where each canonical item can be found in the locally verified question
paper.  Text is used only to establish conservative block boundaries and is
never copied into the output.  Image-only or weakly extractable papers receive
rendered-page hashes and an explicit manual-review state.

Default outputs live below ``tmp/pyq/build`` (git-ignored).  Running this script
never opens a database and never changes ``practice_eligible``.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Sequence

from pypdf import PdfReader


REPO_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_DIR / "backend"
DEFAULT_MANIFEST = BACKEND_DIR / "data" / "pyq_source_manifest.json"
DEFAULT_CONSOLIDATED = BACKEND_DIR / "data" / "pyq_consolidated.json"
DEFAULT_BOOKLET_OCCURRENCES = (
    BACKEND_DIR / "data" / "gate_cs_2013_booklet_occurrences.json"
)
DEFAULT_LOCATOR_OVERRIDES = (
    BACKEND_DIR / "data" / "pyq_original_locator_overrides.json"
)
DEFAULT_OUTPUT = REPO_DIR / "tmp" / "pyq" / "build" / "original_pdf_provenance.json"
SCHEMA_VERSION = "1.0"
LOCATOR_OVERRIDE_SCHEMA_VERSION = "1.0"
EXPECTED_PAPERS = 39
EXPECTED_ITEMS = 2712
RENDER_DPI = 144

# These two earlier page-locator runs are reusable because their OCR input is
# byte-for-byte identical to the current manifested paper.  Only page integers
# and the reviewed extraction-method label are consumed; no third-party text,
# answers, or explanations are copied.
REVIEWED_OCR_LOCATOR_SOURCE_SHA256 = {
    "CS-2019": "aa80100a9136a07aaba70b48a9e86b23246e53f2f5fc80760784d8ce3b8994cd",
    "CS2-2021": "413f505a27b48dba60863120740aaa231ac39909b267938f75d24fee9f8af3ea",
}


class ProvenanceIndexError(ValueError):
    """Raised when a source identity or index invariant is unsafe."""


@dataclass(frozen=True, slots=True)
class PageText:
    page: int
    raw: str
    normalized: str
    normalized_sha256: str | None


@dataclass(frozen=True, slots=True)
class Marker:
    target_index: int
    source_label: str
    page: int
    start: int
    end: int
    matched_text: str


@dataclass(frozen=True, slots=True)
class Target:
    canonical_ordinal: int
    item_label: str
    source_label: str


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "")
    value = value.replace("\u00ad", "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [" ".join(line.split()) for line in value.split("\n")]
    return "\n".join(line for line in lines if line).strip()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProvenanceIndexError(f"Cannot read JSON source {path}: {exc}") from exc


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _load_builder():
    path = Path(__file__).with_name("build_canonical_pyq_archive.py")
    spec = importlib.util.spec_from_file_location("canonical_pyq_builder_for_provenance", path)
    if spec is None or spec.loader is None:
        raise ProvenanceIndexError(f"Cannot import canonical builder from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _parse_page_range(raw: Any, page_count: int) -> tuple[int, int] | None:
    if raw in (None, ""):
        return None
    match = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", str(raw))
    if not match:
        raise ProvenanceIndexError(f"Invalid manifest source_page_range {raw!r}")
    start, end = map(int, match.groups())
    if start < 1 or end < start or end > page_count:
        raise ProvenanceIndexError(
            f"Manifest source_page_range {raw!r} falls outside 1..{page_count}"
        )
    return start, end


def _extract_pages(reader: PdfReader) -> list[PageText]:
    pages: list[PageText] = []
    for page_number, page in enumerate(reader.pages, start=1):
        try:
            raw = page.extract_text(extraction_mode="layout") or ""
        except Exception:  # pypdf can fail on a malformed form XObject.
            raw = page.extract_text() or ""
        normalized = _normalize_text(raw)
        pages.append(
            PageText(
                page=page_number,
                raw=raw,
                normalized=normalized,
                normalized_sha256=_sha256_text(normalized) if normalized else None,
            )
        )
    return pages


_ANSWER_KEY_PAGE = re.compile(
    r"(?:Answer\s*Keys?|AnswerKey|Q\.\s*No\s+Type\s+Section\s+Key\s+Marks)",
    re.IGNORECASE,
)


def _question_page_range(
    paper: dict[str, Any],
    page_texts: Sequence[PageText],
    declared_range: tuple[int, int],
    *,
    booklet_a_range: tuple[int, int],
) -> tuple[tuple[int, int], str]:
    paper_id = str(paper["id"])
    if paper_id == "gate-cs-2013":
        return booklet_a_range, "verified_2013_booklet_A_range"
    # The supplied 2016 compilation is two papers followed by each paper's key.
    # These boundaries are also independently detectable from the Set-5/Set-6
    # headers and the answer-table headers on pages 21 and 44.
    if paper_id == "gate-cs-2016-session-1":
        return (1, 20), "detected_session_header_and_answer_key_boundary"
    if paper_id == "gate-cs-2016-session-2":
        return (23, 43), "detected_session_header_and_answer_key_boundary"
    if paper_id == "gate-cs-2021-session-1":
        return (1, 40), "manifest_note_40_question_pages_then_keys"
    if paper_id == "gate-cs-2004":
        return (1, 19), "rendered_answer_grid_is_page_20"

    start, end = declared_range
    for page in page_texts[start - 1 : end]:
        if page.page == start:
            continue
        if _ANSWER_KEY_PAGE.search(page.normalized):
            return (start, page.page - 1), "embedded_answer_key_heading"
    return declared_range, "manifest_or_full_pdf_range"


def _source_targets(paper: dict[str, Any], canonical_items: Sequence[dict[str, Any]]) -> list[Target]:
    year = int(paper["year"])
    targets: list[Target] = []
    for item in canonical_items:
        ordinal = int(item["ordinal"])
        label = str(item["item_label"])
        if year == 2017:
            # The source export prints CS 1..55 first and GA 56..65.  Canonical
            # archive order is GA first; never infer this from position.
            source_ordinal = ordinal - 10 if ordinal >= 11 else ordinal + 55
            source_label = str(source_ordinal)
        elif year == 2015 or year >= 2022:
            # Recent official master papers use one global Q.1..Q.65 sequence
            # even though the canonical archive names the technical part CS-1..55.
            source_label = str(ordinal)
        elif year >= 2014:
            source_label = label.split("-", 1)[1]
        else:
            source_label = label
        targets.append(Target(ordinal, label, source_label))
    if year == 2017:
        # Canonical order and printed order differ in 2017.  Boundary detection
        # must follow the printed 1..65 sequence, then records are sorted back by
        # canonical ordinal at serialization time.
        targets.sort(key=lambda target: int(target.source_label))
    return targets


def _marker_pattern(source_label: str, *, year: int) -> re.Pattern[str]:
    if re.fullmatch(r"\d+\.\d+", source_label):
        escaped = re.escape(source_label)
        return re.compile(rf"(?m)^[ \t]*(?P<label>{escaped})(?!\d)[ \t]+")
    if re.fullmatch(r"\d+[ab]", source_label):
        number, part = source_label[:-1], source_label[-1]
        # Original 2005 scans use both 81(a) and 81 (a); OCR can insert dots.
        return re.compile(
            rf"(?im)^[ \t]*(?P<label>{number}[ \t.]*\([ \t]*{part}[ \t]*\))(?=\s|$)"
        )
    if not source_label.isdigit():
        raise ProvenanceIndexError(f"Unsupported source label {source_label!r}")
    number = int(source_label)
    if year in {2015, 2017}:
        return re.compile(
            rf"(?im)^[ \t]*(?P<label>Question[ \t]+Number[ \t]*:[ \t]*{number})(?!\d)"
        )
    if year >= 2014:
        return re.compile(
            rf"(?im)^[ \t]*(?P<label>Q(?:uestion)?(?:\.|[ \t])*"
            rf"(?:No\.?[ \t]*)?{number})(?!\d)"
        )
    return re.compile(
        rf"(?im)^[ \t]*(?P<label>(?:Q\.[ \t]*{number}(?!\d)|"
        rf"(?:Q[ \t]*)?{number}[ \t]*\.))(?!\d)"
    )


_RANGE_AFTER_MARKER = re.compile(
    r"^[ \t]*(?:[-–—]|to\b)[ \t]*(?:Q\.?[ \t]*)?\d+", re.IGNORECASE
)
_INSTRUCTION_AFTER_MARKER = re.compile(
    r"^[ \t]*(?:Do not|Take out|On the|This Question|There are|Since|Questions?[ \t]+Q|"
    r"Unattempted|Calculator|Rough work|Before the start|Mobile phones?)",
    re.IGNORECASE,
)


def _candidate_markers(
    pages: Sequence[PageText],
    targets: Sequence[Target],
    *,
    year: int,
    page_range: tuple[int, int],
) -> dict[int, list[Marker]]:
    start_page, end_page = page_range
    result: dict[int, list[Marker]] = defaultdict(list)
    for target_index, target in enumerate(targets):
        pattern = _marker_pattern(target.source_label, year=year)
        for page in pages[start_page - 1 : end_page]:
            for match in pattern.finditer(page.raw):
                tail = page.raw[match.end() : match.end() + 32]
                # Instruction headings such as "Q.1 - Q.5 carry..." are not
                # question boundaries.
                if _RANGE_AFTER_MARKER.match(tail):
                    continue
                if _INSTRUCTION_AFTER_MARKER.match(page.raw[match.end() : match.end() + 120]):
                    continue
                result[target_index].append(
                    Marker(
                        target_index=target_index,
                        source_label=target.source_label,
                        page=page.page,
                        start=match.start("label"),
                        end=match.end("label"),
                        matched_text=match.group("label"),
                    )
                )
    return result


def _marker_position(marker: Marker) -> tuple[int, int]:
    return marker.page, marker.start


def _select_monotonic_markers(
    candidates: dict[int, list[Marker]], targets: Sequence[Target]
) -> tuple[dict[int, Marker], set[int]]:
    """Choose only uniquely forced monotonic boundaries.

    A forward/backward pass finds candidates that can participate in a complete
    monotonic sequence.  We select an item only when exactly one candidate is
    possible between its nearest selected neighbours.  Missing or genuinely
    ambiguous labels stay explicit; we never repair them by positional guessing.
    """

    selected: dict[int, Marker] = {}
    ambiguous: set[int] = set()
    segments: list[tuple[int, int]] = []
    segment_start = 0
    for index in range(1, len(targets)):
        previous_label = targets[index - 1].source_label
        current_label = targets[index].source_label
        if previous_label.isdigit() and current_label.isdigit() and int(current_label) <= int(previous_label):
            segments.append((segment_start, index))
            segment_start = index
    segments.append((segment_start, len(targets)))

    previous: tuple[int, int] = (0, -1)
    for segment_start, segment_end in segments:
        for index in range(segment_start, segment_end):
            possible = [
                marker
                for marker in candidates.get(index, [])
                if _marker_position(marker) > previous
            ]
            if len(possible) == 1:
                selected[index] = possible[0]
                previous = _marker_position(possible[0])
            elif len(possible) > 1:
                # Only labels in the current printed section constrain this
                # choice.  A later section may legitimately restart at Q.1.
                next_positions = [
                    _marker_position(marker)
                    for next_index in range(index + 1, segment_end)
                    for marker in candidates.get(next_index, [])
                    if _marker_position(marker) > previous
                ]
                if next_positions:
                    upper = min(next_positions)
                    bounded = [m for m in possible if _marker_position(m) < upper]
                elif segment_end < len(targets):
                    # The next printed section restarts its numbering.  With a
                    # complete 1..N run already established, the earliest
                    # remaining N is the final item of this section.
                    bounded = [min(possible, key=_marker_position)]
                else:
                    bounded = possible
                if len(bounded) == 1:
                    selected[index] = bounded[0]
                    previous = _marker_position(bounded[0])
                else:
                    ambiguous.add(index)
    return selected, ambiguous


def _block_for_marker(
    marker: Marker,
    next_marker: Marker | None,
    pages_by_number: dict[int, PageText],
    paper_end_page: int,
) -> tuple[str, list[int], dict[str, int]]:
    end_page = next_marker.page if next_marker else paper_end_page
    chunks: list[str] = []
    touched_pages: list[int] = []
    for page_number in range(marker.page, end_page + 1):
        page = pages_by_number[page_number]
        start = marker.start if page_number == marker.page else 0
        end = (
            next_marker.start
            if next_marker is not None and page_number == next_marker.page
            else len(page.raw)
        )
        if end < start:
            raise ProvenanceIndexError("Question block boundary is reversed")
        chunk = page.raw[start:end]
        if _normalize_text(chunk):
            touched_pages.append(page_number)
            chunks.append(chunk)
    normalized = _normalize_text("\n".join(chunks))
    return (
        normalized,
        touched_pages or [marker.page],
        {
            "start_page": marker.page,
            "start_offset": marker.start,
            "end_page": end_page,
            "end_offset": next_marker.start if next_marker else len(pages_by_number[end_page].raw),
        },
    )


def _paper_text_grade(
    page_texts: Sequence[PageText], block_lengths: Sequence[int], page_range: tuple[int, int]
) -> str:
    selected_pages = page_texts[page_range[0] - 1 : page_range[1]]
    embedded_pages = sum(len(page.normalized) >= 40 for page in selected_pages)
    if embedded_pages == 0:
        return "image_only"
    if embedded_pages < max(1, len(selected_pages) * 3 // 4):
        return "weak"
    if not block_lengths or median(block_lengths) < 80:
        return "weak"
    return "text_bearing"


def _find_pdftoppm(explicit: str | None = None) -> str:
    if explicit:
        return explicit
    found = shutil.which("pdftoppm.exe") or shutil.which("pdftoppm") or shutil.which("pdftoppm.cmd")
    if not found:
        raise ProvenanceIndexError(
            "pdftoppm is required to hash rendered evidence for weak/image-only PDFs"
        )
    found_path = Path(found).resolve()
    if found_path.suffix.casefold() == ".cmd":
        for ancestor in found_path.parents:
            if ancestor.name.casefold() != "dependencies":
                continue
            bundled_exe = (
                ancestor
                / "native"
                / "poppler"
                / "Library"
                / "bin"
                / "pdftoppm.exe"
            )
            if bundled_exe.is_file():
                return str(bundled_exe)
    return str(found_path)


class RenderHashCache:
    def __init__(self, pdftoppm: str, dpi: int = RENDER_DPI) -> None:
        self.pdftoppm = pdftoppm
        self.dpi = dpi
        self._cache: dict[tuple[Path, int], str] = {}

    def page_sha256(self, source: Path, page: int) -> str:
        key = (source.resolve(), page)
        cached = self._cache.get(key)
        if cached:
            return cached
        with tempfile.TemporaryDirectory(prefix="gate-pyq-render-") as tmp:
            prefix = Path(tmp) / "page"
            command = [
                self.pdftoppm,
                "-f",
                str(page),
                "-l",
                str(page),
                "-r",
                str(self.dpi),
                "-gray",
                "-singlefile",
                str(source),
                str(prefix),
            ]
            completed = subprocess.run(
                command,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if completed.returncode != 0:
                detail = completed.stderr.decode("utf-8", errors="replace").strip()
                raise ProvenanceIndexError(
                    f"pdftoppm failed for {source} page {page}: {detail}"
                )
            rendered = prefix.with_suffix(".pgm")
            if not rendered.is_file():
                raise ProvenanceIndexError(
                    f"pdftoppm did not create rendered evidence for {source} page {page}"
                )
            digest = _sha256_bytes(rendered.read_bytes())
        self._cache[key] = digest
        return digest


def _render_evidence(
    cache: RenderHashCache,
    source: Path,
    pages: Iterable[int],
) -> list[dict[str, Any]]:
    return [
        {
            "page": page,
            "sha256": cache.page_sha256(source, page),
            "format": "pgm",
            "dpi": cache.dpi,
            "color_mode": "gray",
        }
        for page in sorted(set(pages))
    ]


def _build_text_records(
    paper: dict[str, Any],
    canonical_items: Sequence[dict[str, Any]],
    page_texts: Sequence[PageText],
    page_range: tuple[int, int],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    targets = _source_targets(paper, canonical_items)
    candidates = _candidate_markers(
        page_texts,
        targets,
        year=int(paper["year"]),
        page_range=page_range,
    )
    selected, ambiguous = _select_monotonic_markers(candidates, targets)
    pages_by_number = {page.page: page for page in page_texts}
    draft: list[dict[str, Any]] = []
    block_lengths: list[int] = []
    for index, target in enumerate(targets):
        marker = selected.get(index)
        if marker is None:
            status = "ambiguous_marker" if index in ambiguous else "unmatched_marker"
            draft.append(
                {
                    "source_paper_id": paper["id"],
                    "canonical_ordinal": target.canonical_ordinal,
                    "item_label": target.item_label,
                    "source_label": target.source_label,
                    "source_pages": [],
                    "boundary": None,
                    "text_block_sha256": None,
                    "normalized_character_count": 0,
                    "locator_status": status,
                }
            )
            continue
        immediate_next = selected.get(index + 1)
        boundary_exact = immediate_next is not None or index == len(targets) - 1
        if boundary_exact:
            normalized, touched_pages, boundary = _block_for_marker(
                marker,
                immediate_next,
                pages_by_number,
                page_range[1],
            )
        else:
            page = pages_by_number[marker.page]
            normalized = _normalize_text(page.raw[marker.start :])
            touched_pages = [marker.page]
            boundary = {
                "start_page": marker.page,
                "start_offset": marker.start,
                "end_page": marker.page,
                "end_offset": len(page.raw),
            }
        block_lengths.append(len(normalized))
        draft.append(
            {
                "source_paper_id": paper["id"],
                "canonical_ordinal": target.canonical_ordinal,
                "item_label": target.item_label,
                "source_label": target.source_label,
                "source_pages": touched_pages,
                "boundary": boundary,
                "text_block_sha256": _sha256_text(normalized) if normalized else None,
                "normalized_character_count": len(normalized),
                "locator_status": "marker_located",
                "boundary_status": "exact" if boundary_exact else "next_marker_missing",
            }
        )
    grade = _paper_text_grade(page_texts, block_lengths, page_range)
    if grade == "text_bearing" and len(selected) < len(targets) * 0.9:
        grade = "weak"
    return draft, {
        "text_grade": grade,
        "marker_located_count": len(selected),
        "ambiguous_marker_count": len(ambiguous),
        "unmatched_marker_count": len(targets) - len(selected) - len(ambiguous),
        "candidate_marker_count": sum(len(values) for values in candidates.values()),
        "median_block_characters": int(median(block_lengths)) if block_lengths else 0,
    }


def _load_2013_occurrences(path: Path) -> dict[int, list[dict[str, Any]]]:
    payload = _read_json(path)
    if payload.get("paper_id") != "gate-cs-2013":
        raise ProvenanceIndexError("2013 booklet occurrence file has wrong paper_id")
    if payload.get("mapping_status") != "verified_from_complete_pdf_bundle":
        raise ProvenanceIndexError("2013 booklet occurrence file is not verified")
    result: dict[int, list[dict[str, Any]]] = {}
    for item in payload.get("items", []):
        ordinal = int(item["canonical_ordinal"])
        occurrences = item.get("occurrences")
        if not isinstance(occurrences, list) or len(occurrences) != 4:
            raise ProvenanceIndexError(f"2013 item {ordinal} lacks four occurrences")
        result[ordinal] = occurrences
    if set(result) != set(range(1, 66)):
        raise ProvenanceIndexError("2013 occurrence map is not a 65-item bijection")
    return result


def _is_plain_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _validated_locator_override_catalog(
    path: Path,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Load the reviewed page-locator overlay and reject structural ambiguity.

    The catalog is intentionally source-identity bound.  It may only add page
    evidence for records that the conservative automatic locator left
    unresolved; it cannot silently replace an automatic marker.
    """

    payload = _read_json(path)
    if not isinstance(payload, dict):
        raise ProvenanceIndexError("Locator override catalog must be a JSON object")
    if payload.get("schema_version") != LOCATOR_OVERRIDE_SCHEMA_VERSION:
        raise ProvenanceIndexError("Unsupported locator override schema version")
    if payload.get("production_import_authorized") is not False:
        raise ProvenanceIndexError(
            "Locator override catalog must remain production-import unauthorized"
        )
    if payload.get("practice_eligible_count") != 0:
        raise ProvenanceIndexError(
            "Locator override catalog cannot make any item practice eligible"
        )
    if payload.get("review_required") is not True:
        raise ProvenanceIndexError("Locator override catalog must remain review-required")
    render_spec = payload.get("render_specification")
    if render_spec != {
        "format": "pgm",
        "dpi": RENDER_DPI,
        "color_mode": "gray",
        "renderer": "pdftoppm",
    }:
        raise ProvenanceIndexError("Locator override render specification is invalid")
    papers = payload.get("papers")
    if not isinstance(papers, list):
        raise ProvenanceIndexError("Locator override catalog must contain a papers list")

    by_paper: dict[str, dict[str, Any]] = {}
    global_keys: set[tuple[str, int, str]] = set()
    locator_total = 0
    for paper in papers:
        if not isinstance(paper, dict):
            raise ProvenanceIndexError("Locator override paper entries must be objects")
        paper_id = paper.get("paper_id")
        if not isinstance(paper_id, str) or not paper_id:
            raise ProvenanceIndexError("Locator override paper_id is missing")
        if paper_id in by_paper:
            raise ProvenanceIndexError(f"Duplicate locator override paper {paper_id}")
        source_sha256 = paper.get("source_pdf_sha256")
        if not isinstance(source_sha256, str) or not re.fullmatch(
            r"[0-9a-f]{64}", source_sha256
        ):
            raise ProvenanceIndexError(f"{paper_id}: invalid source PDF SHA-256")
        source_page_count = paper.get("source_page_count")
        if not _is_plain_int(source_page_count) or source_page_count < 1:
            raise ProvenanceIndexError(f"{paper_id}: invalid source page count")
        if paper.get("review_required") is not True:
            raise ProvenanceIndexError(f"{paper_id}: locator evidence must require review")

        evidence_rows = paper.get("page_evidence")
        locators = paper.get("locators")
        if not isinstance(evidence_rows, list) or not evidence_rows:
            raise ProvenanceIndexError(f"{paper_id}: page evidence is missing")
        if not isinstance(locators, list) or not locators:
            raise ProvenanceIndexError(f"{paper_id}: locators are missing")

        evidence_by_page: dict[int, dict[str, Any]] = {}
        for evidence in evidence_rows:
            if not isinstance(evidence, dict):
                raise ProvenanceIndexError(f"{paper_id}: page evidence must be an object")
            page = evidence.get("page")
            if not _is_plain_int(page) or not 1 <= page <= source_page_count:
                raise ProvenanceIndexError(
                    f"{paper_id}: locator evidence page {page!r} is outside "
                    f"1..{source_page_count}"
                )
            if page in evidence_by_page:
                raise ProvenanceIndexError(
                    f"{paper_id}: duplicate locator evidence page {page}"
                )
            if (
                not isinstance(evidence.get("sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", evidence["sha256"])
                or evidence.get("format") != "pgm"
                or evidence.get("dpi") != RENDER_DPI
                or evidence.get("color_mode") != "gray"
            ):
                raise ProvenanceIndexError(
                    f"{paper_id}: invalid rendered evidence for page {page}"
                )
            if not isinstance(evidence.get("evidence_method"), str) or not evidence[
                "evidence_method"
            ]:
                raise ProvenanceIndexError(
                    f"{paper_id}: evidence method is missing for page {page}"
                )
            if not isinstance(evidence.get("visual_spot_check"), bool):
                raise ProvenanceIndexError(
                    f"{paper_id}: visual_spot_check must be boolean for page {page}"
                )
            labels = evidence.get("item_labels")
            if (
                not isinstance(labels, list)
                or not labels
                or any(not isinstance(label, str) or not label for label in labels)
                or len(labels) != len(set(labels))
            ):
                raise ProvenanceIndexError(
                    f"{paper_id}: page {page} item_labels are invalid"
                )
            evidence_by_page[page] = evidence

        locator_keys: set[tuple[int, str]] = set()
        labels_by_page: dict[int, list[str]] = defaultdict(list)
        for locator in locators:
            if not isinstance(locator, dict):
                raise ProvenanceIndexError(f"{paper_id}: locator must be an object")
            ordinal = locator.get("canonical_ordinal")
            label = locator.get("item_label")
            page = locator.get("source_page")
            if not _is_plain_int(ordinal) or ordinal < 1:
                raise ProvenanceIndexError(f"{paper_id}: invalid canonical ordinal")
            if not isinstance(label, str) or not label:
                raise ProvenanceIndexError(
                    f"{paper_id}/{ordinal}: locator item label is missing"
                )
            key = (ordinal, label)
            if key in locator_keys:
                raise ProvenanceIndexError(
                    f"{paper_id}: duplicate locator key {ordinal}|{label}"
                )
            global_key = (paper_id, ordinal, label)
            if global_key in global_keys:
                raise ProvenanceIndexError(
                    f"Duplicate global locator key {paper_id}/{ordinal}|{label}"
                )
            if not _is_plain_int(page) or page not in evidence_by_page:
                raise ProvenanceIndexError(
                    f"{paper_id}/{ordinal}|{label}: source page lacks exact evidence"
                )
            locator_keys.add(key)
            global_keys.add(global_key)
            labels_by_page[page].append(label)
        locator_total += len(locators)

        if set(labels_by_page) != set(evidence_by_page):
            raise ProvenanceIndexError(
                f"{paper_id}: page evidence and locator pages are not a bijection"
            )
        for page, evidence in evidence_by_page.items():
            if labels_by_page[page] != evidence["item_labels"]:
                raise ProvenanceIndexError(
                    f"{paper_id}: page {page} evidence labels do not match locators"
                )
        sorted_pages = sorted(evidence_by_page)
        visual_pages = {
            page
            for page, evidence in evidence_by_page.items()
            if evidence["visual_spot_check"]
        }
        if sorted_pages[0] not in visual_pages or sorted_pages[-1] not in visual_pages:
            raise ProvenanceIndexError(
                f"{paper_id}: first and last locator pages need visual spot checks"
            )
        if len(sorted_pages) >= 3:
            lower = sorted_pages[len(sorted_pages) // 3]
            upper = sorted_pages[(2 * len(sorted_pages)) // 3]
            if not any(lower <= page <= upper for page in visual_pages):
                raise ProvenanceIndexError(
                    f"{paper_id}: a middle locator page needs visual spot checking"
                )
        by_paper[paper_id] = paper

    if payload.get("locator_count") != locator_total:
        raise ProvenanceIndexError(
            "Locator override count does not equal the explicit locator inventory"
        )
    unresolved = payload.get("unresolved_locators")
    if not isinstance(unresolved, list):
        raise ProvenanceIndexError("unresolved_locators must be an explicit list")
    return payload, by_paper


def _apply_explicit_locator_overrides(
    records: list[dict[str, Any]],
    paper_override: dict[str, Any] | None,
    *,
    paper_id: str,
    source: Path,
    source_sha256: str,
    source_page_count: int,
    page_range: tuple[int, int],
    render_cache: RenderHashCache | None,
) -> int:
    """Apply a complete, exact-key overlay for one paper or fail closed."""

    located_statuses = {"marker_located", "hash_matched_reviewed_ocr_page"}
    required = {
        (int(record["canonical_ordinal"]), str(record["item_label"])): record
        for record in records
        if record["locator_status"] not in located_statuses
    }
    if paper_override is None:
        if required:
            raise ProvenanceIndexError(
                f"{paper_id}: {len(required)} unresolved locators lack explicit overrides"
            )
        return 0
    if paper_override.get("paper_id") != paper_id:
        raise ProvenanceIndexError(
            f"Cross-paper locator override rejected: expected {paper_id}, got "
            f"{paper_override.get('paper_id')!r}"
        )
    if paper_override["source_pdf_sha256"].casefold() != source_sha256.casefold():
        raise ProvenanceIndexError(f"{paper_id}: locator override source SHA-256 mismatch")
    if int(paper_override["source_page_count"]) != source_page_count:
        raise ProvenanceIndexError(f"{paper_id}: locator override page-count mismatch")

    locator_rows = paper_override["locators"]
    provided = {
        (int(locator["canonical_ordinal"]), str(locator["item_label"])): locator
        for locator in locator_rows
    }
    if len(provided) != len(locator_rows):
        raise ProvenanceIndexError(f"{paper_id}: duplicate explicit locator keys")
    extra = set(provided) - set(required)
    if extra:
        detail = sorted(f"{ordinal}|{label}" for ordinal, label in extra)
        raise ProvenanceIndexError(
            f"{paper_id}: explicit locator conflicts with automatic/existing markers: "
            f"{detail}"
        )
    missing = set(required) - set(provided)
    if missing:
        detail = sorted(f"{ordinal}|{label}" for ordinal, label in missing)
        raise ProvenanceIndexError(
            f"{paper_id}: incomplete explicit locator keys: {detail}"
        )

    evidence_by_page = {
        int(evidence["page"]): evidence for evidence in paper_override["page_evidence"]
    }
    for page, evidence in evidence_by_page.items():
        if not page_range[0] <= page <= page_range[1]:
            raise ProvenanceIndexError(
                f"{paper_id}: override page {page} lies outside question range {page_range}"
            )
        if render_cache is not None:
            actual = render_cache.page_sha256(source, page)
            if actual != evidence["sha256"]:
                raise ProvenanceIndexError(
                    f"{paper_id}: rendered locator evidence hash mismatch on page {page}"
                )

    for key, record in required.items():
        locator = provided[key]
        page = int(locator["source_page"])
        evidence = evidence_by_page[page]
        record.update(
            {
                "source_pages": [page],
                "boundary": None,
                "boundary_status": "page_only",
                "text_block_sha256": None,
                "normalized_character_count": 0,
                "locator_status": "hash_matched_reviewed_original_page_override",
                "locator_override_evidence": {
                    "evidence_method": evidence["evidence_method"],
                    "visual_spot_check": evidence["visual_spot_check"],
                    "rendered_page_evidence": {
                        key: evidence[key]
                        for key in ("page", "sha256", "format", "dpi", "color_mode")
                    },
                },
            }
        )
    return len(required)


def _reviewed_ocr_page_locators(
    consolidated_payload: dict[str, Any],
    *,
    paper_id: str,
    source_sha256: str,
    builder: Any,
) -> dict[int, int]:
    aliases = [
        alias
        for alias, mapped_paper_id in builder.CONSOLIDATED_PAPER_IDS.items()
        if mapped_paper_id == paper_id
        and REVIEWED_OCR_LOCATOR_SOURCE_SHA256.get(alias) == source_sha256
    ]
    if not aliases:
        return {}
    alias = aliases[0]
    rows = [
        row
        for row in consolidated_payload.get("questions", [])
        if row.get("source_paper") == alias
    ]
    result: dict[int, int] = {}
    for row in rows:
        if row.get("extraction_method") != "rapidocr_onnxruntime+visual_review":
            continue
        page = row.get("source_page")
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            continue
        ordinal = builder._consolidated_ordinal(row)
        if ordinal in result and result[ordinal] != page:
            raise ProvenanceIndexError(
                f"{paper_id}: conflicting reviewed OCR pages for ordinal {ordinal}"
            )
        result[ordinal] = page
    return result


def _apply_reviewed_ocr_page_locators(
    records: list[dict[str, Any]], locators: dict[int, int], page_range: tuple[int, int]
) -> int:
    adopted = 0
    for record in records:
        if record["locator_status"] == "marker_located":
            continue
        page = locators.get(int(record["canonical_ordinal"]))
        if page is None:
            continue
        if not page_range[0] <= page <= page_range[1]:
            raise ProvenanceIndexError(
                f"{record['source_paper_id']}/{record['canonical_ordinal']}: "
                f"reviewed OCR page {page} lies outside {page_range}"
            )
        record.update(
            {
                "source_pages": [page],
                "boundary": None,
                "boundary_status": "page_only",
                "text_block_sha256": None,
                "normalized_character_count": 0,
                "locator_status": "hash_matched_reviewed_ocr_page",
            }
        )
        adopted += 1
    return adopted


def _decorate_records(
    records: list[dict[str, Any]],
    *,
    paper: dict[str, Any],
    source: Path,
    source_sha256: str,
    text_grade: str,
    page_texts: Sequence[PageText],
    render_cache: RenderHashCache | None,
    occurrences_2013: dict[int, list[dict[str, Any]]] | None,
) -> None:
    pages_by_number = {page.page: page for page in page_texts}
    for record in records:
        record["source_pdf_sha256"] = source_sha256
        record["source_path"] = str(source.relative_to(REPO_DIR)).replace("\\", "/") if source.is_relative_to(REPO_DIR) else str(source)
        record["practice_eligible"] = False
        record["production_import_authorized"] = False
        record["page_text_sha256"] = [
            {
                "page": page,
                "sha256": pages_by_number[page].normalized_sha256,
            }
            for page in record["source_pages"]
        ]
        if occurrences_2013 is not None:
            record["booklet_occurrences"] = occurrences_2013[
                int(record["canonical_ordinal"])
            ]
        if record["locator_status"] not in {
            "marker_located",
            "hash_matched_reviewed_ocr_page",
            "hash_matched_reviewed_original_page_override",
        }:
            record["evidence_status"] = "unresolved"
            record["review_flags"] = [record["locator_status"], "manual_source_review_required"]
            record["rendered_page_evidence"] = []
            continue
        if (
            text_grade == "text_bearing"
            and record["text_block_sha256"]
            and record.get("boundary_status") == "exact"
        ):
            record["evidence_status"] = "exact_text_block"
            record["review_flags"] = []
            record["rendered_page_evidence"] = []
        else:
            record["evidence_status"] = "rendered_page_review_required"
            record["review_flags"] = [
                "weak_or_image_source",
                "manual_source_review_required",
            ]
            if record["locator_status"] == "hash_matched_reviewed_ocr_page":
                record["review_flags"].append("hash_matched_reviewed_ocr_page_locator")
            if record["locator_status"] == "hash_matched_reviewed_original_page_override":
                record["review_flags"].append(
                    "hash_matched_reviewed_original_page_override_locator"
                )
            if record.get("boundary_status") == "next_marker_missing":
                record["review_flags"].append("question_block_boundary_unresolved")
            override_evidence = record.get("locator_override_evidence")
            if override_evidence is not None:
                record["rendered_page_evidence"] = [
                    override_evidence["rendered_page_evidence"]
                ]
                if render_cache is None:
                    record["review_flags"].append("render_hash_not_reverified_this_run")
            elif render_cache is None:
                record["review_flags"].append("render_hash_pending")
                record["rendered_page_evidence"] = []
            else:
                record["rendered_page_evidence"] = _render_evidence(
                    render_cache, source, record["source_pages"]
                )


def build_provenance_index(
    manifest_path: Path = DEFAULT_MANIFEST,
    consolidated_path: Path = DEFAULT_CONSOLIDATED,
    *,
    booklet_occurrences_path: Path = DEFAULT_BOOKLET_OCCURRENCES,
    locator_overrides_path: Path = DEFAULT_LOCATOR_OVERRIDES,
    verify_source_hashes: bool = True,
    pdftoppm: str | None = None,
    render_weak_sources: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    builder = _load_builder()
    manifest = _read_json(manifest_path)
    consolidated_payload = _read_json(consolidated_path)
    locator_override_payload, locator_overrides_by_paper = (
        _validated_locator_override_catalog(locator_overrides_path)
    )
    papers = manifest.get("papers")
    if not isinstance(papers, list):
        raise ProvenanceIndexError("Source manifest must contain a papers list")
    canonical, _ = builder.build_archive(
        manifest_path,
        consolidated_path,
        go_index_path=None,
        examside_index_path=None,
        booklet_occurrence_path=booklet_occurrences_path,
        verify_source_hashes=verify_source_hashes,
    )
    if len(canonical["papers"]) != EXPECTED_PAPERS or len(canonical["questions"]) != EXPECTED_ITEMS:
        raise ProvenanceIndexError("Canonical builder did not produce the reviewed 39/2712 inventory")
    items_by_paper: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in canonical["questions"]:
        items_by_paper[item["source_paper_id"]].append(item)

    renderer = (
        RenderHashCache(_find_pdftoppm(pdftoppm)) if render_weak_sources else None
    )
    occurrence_payload = _read_json(booklet_occurrences_path)
    occurrence_map = _load_2013_occurrences(booklet_occurrences_path)
    booklet_a_range_raw = occurrence_payload.get("booklet_page_ranges", {}).get("A")
    if (
        not isinstance(booklet_a_range_raw, list)
        or len(booklet_a_range_raw) != 2
        or not all(isinstance(value, int) for value in booklet_a_range_raw)
    ):
        raise ProvenanceIndexError("2013 booklet A page range is missing or invalid")
    booklet_a_range = (booklet_a_range_raw[0], booklet_a_range_raw[1])
    booklet_a_item_pages = [
        int(occurrence["source_page"])
        for occurrences in occurrence_map.values()
        for occurrence in occurrences
        if occurrence.get("booklet_code") == "A"
    ]
    if len(booklet_a_item_pages) != 65:
        raise ProvenanceIndexError("2013 booklet A must expose 65 item pages")
    booklet_a_range = (min(booklet_a_item_pages), max(booklet_a_item_pages))
    all_records: list[dict[str, Any]] = []
    paper_reports: list[dict[str, Any]] = []
    explicit_locator_override_count = 0
    source_cache: dict[Path, tuple[PdfReader, list[PageText], str]] = {}
    for paper in papers:
        paper_id = str(paper["id"])
        source = builder._resolve_manifest_file(
            str(paper["local_file"]),
            origin=paper.get("local_file_origin"),
            manifest_path=manifest_path,
        )
        if source not in source_cache:
            reader = PdfReader(source)
            page_texts = _extract_pages(reader)
            source_cache[source] = (reader, page_texts, builder._sha256(source))
        reader, page_texts, source_sha256 = source_cache[source]
        expected_sha256 = str(paper.get("local_sha256") or "").casefold()
        if expected_sha256 and source_sha256.casefold() != expected_sha256:
            raise ProvenanceIndexError(f"{paper_id}: source PDF SHA-256 mismatch")
        declared_pages = paper.get("local_page_count")
        if declared_pages is not None and len(reader.pages) != int(declared_pages):
            raise ProvenanceIndexError(f"{paper_id}: source PDF page-count mismatch")
        page_range = _parse_page_range(paper.get("source_page_range"), len(reader.pages))
        if page_range is None:
            page_range = (1, len(reader.pages))
        page_range, page_range_evidence = _question_page_range(
            paper,
            page_texts,
            page_range,
            booklet_a_range=booklet_a_range,
        )
        records, paper_report = _build_text_records(
            paper,
            items_by_paper[paper_id],
            page_texts,
            page_range,
        )
        reviewed_ocr_locators = _reviewed_ocr_page_locators(
            consolidated_payload,
            paper_id=paper_id,
            source_sha256=source_sha256,
            builder=builder,
        )
        reviewed_ocr_adopted = _apply_reviewed_ocr_page_locators(
            records, reviewed_ocr_locators, page_range
        )
        explicit_locator_overrides_adopted = _apply_explicit_locator_overrides(
            records,
            locator_overrides_by_paper.get(paper_id),
            paper_id=paper_id,
            source=source,
            source_sha256=source_sha256,
            source_page_count=len(reader.pages),
            page_range=page_range,
            render_cache=renderer,
        )
        explicit_locator_override_count += explicit_locator_overrides_adopted
        _decorate_records(
            records,
            paper=paper,
            source=source,
            source_sha256=source_sha256,
            text_grade=paper_report["text_grade"],
            page_texts=page_texts,
            render_cache=renderer,
            occurrences_2013=occurrence_map if paper_id == "gate-cs-2013" else None,
        )
        paper_report.update(
            {
                "paper_id": paper_id,
                "year": int(paper["year"]),
                "source_pdf_sha256": source_sha256,
                "source_page_count": len(reader.pages),
                "question_page_range": list(page_range),
                "question_page_range_evidence": page_range_evidence,
                "item_count": len(records),
                "hash_matched_reviewed_ocr_page_count": reviewed_ocr_adopted,
                "hash_matched_reviewed_original_page_override_count": (
                    explicit_locator_overrides_adopted
                ),
                "exact_text_block_count": sum(
                    record["evidence_status"] == "exact_text_block" for record in records
                ),
                "rendered_page_review_count": sum(
                    record["evidence_status"] == "rendered_page_review_required"
                    for record in records
                ),
                "unresolved_count": sum(
                    record["evidence_status"] == "unresolved" for record in records
                ),
            }
        )
        all_records.extend(records)
        paper_reports.append(paper_report)

    manifest_paper_ids = {str(paper["id"]) for paper in papers}
    unknown_override_papers = set(locator_overrides_by_paper) - manifest_paper_ids
    if unknown_override_papers:
        raise ProvenanceIndexError(
            "Locator overrides reference papers outside the source manifest: "
            f"{sorted(unknown_override_papers)}"
        )
    if explicit_locator_override_count != locator_override_payload["locator_count"]:
        raise ProvenanceIndexError(
            "Applied explicit locator count does not match the validated overlay"
        )

    all_records.sort(key=lambda item: (item["source_paper_id"], item["canonical_ordinal"]))
    counts = Counter(record["evidence_status"] for record in all_records)
    page_counts_by_paper = {
        paper_report["paper_id"]: paper_report["source_page_count"]
        for paper_report in paper_reports
    }
    rendered_evidence_entries = [
        evidence
        for record in all_records
        for evidence in record["rendered_page_evidence"]
    ]
    artifact_core = {
        "schema_version": SCHEMA_VERSION,
        "scope": "Original question-paper PDF provenance for canonical GATE CS 1996-2025 slots",
        "production_import_authorized": False,
        "practice_eligible_count": 0,
        "render_specification": {
            "enabled": render_weak_sources,
            "format": "pgm",
            "dpi": RENDER_DPI,
            "color_mode": "gray",
            "renderer": "pdftoppm",
        },
        "source_manifest_sha256": _sha256_bytes(manifest_path.read_bytes()),
        "locator_overrides_sha256": _sha256_bytes(locator_overrides_path.read_bytes()),
        "canonical_identity": {"paper_count": EXPECTED_PAPERS, "item_count": EXPECTED_ITEMS},
        "papers": paper_reports,
        "items": all_records,
    }
    artifact_sha256 = _sha256_text(
        json.dumps(artifact_core, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    artifact = {**artifact_core, "artifact_sha256": artifact_sha256}
    report = {
        "schema_version": SCHEMA_VERSION,
        "artifact_sha256": artifact_sha256,
        "paper_count": len(paper_reports),
        "item_count": len(all_records),
        "evidence_counts": dict(sorted(counts.items())),
        "located_item_count": len(all_records) - counts.get("unresolved", 0),
        "unresolved_locator_count": counts.get("unresolved", 0),
        "hash_matched_reviewed_ocr_page_count": sum(
            paper_report["hash_matched_reviewed_ocr_page_count"]
            for paper_report in paper_reports
        ),
        "hash_matched_reviewed_original_page_override_count": (
            explicit_locator_override_count
        ),
        "auto_marker_review_finding_count": len(
            locator_override_payload.get("auto_marker_review_findings", [])
        ),
        "text_block_hash_count": sum(
            bool(record["text_block_sha256"]) for record in all_records
        ),
        "rendered_page_hash_reference_count": len(rendered_evidence_entries),
        "unique_rendered_page_hash_count": len(
            {evidence["sha256"] for evidence in rendered_evidence_entries}
        ),
        "marker_located_count": sum(
            report["marker_located_count"] for report in paper_reports
        ),
        "ambiguous_marker_count": sum(
            report["ambiguous_marker_count"] for report in paper_reports
        ),
        "unmatched_marker_count": sum(
            report["unmatched_marker_count"] for report in paper_reports
        ),
        "invariants": {
            "paper_count_is_39": len(paper_reports) == EXPECTED_PAPERS,
            "item_count_is_2712": len(all_records) == EXPECTED_ITEMS,
            "all_records_staging_only": all(
                record["practice_eligible"] is False
                and record["production_import_authorized"] is False
                for record in all_records
            ),
            "unique_paper_ordinal": len(
                {
                    (record["source_paper_id"], record["canonical_ordinal"])
                    for record in all_records
                }
            )
            == EXPECTED_ITEMS,
            "all_hashes_well_formed": all(
                record["text_block_sha256"] is None
                or re.fullmatch(r"[0-9a-f]{64}", record["text_block_sha256"])
                for record in all_records
            ),
            "all_located_records_have_pages": all(
                record["evidence_status"] == "unresolved" or record["source_pages"]
                for record in all_records
            ),
            "all_source_pages_inside_pdf": all(
                1 <= page <= page_counts_by_paper[record["source_paper_id"]]
                for record in all_records
                for page in record["source_pages"]
            ),
            "all_exact_blocks_have_text_hash": all(
                record["evidence_status"] != "exact_text_block"
                or bool(record["text_block_sha256"])
                for record in all_records
            ),
            "rendered_hashes_complete_when_enabled": (
                not render_weak_sources
                or all(
                    record["evidence_status"] != "rendered_page_review_required"
                    or bool(record["rendered_page_evidence"])
                    for record in all_records
                )
            ),
            "all_rendered_hashes_well_formed": all(
                re.fullmatch(r"[0-9a-f]{64}", evidence["sha256"])
                for evidence in rendered_evidence_entries
            ),
        },
        "papers": paper_reports,
    }
    if not all(report["invariants"].values()):
        raise ProvenanceIndexError(f"Provenance invariants failed: {report['invariants']}")
    return artifact, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--consolidated", type=Path, default=DEFAULT_CONSOLIDATED)
    parser.add_argument(
        "--booklet-occurrences", type=Path, default=DEFAULT_BOOKLET_OCCURRENCES
    )
    parser.add_argument(
        "--locator-overrides", type=Path, default=DEFAULT_LOCATOR_OVERRIDES
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--pdftoppm")
    parser.add_argument("--skip-source-hash-verification", action="store_true")
    parser.add_argument("--no-render-weak-sources", action="store_true")
    args = parser.parse_args()
    artifact, report = build_provenance_index(
        args.manifest,
        args.consolidated,
        booklet_occurrences_path=args.booklet_occurrences,
        locator_overrides_path=args.locator_overrides,
        verify_source_hashes=not args.skip_source_hash_verification,
        pdftoppm=args.pdftoppm,
        render_weak_sources=not args.no_render_weak_sources,
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
                "paper_count": report["paper_count"],
                "item_count": report["item_count"],
                "evidence_counts": report["evidence_counts"],
                "located_item_count": report["located_item_count"],
                "unresolved_locator_count": report["unresolved_locator_count"],
                "explicit_locator_override_count": report[
                    "hash_matched_reviewed_original_page_override_count"
                ],
                "rendered_page_hash_reference_count": report[
                    "rendered_page_hash_reference_count"
                ],
                "ambiguous_marker_count": report["ambiguous_marker_count"],
                "unmatched_marker_count": report["unmatched_marker_count"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
