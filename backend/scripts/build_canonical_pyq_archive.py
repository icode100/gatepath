"""Build a deterministic, review-first GATE CSE PYQ archive artifact.

This script is intentionally a *staging* builder.  It never opens a database
and never marks a question practice-eligible.  Its first responsibility is to
make omissions measurable: every canonical scoring item declared by
``pyq_source_manifest.json`` receives exactly one contiguous paper-local
ordinal.  Existing transcriptions and secondary locators are then joined only
through explicit paper/number mappings.

The default artifact and audit report are written below ``tmp/pyq/build``
(which is ignored by git).  They can be validated and reviewed before the
separate archive importer is ever invoked.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import unicodedata
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_DIR = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = REPO_DIR / "backend" / "data" / "pyq_source_manifest.json"
DEFAULT_CONSOLIDATED = REPO_DIR / "backend" / "data" / "pyq_consolidated.json"
DEFAULT_GO_INDEX = (
    REPO_DIR
    / "tmp"
    / "pyq"
    / "reference"
    / "extracted"
    / "question_locator_index.jsonl"
)
DEFAULT_2013_BOOKLET_OCCURRENCES = (
    REPO_DIR
    / "backend"
    / "data"
    / "gate_cs_2013_booklet_occurrences.json"
)
DEFAULT_OUTPUT = REPO_DIR / "tmp" / "pyq" / "build" / "canonical_pyq_archive.json"

EXPECTED_PAPER_COUNT = 39
EXPECTED_ITEM_COUNT = 2712
BUILDER_SCHEMA_VERSION = "1.2"
GATE_2013_PAPER_ID = "gate-cs-2013"
GATE_2013_BOOKLET_CODES = ("A", "B", "C", "D")


class ArchiveBuildError(ValueError):
    """Raised when a source cannot be joined without guessing."""


@dataclass(frozen=True, slots=True)
class SlotSpec:
    item_label: str
    item_type: str = "unknown"
    parent_item_label: str | None = None


@dataclass(frozen=True, slots=True)
class BookletOccurrence:
    booklet_code: str
    item_label: str
    source_page: int


@dataclass(frozen=True, slots=True)
class BookletOccurrenceMap:
    paper_id: str
    canonical_booklet_code: str
    source_pdf_sha256: str
    by_canonical_ordinal: dict[int, tuple[BookletOccurrence, ...]]
    canonical_ordinal_by_occurrence: dict[tuple[str, str], int]


# These are the exact labels used by the previously consolidated 2017-2025
# corpus.  Keeping the map explicit prevents a same-year session from being
# inferred from a loose string comparison.
CONSOLIDATED_PAPER_IDS: dict[str, str] = {
    "CS1-2017": "gate-cs-2017-session-1",
    "CS2-2017": "gate-cs-2017-session-2",
    "CS-2018": "gate-cs-2018",
    "CS-2019": "gate-cs-2019",
    "CS-2020": "gate-cs-2020",
    "CS1-2021": "gate-cs-2021-session-1",
    "CS2-2021": "gate-cs-2021-session-2",
    "CS-2022": "gate-cs-2022",
    "CS-2023": "gate-cs-2023",
    "CS1-2024": "gate-cs-2024-set-1",
    "CS2-2024": "gate-cs-2024-set-2",
    "CS1-2025": "gate-cs-2025-set-1",
    "CS2-2025": "gate-cs-2025-set-2",
}

# The old 2017 extractor numbered the 55 technical questions first and then
# appended ten GA questions as 56..65.  Canonical archive ordinals are GA
# 1..10 followed by technical 11..65, matching every later consolidated paper.
CONSOLIDATED_TECHNICAL_FIRST = {"CS1-2017", "CS2-2017"}

# A total-only assertion could miss a compensating count error between two
# papers.  This is the reviewed canonical inventory, including the deliberate
# single-paper representation of the four reordered 2013 booklet codes.
EXPECTED_PAPER_LAYOUT: tuple[tuple[str, int, str, int], ...] = (
    ("gate-cs-1996", 1996, "single", 75),
    ("gate-cs-1997", 1997, "single", 68),
    ("gate-cs-1998", 1998, "single", 80),
    ("gate-cs-1999", 1999, "single", 70),
    ("gate-cs-2000", 2000, "single", 69),
    ("gate-cs-2001", 2001, "single", 70),
    ("gate-cs-2002", 2002, "single", 70),
    ("gate-cs-2003", 2003, "single", 90),
    ("gate-cs-2004", 2004, "single", 90),
    ("gate-cs-2005", 2005, "single", 90),
    ("gate-cs-2006", 2006, "single", 85),
    ("gate-cs-2007", 2007, "single", 85),
    ("gate-cs-2008", 2008, "single", 85),
    ("gate-cs-2009", 2009, "single", 60),
    ("gate-cs-2010", 2010, "single", 65),
    ("gate-cs-2011", 2011, "single", 65),
    ("gate-cs-2012", 2012, "single", 65),
    ("gate-cs-2013", 2013, "single-canonical-paper", 65),
    ("gate-cs-2014-session-1", 2014, "1", 65),
    ("gate-cs-2014-session-2", 2014, "2", 65),
    ("gate-cs-2014-session-3", 2014, "3", 65),
    ("gate-cs-2015-session-1", 2015, "1", 65),
    ("gate-cs-2015-session-2", 2015, "2", 65),
    ("gate-cs-2015-session-3", 2015, "3", 65),
    ("gate-cs-2016-session-1", 2016, "1", 65),
    ("gate-cs-2016-session-2", 2016, "2", 65),
    ("gate-cs-2017-session-1", 2017, "1", 65),
    ("gate-cs-2017-session-2", 2017, "2", 65),
    ("gate-cs-2018", 2018, "single", 65),
    ("gate-cs-2019", 2019, "single", 65),
    ("gate-cs-2020", 2020, "single", 65),
    ("gate-cs-2021-session-1", 2021, "1", 65),
    ("gate-cs-2021-session-2", 2021, "2", 65),
    ("gate-cs-2022", 2022, "single", 65),
    ("gate-cs-2023", 2023, "single", 65),
    ("gate-cs-2024-set-1", 2024, "set-1", 65),
    ("gate-cs-2024-set-2", 2024, "set-2", 65),
    ("gate-cs-2025-set-1", 2025, "set-1", 65),
    ("gate-cs-2025-set-2", 2025, "set-2", 65),
)

# Explicit legacy layouts, verified from the supplied paper headings.  A tuple
# is (outer question number, number of objective sub-parts).
LEGACY_OBJECTIVE_BLOCKS: dict[int, tuple[tuple[int, int], ...]] = {
    1996: ((1, 25), (2, 25)),
    1997: ((1, 10), (2, 5), (3, 10), (4, 10), (5, 5), (6, 10)),
    1998: ((1, 35), (2, 20)),
    1999: ((1, 25), (2, 25)),
    2000: ((1, 23), (2, 26)),
    2001: ((1, 25), (2, 25)),
    2002: ((1, 25), (2, 25)),
}
LEGACY_DESCRIPTIVE_RANGES: dict[int, tuple[int, int]] = {
    1996: (3, 27),
    1997: (7, 24),
    1998: (3, 27),
    1999: (3, 22),
    2000: (3, 22),
    2001: (3, 22),
    2002: (3, 22),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_manifest_file(
    raw_path: str,
    *,
    origin: str | None,
    manifest_path: Path,
) -> Path:
    supplied = Path(raw_path)
    candidates: list[Path] = []
    if supplied.is_absolute():
        candidates.append(supplied)
    if origin == "user_supplied_downloads":
        download_root = Path.home() / "Downloads"
        candidates.extend(
            (
                download_root / supplied,
                download_root / "CS" / "CS" / supplied,
            )
        )
    candidates.extend(
        (
            REPO_DIR / supplied,
            manifest_path.parent / supplied,
        )
    )
    unique_candidates = list(dict.fromkeys(candidate.resolve() for candidate in candidates))
    for candidate in unique_candidates:
        if candidate.is_file():
            return candidate
    locations = ", ".join(str(candidate) for candidate in unique_candidates)
    raise ArchiveBuildError(
        f"Manifest source {raw_path!r} cannot be resolved; checked {locations}"
    )


def _verify_manifest_sources(
    papers: list[dict[str, Any]], manifest_path: Path
) -> dict[str, Any]:
    declarations: list[tuple[str, str, str, str | None, int | None]] = []
    for paper in papers:
        if paper.get("local_file"):
            declarations.append(
                (
                    paper["id"],
                    "question_paper",
                    str(paper["local_file"]),
                    paper.get("local_sha256"),
                    paper.get("local_bytes"),
                )
            )
        if paper.get("answer_key_local_file"):
            declarations.append(
                (
                    paper["id"],
                    "answer_key",
                    str(paper["answer_key_local_file"]),
                    paper.get("answer_key_local_sha256"),
                    paper.get("answer_key_local_bytes"),
                )
            )

    cache: dict[Path, tuple[int, str]] = {}
    records: list[dict[str, Any]] = []
    papers_by_id = {paper["id"]: paper for paper in papers}
    for paper_id, role, raw_path, expected_sha, expected_bytes in declarations:
        if not expected_sha or not re.fullmatch(r"[0-9a-fA-F]{64}", str(expected_sha)):
            raise ArchiveBuildError(
                f"{paper_id}/{role}: a valid manifest SHA-256 is required"
            )
        paper = papers_by_id[paper_id]
        path = _resolve_manifest_file(
            raw_path,
            origin=paper.get("local_file_origin"),
            manifest_path=manifest_path,
        )
        if path not in cache:
            cache[path] = (path.stat().st_size, _sha256(path))
        actual_bytes, actual_sha = cache[path]
        if expected_bytes is not None and actual_bytes != int(expected_bytes):
            raise ArchiveBuildError(
                f"{paper_id}/{role}: byte-size mismatch for {path} "
                f"({actual_bytes} != {expected_bytes})"
            )
        if actual_sha.casefold() != str(expected_sha).casefold():
            raise ArchiveBuildError(
                f"{paper_id}/{role}: SHA-256 mismatch for {path} "
                f"({actual_sha} != {expected_sha})"
            )
        records.append(
            {
                "paper_id": paper_id,
                "role": role,
                "path": _relative(path),
                "bytes": actual_bytes,
                "sha256": actual_sha,
            }
        )
    return {
        "performed": True,
        "declaration_count": len(records),
        "unique_file_count": len(cache),
        "records": records,
    }


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArchiveBuildError(f"Cannot read JSON source {path}: {exc}") from exc


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    continue
                payload = json.loads(line)
                if not isinstance(payload, dict):
                    raise ArchiveBuildError(
                        f"{path}:{line_number} is not a JSON object"
                    )
                records.append(payload)
    except (OSError, json.JSONDecodeError) as exc:
        raise ArchiveBuildError(f"Cannot read JSONL source {path}: {exc}") from exc
    return records


def _records_from_json_or_jsonl(path: Path) -> list[dict[str, Any]]:
    if path.suffix.casefold() == ".jsonl":
        return _read_jsonl(path)
    payload = _read_json(path)
    if isinstance(payload, list):
        records = payload
    elif isinstance(payload, dict):
        records = next(
            (
                payload[key]
                for key in ("questions", "records", "items")
                if isinstance(payload.get(key), list)
            ),
            [],
        )
    else:
        records = []
    if not all(isinstance(record, dict) for record in records):
        raise ArchiveBuildError(f"{path} contains non-object records")
    return list(records)


def _load_2013_booklet_occurrences(
    path: Path,
    manifest_paper: dict[str, Any],
) -> BookletOccurrenceMap:
    """Load the reviewed A/B/C/D permutation without inferring any labels.

    The 2013 download contains four reordered booklets, but it is one exam
    paper.  This staging map is therefore mandatory whenever a source refers
    to a booklet-local number.  A missing or malformed map fails the build;
    the builder must never pretend that ``B/Q1`` means canonical ``A/Q1``.
    """

    payload = _read_json(path)
    if not isinstance(payload, dict):
        raise ArchiveBuildError("2013 booklet occurrence map must be a JSON object")
    if str(payload.get("schema_version") or "").split(".", 1)[0] != "1":
        raise ArchiveBuildError("Unsupported 2013 booklet occurrence schema")
    if payload.get("paper_id") != GATE_2013_PAPER_ID:
        raise ArchiveBuildError("2013 booklet map has the wrong paper_id")
    if manifest_paper.get("id") != GATE_2013_PAPER_ID:
        raise ArchiveBuildError("2013 manifest paper is missing")
    canonical_code = str(payload.get("canonical_booklet_code") or "").upper()
    if canonical_code != "A":
        raise ArchiveBuildError("2013 canonical booklet must be code A")
    if payload.get("mapping_status") != "verified_from_complete_pdf_bundle":
        raise ArchiveBuildError("2013 booklet occurrence map is not verified")
    if payload.get("production_import_authorized") is not False:
        raise ArchiveBuildError(
            "2013 booklet occurrence map must remain staging-only"
        )
    source_sha = str(payload.get("source_pdf_sha256") or "").casefold()
    manifest_sha = str(manifest_paper.get("local_sha256") or "").casefold()
    if not re.fullmatch(r"[0-9a-f]{64}", source_sha) or source_sha != manifest_sha:
        raise ArchiveBuildError(
            "2013 booklet occurrence source checksum does not match the manifest"
        )

    raw_ranges = payload.get("booklet_page_ranges")
    if not isinstance(raw_ranges, dict) or set(raw_ranges) != set(
        GATE_2013_BOOKLET_CODES
    ):
        raise ArchiveBuildError("2013 booklet page ranges must cover A/B/C/D")
    page_ranges: dict[str, tuple[int, int]] = {}
    for code in GATE_2013_BOOKLET_CODES:
        value = raw_ranges.get(code)
        if (
            not isinstance(value, list)
            or len(value) != 2
            or any(isinstance(number, bool) or not isinstance(number, int) for number in value)
            or value[0] < 1
            or value[1] < value[0]
        ):
            raise ArchiveBuildError(f"2013 booklet {code} has an invalid page range")
        page_ranges[code] = (value[0], value[1])

    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or len(raw_items) != 65:
        raise ArchiveBuildError("2013 booklet map must contain 65 canonical items")
    by_canonical: dict[int, tuple[BookletOccurrence, ...]] = {}
    by_occurrence: dict[tuple[str, str], int] = {}
    pages_by_code_and_label: dict[str, dict[int, int]] = {
        code: {} for code in GATE_2013_BOOKLET_CODES
    }
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            raise ArchiveBuildError("2013 booklet item must be an object")
        ordinal = raw_item.get("canonical_ordinal")
        if isinstance(ordinal, bool) or not isinstance(ordinal, int):
            raise ArchiveBuildError("2013 canonical ordinal must be an integer")
        if ordinal in by_canonical or not 1 <= ordinal <= 65:
            raise ArchiveBuildError(
                f"2013 canonical ordinal {ordinal!r} is duplicate or outside 1..65"
            )
        if str(raw_item.get("canonical_item_label") or "") != str(ordinal):
            raise ArchiveBuildError(
                f"2013 canonical item {ordinal} must use booklet-A label {ordinal}"
            )
        raw_occurrences = raw_item.get("occurrences")
        if not isinstance(raw_occurrences, list) or len(raw_occurrences) != 4:
            raise ArchiveBuildError(
                f"2013 canonical item {ordinal} must have four occurrences"
            )
        occurrences: list[BookletOccurrence] = []
        seen_codes: set[str] = set()
        for raw_occurrence in raw_occurrences:
            if not isinstance(raw_occurrence, dict):
                raise ArchiveBuildError("2013 booklet occurrence must be an object")
            code = str(raw_occurrence.get("booklet_code") or "").upper()
            if code not in GATE_2013_BOOKLET_CODES or code in seen_codes:
                raise ArchiveBuildError(
                    f"2013 canonical item {ordinal} has duplicate/unknown booklet {code!r}"
                )
            seen_codes.add(code)
            item_label = str(raw_occurrence.get("item_label") or "")
            if not item_label.isdigit() or not 1 <= int(item_label) <= 65:
                raise ArchiveBuildError(
                    f"2013 booklet {code} has invalid item label {item_label!r}"
                )
            page = raw_occurrence.get("source_page")
            page_start, page_end = page_ranges[code]
            if (
                isinstance(page, bool)
                or not isinstance(page, int)
                or not page_start <= page <= page_end
            ):
                raise ArchiveBuildError(
                    f"2013 booklet {code}/{item_label} has an invalid source page"
                )
            occurrence_key = (code, item_label)
            if occurrence_key in by_occurrence:
                raise ArchiveBuildError(
                    f"Duplicate 2013 booklet occurrence {code}/{item_label}"
                )
            by_occurrence[occurrence_key] = ordinal
            pages_by_code_and_label[code][int(item_label)] = page
            occurrences.append(BookletOccurrence(code, item_label, page))
        if seen_codes != set(GATE_2013_BOOKLET_CODES):
            raise ArchiveBuildError(
                f"2013 canonical item {ordinal} does not cover A/B/C/D"
            )
        canonical_occurrence = next(
            occurrence
            for occurrence in occurrences
            if occurrence.booklet_code == canonical_code
        )
        if canonical_occurrence.item_label != str(ordinal):
            raise ArchiveBuildError(
                f"2013 booklet A must be identity-mapped at canonical item {ordinal}"
            )
        by_canonical[ordinal] = tuple(
            sorted(occurrences, key=lambda occurrence: occurrence.booklet_code)
        )

    expected_ordinals = set(range(1, 66))
    if set(by_canonical) != expected_ordinals:
        raise ArchiveBuildError("2013 canonical ordinals are not exactly 1..65")
    for code in GATE_2013_BOOKLET_CODES:
        label_pages = pages_by_code_and_label[code]
        if set(label_pages) != expected_ordinals:
            raise ArchiveBuildError(
                f"2013 booklet {code} labels are not a bijection over 1..65"
            )
        ordered_pages = [label_pages[label] for label in range(1, 66)]
        if ordered_pages != sorted(ordered_pages):
            raise ArchiveBuildError(
                f"2013 booklet {code} source pages do not follow item-label order"
            )

    return BookletOccurrenceMap(
        paper_id=GATE_2013_PAPER_ID,
        canonical_booklet_code=canonical_code,
        source_pdf_sha256=source_sha,
        by_canonical_ordinal=by_canonical,
        canonical_ordinal_by_occurrence=by_occurrence,
    )


def _attach_2013_booklet_occurrences(
    slots: dict[tuple[str, int], dict[str, Any]],
    occurrence_map: BookletOccurrenceMap,
    paper_stats: dict[str, Counter[str]],
) -> dict[str, Any]:
    for ordinal in range(1, 66):
        item = slots.get((occurrence_map.paper_id, ordinal))
        if item is None:
            raise ArchiveBuildError(f"Missing canonical 2013 slot {ordinal}")
        canonical_occurrence = next(
            occurrence
            for occurrence in occurrence_map.by_canonical_ordinal[ordinal]
            if occurrence.booklet_code == occurrence_map.canonical_booklet_code
        )
        if item.get("source_page") not in {None, canonical_occurrence.source_page}:
            raise ArchiveBuildError(
                f"Canonical 2013 slot {ordinal} conflicts with booklet-A source page"
            )
        item["source_page"] = canonical_occurrence.source_page
        for occurrence in occurrence_map.by_canonical_ordinal[ordinal]:
            _append_reference(
                item,
                {
                    "kind": "booklet_occurrence",
                    "url": None,
                    "sha256": occurrence_map.source_pdf_sha256,
                    "note": json.dumps(
                        {
                            "booklet_code": occurrence.booklet_code,
                            "item_label": occurrence.item_label,
                            "source_page": occurrence.source_page,
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                },
            )
        _append_flag(item, "booklet_occurrence_mapping_staging_only")
        paper_stats[occurrence_map.paper_id]["canonical_items_mapped"] += 1
        paper_stats[occurrence_map.paper_id]["booklet_occurrences_attached"] += 4
    return {
        "paper_id": occurrence_map.paper_id,
        "canonical_booklet_code": occurrence_map.canonical_booklet_code,
        "canonical_item_count": len(occurrence_map.by_canonical_ordinal),
        "occurrence_count": len(occurrence_map.canonical_ordinal_by_occurrence),
        "booklet_codes": list(GATE_2013_BOOKLET_CODES),
        "all_booklets_bijective": True,
        "staging_only": True,
    }


def _append_flag(item: dict[str, Any], flag: str) -> None:
    if flag and flag not in item["review_flags"]:
        item["review_flags"].append(flag)


def _append_reference(item: dict[str, Any], reference: dict[str, Any]) -> None:
    identity = (
        reference.get("kind"),
        reference.get("url"),
        reference.get("sha256"),
        reference.get("note"),
    )
    if all(
        (
            current.get("kind"),
            current.get("url"),
            current.get("sha256"),
            current.get("note"),
        )
        != identity
        for current in item["source_references"]
    ):
        item["source_references"].append(reference)


def _legacy_slots(year: int) -> list[SlotSpec]:
    blocks = LEGACY_OBJECTIVE_BLOCKS[year]
    descriptive_start, descriptive_end = LEGACY_DESCRIPTIVE_RANGES[year]
    result = [
        SlotSpec(f"{outer}.{part}", "mcq")
        for outer, count in blocks
        for part in range(1, count + 1)
    ]
    result.extend(
        SlotSpec(str(number), "descriptive")
        for number in range(descriptive_start, descriptive_end + 1)
    )
    return result


def _slot_specs(paper: dict[str, Any]) -> list[SlotSpec]:
    year = int(paper["year"])
    expected = int(paper["expected_item_count"])
    if year in LEGACY_OBJECTIVE_BLOCKS:
        result = _legacy_slots(year)
    elif year == 2005:
        result = [SlotSpec(str(number)) for number in range(1, 81)]
        result.extend(
            SlotSpec(f"{number}{part}", parent_item_label=str(number))
            for number in range(81, 86)
            for part in ("a", "b")
        )
    elif year >= 2014:
        if expected != 65:
            raise ArchiveBuildError(
                f"{paper['id']}: modern sectioned papers must declare 65 items"
            )
        result = [SlotSpec(f"GA-{number}") for number in range(1, 11)]
        result.extend(SlotSpec(f"CS-{number}") for number in range(1, 56))
    else:
        result = [SlotSpec(str(number)) for number in range(1, expected + 1)]
    if len(result) != expected:
        raise ArchiveBuildError(
            f"{paper['id']}: explicit layout produced {len(result)} slots, "
            f"manifest expects {expected}"
        )
    return result


def _display_name(paper: dict[str, Any]) -> str:
    session = str(paper["session"])
    if session == "single":
        suffix = ""
    elif session == "single-canonical-paper":
        suffix = " (canonical booklet ordering)"
    elif session.startswith("set-"):
        suffix = f" Set {session.rsplit('-', 1)[-1]}"
    elif session.isdigit():
        suffix = f" Session {session}"
    else:
        suffix = f" {session}"
    return f"GATE CS {paper['year']}{suffix}"


def _paper_aliases(paper_id: str) -> list[str]:
    return sorted(
        alias
        for alias, mapped_paper_id in CONSOLIDATED_PAPER_IDS.items()
        if mapped_paper_id == paper_id
    )


def _archive_paper(paper: dict[str, Any]) -> dict[str, Any]:
    valid_local = bool(paper.get("local_valid_pdf"))
    note_parts = [str(paper.get("notes") or "").strip()]
    note_parts.append(
        "Review-first staging record; source authority and completeness must be "
        "approved before production materialization."
    )
    return {
        "id": paper["id"],
        "exam_code": "GATE",
        "paper_code": "CS",
        "year": int(paper["year"]),
        "session_label": str(paper["session"]),
        "display_name": _display_name(paper),
        "expected_item_count": int(paper["expected_item_count"]),
        "source_url": paper.get("question_paper_url"),
        "answer_key_url": paper.get("answer_key_url"),
        "source_pdf_sha256": paper.get("local_sha256") if valid_local else None,
        "answer_key_sha256": paper.get("answer_key_local_sha256"),
        "source_aliases": _paper_aliases(paper["id"]),
        "source_status": "review_required",
        "notes": " ".join(part for part in note_parts if part),
    }


def _placeholder(paper: dict[str, Any], spec: SlotSpec, ordinal: int) -> dict[str, Any]:
    flags = [
        "missing_transcription",
        "answer_unresolved",
        "classification_review_required",
    ]
    if spec.item_type == "descriptive":
        flags.append("descriptive_not_auto_gradable")
    if paper.get("source_status") not in {
        "complete_local_secondary",
        "complete_local_secondary_bundle",
    }:
        flags.append("paper_source_review_required")
    subject_code = "GA" if spec.item_label.startswith("GA-") else None
    return {
        "source_paper_id": paper["id"],
        "item_label": spec.item_label,
        "ordinal": ordinal,
        "legacy_source_ordinals": [],
        "parent_item_label": spec.parent_item_label,
        "source_page": None,
        "marks": None,
        "item_type": spec.item_type,
        "question_md": None,
        "options": [],
        "accepted_answers": None,
        "solution_md": None,
        "subject_code": subject_code,
        "topic_slug": None,
        "syllabus_status": "review_required",
        "transcription_status": "missing",
        "answer_status": "unresolved",
        "classification_status": "review_required",
        "practice_eligible": False,
        "review_flags": flags,
        "assets": [],
        "source_references": [],
        "extraction_method": None,
        "extraction_confidence": None,
    }


def _coerce_ordinal(value: Any, *, context: str) -> int:
    if isinstance(value, bool):
        raise ArchiveBuildError(f"{context}: boolean is not a question ordinal")
    try:
        ordinal = int(value)
    except (TypeError, ValueError) as exc:
        raise ArchiveBuildError(f"{context}: invalid question ordinal {value!r}") from exc
    if str(value).strip() not in {str(ordinal), f"{ordinal}.0"}:
        raise ArchiveBuildError(f"{context}: non-integral question ordinal {value!r}")
    return ordinal


def _consolidated_ordinal(record: dict[str, Any]) -> int:
    label = str(record.get("source_paper") or "")
    number = _coerce_ordinal(
        record.get("source_question_number"),
        context=str(record.get("external_id") or label),
    )
    if label in CONSOLIDATED_TECHNICAL_FIRST:
        if 1 <= number <= 55:
            return number + 10
        if 56 <= number <= 65:
            return number - 55
        raise ArchiveBuildError(f"{label}: source question {number} is outside 1..65")
    return number


def _valid_subject(record: dict[str, Any]) -> str | None:
    course = str(record.get("course") or "").strip().upper()
    return course if course and course != "UNRESOLVED" else None


def _valid_topic(record: dict[str, Any]) -> str | None:
    topic = str(record.get("topic_slug") or "").strip()
    return topic if topic and topic != "unresolved" else None


def _adopt_consolidated(
    slots: dict[tuple[str, int], dict[str, Any]],
    records: list[dict[str, Any]],
    source_papers: dict[str, dict[str, Any]],
    paper_stats: dict[str, Counter[str]],
) -> dict[str, Any]:
    occupied: dict[tuple[str, int], str] = {}
    safe_count = 0
    for record in records:
        source_label = str(record.get("source_paper") or "")
        paper_id = CONSOLIDATED_PAPER_IDS.get(source_label)
        if paper_id is None:
            raise ArchiveBuildError(
                f"Unmapped consolidated source_paper {source_label!r} for "
                f"{record.get('external_id')!r}"
            )
        ordinal = _consolidated_ordinal(record)
        legacy_source_ordinal = _coerce_ordinal(
            record.get("source_question_number"),
            context=str(record.get("external_id") or source_label),
        )
        key = (paper_id, ordinal)
        item = slots.get(key)
        if item is None:
            raise ArchiveBuildError(
                f"{record.get('external_id')}: normalized slot {paper_id}/{ordinal} "
                "does not exist"
            )
        if key in occupied:
            raise ArchiveBuildError(
                f"Consolidated records {occupied[key]!r} and "
                f"{record.get('external_id')!r} collide at {paper_id}/{ordinal}"
            )
        occupied[key] = str(record.get("external_id"))

        question = str(record.get("question") or "").strip() or None
        subject = _valid_subject(record)
        topic = _valid_topic(record)
        safe = bool(record.get("safe_for_quiz")) and record.get("status") == "verified"
        safe = bool(safe and question and subject and topic)
        safe_count += int(safe)
        # A checksum-bound key file attached to the paper is provenance, not a
        # proof that this legacy record's answer was reconciled to the same
        # canonical ordinal.  Official status may only be applied by consuming
        # an exact resolved claim from the staging answer-key index; community
        # status likewise requires two independent source-file hashes.  This
        # builder consumes neither evidence class, so every adopted answer is
        # intentionally left unresolved.
        answer_status = "unresolved"

        item.update(
            {
                "source_page": record.get("source_page"),
                "legacy_source_ordinals": (
                    [legacy_source_ordinal]
                    if legacy_source_ordinal != ordinal
                    else []
                ),
                "marks": record.get("marks"),
                "item_type": str(record.get("question_type") or "unknown").lower(),
                "question_md": question,
                "options": deepcopy(record.get("options") or []),
                "accepted_answers": deepcopy(record.get("correct_answer")),
                "solution_md": str(record.get("explanation") or "").strip() or None,
                "subject_code": subject,
                "topic_slug": topic,
                "syllabus_status": "in_syllabus" if safe else "review_required",
                "transcription_status": (
                    "verified" if safe else "review_required" if question else "missing"
                ),
                "answer_status": answer_status,
                "classification_status": "verified" if safe else "review_required",
                "practice_eligible": False,
                "review_flags": list(dict.fromkeys(record.get("review_flags") or [])),
                "extraction_method": (
                    f"consolidated:{record.get('extraction_method')}"
                    if record.get("extraction_method")
                    else "consolidated"
                ),
                "extraction_confidence": record.get("extraction_confidence"),
            }
        )
        _append_flag(item, "staging_only_not_materialized")
        if record.get("correct_answer") is not None:
            _append_flag(item, "answer_candidate_requires_checksum_reconciliation")
        if not safe:
            _append_flag(item, "consolidated_record_requires_review")
            if not question:
                _append_flag(item, "missing_transcription")
            if not subject or not topic:
                _append_flag(item, "classification_review_required")
            if record.get("correct_answer") is not None:
                _append_flag(item, "answer_candidate_requires_review")
        for url, kind in (
            (record.get("source_url"), "consolidated_question_source"),
            (record.get("answer_key_url"), "consolidated_answer_key"),
        ):
            if url:
                _append_reference(
                    item,
                    {
                        "kind": kind,
                        "url": str(url),
                        "sha256": None,
                        "note": f"legacy_external_id={record.get('external_id')}",
                    },
                )
        paper_stats[paper_id]["consolidated_adopted"] += 1
        paper_stats[paper_id]["consolidated_safe"] += int(safe)
    return {
        "record_count": len(records),
        "adopted_count": len(occupied),
        "verified_safe_count": safe_count,
    }


_LABEL_RE = re.compile(
    r"^0*(?P<outer>\d+)(?:(?P<sep>[.\-]?)(?:0*(?P<inner>\d+)|(?P<part>[a-z])))?$",
    re.IGNORECASE,
)


def _label_key(raw_label: Any) -> str | None:
    value = str(raw_label or "").split(",", 1)[0].strip().replace(" ", "")
    match = _LABEL_RE.fullmatch(value)
    if not match:
        return None
    outer = str(int(match.group("outer")))
    inner = match.group("inner")
    part = match.group("part")
    if inner is not None:
        return f"{outer}.{int(inner)}"
    if part is not None:
        return f"{outer}{part.casefold()}"
    return outer


def _session_number(value: Any) -> int | None:
    match = re.search(r"(\d+)$", str(value or ""))
    return int(match.group(1)) if match else None


def _explicit_booklet_code(row: dict[str, Any]) -> str | None:
    candidates: list[Any] = [row.get("booklet_code")]
    question = row.get("question")
    if isinstance(question, dict):
        candidates.append(question.get("booklet_code"))
    for value in candidates:
        match = re.fullmatch(r"(?:CS\s*-?\s*)?([ABCD])", str(value or "").strip(), re.I)
        if match:
            return match.group(1).upper()
    return None


def _reference_paper_id(
    row: dict[str, Any], papers_by_year: dict[int, list[dict[str, Any]]]
) -> str | None:
    try:
        year = int(row.get("year"))
    except (TypeError, ValueError):
        return None
    candidates = papers_by_year.get(year, [])
    if len(candidates) == 1:
        return candidates[0]["id"]
    wanted = row.get("set_number")
    if wanted is None:
        wanted = _session_number(row.get("session"))
    if wanted is None:
        return None
    matched = [
        paper
        for paper in candidates
        if _session_number(paper.get("session")) == int(wanted)
    ]
    return matched[0]["id"] if len(matched) == 1 else None


def _reference_slot_key(
    row: dict[str, Any],
    paper_id: str,
    paper_year: int,
    labels_to_ordinals: dict[str, dict[str, int]],
    booklet_occurrence_map: BookletOccurrenceMap | None = None,
) -> tuple[str, int] | None:
    key = _label_key(row.get("item_label"))
    if key is None:
        return None
    if paper_year == 2013:
        # Every booklet restarts at Q1, so a bare 2013 item label is
        # ambiguous.  Only an explicit booklet code plus the validated
        # permutation may select a canonical slot.
        code = _explicit_booklet_code(row)
        if (
            booklet_occurrence_map is None
            or booklet_occurrence_map.paper_id != paper_id
            or code is None
            or "." in key
            or key[-1:].isalpha()
        ):
            return None
        canonical_ordinal = booklet_occurrence_map.canonical_ordinal_by_occurrence.get(
            (code, key)
        )
        return (
            (paper_id, canonical_ordinal)
            if canonical_ordinal is not None
            else None
        )
    if paper_year >= 2014:
        if "." in key or key[-1:].isalpha():
            return None
        local_number = int(key)
        section = str(row.get("section_code") or "").upper()
        if section == "GA" and 1 <= local_number <= 10:
            return (paper_id, local_number)
        if section == "CS" and 1 <= local_number <= 55:
            return (paper_id, local_number + 10)
        return None
    ordinal = labels_to_ordinals[paper_id].get(key)
    return (paper_id, ordinal) if ordinal is not None else None


def _attach_gateoverflow(
    slots: dict[tuple[str, int], dict[str, Any]],
    papers: list[dict[str, Any]],
    labels_to_ordinals: dict[str, dict[str, int]],
    rows: list[dict[str, Any]],
    paper_stats: dict[str, Counter[str]],
    booklet_occurrence_map: BookletOccurrenceMap | None = None,
) -> dict[str, Any]:
    papers_by_year: dict[int, list[dict[str, Any]]] = defaultdict(list)
    paper_year: dict[str, int] = {}
    for paper in papers:
        papers_by_year[int(paper["year"])].append(paper)
        paper_year[paper["id"]] = int(paper["year"])

    mapped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    unmatched = 0
    for row in rows:
        paper_id = _reference_paper_id(row, papers_by_year)
        if paper_id is None:
            unmatched += 1
            continue
        key = _reference_slot_key(
            row,
            paper_id,
            paper_year[paper_id],
            labels_to_ordinals,
            booklet_occurrence_map,
        )
        if key is None or key not in slots:
            unmatched += 1
            continue
        mapped[key].append(row)

    attached = ambiguous = answer_candidates = classification_candidates = 0
    for key, candidates in mapped.items():
        item = slots[key]
        if len(candidates) != 1:
            ambiguous += 1
            _append_flag(item, "ambiguous_gateoverflow_locator")
            paper_stats[key[0]]["gateoverflow_ambiguous"] += 1
            continue
        row = candidates[0]
        note_fields = {
            "volume": row.get("volume"),
            "page": row.get("source_page"),
            "book_id": row.get("book_id"),
            "source_label": row.get("item_label"),
            "answer_join_status": row.get("answer_join_status"),
        }
        note = "; ".join(
            f"{name}={value}"
            for name, value in note_fields.items()
            if value is not None
        )
        _append_reference(
            item,
            {
                "kind": "gateoverflow_locator",
                "url": None,
                "sha256": None,
                "note": note or "exact paper/section/item locator",
            },
        )
        attached += 1
        paper_stats[key[0]]["gateoverflow_attached"] += 1

        if row.get("answer") is not None and row.get("answer_join_status") == "joined":
            answer_candidates += 1
            _append_flag(item, "community_answer_candidate_available")
        course = str(row.get("course_code") or "").strip().upper()
        topic = str(row.get("topic_slug") or "").strip()
        mapping_agrees = row.get("course_mapping_agrees") is not False
        if mapping_agrees and course and topic:
            if not item.get("subject_code"):
                item["subject_code"] = course
            if not item.get("topic_slug"):
                item["topic_slug"] = topic
            if item["classification_status"] != "verified":
                _append_flag(item, "classification_candidate_gateoverflow")
            classification_candidates += 1
    return {
        "record_count": len(rows),
        "exact_locator_count": attached,
        "ambiguous_slot_count": ambiguous,
        "unmatched_record_count": unmatched,
        "answer_candidate_count": answer_candidates,
        "classification_candidate_count": classification_candidates,
    }


def _explicit_secondary_key(
    row: dict[str, Any],
    slots: dict[tuple[str, int], dict[str, Any]],
    labels_to_ordinals: dict[str, dict[str, int]],
    paper_years: dict[str, int],
    booklet_occurrence_map: BookletOccurrenceMap | None = None,
) -> tuple[str, int] | None:
    paper_id = row.get("source_paper_id") or row.get("manifest_paper_id")
    if paper_id not in paper_years:
        return None
    global_ordinal = row.get("global_ordinal")
    if global_ordinal is not None:
        try:
            key = (
                str(paper_id),
                _coerce_ordinal(global_ordinal, context="secondary"),
            )
        except ArchiveBuildError:
            return None
        return key if key in slots else None
    # A generic ``ordinal`` is paper-local in most secondary indexes.  For
    # 2013 that means booklet-local and must pass through the occurrence map;
    # treating it as canonical would silently attach B/C/D answers to A labels.
    if row.get("ordinal") is not None:
        if paper_years[str(paper_id)] == 2013:
            row = {**row, "item_label": row.get("item_label") or row.get("ordinal")}
        else:
            try:
                key = (
                    str(paper_id),
                    _coerce_ordinal(row.get("ordinal"), context="secondary"),
                )
            except ArchiveBuildError:
                return None
            return key if key in slots else None
    return _reference_slot_key(
        row,
        str(paper_id),
        paper_years[str(paper_id)],
        labels_to_ordinals,
        booklet_occurrence_map,
    )


def _normalized_full_text(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    plain = re.sub(r"<[^>]+>", " ", html.unescape(value))
    plain = unicodedata.normalize("NFKC", plain).casefold()
    plain = re.sub(r"\s+", " ", plain).strip()
    return plain if len(plain) >= 30 else None


def _nested_examside_paper_id(
    row: dict[str, Any], papers: list[dict[str, Any]]
) -> str | None:
    paper_meta = row.get("paper")
    if not isinstance(paper_meta, dict):
        return None
    slug = str(paper_meta.get("slug") or "").strip().casefold()
    if not re.fullmatch(r"gate-cse-\d{4}(?:-set-\d+)?", slug):
        return None
    direct = slug.replace("gate-cse-", "gate-cs-", 1)
    paper_ids = {paper["id"] for paper in papers}
    if direct in paper_ids:
        return direct
    try:
        year = int(paper_meta.get("year"))
    except (TypeError, ValueError):
        return None
    set_number = _session_number(paper_meta.get("session"))
    candidates = [paper for paper in papers if int(paper["year"]) == year]
    if set_number is not None:
        candidates = [
            paper
            for paper in candidates
            if _session_number(paper.get("session")) == set_number
        ]
    return candidates[0]["id"] if len(candidates) == 1 else None


def _attach_examside_sanitized(
    slots: dict[tuple[str, int], dict[str, Any]],
    papers: list[dict[str, Any]],
    labels_to_ordinals: dict[str, dict[str, int]],
    rows: list[dict[str, Any]],
    paper_stats: dict[str, Counter[str]],
    booklet_occurrence_map: BookletOccurrenceMap | None = None,
) -> dict[str, Any]:
    """Attach only explicit sanitized locators; never copy third-party content."""

    paper_years = {paper["id"]: int(paper["year"]) for paper in papers}
    mapped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    full_text_slots: dict[tuple[str, str], list[tuple[str, int]]] = defaultdict(list)
    for key, item in slots.items():
        normalized = _normalized_full_text(item.get("question_md"))
        if normalized:
            full_text_slots[(key[0], normalized)].append(key)
    unmatched = ignored_content = 0
    content_fields = {"question", "content", "options", "answer", "explanation"}
    for row in rows:
        question_meta = row.get("question")
        ignored_content += int(
            any(field in row for field in content_fields)
            or (
                isinstance(question_meta, dict)
                and any(
                    field in question_meta
                    for field in (
                        "question_text",
                        "direction_text",
                        "comprehension_text",
                        "options",
                        "correct_options",
                        "numerical_answer",
                        "explanation_sha256",
                    )
                )
            )
        )
        key = _explicit_secondary_key(
            row,
            slots,
            labels_to_ordinals,
            paper_years,
            booklet_occurrence_map,
        )
        if key is None and isinstance(question_meta, dict):
            paper_id = _nested_examside_paper_id(row, papers)
            normalized = _normalized_full_text(question_meta.get("question_text"))
            exact_matches = (
                full_text_slots.get((paper_id, normalized), [])
                if paper_id and normalized
                else []
            )
            if len(exact_matches) == 1:
                key = exact_matches[0]
        if key is None:
            unmatched += 1
            continue
        mapped[key].append(row)

    attached = ambiguous = 0
    for key, candidates in mapped.items():
        item = slots[key]
        if len(candidates) != 1:
            ambiguous += 1
            _append_flag(item, "ambiguous_examside_locator")
            paper_stats[key[0]]["examside_ambiguous"] += 1
            continue
        row = candidates[0]
        question_meta = row.get("question") if isinstance(row.get("question"), dict) else {}
        provenance = row.get("provenance") if isinstance(row.get("provenance"), dict) else {}
        digest = (
            row.get("content_sha256")
            or row.get("sha256")
            or provenance.get("question_raw_sha256")
        )
        if digest is not None and not re.fullmatch(r"[0-9a-fA-F]{64}", str(digest)):
            digest = None
        identifier = (
            row.get("question_id")
            or row.get("id")
            or row.get("source_item_id")
            or question_meta.get("source_id")
            or "explicit sanitized locator"
        )
        _append_reference(
            item,
            {
                "kind": "examside_sanitized_locator",
                "url": (
                    row.get("source_url")
                    or row.get("url")
                    or question_meta.get("url")
                ),
                "sha256": str(digest).lower() if digest else None,
                "note": f"id={identifier}; third-party content intentionally not copied",
            },
        )
        _append_flag(item, "secondary_locator_requires_source_crosscheck")
        attached += 1
        paper_stats[key[0]]["examside_attached"] += 1
    return {
        "record_count": len(rows),
        "exact_locator_count": attached,
        "ambiguous_slot_count": ambiguous,
        "unmatched_record_count": unmatched,
        "records_with_ignored_content_fields": ignored_content,
    }


def _validate_manifest(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    papers = manifest.get("papers")
    if not isinstance(papers, list) or not all(isinstance(paper, dict) for paper in papers):
        raise ArchiveBuildError("Source manifest must contain a papers array")
    ids = [paper.get("id") for paper in papers]
    if len(ids) != len(set(ids)):
        raise ArchiveBuildError("Source manifest contains duplicate paper ids")
    count = sum(int(paper.get("expected_item_count") or 0) for paper in papers)
    if len(papers) != EXPECTED_PAPER_COUNT or count != EXPECTED_ITEM_COUNT:
        raise ArchiveBuildError(
            f"Manifest invariant failed: {len(papers)} papers/{count} items; "
            f"expected {EXPECTED_PAPER_COUNT}/{EXPECTED_ITEM_COUNT}"
        )
    actual_layout = tuple(
        (
            str(paper.get("id")),
            int(paper.get("year") or 0),
            str(paper.get("session")),
            int(paper.get("expected_item_count") or 0),
        )
        for paper in papers
    )
    if actual_layout != EXPECTED_PAPER_LAYOUT:
        mismatches = [
            {"position": index + 1, "expected": expected, "actual": actual}
            for index, (expected, actual) in enumerate(
                zip(EXPECTED_PAPER_LAYOUT, actual_layout, strict=False)
            )
            if expected != actual
        ]
        if len(actual_layout) != len(EXPECTED_PAPER_LAYOUT):
            mismatches.append(
                {
                    "expected_length": len(EXPECTED_PAPER_LAYOUT),
                    "actual_length": len(actual_layout),
                }
            )
        raise ArchiveBuildError(
            "Manifest paper layout differs from the reviewed 39-paper inventory: "
            + json.dumps(mismatches[:8], ensure_ascii=False)
        )
    if manifest.get("production_import_authorized") is not False:
        raise ArchiveBuildError(
            "Review-first builder requires production_import_authorized=false"
        )
    return papers


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_DIR).as_posix()
    except ValueError:
        return str(path.resolve())


def build_archive(
    manifest_path: Path,
    consolidated_path: Path,
    *,
    go_index_path: Path | None = None,
    examside_index_path: Path | None = None,
    booklet_occurrence_path: Path = DEFAULT_2013_BOOKLET_OCCURRENCES,
    verify_source_hashes: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest_path = manifest_path.resolve()
    consolidated_path = consolidated_path.resolve()
    manifest = _read_json(manifest_path)
    papers = _validate_manifest(manifest)
    paper_2013 = next(
        (paper for paper in papers if paper.get("id") == GATE_2013_PAPER_ID),
        None,
    )
    if paper_2013 is None:
        raise ArchiveBuildError("Reviewed inventory is missing GATE CS 2013")
    booklet_occurrence_path = booklet_occurrence_path.resolve()
    booklet_occurrence_map = _load_2013_booklet_occurrences(
        booklet_occurrence_path,
        paper_2013,
    )
    source_verification = (
        _verify_manifest_sources(papers, manifest_path)
        if verify_source_hashes
        else {
            "performed": False,
            "declaration_count": 0,
            "unique_file_count": 0,
            "records": [],
        }
    )
    consolidated_payload = _read_json(consolidated_path)
    consolidated = consolidated_payload.get("questions")
    if not isinstance(consolidated, list):
        raise ArchiveBuildError("Consolidated source must contain a questions array")

    archive_papers = [_archive_paper(paper) for paper in papers]
    questions: list[dict[str, Any]] = []
    slots: dict[tuple[str, int], dict[str, Any]] = {}
    labels_to_ordinals: dict[str, dict[str, int]] = {}
    paper_stats: dict[str, Counter[str]] = defaultdict(Counter)
    for paper in papers:
        label_map: dict[str, int] = {}
        for ordinal, spec in enumerate(_slot_specs(paper), start=1):
            item = _placeholder(paper, spec, ordinal)
            key = (paper["id"], ordinal)
            if key in slots:
                raise ArchiveBuildError(f"Duplicate generated slot {key}")
            normalized_label = _label_key(spec.item_label)
            if normalized_label:
                if normalized_label in label_map:
                    raise ArchiveBuildError(
                        f"{paper['id']}: duplicate normalized label {normalized_label}"
                    )
                label_map[normalized_label] = ordinal
            slots[key] = item
            questions.append(item)
        labels_to_ordinals[paper["id"]] = label_map

    booklet_report = _attach_2013_booklet_occurrences(
        slots,
        booklet_occurrence_map,
        paper_stats,
    )

    consolidated_report = _adopt_consolidated(
        slots,
        consolidated,
        {paper["id"]: paper for paper in papers},
        paper_stats,
    )
    go_rows: list[dict[str, Any]] = []
    if go_index_path is not None and go_index_path.exists():
        go_rows = _read_jsonl(go_index_path.resolve())
    go_report = _attach_gateoverflow(
        slots,
        papers,
        labels_to_ordinals,
        go_rows,
        paper_stats,
        booklet_occurrence_map,
    )

    examside_rows: list[dict[str, Any]] = []
    if examside_index_path is not None and examside_index_path.exists():
        examside_rows = _records_from_json_or_jsonl(examside_index_path.resolve())
    examside_report = _attach_examside_sanitized(
        slots,
        papers,
        labels_to_ordinals,
        examside_rows,
        paper_stats,
        booklet_occurrence_map,
    )

    input_paths = {
        "builder": Path(__file__).resolve(),
        "manifest": manifest_path,
        "consolidated": consolidated_path,
        "booklet_occurrences_2013": booklet_occurrence_path,
        "gateoverflow_locator": (
            go_index_path.resolve()
            if go_index_path is not None and go_index_path.exists()
            else None
        ),
        "examside_sanitized_locator": (
            examside_index_path.resolve()
            if examside_index_path is not None and examside_index_path.exists()
            else None
        ),
    }
    input_fingerprints = {
        name: {
            "path": _relative(path) if path else None,
            "sha256": _sha256(path) if path else None,
        }
        for name, path in input_paths.items()
    }
    version_basis = {
        "builder_schema_version": BUILDER_SCHEMA_VERSION,
        "inputs": {name: value["sha256"] for name, value in input_fingerprints.items()},
    }
    version_hash = hashlib.sha256(
        json.dumps(version_basis, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    artifact = {
        "schema_version": "1.0",
        "artifact_version": f"gate-cs-1996-2025-staging-{version_hash}",
        "papers": archive_papers,
        "questions": questions,
    }

    paper_report: list[dict[str, Any]] = []
    for paper in papers:
        paper_items = [item for item in questions if item["source_paper_id"] == paper["id"]]
        transcribed = sum(item["question_md"] is not None for item in paper_items)
        paper_report.append(
            {
                "paper_id": paper["id"],
                "expected_item_count": paper["expected_item_count"],
                "slot_count": len(paper_items),
                "contiguous_ordinals": [item["ordinal"] for item in paper_items]
                == list(range(1, int(paper["expected_item_count"]) + 1)),
                "transcribed_count": transcribed,
                "missing_transcription_count": len(paper_items) - transcribed,
                **dict(sorted(paper_stats[paper["id"]].items())),
            }
        )
    status_counts = Counter(item["transcription_status"] for item in questions)
    report = {
        "schema_version": "1.0",
        "artifact_version": artifact["artifact_version"],
        "source_role": (
            "Review-only canonical skeleton. No database writes and no question is "
            "practice-eligible."
        ),
        "inputs": input_fingerprints,
        "source_file_verification": source_verification,
        "invariants": {
            "expected_paper_count": EXPECTED_PAPER_COUNT,
            "actual_paper_count": len(archive_papers),
            "expected_item_count": EXPECTED_ITEM_COUNT,
            "actual_item_count": len(questions),
            "all_paper_ordinals_contiguous": all(
                row["contiguous_ordinals"] for row in paper_report
            ),
            "practice_eligible_count": sum(
                bool(item["practice_eligible"]) for item in questions
            ),
        },
        "coverage": {
            "transcription_status": dict(sorted(status_counts.items())),
            "transcribed_count": sum(item["question_md"] is not None for item in questions),
            "missing_transcription_count": sum(
                item["question_md"] is None for item in questions
            ),
            "accepted_answer_candidate_count": sum(
                item["accepted_answers"] is not None for item in questions
            ),
            "verified_answer_status_count": sum(
                item["answer_status"] in {"official", "community_verified"}
                for item in questions
            ),
        },
        "joins": {
            "consolidated": consolidated_report,
            "booklet_occurrences_2013": booklet_report,
            "gateoverflow": go_report,
            "examside_sanitized": examside_report,
        },
        "papers": paper_report,
    }
    return artifact, report


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--consolidated", type=Path, default=DEFAULT_CONSOLIDATED)
    parser.add_argument("--go-index", type=Path, default=DEFAULT_GO_INDEX)
    parser.add_argument("--without-go", action="store_true")
    parser.add_argument("--examside-index", type=Path, default=None)
    parser.add_argument(
        "--booklet-2013-map",
        type=Path,
        default=DEFAULT_2013_BOOKLET_OCCURRENCES,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    go_path = None if args.without_go else args.go_index.resolve()
    # ExamSIDE is an optional secondary reconciliation source and its crawler
    # writes incrementally.  Requiring an explicit path prevents a partial,
    # still-growing index from silently changing an otherwise deterministic
    # canonical build.
    examside_path = (
        args.examside_index.resolve() if args.examside_index is not None else None
    )
    artifact, report = build_archive(
        args.manifest.resolve(),
        args.consolidated.resolve(),
        go_index_path=go_path,
        examside_index_path=examside_path,
        booklet_occurrence_path=args.booklet_2013_map.resolve(),
    )
    output = args.output.resolve()
    report_path = (
        args.report.resolve()
        if args.report is not None
        else output.with_suffix(".report.json")
    )
    _write_json(output, artifact)
    _write_json(report_path, report)
    print(
        f"Built {len(artifact['papers'])} papers / {len(artifact['questions'])} "
        f"canonical slots; adopted "
        f"{report['joins']['consolidated']['adopted_count']} consolidated records."
    )
    print(f"Artifact: {output}")
    print(f"Audit: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
