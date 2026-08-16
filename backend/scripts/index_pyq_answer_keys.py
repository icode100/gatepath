"""Build a checksum-bound, staging-only GATE CSE answer-key index.

The archive corpus deliberately separates transcription from answer authority.
This script inventories every answer source declared by
``pyq_source_manifest.json``, extracts only deterministic key tables, maps each
claim onto the canonical paper/section/ordinal coordinate system, and reports
conflicts.  It never opens a database and never authorizes practice promotion.

Official claims may resolve an answer directly.  Secondary/community-only
claims require agreement from two different source-file hashes; a single
secondary compilation remains explicitly unverified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from pypdf import PdfReader


REPO_DIR = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = REPO_DIR / "backend" / "data" / "pyq_source_manifest.json"
DEFAULT_2013_BOOKLET_MAP = (
    REPO_DIR / "backend" / "data" / "gate_cs_2013_booklet_occurrences.json"
)
DEFAULT_OUTPUT = (
    REPO_DIR
    / "tmp"
    / "pyq"
    / "reference"
    / "answer-keys"
    / "pyq_answer_key_index.json"
)
DEFAULT_REPORT = DEFAULT_OUTPUT.with_name("pyq_answer_key_report.json")

SCHEMA_VERSION = "1.0"
EXPECTED_PAPER_COUNT = 39
EXPECTED_ITEMS_PER_MODERN_PAPER = 65


class AnswerKeyIndexError(ValueError):
    """Raised when a source or key table cannot be joined without guessing."""


@dataclass(frozen=True, slots=True)
class KeySource:
    paper_id: str
    year: int
    role: str
    raw_path: str
    path: Path
    sha256: str
    expected_bytes: int
    expected_pages: int
    authority: str
    authority_level: str
    source_url: str | None
    index_url: str | None
    parser_profile: str


@dataclass(frozen=True, slots=True)
class ParsedRow:
    source_question_number: int
    section: str | None
    section_question_number: int | None
    question_type: str
    raw_key: str
    answer: dict[str, Any]
    marks: int | None
    key_page: int
    review_flags: tuple[str, ...] = ()


# Profiles are keyed by paper identity, never inferred from a year alone.  That
# prevents a key from one multi-session paper being attached to another.
SEPARATE_PROFILES: dict[str, str] = {
    "gate-cs-2011": "booklet_code_a_2011",
    "gate-cs-2012": "booklet_code_a_2012",
    "gate-cs-2013": "verified_booklet_table_2013",
    "gate-cs-2014-session-1": "untyped_local_2014",
    "gate-cs-2014-session-2": "untyped_local_2014",
    "gate-cs-2014-session-3": "untyped_local_2014",
    "gate-cs-2015-session-1": "audited_visual_2015_session_1",
    "gate-cs-2015-session-2": "audited_visual_2015_session_2",
    "gate-cs-2015-session-3": "audited_visual_2015_session_3",
    "gate-cs-2016-session-1": "structured_local_no_session",
    "gate-cs-2016-session-2": "structured_local_no_session",
    "gate-cs-2017-session-1": "structured_technical_first_no_session",
    "gate-cs-2017-session-2": "structured_technical_first_no_session",
    "gate-cs-2018": "structured_local_no_session",
    "gate-cs-2019": "structured_local_no_session",
    "gate-cs-2020": "structured_local_session_6",
    "gate-cs-2021-session-1": "audited_image_2021_session_1",
    "gate-cs-2021-session-2": "structured_local_session_6",
    "gate-cs-2022": "structured_global_session_1",
    "gate-cs-2023": "structured_global_session_1",
    "gate-cs-2024-set-1": "structured_global_session_5",
    "gate-cs-2024-set-2": "structured_global_session_6",
    "gate-cs-2025-set-1": "structured_global_session_1",
    "gate-cs-2025-set-2": "structured_global_session_2",
}

EMBEDDED_PROFILES: dict[str, str] = {
    "gate-cs-2004": "secondary_2004_symbols_page_20",
    "gate-cs-2012": "booklet_code_a_2012_pages_18_19",
    "gate-cs-2014-session-1": "secondary_2014_session_1_page_22",
    "gate-cs-2014-session-2": "secondary_2014_session_2_page_45",
    "gate-cs-2014-session-3": "secondary_2014_session_3_page_67",
    "gate-cs-2015-session-1": "manual_visual_highlights",
    "gate-cs-2015-session-2": "manual_visual_highlights",
    "gate-cs-2015-session-3": "manual_visual_highlights",
    "gate-cs-2016-session-1": "structured_local_pages_21_22",
    "gate-cs-2016-session-2": "structured_local_pages_44_45",
    "gate-cs-2017-session-2": "structured_technical_first_pages_26_27",
    "gate-cs-2018": "structured_local_pages_24_26",
    "gate-cs-2019": "manual_image_only_embedded_key",
    "gate-cs-2020": "structured_local_session_6_pages_17_18",
    "gate-cs-2021-session-1": "manual_image_only_embedded_key",
}

CROSSCHECK_PROFILES: dict[str, str] = {
    "gate-cs-2021-session-2": "audited_image_2021_session_2",
}

# These observations describe pages that were rendered from the exact SHA-bound
# files and visually inspected.  They are audit evidence, not parser input.
VISUAL_VERIFICATION: dict[str, list[dict[str, Any]]] = {
    "201a7d66929a121f8d89d6277cf3774e1118dbf9dd48b8e99c7099ad37861e6c": [
        {"page": 1, "observation": "IITK Session 1 names the correct shift and declares 65 questions; Q1 has green/check option A."},
        {"page": 23, "observation": "Endpoint page contains Q65 and the final green/check MCQ option."},
    ],
    "99687d6b2679e106f747df67ce2cb728242f5ff655cadcc5c652947417612171": [
        {"page": 1, "observation": "IITK Session 2 names the correct shift and declares 65 questions; Q1 has green/check option C."},
        {"page": 25, "observation": "Endpoint page completes Q65 with NAT answer 19.2."},
    ],
    "e08dedac660110701c4af7b6477a723ac334b6184dd101719e571de11f5ed722": [
        {"page": 1, "observation": "IITK Session 3 names the correct shift and declares 65 questions; Q1 has green/check option B."},
        {"page": 27, "observation": "Endpoint page completes Q65 with the final green/check MCQ option D."},
    ],
    "856c52ae348b6b0583fdb1ee3d7664e9d5752bc50068ca6b33d334b2c453edd4": [
        {
            "page": 1,
            "observation": "CS-1 begins with GA Q1=C and contains GA Q9=C OR D.",
        },
        {
            "page": 3,
            "observation": "CS-1 ends at CS Q55 with NAT range 50 to 50.",
        },
        {
            "page": 4,
            "observation": "CS-2 begins on a new page with GA Q1=A.",
        },
        {
            "page": 6,
            "observation": "CS-2 ends at CS Q55 with NAT range 929 to 929.",
        },
    ],
    "5de4a3171f8e9629832f2080b178e802fc81945e44826ac45e82c635d9959f2e": [
        {"page": 1, "observation": "CS1 table starts at global Q1 (GA, MCQ A)."},
        {
            "page": 2,
            "observation": "CS1 table ends at global Q65 (CS-1, NAT 10 to 11).",
        },
    ],
    "cd046a9c634aad151adff94bae3addbcb846fb8ab78710e415c684b4b8bb966a": [
        {"page": 1, "observation": "CS2 table starts at global Q1 (GA, MCQ C)."},
        {
            "page": 2,
            "observation": "CS2 table ends at global Q65 (CS-2, NAT 0.70 to 0.80).",
        },
    ],
}


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AnswerKeyIndexError(f"{path} must contain a JSON object")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_file(
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
        candidates.extend(
            (
                Path.home() / "Downloads" / supplied,
                Path.home() / "Downloads" / "CS" / "CS" / supplied,
            )
        )
    candidates.extend((REPO_DIR / supplied, manifest_path.parent / supplied))
    for candidate in dict.fromkeys(path.resolve() for path in candidates):
        if candidate.is_file():
            return candidate
    raise AnswerKeyIndexError(
        f"Cannot resolve manifest file {raw_path!r}; checked "
        + ", ".join(str(path) for path in candidates)
    )


def _authority_level(authority: str) -> str:
    folded = authority.casefold()
    if "official" in folded and not folded.startswith("secondary"):
        return "official"
    return "secondary"


def _validate_source(source: KeySource) -> None:
    actual_bytes = source.path.stat().st_size
    if actual_bytes != source.expected_bytes:
        raise AnswerKeyIndexError(
            f"{source.paper_id}/{source.role}: byte-size mismatch for {source.path}; "
            f"expected {source.expected_bytes}, got {actual_bytes}"
        )
    actual_sha = _sha256(source.path)
    if actual_sha != source.sha256:
        raise AnswerKeyIndexError(
            f"{source.paper_id}/{source.role}: SHA-256 mismatch for {source.path}"
        )
    actual_pages = len(PdfReader(source.path).pages)
    if actual_pages != source.expected_pages:
        raise AnswerKeyIndexError(
            f"{source.paper_id}/{source.role}: page-count mismatch; "
            f"expected {source.expected_pages}, got {actual_pages}"
        )


def _manifest_sources(
    manifest: dict[str, Any], manifest_path: Path
) -> tuple[list[KeySource], list[dict[str, Any]]]:
    papers = manifest.get("papers")
    if not isinstance(papers, list) or len(papers) != EXPECTED_PAPER_COUNT:
        raise AnswerKeyIndexError("Manifest must contain the reviewed 39-paper inventory")

    sources: list[KeySource] = []
    skipped: list[dict[str, Any]] = []
    seen_paper_ids: set[str] = set()
    for paper in papers:
        paper_id = str(paper.get("id") or "")
        if not paper_id or paper_id in seen_paper_ids:
            raise AnswerKeyIndexError(f"Duplicate or missing manifest paper id: {paper_id!r}")
        seen_paper_ids.add(paper_id)
        year = int(paper["year"])

        if paper.get("answer_key_local_file"):
            profile = SEPARATE_PROFILES.get(paper_id)
            if profile is None:
                raise AnswerKeyIndexError(
                    f"{paper_id}: separate answer key has no reviewed parser profile"
                )
            raw_path = str(paper["answer_key_local_file"])
            authority = str(paper.get("answer_key_authority") or "unresolved")
            sources.append(
                KeySource(
                    paper_id=paper_id,
                    year=year,
                    role="answer_key",
                    raw_path=raw_path,
                    path=_resolve_file(
                        raw_path,
                        origin="repo_staging",
                        manifest_path=manifest_path,
                    ),
                    sha256=str(paper["answer_key_local_sha256"]).casefold(),
                    expected_bytes=int(paper["answer_key_local_bytes"]),
                    expected_pages=int(paper["answer_key_local_page_count"]),
                    authority=authority,
                    authority_level=_authority_level(authority),
                    source_url=paper.get("answer_key_url"),
                    index_url=paper.get("answer_key_index_url"),
                    parser_profile=profile,
                )
            )

        if paper.get("answer_key_in_local_file") is True:
            profile = EMBEDDED_PROFILES.get(paper_id)
            if profile is None:
                raise AnswerKeyIndexError(
                    f"{paper_id}: embedded answer key has no reviewed parser profile"
                )
            raw_path = str(paper["local_file"])
            authority = str(paper.get("source_authority") or "unresolved")
            embedded = KeySource(
                paper_id=paper_id,
                year=year,
                role="embedded_answer_key",
                raw_path=raw_path,
                path=_resolve_file(
                    raw_path,
                    origin=paper.get("local_file_origin"),
                    manifest_path=manifest_path,
                ),
                sha256=str(paper["local_sha256"]).casefold(),
                expected_bytes=int(paper["local_bytes"]),
                expected_pages=int(paper["local_page_count"]),
                authority=authority,
                authority_level="secondary",
                source_url=paper.get("question_paper_url"),
                index_url=paper.get("question_paper_index_url"),
                parser_profile=profile,
            )
            sources.append(embedded)

        for position, crosscheck in enumerate(
            paper.get("answer_key_crosscheck_sources") or [], start=1
        ):
            profile = CROSSCHECK_PROFILES.get(paper_id)
            if profile is None:
                raise AnswerKeyIndexError(
                    f"{paper_id}: answer-key crosscheck has no reviewed parser profile"
                )
            raw_path = str(crosscheck["local_file"])
            authority = str(crosscheck.get("authority") or "unresolved")
            sources.append(
                KeySource(
                    paper_id=paper_id,
                    year=year,
                    role=f"answer_key_crosscheck_{position}",
                    raw_path=raw_path,
                    path=_resolve_file(
                        raw_path,
                        origin="repo_staging",
                        manifest_path=manifest_path,
                    ),
                    sha256=str(crosscheck["local_sha256"]).casefold(),
                    expected_bytes=int(crosscheck["local_bytes"]),
                    expected_pages=int(crosscheck["local_page_count"]),
                    authority=authority,
                    authority_level=_authority_level(authority),
                    source_url=crosscheck.get("source_url"),
                    index_url=crosscheck.get("index_url"),
                    parser_profile=profile,
                )
            )

    return sources, skipped


def _clean(text: str) -> str:
    text = (
        text.replace("\u00a0", " ")
        .replace("\u2010", "-")
        .replace("\u2011", "-")
        .replace("\u2012", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u2212", "-")
        .replace("\uf0b7", " ")
    )
    # Some official PDFs expose a table row as ``1M C Q G A C 1``: the first
    # acronym is glued to the question number, so a leading word-boundary does
    # not exist.  Excluding only ASCII letters still permits that exact table
    # shape while avoiding substitutions inside ordinary words.
    text = re.sub(r"(?<![A-Za-z])M\s*C\s*Q\b", "MCQ", text, flags=re.IGNORECASE)
    text = re.sub(r"(?<![A-Za-z])M\s*S\s*Q\b", "MSQ", text, flags=re.IGNORECASE)
    text = re.sub(r"(?<![A-Za-z])N\s*A\s*T\b", "NAT", text, flags=re.IGNORECASE)
    text = re.sub(r"(?<![A-Za-z])G\s*A\b", "GA", text, flags=re.IGNORECASE)
    text = re.sub(r"(?<![A-Za-z])C\s*S\b", "CS", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


NUMBER = r"-?\d+(?:\.\d+)?"


def _options_answer(question_type: str, raw_key: str) -> dict[str, Any]:
    normalized = re.sub(r"\s+", " ", raw_key.upper()).strip()
    if normalized in {"MTA", "MARKS TO ALL"}:
        return {"kind": "marks_to_all"}
    alternatives = re.split(r"\s+OR\s+", normalized)
    parsed = [re.findall(r"[A-D]", part) for part in alternatives]
    if any(not choices for choices in parsed):
        raise AnswerKeyIndexError(f"Invalid {question_type} option key {raw_key!r}")
    if len(parsed) > 1:
        return {"kind": "options_any_of", "alternatives": parsed}
    choices = parsed[0]
    if question_type == "MCQ" and len(choices) != 1:
        raise AnswerKeyIndexError(f"MCQ key must select one option: {raw_key!r}")
    return {"kind": "options", "options": choices}


def _numeric_answer(raw_key: str) -> dict[str, Any]:
    normalized = _clean(raw_key)
    matches = re.findall(
        rf"({NUMBER})\s*(?:to|:)\s*({NUMBER})", normalized, re.IGNORECASE
    )
    if not matches:
        raise AnswerKeyIndexError(f"Invalid NAT range {raw_key!r}")
    return {
        "kind": "numeric_ranges",
        "ranges": [
            {"minimum": minimum, "maximum": maximum}
            for minimum, maximum in matches
        ],
    }


def _parse_answer_tail(
    question_type: str, tail: str
) -> tuple[str, dict[str, Any], int]:
    tail = _clean(tail)
    if question_type in {"MCQ", "MSQ"}:
        match = re.match(
            r"(MTA|Marks\s+to\s+All|[A-D](?:\s*(?:[,;]|OR)\s*[A-D])*)"
            r"\s*([12])(?=(?:\s*0)?(?:\s|$))",
            tail,
            re.IGNORECASE,
        )
        if not match:
            raise AnswerKeyIndexError(
                f"Could not parse {question_type} answer tail {tail[:100]!r}"
            )
        raw_key, marks_text = match.groups()
        return raw_key, _options_answer(question_type, raw_key), int(marks_text)

    match = re.match(
        rf"({NUMBER}\s*(?:to|:)\s*{NUMBER}"
        rf"(?:\s+OR\s+{NUMBER}\s*(?:to|:)\s*{NUMBER})*)"
        r"\s+([12])(?:\s*0)?(?:\s|$)",
        tail,
        re.IGNORECASE,
    )
    if match:
        raw_key, marks_text = match.groups()
        return raw_key, _numeric_answer(raw_key), int(marks_text)

    # Some older PDF text streams concatenate an integer range endpoint and
    # the marks column ("3 to 31" = "3 to 3", one mark).  This fallback is
    # accepted only when the complete tail has that exact table-cell shape.
    compact = re.match(
        rf"({NUMBER})\s*(?:to|:)\s*(-?\d+(?:\.\d+)?)([12])(?:\s|$)",
        tail,
        re.IGNORECASE,
    )
    if compact:
        minimum, maximum, marks_text = compact.groups()
        raw_key = f"{minimum} to {maximum}"
        return raw_key, _numeric_answer(raw_key), int(marks_text)
    raise AnswerKeyIndexError(f"Could not parse NAT answer tail {tail[:100]!r}")


def _structured_rows(
    path: Path,
    *,
    pages: Iterable[int] | None = None,
    session_number: int | None,
) -> list[tuple[int, str, int, str, dict[str, Any], int, str]]:
    reader = PdfReader(path)
    selected_pages = set(pages or range(1, len(reader.pages) + 1))
    rows: list[tuple[int, str, int, str, dict[str, Any], int, int]] = []
    if session_number is None:
        start_pattern = re.compile(
            r"(?<!\d)(\d{1,2})\s*(MCQ|MSQ|NAT)\s+(GA|CS(?:-\d)?)\s+",
            re.IGNORECASE,
        )
    else:
        start_pattern = re.compile(
            rf"(?<!\d)(\d{{1,2}})\s*{session_number}\s*"
            r"(MCQ|MSQ|NAT)\s+(GA|CS(?:-\d)?)\s+",
            re.IGNORECASE,
        )

    for page_number, page in enumerate(reader.pages, start=1):
        if page_number not in selected_pages:
            continue
        text = _clean(page.extract_text() or "")
        starts = list(start_pattern.finditer(text))
        for index, match in enumerate(starts):
            end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
            local_number = int(match.group(1))
            question_type = match.group(2).upper()
            section = "GA" if match.group(3).upper() == "GA" else "CS"
            raw_key, answer, marks = _parse_answer_tail(
                question_type, text[match.end() : end]
            )
            rows.append(
                (
                    local_number,
                    section,
                    page_number,
                    question_type,
                    answer,
                    marks,
                    raw_key,
                )
            )
    return rows


def _canonical_row(
    *,
    paper_id: str,
    year: int,
    numbering: str,
    local_number: int,
    section: str | None,
    page: int,
    question_type: str,
    answer: dict[str, Any],
    marks: int | None,
    raw_key: str,
    review_flags: tuple[str, ...] = (),
) -> ParsedRow:
    if year < 2014:
        canonical = local_number
        section_number = local_number
    elif numbering == "local_sections":
        if section not in {"GA", "CS"}:
            raise AnswerKeyIndexError(f"{paper_id}: section-local row lacks GA/CS")
        canonical = local_number if section == "GA" else local_number + 10
        section_number = local_number
    elif numbering == "technical_first_global":
        if section == "GA":
            canonical = local_number - 55
            section_number = canonical
        else:
            canonical = local_number + 10
            section_number = local_number
    elif numbering == "global":
        canonical = local_number
        section_number = local_number if section == "GA" else local_number - 10
    else:
        raise AnswerKeyIndexError(f"Unknown numbering policy {numbering!r}")
    if canonical < 1 or (year >= 2014 and canonical > 65):
        raise AnswerKeyIndexError(
            f"{paper_id}: invalid canonical ordinal {canonical} from {section}/{local_number}"
        )
    return ParsedRow(
        source_question_number=local_number,
        section=section,
        section_question_number=section_number,
        question_type=question_type,
        raw_key=raw_key,
        answer=answer,
        marks=marks,
        key_page=page,
        review_flags=review_flags,
    )


def _from_structured(
    source: KeySource,
    *,
    numbering: str,
    session_number: int | None,
    pages: Iterable[int] | None = None,
) -> list[ParsedRow]:
    result: list[ParsedRow] = []
    for local, section, page, question_type, answer, marks, raw_key in _structured_rows(
        source.path, pages=pages, session_number=session_number
    ):
        result.append(
            _canonical_row(
                paper_id=source.paper_id,
                year=source.year,
                numbering=numbering,
                local_number=local,
                section=section,
                page=page,
                question_type=question_type,
                answer=answer,
                marks=marks,
                raw_key=raw_key,
            )
        )
    return result


def _pre2014_marks(question_number: int) -> int:
    if 1 <= question_number <= 25 or 56 <= question_number <= 60:
        return 1
    return 2


def _booklet_code_a_rows(
    source: KeySource, *, pages: Iterable[int]
) -> list[ParsedRow]:
    reader = PdfReader(source.path)
    result: list[ParsedRow] = []
    for page_number in pages:
        text = reader.pages[page_number - 1].extract_text() or ""
        for line in text.splitlines():
            cleaned = _clean(line)
            match = re.match(
                # Code-A values for several rows are concatenated to the
                # ordinal in this PDF's text stream (for example ``CS 1B``).
                r"CS\s+(\d{1,2})\s*(Marks\s+to\s+All|[A-D])(?=\s|$)",
                cleaned,
                re.IGNORECASE,
            )
            if not match:
                continue
            number = int(match.group(1))
            raw_key = match.group(2)
            section = "CS" if number <= 55 else "GA"
            result.append(
                ParsedRow(
                    source_question_number=number,
                    section=section,
                    section_question_number=number if section == "CS" else number - 55,
                    question_type="MCQ",
                    raw_key=raw_key,
                    answer=_options_answer("MCQ", raw_key),
                    marks=_pre2014_marks(number),
                    key_page=page_number,
                )
            )
    return result


def _verified_2013_booklet_rows(source: KeySource) -> list[ParsedRow]:
    """Parse all four official booklet columns and emit canonical booklet-A rows.

    The 2013 paper used four reordered booklet codes.  Parsing only the first
    column would recover answers, but would not prove that the key and the
    separately reviewed 260-occurrence booklet map describe the same paper.
    This parser therefore checks every A/B/C/D occurrence before emitting the
    65 canonical booklet-A claims.
    """

    mapping = _read_json(DEFAULT_2013_BOOKLET_MAP)
    if mapping.get("paper_id") != source.paper_id:
        raise AnswerKeyIndexError(
            f"{source.paper_id}: 2013 booklet map has the wrong paper identity"
        )
    if mapping.get("canonical_booklet_code") != "A":
        raise AnswerKeyIndexError(
            f"{source.paper_id}: 2013 canonical booklet must be code A"
        )
    key_evidence = (mapping.get("derivation") or {}).get("answer_key_crosscheck") or {}
    if str(key_evidence.get("source_pdf_sha256") or "").casefold() != source.sha256:
        raise AnswerKeyIndexError(
            f"{source.paper_id}: 2013 key hash does not match the booklet-map evidence"
        )
    if key_evidence.get("mismatch_count") != 0:
        raise AnswerKeyIndexError(
            f"{source.paper_id}: 2013 booklet-map key cross-check is not clean"
        )

    cell = r"(Marks\s+to\s+All|[A-D])"
    row_pattern = re.compile(
        # Several two-digit labels are exposed as ``C S  1 0`` by the PDF
        # text layer.  Accept optional whitespace *inside* the two-digit
        # label, then remove it before integer conversion.
        rf"^CS\s+(\d(?:\s*\d)?)\s*{cell}\s*{cell}\s*{cell}\s*{cell}\s*$",
        re.IGNORECASE,
    )
    values: dict[str, dict[int, tuple[str, int]]] = {
        code: {} for code in ("A", "B", "C", "D")
    }
    for page_number, page in enumerate(PdfReader(source.path).pages, start=1):
        for line in (page.extract_text() or "").splitlines():
            match = row_pattern.match(_clean(line))
            if not match:
                continue
            label = int(re.sub(r"\s+", "", match.group(1)))
            for code, raw_key in zip(("A", "B", "C", "D"), match.groups()[1:]):
                if label in values[code]:
                    raise AnswerKeyIndexError(
                        f"{source.paper_id}: duplicate code-{code} key row {label}"
                    )
                values[code][label] = (_clean(raw_key), page_number)

    expected = set(range(1, 66))
    for code, rows in values.items():
        if set(rows) != expected:
            raise AnswerKeyIndexError(
                f"{source.paper_id}: code-{code} key rows mismatch; "
                f"missing={sorted(expected - set(rows))}, "
                f"extra={sorted(set(rows) - expected)}"
            )

    items = mapping.get("items")
    if not isinstance(items, list) or len(items) != 65:
        raise AnswerKeyIndexError(
            f"{source.paper_id}: 2013 booklet map must contain 65 canonical items"
        )
    seen_ordinals: set[int] = set()
    seen_occurrences: set[tuple[str, int]] = set()
    rows: list[ParsedRow] = []
    for item in items:
        canonical = int(item["canonical_ordinal"])
        if canonical in seen_ordinals or canonical not in expected:
            raise AnswerKeyIndexError(
                f"{source.paper_id}: duplicate or invalid canonical ordinal {canonical}"
            )
        seen_ordinals.add(canonical)
        occurrences = item.get("occurrences")
        if not isinstance(occurrences, list) or len(occurrences) != 4:
            raise AnswerKeyIndexError(
                f"{source.paper_id}: canonical Q{canonical} must have four occurrences"
            )
        if {str(occ["booklet_code"]) for occ in occurrences} != set(values):
            raise AnswerKeyIndexError(
                f"{source.paper_id}: canonical Q{canonical} lacks an A/B/C/D bijection"
            )

        raw_key, key_page = values["A"][canonical]
        canonical_fingerprint = _clean(raw_key).casefold()
        for occurrence in occurrences:
            code = str(occurrence["booklet_code"])
            label = int(occurrence["item_label"])
            occurrence_id = (code, label)
            if occurrence_id in seen_occurrences:
                raise AnswerKeyIndexError(
                    f"{source.paper_id}: duplicate code-{code} occurrence Q{label}"
                )
            seen_occurrences.add(occurrence_id)
            occurrence_key = values[code][label][0]
            if _clean(occurrence_key).casefold() != canonical_fingerprint:
                raise AnswerKeyIndexError(
                    f"{source.paper_id}: key mismatch for canonical Q{canonical}; "
                    f"code {code} Q{label}={occurrence_key!r}, code A={raw_key!r}"
                )

        section = "CS" if canonical <= 55 else "GA"
        rows.append(
            ParsedRow(
                source_question_number=canonical,
                section=section,
                section_question_number=(
                    canonical if section == "CS" else canonical - 55
                ),
                question_type="MCQ",
                raw_key=raw_key,
                answer=_options_answer("MCQ", raw_key),
                marks=_pre2014_marks(canonical),
                key_page=key_page,
                review_flags=(
                    "verified_against_all_260_booklet_occurrences_exact_sha",
                ),
            )
        )
    if seen_ordinals != expected:
        raise AnswerKeyIndexError(
            f"{source.paper_id}: 2013 canonical booklet rows are incomplete"
        )
    expected_occurrences = {
        (code, label) for code in values for label in expected
    }
    if seen_occurrences != expected_occurrences:
        missing = sorted(expected_occurrences - seen_occurrences)
        extra = sorted(seen_occurrences - expected_occurrences)
        raise AnswerKeyIndexError(
            f"{source.paper_id}: 2013 occurrence bijection is incomplete; "
            f"missing={missing}, extra={extra}"
        )
    return sorted(rows, key=lambda row: row.source_question_number)


def _secondary_2004_rows(source: KeySource) -> list[ParsedRow]:
    text = PdfReader(source.path).pages[19].extract_text() or ""
    symbols = re.findall(r"\(([^)]*)\)", text)
    if len(symbols) != 90:
        raise AnswerKeyIndexError(
            f"{source.paper_id}: expected 90 parenthesized key symbols, got {len(symbols)}"
        )
    result: list[ParsedRow] = []
    for number, symbol in enumerate(symbols, start=1):
        cleaned = symbol.strip().upper()
        flags = ["secondary_single_source_requires_independent_confirmation"]
        if cleaned in {"A", "B", "C", "D"}:
            answer = _options_answer("MCQ", cleaned)
        elif cleaned == "*":
            answer = {"kind": "unresolved_source_symbol", "symbol": "*"}
            flags.append("source_symbol_meaning_requires_review")
        elif cleaned == "":
            answer = {"kind": "unresolved_source_symbol", "symbol": ""}
            flags.append("blank_key_cell")
        else:
            raise AnswerKeyIndexError(f"Unexpected 2004 key symbol {cleaned!r}")
        result.append(
            ParsedRow(
                source_question_number=number,
                section=None,
                section_question_number=number,
                question_type="MCQ",
                raw_key=cleaned,
                answer=answer,
                marks=None,
                key_page=20,
                review_flags=tuple(flags + ["marks_not_present_in_key_table"]),
            )
        )
    return result


def _secondary_2014_rows(
    source: KeySource,
    page_number: int,
    *,
    review_flags: tuple[str, ...] = (
        "secondary_single_source_requires_independent_confirmation",
    ),
) -> list[ParsedRow]:
    text = _clean(PdfReader(source.path).pages[page_number - 1].extract_text() or "")
    start_pattern = re.compile(r"\b(GA|CS)\s+(\d{1,2})\s+", re.IGNORECASE)
    starts = list(start_pattern.finditer(text))
    result: list[ParsedRow] = []
    for index, match in enumerate(starts):
        section = match.group(1).upper()
        number = int(match.group(2))
        if section == "GA" and not 1 <= number <= 10:
            continue
        if section == "CS" and not 1 <= number <= 55:
            continue
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        tail = text[match.end() : end]
        question_type = "NAT" if re.match(rf"{NUMBER}\s+(?:to|:)", tail) else "MCQ"
        raw_key, answer, marks = _parse_answer_tail(question_type, tail)
        result.append(
            _canonical_row(
                paper_id=source.paper_id,
                year=source.year,
                numbering="local_sections",
                local_number=number,
                section=section,
                page=page_number,
                question_type=question_type,
                answer=answer,
                marks=marks,
                raw_key=raw_key,
                review_flags=review_flags,
            )
        )
    return result


def _append_group(
    rows: list[ParsedRow],
    *,
    section: str,
    start: int,
    question_type: str,
    keys: list[str],
    marks: int,
    page_for: Any,
) -> None:
    for offset, raw_key in enumerate(keys):
        number = start + offset
        rows.append(
            ParsedRow(
                source_question_number=number,
                section=section,
                section_question_number=number,
                question_type=question_type,
                raw_key=raw_key,
                answer=(
                    _numeric_answer(raw_key)
                    if question_type == "NAT"
                    else _options_answer(question_type, raw_key)
                ),
                marks=marks,
                key_page=int(page_for(section, number)),
            )
        )


# Exact-SHA transcriptions of the IIT Kanpur 2015 key PDFs.  The PDFs encode
# MCQ answers as four embedded option-row images (one green/check row and three
# red/cross rows), while NAT answers are embedded text.  Each tuple below was
# produced by walking the image XObjects in content-stream order and selecting
# the sole green row in every group of four.  The parser independently recovers
# all 65 question numbers/types/pages from the PDF text and rejects a mismatch.
AUDITED_2015_KEYS: dict[int, tuple[str, ...]] = {
    1: (
        "A", "C", "B", "A", "A", "C", "A", "32", "D", "C", "A", "C", "C",
        "B", "A", "C", "A", "C", "C", "C", "D", "A", "B", "C", "C", "B",
        "A", "D", "4", "3", "D", "C", "5", "-5", "B", "160", "B", "5",
        "0.40 to 0.46", "A", "0.99", "D", "B", "24", "A", "C", "8", "4",
        "1", "B", "D", "12", "A", "14020", "3.2", "10", "A", "-1", "D",
        "A", "2", "A", "69", "D", "B",
    ),
    2: (
        "C", "C", "D", "C", "C", "A", "B", "8", "B", "A", "C", "2048", "D",
        "36", "6", "D", "3", "14", "22", "D", "D", "A", "19", "51", "C", "A",
        "C", "C", "A", "D", "B", "5", "B", "12", "A", "A", "C", "C", "A", "C",
        "A", "6.1 to 6.2", "36", "B", "3", "A", "C", "5", "A", "B", "C", "15",
        "13", "D", "1", "C", "0", "36", "0.95", "C", "D", "B", "C", "C", "19.2",
    ),
    3: (
        "B", "B", "C", "B", "C", "A", "B", "2006", "B", "B", "C", "D", "C",
        "D", "C", "B", "612 to 613", "B", "A", "C", "199", "80", "B", "C", "15",
        "A", "B", "C", "A", "D", "A", "B", "28", "A", "D", "308 to 310", "B",
        "B", "50", "A", "C", "230", "140", "B", "D", "158", "8", "3", "B", "C",
        "B", "C", "10", "A", "995", "1575", "C", "A", "5", "C", "0.75", "3", "0",
        "D", "D",
    ),
}


def _audited_2015_rows(source: KeySource, session: int) -> list[ParsedRow]:
    reader = PdfReader(source.path)
    metadata: dict[int, tuple[str, int]] = {}
    pattern = re.compile(
        r"Question\s+Number\s*:\s*(\d+)\s+Question\s+Type\s*:\s*(MCQ|NAT)",
        re.IGNORECASE,
    )
    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        for match in pattern.finditer(text):
            number = int(match.group(1))
            if number in metadata:
                raise AnswerKeyIndexError(
                    f"{source.paper_id}: duplicate visual-key question {number}"
                )
            metadata[number] = (match.group(2).upper(), page_number)
    expected = set(range(1, 66))
    if set(metadata) != expected:
        missing = sorted(expected - set(metadata))
        extra = sorted(set(metadata) - expected)
        raise AnswerKeyIndexError(
            f"{source.paper_id}: visual-key metadata mismatch; missing={missing}, extra={extra}"
        )

    keys = AUDITED_2015_KEYS[session]
    if len(keys) != 65:
        raise AnswerKeyIndexError(f"2015 session {session}: audited key must have 65 rows")
    rows: list[ParsedRow] = []
    for number, key in enumerate(keys, start=1):
        question_type, page_number = metadata[number]
        is_option = key in {"A", "B", "C", "D"}
        if (question_type == "MCQ") != is_option:
            raise AnswerKeyIndexError(
                f"{source.paper_id}: audited key/type mismatch at Q{number}: "
                f"{question_type}/{key}"
            )
        raw_key = key if is_option or " to " in key else f"{key} to {key}"
        answer = (
            _options_answer("MCQ", raw_key)
            if is_option
            else _numeric_answer(raw_key)
        )
        rows.append(
            _canonical_row(
                paper_id=source.paper_id,
                year=2015,
                numbering="global",
                local_number=number,
                section="GA" if number <= 10 else "CS",
                page=page_number,
                question_type=question_type,
                answer=answer,
                marks=(1 if number <= 5 or 11 <= number <= 35 else 2),
                raw_key=raw_key,
                review_flags=(
                    "audited_green_check_image_rows_exact_sha"
                    if is_option
                    else "embedded_nat_text_exact_sha"
                ,),
            )
        )
    return rows


def _audited_2021_rows(session: int) -> list[ParsedRow]:
    """Rows transcribed from the rendered exact-SHA official merged key.

    The PDF is image-only.  Keeping the reviewed table as code makes the source
    checksum and the human transcription auditable; OCR output is never trusted
    silently and a different file hash fails before these rows are used.
    """

    if session == 1:
        page_for = lambda section, q: (
            1
            if section == "GA" or q <= 11
            else 2
            if q <= 34
            else 3
        )
        groups = [
            ("GA", 1, "MCQ", "C A C A C".split(), 1),
            ("GA", 6, "MCQ", ["C", "C", "C", "C OR D", "D"], 2),
            ("CS", 1, "MCQ", "C C D C C A B C C D".split(), 1),
            ("CS", 11, "MSQ", ["A;C", "D", "A", "A;C", "A;C"], 1),
            (
                "CS",
                16,
                "NAT",
                [
                    "11 to 11",
                    "3 to 3",
                    "0.35 to 0.39",
                    "65 to 65",
                    "0.25 to 0.25",
                    "86 to 86",
                    "17 to 17",
                    "819 to 820 OR 205 to 205",
                    "-7.75 to -7.75",
                    "12 to 12",
                ],
                1,
            ),
            (
                "CS",
                26,
                "MCQ",
                "B C A A C A B A B D A B D A".split(),
                2,
            ),
            (
                "CS",
                40,
                "MSQ",
                ["A;C", "B", "B;C;D", "C", "A;B;C", "A;C", "A;B;D", "C"],
                2,
            ),
            (
                "CS",
                48,
                "NAT",
                [
                    "1023 to 1023",
                    "50 to 52",
                    "6 to 6",
                    "50 to 50",
                    "3 to 3",
                    "17160 to 17160",
                    "0.04 to 0.04",
                    "50 to 50",
                ],
                2,
            ),
        ]
    elif session == 2:
        page_for = lambda section, q: (
            4
            if section == "GA" or q <= 11
            else 5
            if q <= 34
            else 6
        )
        groups = [
            ("GA", 1, "MCQ", "A B B B C".split(), 1),
            ("GA", 6, "MCQ", "C A C A C".split(), 2),
            ("CS", 1, "MCQ", "C C C C A D C B C C".split(), 1),
            ("CS", 11, "MSQ", ["B;C", "B;C;D", "D", "A;C;D", "B;D"], 1),
            (
                "CS",
                16,
                "NAT",
                [
                    "1 to 1",
                    "256 to 256",
                    "3 to 3",
                    "2 to 2",
                    "80000 to 80000",
                    "698 to 698",
                    "15.00 to 16.00",
                    "15 to 15",
                    "4 to 4",
                    "19 to 19",
                ],
                1,
            ),
            (
                "CS",
                26,
                "MCQ",
                "B A B D D B B A C D C B A C".split(),
                2,
            ),
            (
                "CS",
                40,
                "MSQ",
                [
                    "A;C;D",
                    "B;C;D",
                    "A;D",
                    "A;B;C",
                    "A;D",
                    "B;C",
                    "A;B",
                    "A;B;C",
                ],
                2,
            ),
            (
                "CS",
                48,
                "NAT",
                [
                    "4108 to 4108",
                    "60 to 60",
                    "59049 to 59049",
                    "8 to 8",
                    "6 to 6",
                    "1.87 to 1.88",
                    "130 to 140",
                    "929 to 929",
                ],
                2,
            ),
        ]
    else:
        raise AnswerKeyIndexError(f"Unsupported audited 2021 session {session}")

    rows: list[ParsedRow] = []
    for section, start, question_type, keys, marks in groups:
        _append_group(
            rows,
            section=section,
            start=start,
            question_type=question_type,
            keys=list(keys),
            marks=marks,
            page_for=page_for,
        )
    return [
        _canonical_row(
            paper_id=f"gate-cs-2021-session-{session}",
            year=2021,
            numbering="local_sections",
            local_number=row.source_question_number,
            section=row.section,
            page=row.key_page,
            question_type=row.question_type,
            answer=row.answer,
            marks=row.marks,
            raw_key=row.raw_key,
            review_flags=("audited_image_table_exact_sha",),
        )
        for row in rows
    ]


def _parse_source(source: KeySource) -> tuple[list[ParsedRow], str | None]:
    profile = source.parser_profile
    if profile == "booklet_code_a_2011":
        return _booklet_code_a_rows(source, pages=(1, 2)), None
    if profile == "booklet_code_a_2012":
        return _booklet_code_a_rows(source, pages=(1, 2)), None
    if profile == "verified_booklet_table_2013":
        return _verified_2013_booklet_rows(source), None
    if profile == "booklet_code_a_2012_pages_18_19":
        return _booklet_code_a_rows(source, pages=(18, 19)), None
    if profile == "secondary_2004_symbols_page_20":
        return _secondary_2004_rows(source), None
    if profile.startswith("secondary_2014_session_"):
        page = {"gate-cs-2014-session-1": 22, "gate-cs-2014-session-2": 45, "gate-cs-2014-session-3": 67}[source.paper_id]
        return _secondary_2014_rows(source, page), None
    if profile == "untyped_local_2014":
        return _secondary_2014_rows(source, 1, review_flags=()), None
    if profile == "structured_technical_first_no_session":
        return _from_structured(source, numbering="technical_first_global", session_number=None), None
    if profile == "structured_technical_first_pages_26_27":
        return _from_structured(source, numbering="technical_first_global", session_number=None, pages=(26, 27)), None
    if profile in {"structured_local_no_session", "structured_local_pages_24_26"}:
        pages = (24, 25, 26) if profile.endswith("pages_24_26") else None
        return _from_structured(source, numbering="local_sections", session_number=None, pages=pages), None
    if profile == "structured_local_session_6":
        return _from_structured(source, numbering="local_sections", session_number=6), None
    if profile == "structured_local_session_6_pages_17_18":
        return _from_structured(source, numbering="local_sections", session_number=6, pages=(17, 18)), None
    if profile == "structured_local_pages_21_22":
        return _from_structured(source, numbering="local_sections", session_number=None, pages=(21, 22)), None
    if profile == "structured_local_pages_44_45":
        return _from_structured(source, numbering="local_sections", session_number=None, pages=(44, 45)), None
    if profile.startswith("structured_global_session_"):
        session = int(profile.rsplit("_", 1)[1])
        return _from_structured(source, numbering="global", session_number=session), None
    if profile == "audited_image_2021_session_1":
        return _audited_2021_rows(1), None
    if profile == "audited_image_2021_session_2":
        return _audited_2021_rows(2), None
    if profile.startswith("audited_visual_2015_session_"):
        session = int(profile.rsplit("_", 1)[1])
        return _audited_2015_rows(source, session), None
    if profile == "manual_visual_highlights":
        return [], "correct options are encoded as visual highlights, not a deterministic key table"
    if profile == "manual_image_only_embedded_key":
        return [], "embedded key pages are image-only; a separate official key covers this paper"
    raise AnswerKeyIndexError(f"Unknown parser profile {profile!r}")


def _item_label(year: int, canonical_ordinal: int) -> str:
    if year >= 2014:
        return (
            f"GA-{canonical_ordinal}"
            if canonical_ordinal <= 10
            else f"CS-{canonical_ordinal - 10}"
        )
    return str(canonical_ordinal)


def _claim(source: KeySource, row: ParsedRow) -> dict[str, Any]:
    if source.year >= 2014:
        canonical = (
            row.section_question_number
            if row.section == "GA"
            else int(row.section_question_number or 0) + 10
        )
    else:
        canonical = row.source_question_number
    if canonical <= 0:
        raise AnswerKeyIndexError(f"{source.paper_id}: invalid canonical row {row}")
    return {
        "claim_id": hashlib.sha256(
            f"{source.sha256}:{source.paper_id}:{canonical}:{source.role}".encode()
        ).hexdigest(),
        "source_paper_id": source.paper_id,
        "canonical_ordinal": canonical,
        "item_label": _item_label(source.year, canonical),
        "source_question_number": row.source_question_number,
        "section": row.section,
        "section_question_number": row.section_question_number,
        "question_type": row.question_type,
        "marks": row.marks,
        "raw_key": row.raw_key,
        "answer": row.answer,
        "key_page": row.key_page,
        "source_role": source.role,
        "source_file": source.raw_path,
        "source_sha256": source.sha256,
        "source_authority": source.authority,
        "source_authority_level": source.authority_level,
        "source_url": source.source_url,
        "source_index_url": source.index_url,
        "parser_profile": source.parser_profile,
        "review_flags": list(row.review_flags),
    }


def _fingerprint(claim: dict[str, Any]) -> str:
    return json.dumps(
        {
            "question_type": claim["question_type"],
            "marks": claim["marks"],
            "answer": claim["answer"],
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _resolve_claims(
    claims: list[dict[str, Any]], papers: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for claim in claims:
        grouped[(claim["source_paper_id"], claim["canonical_ordinal"])].append(claim)

    resolutions: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    paper_by_id = {paper["id"]: paper for paper in papers}
    for paper in papers:
        expected = int(paper["expected_item_count"])
        for ordinal in range(1, expected + 1):
            current = grouped.get((paper["id"], ordinal), [])
            if not current:
                gaps.append(
                    {
                        "source_paper_id": paper["id"],
                        "canonical_ordinal": ordinal,
                        "item_label": _item_label(int(paper["year"]), ordinal),
                        "reason": (
                            "deferred_to_verified_2013_booklet_bijection"
                            if paper["id"] == "gate-cs-2013"
                            else "no_deterministically_parsed_answer_claim"
                        ),
                    }
                )
                continue

            official = [
                claim
                for claim in current
                if claim["source_authority_level"] == "official"
            ]
            official_fingerprints = {_fingerprint(claim) for claim in official}
            all_fingerprints = defaultdict(list)
            for claim in current:
                all_fingerprints[_fingerprint(claim)].append(claim)

            selected: dict[str, Any] | None = None
            if len(official_fingerprints) > 1:
                status = "official_conflict"
                conflicts.append(
                    {
                        "source_paper_id": paper["id"],
                        "canonical_ordinal": ordinal,
                        "kind": "official_claim_conflict",
                        "claim_ids": [claim["claim_id"] for claim in official],
                    }
                )
            elif official:
                selected = official[0]
                status = "official"
                selected_fp = _fingerprint(selected)
                disagreeing = [
                    claim for claim in current if _fingerprint(claim) != selected_fp
                ]
                if disagreeing:
                    conflicts.append(
                        {
                            "source_paper_id": paper["id"],
                            "canonical_ordinal": ordinal,
                            "kind": "secondary_disagrees_with_official",
                            "official_claim_ids": [
                                claim["claim_id"] for claim in official
                            ],
                            "disagreeing_claim_ids": [
                                claim["claim_id"] for claim in disagreeing
                            ],
                        }
                    )
            else:
                independently_supported = [
                    bucket
                    for bucket in all_fingerprints.values()
                    if len({claim["source_sha256"] for claim in bucket}) >= 2
                ]
                if len(independently_supported) == 1:
                    selected = independently_supported[0][0]
                    status = "secondary_two_source_agreement"
                elif len(independently_supported) > 1:
                    status = "secondary_conflict"
                    conflicts.append(
                        {
                            "source_paper_id": paper["id"],
                            "canonical_ordinal": ordinal,
                            "kind": "secondary_claim_conflict",
                            "claim_ids": [claim["claim_id"] for claim in current],
                        }
                    )
                else:
                    status = "secondary_single_source_unverified"

            resolutions.append(
                {
                    "source_paper_id": paper["id"],
                    "canonical_ordinal": ordinal,
                    "item_label": _item_label(int(paper["year"]), ordinal),
                    "status": status,
                    "selected_answer": selected["answer"] if selected else None,
                    "selected_question_type": (
                        selected["question_type"] if selected else None
                    ),
                    "selected_marks": selected["marks"] if selected else None,
                    "supporting_claim_ids": [
                        claim["claim_id"]
                        for claim in current
                        if selected is not None
                        and _fingerprint(claim) == _fingerprint(selected)
                    ],
                    "claim_ids": [claim["claim_id"] for claim in current],
                }
            )

    # Guard against any claim outside the declared paper range.
    declared = {
        (paper["id"], ordinal)
        for paper in papers
        for ordinal in range(1, int(paper["expected_item_count"]) + 1)
    }
    extras = sorted(set(grouped) - declared)
    if extras:
        raise AnswerKeyIndexError(f"Claims outside manifest ranges: {extras[:5]}")
    return resolutions, conflicts, gaps


def build_index(
    manifest_path: Path = DEFAULT_MANIFEST,
    *,
    verify_source_hashes: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest_path = manifest_path.resolve()
    manifest = _read_json(manifest_path)
    papers = manifest["papers"]
    sources, skipped = _manifest_sources(manifest, manifest_path)

    claims: list[dict[str, Any]] = []
    source_reports: list[dict[str, Any]] = []
    for source in sources:
        if verify_source_hashes:
            _validate_source(source)
        rows, skip_reason = _parse_source(source)
        canonical_ordinals: set[int] = set()
        source_claims: list[dict[str, Any]] = []
        for row in rows:
            claim = _claim(source, row)
            ordinal = int(claim["canonical_ordinal"])
            if ordinal in canonical_ordinals:
                raise AnswerKeyIndexError(
                    f"{source.paper_id}/{source.role}: duplicate canonical ordinal {ordinal}"
                )
            canonical_ordinals.add(ordinal)
            source_claims.append(claim)
        claims.extend(source_claims)
        source_reports.append(
            {
                "source_paper_id": source.paper_id,
                "role": source.role,
                "file": source.raw_path,
                "sha256": source.sha256,
                "bytes": source.expected_bytes,
                "pages": source.expected_pages,
                "authority": source.authority,
                "authority_level": source.authority_level,
                "source_url": source.source_url,
                "index_url": source.index_url,
                "parser_profile": source.parser_profile,
                "parse_status": "manual_gap" if skip_reason else "parsed",
                "parsed_claim_count": len(source_claims),
                "skip_reason": skip_reason,
                "canonical_ordinals": sorted(canonical_ordinals),
                "visual_verification": VISUAL_VERIFICATION.get(source.sha256, []),
            }
        )

    claims.sort(
        key=lambda claim: (
            claim["source_paper_id"],
            claim["canonical_ordinal"],
            claim["source_role"],
            claim["source_sha256"],
        )
    )
    claim_ids = [claim["claim_id"] for claim in claims]
    if len(claim_ids) != len(set(claim_ids)):
        raise AnswerKeyIndexError("Duplicate claim_id generated")

    resolutions, conflicts, gaps = _resolve_claims(claims, papers)
    resolutions.sort(key=lambda row: (row["source_paper_id"], row["canonical_ordinal"]))
    conflicts.sort(key=lambda row: (row["source_paper_id"], row["canonical_ordinal"], row["kind"]))
    gaps.sort(key=lambda row: (row["source_paper_id"], row["canonical_ordinal"]))

    source_declarations = []
    for paper in papers:
        source_declarations.append(str(paper["local_file"]))
        if paper.get("answer_key_local_file"):
            source_declarations.append(str(paper["answer_key_local_file"]))
        for crosscheck in paper.get("answer_key_crosscheck_sources") or []:
            source_declarations.append(str(crosscheck["local_file"]))

    summary = {
        "paper_count": len(papers),
        "manifest_file_declaration_count": len(source_declarations),
        "manifest_unique_file_count": len(set(source_declarations)),
        "answer_source_count": len(sources),
        "parsed_source_count": sum(
            report["parse_status"] == "parsed" for report in source_reports
        ),
        "manual_gap_source_count": sum(
            report["parse_status"] == "manual_gap" for report in source_reports
        ),
        "claim_count": len(claims),
        "official_claim_count": sum(
            claim["source_authority_level"] == "official" for claim in claims
        ),
        "secondary_claim_count": sum(
            claim["source_authority_level"] == "secondary" for claim in claims
        ),
        "official_resolution_count": sum(
            row["status"] == "official" for row in resolutions
        ),
        "secondary_two_source_resolution_count": sum(
            row["status"] == "secondary_two_source_agreement"
            for row in resolutions
        ),
        "secondary_unverified_count": sum(
            row["status"] == "secondary_single_source_unverified"
            for row in resolutions
        ),
        "conflict_count": len(conflicts),
        "gap_count": len(gaps),
        "claims_by_paper": dict(
            sorted(Counter(claim["source_paper_id"] for claim in claims).items())
        ),
        "official_resolutions_by_paper": dict(
            sorted(
                Counter(
                    row["source_paper_id"]
                    for row in resolutions
                    if row["status"] == "official"
                ).items()
            )
        ),
    }

    artifact: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_from_manifest_validation_date": manifest.get("validation_date"),
        "production_import_authorized": False,
        "practice_promotion_authorized": False,
        "authority_policy": {
            "official": "A checksum-bound official final key may resolve a row unless official sources conflict.",
            "secondary": "At least two distinct source-file hashes must agree; a single community source remains unverified.",
        },
        "manifest_sha256": _sha256(manifest_path),
        "sources": source_reports,
        "claims": claims,
        "resolutions": resolutions,
        "conflicts": conflicts,
        "gaps": gaps,
        "summary": summary,
    }
    canonical = json.dumps(artifact, sort_keys=True, separators=(",", ":")).encode()
    artifact["artifact_version"] = hashlib.sha256(canonical).hexdigest()

    report = {
        "schema_version": SCHEMA_VERSION,
        "production_import_authorized": False,
        "practice_promotion_authorized": False,
        "artifact_version": artifact["artifact_version"],
        "summary": summary,
        "source_reports": source_reports,
        "conflicts": conflicts,
        "paper_gaps": dict(
            sorted(Counter(row["source_paper_id"] for row in gaps).items())
        ),
        "skipped": skipped,
    }
    return artifact, report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--skip-source-hash-verification",
        action="store_true",
        help="Tests only: skip file byte/hash/page verification.",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    artifact, report = build_index(
        args.manifest,
        verify_source_hashes=not args.skip_source_hash_verification,
    )
    _write_json(args.output, artifact)
    _write_json(args.report, report)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "report": str(args.report),
                **artifact["summary"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
