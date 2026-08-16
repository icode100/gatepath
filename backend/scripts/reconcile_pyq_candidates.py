"""Build a deterministic, staging-only PYQ candidate reconciliation artifact.

The canonical archive remains the inventory authority.  This script joins the
ignored GateOverflow locator/page-text cache and the ignored sanitized
ExamSIDE index to those canonical slots without opening a database.  Secondary
content is retained only as a review candidate and can never become practice
eligible here.

Important boundaries:

* paper/slot joins are explicit or unique normalized-text joins;
* ambiguous rows are withheld and explained;
* third-party worked explanations are never copied;
* remote images are recorded as untrusted, not fetched assets;
* source/key evidence requirements are reported, never inferred.
"""

from __future__ import annotations

import argparse
import hashlib
import html as html_lib
import json
import math
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import build_canonical_pyq_archive as canonical_builder  # noqa: E402
import index_gateoverflow_reference as gateoverflow_index  # noqa: E402
import pyq_slot_classification as slot_classification  # noqa: E402
import pyq_topic_classification as topic_classification  # noqa: E402


REPO_DIR = Path(__file__).resolve().parents[2]
DEFAULT_CANONICAL = (
    REPO_DIR / "tmp" / "pyq" / "build" / "canonical_pyq_archive.json"
)
DEFAULT_MANIFEST = REPO_DIR / "backend" / "data" / "pyq_source_manifest.json"
DEFAULT_GO_INDEX = (
    REPO_DIR
    / "tmp"
    / "pyq"
    / "reference"
    / "extracted"
    / "question_locator_index.jsonl"
)
DEFAULT_GO_PAGES = DEFAULT_GO_INDEX.parent
DEFAULT_EXAMSIDE_INDEX = (
    REPO_DIR
    / "tmp"
    / "pyq"
    / "reference"
    / "examside"
    / "examside_reference_index.jsonl"
)
DEFAULT_TOPIC_INVENTORY = (
    REPO_DIR / "backend" / "data" / "question_bank_manifest.json"
)
DEFAULT_TOPIC_ALIASES = (
    REPO_DIR / "backend" / "data" / "pyq_topic_aliases.json"
)
DEFAULT_SLOT_CLASSIFICATIONS = (
    REPO_DIR / "backend" / "data" / "pyq_slot_classification_overrides.json"
)
DEFAULT_ORIGINAL_PROVENANCE = (
    REPO_DIR / "tmp" / "pyq" / "build" / "original_pdf_provenance.json"
)
DEFAULT_OUTPUT = (
    REPO_DIR / "tmp" / "pyq" / "build" / "canonical_pyq_candidates.json"
)

SCHEMA_VERSION = "1.0-staging"
EXPECTED_PAPER_COUNT = 39
EXPECTED_SLOT_COUNT = 2712

EXAMSIDE_SUBJECT_TO_COURSE = {
    "general-aptitude": "GA",
    "discrete-mathematics": "EM",
    "operating-systems": "OS",
    "database-management-system": "DBMS",
    "algorithms": "ALG",
    "theory-of-computation": "TOC",
    "computer-organization": "COA",
    "data-structures": "PDS",
    "computer-networks": "CN",
    "digital-logic": "DL",
    "compiler-design": "CD",
    "programming-languages": "PDS",
}

EXAMSIDE_TYPE_MAP = {
    "mcq": "mcq",
    "mcqm": "msq",
    "integer": "nat",
    "subjective": "descriptive",
}

ACTIVE_HTML_RE = re.compile(
    r"<\s*(?:script|iframe|object|embed)\b|\son[a-z]+\s*=|javascript\s*:",
    re.IGNORECASE,
)
ANSWER_MARKER_RE = re.compile(r"(?im)^\s*Answer\s+key\s*(?:☟)?\s*$")
HEX_SHA256_RE = re.compile(r"[0-9a-f]{64}")


class CandidateReconciliationError(ValueError):
    """Raised when staging inputs violate a deterministic safety invariant."""


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag.casefold() == "img":
            attributes = {name.casefold(): value for name, value in attrs}
            alt = attributes.get("alt")
            if alt:
                self.parts.append(str(alt))
        if tag.casefold() in {"br", "p", "div", "li", "tr"}:
            self.parts.append(" ")


@dataclass(frozen=True, slots=True)
class TextMatch:
    key: tuple[str, int]
    method: str
    normalized_sha256: str


@dataclass(slots=True)
class InputDecision:
    paper_id: str | None
    key: tuple[str, int] | None
    status: str
    reasons: list[str]
    match_method: str | None = None


def _read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise CandidateReconciliationError(
                    f"{path}:{line_number}: invalid JSONL"
                ) from exc
            if not isinstance(record, dict):
                raise CandidateReconciliationError(
                    f"{path}:{line_number}: expected an object"
                )
            records.append(record)
    return records


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _plain_text(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    parser = _TextExtractor()
    try:
        parser.feed(value)
        parser.close()
        result = " ".join(parser.parts)
    except Exception:
        result = re.sub(r"<[^>]+>", " ", value)
    result = html_lib.unescape(result)
    result = re.sub(r"[\u200b-\u200d\ufeff]", "", result)
    result = re.sub(r"\s+", " ", result).strip()
    return result or None


def _normalized_text(value: Any) -> str | None:
    plain = _plain_text(value)
    if plain is None:
        return None
    normalized = unicodedata.normalize("NFKC", plain).casefold().translate(
        str.maketrans(
            {
                "’": "'",
                "‘": "'",
                "“": '"',
                "”": '"',
                "−": "-",
                "–": "-",
                "—": "-",
                "…": "...",
            }
        )
    )
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized if len(normalized) >= 20 else None


def _anchor_tokens(value: Any) -> tuple[str, ...]:
    if not isinstance(value, str):
        return ()
    without_math = re.sub(r"\$.*?\$", " ", value, flags=re.DOTALL)
    without_math = re.sub(r"\\\(.*?\\\)|\\\[.*?\\\]", " ", without_math, flags=re.DOTALL)
    plain = _plain_text(without_math)
    if plain is None:
        return ()
    folded = unicodedata.normalize("NFKC", plain).casefold()
    tokens = re.findall(r"[a-z]+(?:'[a-z]+)?|\d+(?:\.\d+)?", folded)
    return tuple(token for token in tokens if len(token) >= 3 or token.isdigit())


def _normalized_digest(value: Any) -> str | None:
    normalized = _normalized_text(value)
    return _sha256_text(normalized) if normalized else None


def _strip_non_question_tail(body: str) -> str:
    match = ANSWER_MARKER_RE.search(body)
    if match:
        body = body[: match.start()]
    return re.sub(r"\n{3,}", "\n\n", body).strip()


def _validate_sha256(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    lowered = value.casefold()
    return lowered if HEX_SHA256_RE.fullmatch(lowered) else None


def _canonical_maps(
    artifact: dict[str, Any], manifest: dict[str, Any]
) -> tuple[
    list[dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[tuple[str, int], dict[str, Any]],
    dict[str, dict[str, int]],
]:
    papers = artifact.get("papers")
    questions = artifact.get("questions")
    manifest_papers = manifest.get("papers")
    if not isinstance(papers, list) or len(papers) != EXPECTED_PAPER_COUNT:
        raise CandidateReconciliationError(
            f"canonical artifact must contain {EXPECTED_PAPER_COUNT} papers"
        )
    if not isinstance(questions, list) or len(questions) != EXPECTED_SLOT_COUNT:
        raise CandidateReconciliationError(
            f"canonical artifact must contain {EXPECTED_SLOT_COUNT} slots"
        )
    if not isinstance(manifest_papers, list):
        raise CandidateReconciliationError("source manifest papers are missing")
    _validate_manifest_key_identity(manifest_papers)
    manifest_by_id = {str(paper.get("id")): paper for paper in manifest_papers}
    if set(manifest_by_id) != {str(paper.get("id")) for paper in papers}:
        raise CandidateReconciliationError(
            "canonical paper ids and source-manifest paper ids differ"
        )

    slots: dict[tuple[str, int], dict[str, Any]] = {}
    labels_to_ordinals: dict[str, dict[str, int]] = defaultdict(dict)
    paper_counts: Counter[str] = Counter()
    for question in questions:
        if question.get("practice_eligible") is not False:
            raise CandidateReconciliationError(
                "every canonical input row must be explicitly staging-only"
            )
        paper_id = str(question.get("source_paper_id") or "")
        try:
            ordinal = int(question.get("ordinal"))
        except (TypeError, ValueError) as exc:
            raise CandidateReconciliationError(
                f"{paper_id}: invalid canonical ordinal"
            ) from exc
        key = (paper_id, ordinal)
        if key in slots:
            raise CandidateReconciliationError(f"duplicate canonical slot {key}")
        slots[key] = question
        paper_counts[paper_id] += 1
        label_key = canonical_builder._label_key(question.get("item_label"))
        # Modern canonical labels deliberately carry the section (GA-01 / CS-01).
        # ``_reference_slot_key`` resolves those papers from the secondary
        # section plus local number and does not consult this legacy label map.
        if label_key is None:
            continue
        previous = labels_to_ordinals[paper_id].get(label_key)
        if previous is not None and previous != ordinal:
            raise CandidateReconciliationError(
                f"{paper_id}: duplicate normalized label {label_key!r}"
            )
        labels_to_ordinals[paper_id][label_key] = ordinal

    for paper in papers:
        expected = int(paper.get("expected_item_count") or 0)
        if paper_counts[str(paper["id"])] != expected:
            raise CandidateReconciliationError(
                f"{paper['id']}: canonical count does not match {expected}"
            )
    return papers, manifest_by_id, slots, dict(labels_to_ordinals)


def _validate_manifest_key_identity(papers: list[dict[str, Any]]) -> None:
    """Reject answer-key metadata that visibly belongs to a different year."""

    for paper in papers:
        paper_id = str(paper.get("id") or "")
        try:
            year = int(paper.get("year"))
        except (TypeError, ValueError) as exc:
            raise CandidateReconciliationError(
                f"{paper_id}: invalid source-manifest year"
            ) from exc
        local_key = str(paper.get("answer_key_local_file") or "")
        local_match = re.search(
            r"gate-cs(?:e)?-(?P<year>19\d{2}|20\d{2})",
            Path(local_key).name.casefold(),
        )
        if local_match and int(local_match.group("year")) != year:
            raise CandidateReconciliationError(
                f"{paper_id}: answer-key filename visibly belongs to "
                f"{local_match.group('year')}"
            )
        answer_key_url = str(paper.get("answer_key_url") or "")
        path_years = {
            int(value)
            for value in re.findall(
                r"(?<!\d)(19\d{2}|20\d{2})(?!\d)",
                urlparse(answer_key_url).path,
            )
        }
        if path_years and year not in path_years:
            raise CandidateReconciliationError(
                f"{paper_id}: answer-key URL path years {sorted(path_years)} "
                f"do not include {year}"
            )


def _paper_indexes(
    papers: list[dict[str, Any]],
) -> tuple[dict[int, list[dict[str, Any]]], dict[str, int]]:
    by_year: dict[int, list[dict[str, Any]]] = defaultdict(list)
    years: dict[str, int] = {}
    for paper in papers:
        year = int(paper["year"])
        paper_id = str(paper["id"])
        by_year[year].append(paper)
        years[paper_id] = year
    return dict(by_year), years


def _session_number(value: Any) -> int | None:
    match = re.search(r"(\d+)\s*$", str(value or ""))
    return int(match.group(1)) if match else None


def _paper_session_number(paper: dict[str, Any]) -> int | None:
    for value in (
        paper.get("session"),
        paper.get("session_label"),
        paper.get("id"),
    ):
        number = _session_number(value)
        if number is not None:
            return number
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
        return str(candidates[0]["id"])
    wanted = row.get("set_number")
    if wanted is None:
        wanted = _session_number(row.get("session"))
    if wanted is None:
        return None
    matched = [
        paper for paper in candidates if _paper_session_number(paper) == int(wanted)
    ]
    return str(matched[0]["id"]) if len(matched) == 1 else None


def _nested_examside_paper_id(
    row: dict[str, Any], papers: list[dict[str, Any]]
) -> str | None:
    paper_meta = row.get("paper")
    if not isinstance(paper_meta, dict):
        return None
    paper_ids = {str(paper["id"]) for paper in papers}
    slug = str(paper_meta.get("slug") or "").strip().casefold()
    direct = slug.replace("gate-cse-", "gate-cs-", 1)
    if direct in paper_ids:
        return direct
    try:
        year = int(paper_meta.get("year"))
    except (TypeError, ValueError):
        return None
    candidates = [paper for paper in papers if int(paper["year"]) == year]
    wanted = _session_number(paper_meta.get("session"))
    if wanted is not None:
        candidates = [
            paper for paper in candidates if _paper_session_number(paper) == wanted
        ]
    return str(candidates[0]["id"]) if len(candidates) == 1 else None


def _load_gateoverflow_blocks(
    page_dir: Path,
) -> tuple[dict[tuple[str, int, str], list[dict[str, Any]]], dict[str, Any]]:
    blocks: dict[tuple[str, int, str], list[dict[str, Any]]] = defaultdict(list)
    page_count = heading_count = 0
    for page_index_path in sorted(page_dir.glob("filter1_volume*.pages.jsonl")):
        volume = page_index_path.name.removesuffix(".pages.jsonl")
        page_records = _read_jsonl(page_index_path)
        if not page_records:
            raise CandidateReconciliationError(f"{page_index_path}: empty page index")
        page_texts: list[str] = []
        for expected_page, record in enumerate(page_records, 1):
            if int(record.get("page") or 0) != expected_page:
                raise CandidateReconciliationError(
                    f"{page_index_path}: page sequence is not contiguous"
                )
            text = record.get("text")
            if not isinstance(text, str):
                raise CandidateReconciliationError(
                    f"{page_index_path}: page {expected_page} text is missing"
                )
            digest = _validate_sha256(record.get("text_sha256"))
            if digest is None or digest != _sha256_text(text):
                raise CandidateReconciliationError(
                    f"{page_index_path}: page {expected_page} hash mismatch"
                )
            page_texts.append(text)
        page_count += len(page_records)
        joined, spans = gateoverflow_index._join_pages(page_texts)
        headings = list(gateoverflow_index.QUESTION_HEADING_RE.finditer(joined))
        heading_count += len(headings)
        for index, heading in enumerate(headings):
            end = headings[index + 1].start() if index + 1 < len(headings) else len(joined)
            raw_body = gateoverflow_index._question_body(joined[heading.end() : end])
            body = _strip_non_question_tail(raw_body)
            page = gateoverflow_index._page_for_offset(spans, heading.start())
            key = (volume, page, heading.group(0).strip())
            blocks[key].append(
                {
                    "body_text": body,
                    "body_sha256": _sha256_text(body),
                    "page_text_sha256": _sha256_text(page_texts[page - 1]),
                }
            )
    return dict(blocks), {
        "volume_count": len(list(page_dir.glob("filter1_volume*.pages.jsonl"))),
        "page_count": page_count,
        "heading_count": heading_count,
        "all_page_hashes_verified": True,
    }


def _map_gateoverflow(
    rows: list[dict[str, Any]],
    blocks: dict[tuple[str, int, str], list[dict[str, Any]]],
    *,
    papers: list[dict[str, Any]],
    slots: dict[tuple[str, int], dict[str, Any]],
    labels_to_ordinals: dict[str, dict[str, int]],
) -> tuple[
    dict[tuple[str, int], dict[str, Any]],
    dict[tuple[str, int], list[str]],
    dict[str, Any],
]:
    papers_by_year, paper_years = _paper_indexes(papers)
    mapped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    input_counts: dict[str, Counter[str]] = defaultdict(Counter)
    global_reasons: Counter[str] = Counter()

    for row in rows:
        paper_id = _reference_paper_id(row, papers_by_year)
        if paper_id is None:
            global_reasons["paper_not_resolved"] += 1
            continue
        input_counts[paper_id]["input"] += 1
        key = canonical_builder._reference_slot_key(
            row, paper_id, paper_years[paper_id], labels_to_ordinals
        )
        if key is None or key not in slots:
            input_counts[paper_id]["unmatched"] += 1
            global_reasons["section_or_item_label_not_resolved"] += 1
            continue
        lookup_key = (
            str(row.get("volume") or ""),
            int(row.get("source_page") or 0),
            str(row.get("heading") or "").strip(),
        )
        block_candidates = blocks.get(lookup_key, [])
        if len(block_candidates) != 1:
            input_counts[paper_id]["ambiguous"] += 1
            global_reasons[
                "heading_block_missing" if not block_candidates else "heading_block_ambiguous"
            ] += 1
            mapped[key].append(
                {
                    "row": row,
                    "block": None,
                    "mapping_problem": (
                        "heading_block_missing"
                        if not block_candidates
                        else "heading_block_ambiguous"
                    ),
                }
            )
            continue
        mapped[key].append({"row": row, "block": block_candidates[0]})

    exact: dict[tuple[str, int], dict[str, Any]] = {}
    ambiguous: dict[tuple[str, int], list[str]] = {}
    for key, candidates in mapped.items():
        problems = [
            str(candidate["mapping_problem"])
            for candidate in candidates
            if candidate.get("mapping_problem")
        ]
        if len(candidates) != 1 or problems:
            reasons = problems or ["multiple_gateoverflow_rows_for_canonical_slot"]
            ambiguous[key] = sorted(set(reasons))
            input_counts[key[0]]["ambiguous"] += sum(
                not candidate.get("mapping_problem") for candidate in candidates
            )
            continue
        exact[key] = candidates[0]
        input_counts[key[0]]["exact"] += 1

    return exact, ambiguous, {
        "input_record_count": len(rows),
        "exact_slot_count": len(exact),
        "ambiguous_slot_count": len(ambiguous),
        "unmatched_or_out_of_scope_record_count": (
            len(rows) - sum(counter["exact"] for counter in input_counts.values())
        ),
        "reason_counts": dict(sorted(global_reasons.items())),
        "papers": {
            paper_id: dict(counter) for paper_id, counter in sorted(input_counts.items())
        },
    }


def _strict_explicit_secondary_key(
    row: dict[str, Any],
    *,
    nested_paper_id: str | None,
    slots: dict[tuple[str, int], dict[str, Any]],
    labels_to_ordinals: dict[str, dict[str, int]],
    paper_years: dict[str, int],
) -> tuple[tuple[str, int] | None, list[str], bool]:
    explicit_paper = row.get("source_paper_id") or row.get("manifest_paper_id")
    if explicit_paper is not None and str(explicit_paper) not in paper_years:
        return None, ["explicit_paper_id_unknown"], True
    if explicit_paper is not None and nested_paper_id is not None:
        if str(explicit_paper) != nested_paper_id:
            return None, ["explicit_and_nested_paper_disagree"], True
    paper_id = str(explicit_paper) if explicit_paper is not None else nested_paper_id
    if paper_id is None:
        return None, [], False

    ordinal_value = row.get("global_ordinal")
    if ordinal_value is None:
        ordinal_value = row.get("ordinal")
    ordinal_key: tuple[str, int] | None = None
    if ordinal_value is not None:
        try:
            ordinal = canonical_builder._coerce_ordinal(
                ordinal_value, context="secondary explicit ordinal"
            )
        except canonical_builder.ArchiveBuildError:
            return None, ["explicit_ordinal_invalid"], True
        ordinal_key = (paper_id, ordinal)
        if ordinal_key not in slots:
            return None, ["explicit_ordinal_out_of_range"], True

    has_label = row.get("item_label") is not None
    label_key: tuple[str, int] | None = None
    if has_label:
        label_key = canonical_builder._reference_slot_key(
            row, paper_id, paper_years[paper_id], labels_to_ordinals
        )
        if label_key is None:
            return None, ["explicit_section_or_item_label_not_resolvable"], True
    if ordinal_key is not None and label_key is not None and ordinal_key != label_key:
        return None, ["explicit_ordinal_disagrees_with_section_item_label"], True
    key = ordinal_key or label_key
    return key, [], key is not None


def _candidate_text_matches(
    query: Any,
    candidates: dict[tuple[str, int], str],
    *,
    paper_id: str,
) -> list[TextMatch]:
    query_normalized = _normalized_text(query)
    if query_normalized is None:
        return []
    same_paper = {
        key: value for key, value in candidates.items() if key[0] == paper_id
    }
    exact = [
        key
        for key, value in same_paper.items()
        if _normalized_text(value) == query_normalized
    ]
    if exact:
        return [
            TextMatch(key, "normalized_exact", _sha256_text(query_normalized))
            for key in exact
        ]

    if len(query_normalized) >= 40:
        prefix = []
        for key, value in same_paper.items():
            candidate_normalized = _normalized_text(value)
            if candidate_normalized and candidate_normalized.startswith(query_normalized):
                prefix.append(key)
        if prefix:
            return [
                TextMatch(key, "normalized_question_prefix", _sha256_text(query_normalized))
                for key in prefix
            ]

    query_tokens = _anchor_tokens(query)
    token_chars = sum(map(len, query_tokens))
    if len(query_tokens) < 6 or token_chars < 32:
        return []
    token_matches: list[tuple[str, int]] = []
    for key, value in same_paper.items():
        candidate_tokens = _anchor_tokens(value)
        if len(candidate_tokens) >= len(query_tokens):
            agrees = candidate_tokens[: len(query_tokens)] == query_tokens
        else:
            ratio = len(candidate_tokens) / len(query_tokens)
            agrees = (
                len(candidate_tokens) >= 6
                and ratio >= 0.75
                and query_tokens[: len(candidate_tokens)] == candidate_tokens
            )
        if agrees:
            token_matches.append(key)
    token_digest = _sha256_text("\n".join(query_tokens))
    return [
        TextMatch(key, "normalized_anchor_token_prefix", token_digest)
        for key in token_matches
    ]


def _map_examside(
    rows: list[dict[str, Any]],
    *,
    papers: list[dict[str, Any]],
    slots: dict[tuple[str, int], dict[str, Any]],
    labels_to_ordinals: dict[str, dict[str, int]],
    go_exact: dict[tuple[str, int], dict[str, Any]],
) -> tuple[
    dict[tuple[str, int], dict[str, Any]],
    dict[tuple[str, int], list[str]],
    dict[str, Any],
]:
    _, paper_years = _paper_indexes(papers)
    canonical_text = {
        key: str(item["question_md"])
        for key, item in slots.items()
        if isinstance(item.get("question_md"), str) and item["question_md"].strip()
    }
    go_text = {
        key: str(candidate["block"]["body_text"])
        for key, candidate in go_exact.items()
        if candidate.get("block") and candidate["block"].get("body_text")
    }
    decisions: list[InputDecision] = []

    for row in rows:
        nested_paper_id = _nested_examside_paper_id(row, papers)
        key, reasons, explicit_present = _strict_explicit_secondary_key(
            row,
            nested_paper_id=nested_paper_id,
            slots=slots,
            labels_to_ordinals=labels_to_ordinals,
            paper_years=paper_years,
        )
        paper_id = (
            key[0]
            if key is not None
            else str(row.get("source_paper_id") or row.get("manifest_paper_id") or "")
            or nested_paper_id
        )
        if reasons:
            decisions.append(InputDecision(paper_id, None, "ambiguous", reasons))
            continue
        if explicit_present and key is not None:
            decisions.append(InputDecision(paper_id, key, "exact", [], "explicit"))
            continue
        if paper_id is None:
            decisions.append(
                InputDecision(None, None, "unmatched", ["paper_not_resolved"])
            )
            continue
        question = row.get("question") if isinstance(row.get("question"), dict) else {}
        query = question.get("question_text")
        matches = _candidate_text_matches(query, canonical_text, paper_id=paper_id)
        if not matches:
            matches = _candidate_text_matches(query, go_text, paper_id=paper_id)
        distinct = {match.key for match in matches}
        if len(distinct) == 1:
            match = matches[0]
            decisions.append(
                InputDecision(paper_id, match.key, "exact", [], match.method)
            )
        elif len(distinct) > 1:
            decisions.append(
                InputDecision(
                    paper_id,
                    None,
                    "ambiguous",
                    ["normalized_text_matches_multiple_canonical_slots"],
                )
            )
        else:
            decisions.append(
                InputDecision(
                    paper_id,
                    None,
                    "unmatched",
                    ["no_unique_exact_or_normalized_text_match"],
                )
            )

    collisions: dict[tuple[str, int], list[int]] = defaultdict(list)
    for index, decision in enumerate(decisions):
        if decision.status == "exact" and decision.key is not None:
            collisions[decision.key].append(index)
    for key, indexes in collisions.items():
        if len(indexes) <= 1:
            continue
        for index in indexes:
            decisions[index].status = "ambiguous"
            decisions[index].reasons = ["multiple_examside_rows_for_canonical_slot"]
            decisions[index].key = None

    exact: dict[tuple[str, int], dict[str, Any]] = {}
    ambiguous_slots: dict[tuple[str, int], list[str]] = {}
    paper_counts: dict[str, Counter[str]] = defaultdict(Counter)
    reason_counts: Counter[str] = Counter()
    unknown_paper = Counter()
    for row, decision in zip(rows, decisions, strict=True):
        bucket = paper_counts[decision.paper_id] if decision.paper_id else unknown_paper
        bucket["input"] += 1
        bucket[decision.status] += 1
        reason_counts.update(decision.reasons)
        if decision.status == "exact" and decision.key is not None:
            exact[decision.key] = {
                "row": row,
                "match_method": decision.match_method,
            }
        elif decision.status == "ambiguous":
            # An explicit conflict has no trusted key.  Slot collisions do have
            # a key in the collision table and are surfaced below.
            pass
    for key, indexes in collisions.items():
        if len(indexes) > 1:
            ambiguous_slots[key] = ["multiple_examside_rows_for_canonical_slot"]

    return exact, ambiguous_slots, {
        "input_record_count": len(rows),
        "exact_record_count": sum(d.status == "exact" for d in decisions),
        "ambiguous_record_count": sum(d.status == "ambiguous" for d in decisions),
        "unmatched_record_count": sum(d.status == "unmatched" for d in decisions),
        "exact_slot_count": len(exact),
        "ambiguous_slot_count": len(ambiguous_slots),
        "reason_counts": dict(sorted(reason_counts.items())),
        "unknown_paper": dict(unknown_paper),
        "papers": {
            paper_id: dict(counter) for paper_id, counter in sorted(paper_counts.items())
        },
    }


class _ImageReferenceParser(HTMLParser):
    def __init__(self, field: str) -> None:
        super().__init__(convert_charrefs=True)
        self.field = field
        self.references: list[dict[str, Any]] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag.casefold() != "img":
            return
        attributes = {name.casefold(): value for name, value in attrs}
        source = attributes.get("src")
        if not source:
            return
        parsed = urlparse(source)
        safe = parsed.scheme.casefold() in {"http", "https"} and bool(parsed.netloc)
        record: dict[str, Any] = {
            "field": self.field,
            "url_sha256": _sha256_text(source),
            "scheme": parsed.scheme.casefold() or None,
            "host": parsed.netloc.casefold() or None,
            "retrieval_status": "not_fetched",
            "trusted_for_rendering": False,
        }
        if safe:
            record["url"] = source
        else:
            record["rejection_reason"] = "non_http_remote_asset_reference"
        alt = attributes.get("alt")
        if alt:
            record["alt"] = alt
        self.references.append(record)


def _image_references(field: str, value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, str) or "<img" not in value.casefold():
        return []
    parser = _ImageReferenceParser(field)
    parser.feed(value)
    parser.close()
    return parser.references


def _examside_snapshot(candidate: dict[str, Any]) -> dict[str, Any]:
    row = candidate["row"]
    question = row.get("question") if isinstance(row.get("question"), dict) else {}
    provenance = row.get("provenance") if isinstance(row.get("provenance"), dict) else {}
    fields = {
        "question_html": question.get("question_text"),
        "direction_html": question.get("direction_text"),
        "comprehension_html": question.get("comprehension_text"),
    }
    option_rows = []
    remote_assets: list[dict[str, Any]] = []
    active_html_detected = False
    for field, value in fields.items():
        if isinstance(value, str):
            active_html_detected |= bool(ACTIVE_HTML_RE.search(value))
            remote_assets.extend(_image_references(field, value))
    for index, option in enumerate(question.get("options") or []):
        if not isinstance(option, dict):
            continue
        content = option.get("content")
        if isinstance(content, str):
            active_html_detected |= bool(ACTIVE_HTML_RE.search(content))
            remote_assets.extend(_image_references(f"option[{index}]", content))
        option_rows.append(
            {
                "identifier": str(option.get("identifier") or "").strip() or None,
                "content_html": content if isinstance(content, str) else None,
                "content_text": _plain_text(content),
                "content_html_sha256": _sha256_text(content)
                if isinstance(content, str)
                else None,
            }
        )
    html_hashes = {
        field: _sha256_text(value)
        for field, value in fields.items()
        if isinstance(value, str)
    }
    source_id = str(question.get("source_id") or "") or None
    raw_hash = _validate_sha256(provenance.get("question_raw_sha256"))
    snapshot = {
        "source_id": source_id,
        "source_url": question.get("url"),
        "raw_response_sha256": raw_hash,
        "match_method": candidate.get("match_method"),
        "question_html": fields["question_html"],
        "question_text": _plain_text(fields["question_html"]),
        "direction_html": fields["direction_html"],
        "comprehension_html": fields["comprehension_html"],
        "options": option_rows,
        "html_sha256": html_hashes,
        "question_type": EXAMSIDE_TYPE_MAP.get(
            str(question.get("question_type") or "").casefold()
        ),
        "marks": question.get("marks"),
        "answer_candidate": _examside_answer(question),
        "subject_slug": question.get("subject"),
        "course_candidate": EXAMSIDE_SUBJECT_TO_COURSE.get(
            str(question.get("subject") or "").casefold()
        ),
        "topic_candidate": question.get("chapter") or question.get("topic"),
        "is_out_of_syllabus_candidate": bool(question.get("is_out_of_syllabus")),
        "is_bonus_candidate": bool(question.get("is_bonus")),
        "remote_assets": remote_assets,
        "active_html_detected": active_html_detected,
        "rendering_allowed": False,
        "remote_asset_fetch_allowed": False,
    }
    return snapshot


def _examside_answer(question: dict[str, Any]) -> Any:
    question_type = str(question.get("question_type") or "").casefold()
    if question_type in {"mcq", "mcqm"}:
        values = [
            str(value).strip().upper()
            for value in (question.get("correct_options") or [])
            if str(value).strip()
        ]
        if question_type == "mcq" and len(values) == 1:
            return values[0]
        return values or None
    if question_type == "integer":
        value = question.get("numerical_answer")
        return str(value).strip() if value is not None and str(value).strip() else None
    return None


def _gateoverflow_answer(row: dict[str, Any]) -> Any:
    raw = row.get("answer")
    if raw is None or row.get("answer_join_status") != "joined":
        return None
    value = str(raw).strip()
    if not value:
        return None
    parts = [part for part in re.split(r"[;,]", value.upper()) if part]
    if parts and all(re.fullmatch(r"[A-D]", part) for part in parts):
        return parts[0] if len(parts) == 1 else sorted(set(parts))
    return value


def _answer_fingerprint(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        normalized = sorted(str(item).strip().upper() for item in value)
        return json.dumps(normalized, separators=(",", ":"))
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    text = re.sub(r"\s+", "", str(value)).upper()
    return text or None


def _select_answer_claim(
    canonical: dict[str, Any],
    go_snapshot: dict[str, Any] | None,
    exam_snapshot: dict[str, Any] | None,
) -> tuple[Any, str, list[dict[str, Any]], list[str]]:
    claims: list[dict[str, Any]] = []
    if canonical.get("accepted_answers") is not None:
        claims.append(
            {
                "source": "canonical_skeleton",
                "value": deepcopy(canonical["accepted_answers"]),
                "authority": canonical.get("answer_status") or "review_required",
            }
        )
    if go_snapshot and go_snapshot.get("answer_candidate") is not None:
        claims.append(
            {
                "source": "gateoverflow",
                "value": deepcopy(go_snapshot["answer_candidate"]),
                "authority": "secondary_community_candidate",
            }
        )
    if exam_snapshot and exam_snapshot.get("answer_candidate") is not None:
        claims.append(
            {
                "source": "examside",
                "value": deepcopy(exam_snapshot["answer_candidate"]),
                "authority": "secondary_community_candidate",
            }
        )
    if not claims:
        return None, "unresolved", [], ["answer_candidate_missing"]
    fingerprints = {_answer_fingerprint(claim["value"]) for claim in claims}
    if None in fingerprints:
        fingerprints.remove(None)
    canonical_claim = next(
        (claim for claim in claims if claim["source"] == "canonical_skeleton"), None
    )
    secondary_sources = {
        claim["source"]
        for claim in claims
        if claim["source"] in {"gateoverflow", "examside"}
    }
    if len(fingerprints) > 1:
        return None, "conflict", claims, ["answer_candidates_disagree"]
    selected = deepcopy(canonical_claim["value"] if canonical_claim else claims[0]["value"])
    if canonical_claim:
        status = str(canonical_claim["authority"])
    elif len(secondary_sources) >= 2:
        status = "community_corroborated_candidate"
    else:
        status = "single_secondary_candidate"
    return selected, status, claims, []


def evaluate_promotion_evidence(
    *,
    source_page: Any,
    source_reference: Any,
    original_content_sha256: Any,
    answer_status: str,
    official_key_sha256: Any,
    community_answer_sources: Iterable[str],
    is_2013_canonical: bool = False,
    booklet_occurrence_bijection_verified: bool = False,
) -> dict[str, Any]:
    source_complete = bool(
        source_page
        and source_reference
        and _validate_sha256(original_content_sha256)
    )
    blockers = []
    if not source_page:
        blockers.append("original_source_page_missing")
    if not source_reference:
        blockers.append("original_source_reference_missing")
    if not _validate_sha256(original_content_sha256):
        blockers.append("original_item_content_hash_missing")

    official = answer_status in {"official", "primary_official"}
    community = answer_status in {
        "community_verified",
        "community_corroborated_candidate",
        "single_secondary_candidate",
    }
    independent_sources = sorted(set(community_answer_sources))
    if official:
        answer_complete = _validate_sha256(official_key_sha256) is not None
        if not answer_complete:
            blockers.append("official_answer_key_hash_missing")
    elif community:
        answer_complete = len(independent_sources) >= 2
        if not answer_complete:
            blockers.append("two_independent_community_answer_sources_required")
    else:
        answer_complete = False
        blockers.append("verified_answer_evidence_missing")
    if is_2013_canonical and not booklet_occurrence_bijection_verified:
        blockers.append("2013_booklet_occurrence_bijection_missing")
    blockers.append("staging_only_manual_review_required")
    return {
        "practice_eligible": False,
        "automatic_promotion_allowed": False,
        "source_evidence": {
            "source_page_present": bool(source_page),
            "source_reference_present": bool(source_reference),
            "original_content_sha256_present": bool(
                _validate_sha256(original_content_sha256)
            ),
            "requirements_met": source_complete,
        },
        "answer_evidence": {
            "status": answer_status,
            "official_key_sha256_present": bool(
                _validate_sha256(official_key_sha256)
            ),
            "independent_community_sources": independent_sources,
            "requirements_met": answer_complete,
        },
        "blockers": sorted(set(blockers)),
    }


def _verified_2013_booklet_occurrence_bijection(
    slots: dict[tuple[str, int], dict[str, Any]],
) -> bool:
    """Verify the complete A/B/C/D occurrence map embedded by the builder.

    This deliberately revalidates the serialized canonical artifact rather
    than trusting a report flag.  Every one of the 65 canonical items must
    contain four checksum-backed, page-addressed occurrences, and each
    booklet's labels must form an independent bijection over 1..65.
    """

    expected_ordinals = set(range(1, 66))
    occurrences_by_code: dict[str, set[int]] = {
        code: set() for code in ("A", "B", "C", "D")
    }
    source_hashes: set[str] = set()
    for ordinal in expected_ordinals:
        item = slots.get(("gate-cs-2013", ordinal))
        if not isinstance(item, dict):
            return False
        references = [
            reference
            for reference in item.get("source_references") or []
            if isinstance(reference, dict)
            and reference.get("kind") == "booklet_occurrence"
        ]
        if len(references) != 4:
            return False
        codes_seen: set[str] = set()
        canonical_page = item.get("source_page")
        for reference in references:
            source_hash = _validate_sha256(reference.get("sha256"))
            if source_hash is None:
                return False
            source_hashes.add(source_hash)
            try:
                occurrence = json.loads(str(reference.get("note") or ""))
            except json.JSONDecodeError:
                return False
            if not isinstance(occurrence, dict):
                return False
            code = str(occurrence.get("booklet_code") or "").upper()
            label = occurrence.get("item_label")
            page = occurrence.get("source_page")
            if (
                code not in occurrences_by_code
                or code in codes_seen
                or not isinstance(label, str)
                or not label.isdigit()
                or not 1 <= int(label) <= 65
                or isinstance(page, bool)
                or not isinstance(page, int)
                or page < 1
            ):
                return False
            codes_seen.add(code)
            occurrences_by_code[code].add(int(label))
            if code == "A" and (
                int(label) != ordinal or canonical_page != page
            ):
                return False
        if codes_seen != set(occurrences_by_code):
            return False
    return (
        len(source_hashes) == 1
        and all(labels == expected_ordinals for labels in occurrences_by_code.values())
    )


def _gateoverflow_snapshot(candidate: dict[str, Any]) -> dict[str, Any]:
    row = candidate["row"]
    block = candidate["block"]
    body = str(block.get("body_text") or "")
    return {
        "volume": row.get("volume"),
        "book_page": row.get("source_page"),
        "book_id": row.get("book_id"),
        "heading": row.get("heading"),
        "source_item_label": row.get("item_label"),
        "section_code": row.get("section_code"),
        "question_body_text": body or None,
        "question_body_sha256": _validate_sha256(block.get("body_sha256")),
        "page_text_sha256": _validate_sha256(block.get("page_text_sha256")),
        "answer_candidate": _gateoverflow_answer(row),
        "source_course_candidate": row.get("course_code"),
        "source_topic_candidate": row.get("topic_slug"),
        "source_course_mapping_agrees": row.get("course_mapping_agrees"),
        "course_candidate": row.get("course_code")
        if row.get("course_mapping_agrees") is not False
        else None,
        "topic_candidate": row.get("topic_slug")
        if row.get("course_mapping_agrees") is not False
        else None,
        "source_role": "secondary_reconciliation_reference_only",
    }


def _source_reference(manifest_paper: dict[str, Any]) -> str | None:
    return (
        manifest_paper.get("question_paper_url")
        or manifest_paper.get("local_file")
        or None
    )


def _slugify_topic(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", folded.casefold()).strip("-")


def _canonical_topic_inventory(raw: dict[str, Any]) -> dict[str, set[str]]:
    courses = raw.get("courses")
    if not isinstance(courses, dict) or not courses:
        raise CandidateReconciliationError("canonical topic inventory is missing courses")
    inventory: dict[str, set[str]] = {}
    for raw_code, course in courses.items():
        code = str(raw_code).strip().upper()
        by_topic = course.get("by_topic") if isinstance(course, dict) else None
        if not isinstance(by_topic, dict) or not by_topic:
            raise CandidateReconciliationError(
                f"canonical topic inventory for {code} is empty"
            )
        inventory[code] = {_slugify_topic(str(topic)) for topic in by_topic}
    return inventory


def _inventory_topic_candidate(
    *,
    course: Any,
    topic: Any,
    inventory: dict[str, set[str]],
) -> tuple[str | None, str | None]:
    code = str(course or "").strip().upper()
    slug = str(topic or "").strip().casefold()
    if not code or code not in inventory:
        return None, "course_candidate_not_in_canonical_inventory"
    if not slug or slug not in inventory[code]:
        return None, "topic_candidate_not_in_canonical_inventory"
    return slug, None


def _legacy_classification(
    *,
    canonical: dict[str, Any],
    go_snapshot: dict[str, Any] | None,
    exam_snapshot: dict[str, Any] | None,
    inventory: dict[str, set[str]],
) -> dict[str, Any]:
    """Reproduce the pre-policy behavior for an auditable before metric."""

    reasons: list[str] = []
    course = canonical.get("subject_code")
    course_source = "canonical_skeleton" if course else None
    if course and str(course).strip().upper() not in inventory:
        reasons.append(
            "canonical_skeleton:course_candidate_not_in_canonical_inventory"
        )
        course = None
        course_source = None

    topic = None
    topic_source = None
    topic_claims = [
        (
            "canonical_skeleton",
            canonical.get("subject_code"),
            canonical.get("topic_slug"),
        ),
        (
            "gateoverflow_exact_label_join",
            go_snapshot.get("course_candidate") if go_snapshot else None,
            go_snapshot.get("topic_candidate") if go_snapshot else None,
        ),
        (
            "examside_exact_normalized_join",
            exam_snapshot.get("course_candidate") if exam_snapshot else None,
            exam_snapshot.get("topic_candidate") if exam_snapshot else None,
        ),
    ]
    for source, topic_course, raw_topic in topic_claims:
        if not raw_topic:
            continue
        normalized_topic, problem = _inventory_topic_candidate(
            course=topic_course or course,
            topic=raw_topic,
            inventory=inventory,
        )
        if normalized_topic is not None:
            topic = normalized_topic
            topic_source = source
            if topic_course:
                course = str(topic_course).strip().upper()
                course_source = source
            break
        if problem:
            reasons.append(f"{source}:{problem}")
    if not course:
        course_claims = [
            (
                "gateoverflow_exact_label_join",
                go_snapshot.get("course_candidate") if go_snapshot else None,
            ),
            (
                "examside_exact_normalized_join",
                exam_snapshot.get("course_candidate") if exam_snapshot else None,
            ),
        ]
        valid_course_claims = [
            (source, str(value).strip().upper())
            for source, value in course_claims
            if value and str(value).strip().upper() in inventory
        ]
        distinct_courses = {value for _, value in valid_course_claims}
        if len(distinct_courses) == 1:
            course = next(iter(distinct_courses))
            course_source = "+".join(
                source for source, value in valid_course_claims if value == course
            )
        elif len(distinct_courses) > 1:
            reasons.append("secondary_course_candidates_disagree")

    return {
        "course": course,
        "course_source": course_source,
        "topic": topic,
        "topic_source": topic_source,
        "reasons": reasons,
        "conflict": False,
        "unresolved_conflict": False,
        "override_resolved_conflict": False,
        "policy_decision": None,
        "slot_policy_decision": None,
        "classification_outcome": "mapped" if topic is not None else "review",
        "base_review_reasons": sorted(set(reasons)),
        "claims": [],
    }


def _valid_full_classification_claim(
    *,
    course: Any,
    topic: Any,
    inventory: dict[str, set[str]],
) -> tuple[str, str] | None:
    normalized, _ = _inventory_topic_candidate(
        course=course, topic=topic, inventory=inventory
    )
    if normalized is None:
        return None
    return str(course).strip().upper(), normalized


def _policy_classification(
    *,
    key: tuple[str, int],
    canonical: dict[str, Any],
    go_snapshot: dict[str, Any] | None,
    exam_snapshot: dict[str, Any] | None,
    inventory: dict[str, set[str]],
    policy: topic_classification.TopicClassificationPolicy,
    slot_policy: slot_classification.SlotClassificationPolicy | None = None,
    original_provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve a classification without treating broad labels as decisions."""

    reasons: list[str] = []
    claims: list[dict[str, Any]] = []
    policy_decision: dict[str, Any] | None = None
    paper_id, ordinal = key

    canonical_claim = _valid_full_classification_claim(
        course=canonical.get("subject_code"),
        topic=canonical.get("topic_slug"),
        inventory=inventory,
    )
    canonical_verified = (
        canonical_claim
        if canonical.get("classification_status") == "verified"
        else None
    )
    if canonical_verified is not None:
        claims.append(
            {
                "source": "canonical_verified",
                "course": canonical_verified[0],
                "topic": canonical_verified[1],
            }
        )

    if go_snapshot is not None:
        try:
            policy_decision = policy.resolve(
                paper_id=paper_id,
                ordinal=ordinal,
                source_course=go_snapshot.get("source_course_candidate"),
                source_topic=go_snapshot.get("source_topic_candidate"),
                source_course_mapping_agrees=go_snapshot.get(
                    "source_course_mapping_agrees"
                ),
            )
        except topic_classification.TopicClassificationError as exc:
            raise CandidateReconciliationError(str(exc)) from exc
        if policy_decision["decision"] == "map":
            claims.append(
                {
                    "source": policy_decision["source"],
                    "course": policy_decision["course"],
                    "topic": policy_decision["topic"],
                    "decision_key": policy_decision["decision_key"],
                }
            )
        else:
            reasons.append(
                "gateoverflow_topic_policy:"
                + str(policy_decision["reason_code"])
            )

    override_claims = [
        claim
        for claim in claims
        if claim["source"] == "gateoverflow_question_override"
    ]
    verified_claims = [
        claim for claim in claims if claim["source"] == "canonical_verified"
    ]
    policy_claims = [
        claim
        for claim in claims
        if claim["source"] == "gateoverflow_topic_policy"
    ]

    distinct_full_claims = {
        (str(claim["course"]), str(claim["topic"])) for claim in claims
    }
    conflict = len(distinct_full_claims) > 1
    override_resolved_conflict = conflict and bool(override_claims)
    unresolved_conflict = conflict and not override_resolved_conflict
    if unresolved_conflict:
        reasons.append("classification_candidates_disagree")

    selected: dict[str, Any] | None = None
    if override_claims:
        selected = override_claims[0]
    elif unresolved_conflict:
        # A broad alias must never overrule a contradictory item-level claim,
        # and the legacy claim must not silently win either.  Withhold both.
        selected = None
    elif verified_claims:
        selected = verified_claims[0]
    elif policy_claims:
        selected = policy_claims[0]

    course = selected["course"] if selected else None
    topic = selected["topic"] if selected else None
    course_source = selected["source"] if selected else None
    topic_source = selected["source"] if selected else None

    # A manual decision may still retain an agreeing, inventory-valid source
    # course.  It deliberately does not invent a topic.
    if (
        course is None
        and policy_decision is not None
        and policy_decision["decision"] == "manual_review"
        and go_snapshot is not None
        and go_snapshot.get("source_course_mapping_agrees") is True
    ):
        source_course = str(
            go_snapshot.get("source_course_candidate") or ""
        ).strip().upper()
        if source_course in inventory:
            course = source_course
            course_source = "gateoverflow_topic_policy_course_only"

    # Canonical review candidates are retained only when there is no exact
    # GateOverflow classification decision for that slot.  Otherwise a broad
    # source label would be silently forced through the skeleton.
    if selected is None and go_snapshot is None and canonical_claim is not None:
        course, topic = canonical_claim
        course_source = topic_source = "canonical_review_candidate"
        reasons.append("canonical_classification_candidate_requires_review")
        claims.append(
            {
                "source": "canonical_review_candidate",
                "course": course,
                "topic": topic,
            }
        )

    if (
        topic is None
        and exam_snapshot is not None
        and not unresolved_conflict
    ):
        exam_claim = _valid_full_classification_claim(
            course=exam_snapshot.get("course_candidate"),
            topic=exam_snapshot.get("topic_candidate"),
            inventory=inventory,
        )
        if exam_claim is not None:
            course, topic = exam_claim
            course_source = topic_source = "examside_review_candidate"
            reasons.append("examside_classification_candidate_requires_review")
            claims.append(
                {
                    "source": "examside_review_candidate",
                    "course": course,
                    "topic": topic,
                }
            )

    if topic is None and not reasons:
        reasons.append("classification_evidence_missing")

    base_reasons = sorted(set(reasons))
    slot_policy_decision = None
    if slot_policy is not None:
        try:
            slot_policy_decision = slot_policy.resolve(
                key=key,
                base_review_reasons=base_reasons,
                gateoverflow_snapshot=go_snapshot,
                original_provenance=original_provenance,
            )
        except slot_classification.SlotClassificationError as exc:
            raise CandidateReconciliationError(str(exc)) from exc
    classification_outcome = "mapped" if topic is not None else "review"
    if slot_policy_decision is not None:
        decision = slot_policy_decision["decision"]
        # The slot layer cites question-level evidence and therefore owns the
        # final classification outcome.  Base claims remain in the audit trail
        # but cannot overrule this explicit, hash-bound decision.
        conflict_was_resolved = conflict
        conflict = False
        unresolved_conflict = False
        override_resolved_conflict = (
            override_resolved_conflict or conflict_was_resolved
        )
        if decision == "map":
            course = slot_policy_decision["course"]
            topic = slot_policy_decision["topic"]
            course_source = topic_source = slot_policy_decision["source"]
            reasons = []
            classification_outcome = "mapped"
            claims.append(
                {
                    "source": slot_policy_decision["source"],
                    "course": course,
                    "topic": topic,
                    "decision_key": slot_policy_decision["decision_key"],
                }
            )
        elif decision == "out_of_syllabus":
            course = topic = None
            course_source = topic_source = slot_policy_decision["source"]
            reasons = []
            classification_outcome = "out_of_syllabus"
        else:
            course = topic = None
            course_source = topic_source = slot_policy_decision["source"]
            reasons = [
                "question_evidence_slot_policy:"
                + str(slot_policy_decision["reason_code"])
            ]
            classification_outcome = "review"

    return {
        "course": course,
        "course_source": course_source,
        "topic": topic,
        "topic_source": topic_source,
        "reasons": sorted(set(reasons)),
        "conflict": conflict,
        "unresolved_conflict": unresolved_conflict,
        "override_resolved_conflict": override_resolved_conflict,
        "policy_decision": policy_decision,
        "slot_policy_decision": slot_policy_decision,
        "classification_outcome": classification_outcome,
        "base_review_reasons": base_reasons,
        "claims": claims,
    }


def _official_key_hash(manifest_paper: dict[str, Any]) -> str | None:
    return _validate_sha256(
        manifest_paper.get("answer_key_local_sha256")
        or manifest_paper.get("official_answer_key_sha256")
    )


def _assemble_rows(
    *,
    papers: list[dict[str, Any]],
    manifest_by_id: dict[str, dict[str, Any]],
    slots: dict[tuple[str, int], dict[str, Any]],
    topic_inventory: dict[str, set[str]],
    go_exact: dict[tuple[str, int], dict[str, Any]],
    go_ambiguous: dict[tuple[str, int], list[str]],
    exam_exact: dict[tuple[str, int], dict[str, Any]],
    exam_ambiguous: dict[tuple[str, int], list[str]],
    classification_policy: topic_classification.TopicClassificationPolicy
    | None = None,
    slot_classification_policy: slot_classification.SlotClassificationPolicy
    | None = None,
    original_provenance_by_key: dict[tuple[str, int], dict[str, Any]]
    | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    paper_reports: dict[str, Counter[str]] = defaultdict(Counter)
    rows: list[dict[str, Any]] = []
    blocker_counts: Counter[str] = Counter()
    classification_before: Counter[str] = Counter()
    classification_after: Counter[str] = Counter()
    base_review_keys: set[tuple[str, int]] = set()
    booklet_2013_verified = _verified_2013_booklet_occurrence_bijection(slots)

    for key in sorted(slots, key=lambda item: (item[0], item[1])):
        canonical = slots[key]
        paper_id, ordinal = key
        manifest_paper = manifest_by_id[paper_id]
        go_snapshot = (
            _gateoverflow_snapshot(go_exact[key]) if key in go_exact else None
        )
        exam_snapshot = (
            _examside_snapshot(exam_exact[key]) if key in exam_exact else None
        )
        ambiguity_reasons = sorted(
            set(go_ambiguous.get(key, []) + exam_ambiguous.get(key, []))
        )

        canonical_question = canonical.get("question_md")
        if isinstance(canonical_question, str) and canonical_question.strip():
            question_text = canonical_question.strip()
            question_source = "canonical_skeleton"
        elif exam_snapshot and exam_snapshot.get("question_text"):
            question_text = exam_snapshot["question_text"]
            question_source = "examside_exact_normalized_join"
        elif go_snapshot and go_snapshot.get("question_body_text"):
            question_text = go_snapshot["question_body_text"]
            question_source = "gateoverflow_exact_label_join"
        else:
            question_text = None
            question_source = None

        canonical_options = canonical.get("options")
        if isinstance(canonical_options, list) and canonical_options:
            options = deepcopy(canonical_options)
            options_source = "canonical_skeleton"
        elif exam_snapshot and exam_snapshot.get("options"):
            options = deepcopy(exam_snapshot["options"])
            options_source = "examside_exact_normalized_join"
        else:
            options = []
            options_source = None

        item_type = str(canonical.get("item_type") or "unknown").casefold()
        if item_type == "unknown" and exam_snapshot and exam_snapshot.get("question_type"):
            item_type = exam_snapshot["question_type"]
            item_type_source = "examside_exact_normalized_join"
        else:
            item_type_source = "canonical_skeleton" if item_type != "unknown" else None

        legacy_classification = _legacy_classification(
            canonical=canonical,
            go_snapshot=go_snapshot,
            exam_snapshot=exam_snapshot,
            inventory=topic_inventory,
        )
        classification_before["course_classified"] += int(
            bool(legacy_classification["course"])
        )
        classification_before["topic_classified"] += int(
            bool(legacy_classification["topic"])
        )
        classification_before["manual_review"] += int(
            bool(legacy_classification["reasons"])
        )
        classification_before["conflicts"] += int(
            bool(legacy_classification["conflict"])
        )
        classification_before["unresolved_conflicts"] += int(
            bool(legacy_classification["unresolved_conflict"])
        )
        classification_before["override_resolved_conflicts"] += int(
            bool(legacy_classification["override_resolved_conflict"])
        )

        classification = (
            _policy_classification(
                key=key,
                canonical=canonical,
                go_snapshot=go_snapshot,
                exam_snapshot=exam_snapshot,
                inventory=topic_inventory,
                policy=classification_policy,
                slot_policy=slot_classification_policy,
                original_provenance=(original_provenance_by_key or {}).get(key),
            )
            if classification_policy is not None
            else legacy_classification
        )
        course = classification["course"]
        course_source = classification["course_source"]
        topic = classification["topic"]
        topic_source = classification["topic_source"]
        classification_reasons = classification["reasons"]
        if classification["base_review_reasons"]:
            base_review_keys.add(key)
        classification_after["course_classified"] += int(bool(course))
        classification_after["topic_classified"] += int(bool(topic))
        classification_after["manual_review"] += int(bool(classification_reasons))
        classification_after[classification["classification_outcome"]] += 1
        classification_after["slot_decisions_applied"] += int(
            classification["slot_policy_decision"] is not None
        )
        classification_after["conflicts"] += int(bool(classification["conflict"]))
        classification_after["unresolved_conflicts"] += int(
            bool(classification["unresolved_conflict"])
        )
        classification_after["override_resolved_conflicts"] += int(
            bool(classification["override_resolved_conflict"])
        )

        answer, answer_status, answer_claims, answer_reasons = _select_answer_claim(
            canonical, go_snapshot, exam_snapshot
        )
        candidate_review_reasons = sorted(
            set(answer_reasons + classification_reasons)
        )
        community_sources = [
            claim["source"]
            for claim in answer_claims
            if claim["source"] in {"gateoverflow", "examside"}
            and answer is not None
            and _answer_fingerprint(claim["value"]) == _answer_fingerprint(answer)
        ]

        source_page = canonical.get("source_page")
        source_reference = _source_reference(manifest_paper)
        promotion = evaluate_promotion_evidence(
            source_page=source_page,
            source_reference=source_reference,
            original_content_sha256=None,
            answer_status=answer_status,
            official_key_sha256=_official_key_hash(manifest_paper),
            community_answer_sources=community_sources,
            is_2013_canonical=paper_id == "gate-cs-2013",
            booklet_occurrence_bijection_verified=booklet_2013_verified,
        )
        blocker_counts.update(promotion["blockers"])

        has_exact_candidate = bool(
            question_text
            or go_snapshot
            or exam_snapshot
            or canonical.get("accepted_answers") is not None
        )
        if ambiguity_reasons:
            status = "ambiguous"
        elif has_exact_candidate:
            status = "exact"
        else:
            status = "unmatched"
        paper_reports[paper_id][status] += 1
        paper_reports[paper_id]["canonical_content"] += int(
            bool(isinstance(canonical_question, str) and canonical_question.strip())
        )
        paper_reports[paper_id]["gateoverflow_exact"] += int(go_snapshot is not None)
        paper_reports[paper_id]["examside_exact"] += int(exam_snapshot is not None)
        paper_reports[paper_id]["question_candidate"] += int(question_text is not None)
        paper_reports[paper_id]["answer_candidate"] += int(answer is not None)
        paper_reports[paper_id]["options_candidate"] += int(bool(options))
        paper_reports[paper_id]["classification_review_required"] += int(
            bool(classification_reasons)
        )
        paper_reports[paper_id]["course_classified"] += int(bool(course))
        paper_reports[paper_id]["topic_classified"] += int(bool(topic))
        paper_reports[paper_id][
            "classification_" + classification["classification_outcome"]
        ] += 1
        paper_reports[paper_id]["classification_conflict"] += int(
            bool(classification["conflict"])
        )
        paper_reports[paper_id]["classification_unresolved_conflict"] += int(
            bool(classification["unresolved_conflict"])
        )
        paper_reports[paper_id]["classification_override_resolved_conflict"] += int(
            bool(classification["override_resolved_conflict"])
        )
        remote_assets = exam_snapshot.get("remote_assets", []) if exam_snapshot else []
        paper_reports[paper_id]["remote_asset_references_not_fetched"] += len(
            remote_assets
        )
        paper_reports[paper_id]["unsafe_remote_asset_references"] += sum(
            bool(asset.get("rejection_reason")) for asset in remote_assets
        )
        paper_reports[paper_id]["active_html_detected"] += int(
            bool(exam_snapshot and exam_snapshot.get("active_html_detected"))
        )

        row = {
            "source_paper_id": paper_id,
            "item_label": canonical.get("item_label"),
            "ordinal": ordinal,
            "reconciliation_status": status,
            "withheld_reasons": sorted(set(ambiguity_reasons)),
            "candidate_review_reasons": candidate_review_reasons,
            "candidate": {
                "question_text": question_text,
                "question_text_sha256": _sha256_text(question_text)
                if question_text
                else None,
                "question_source": question_source,
                "options": options,
                "options_source": options_source,
                "item_type": item_type,
                "item_type_source": item_type_source,
                "marks": canonical.get("marks")
                if canonical.get("marks") is not None
                else exam_snapshot.get("marks")
                if exam_snapshot
                else None,
                "course": course,
                "course_source": course_source,
                "topic": topic,
                "topic_source": topic_source,
                "classification_claims": classification["claims"],
                "classification_policy_decision": classification[
                    "policy_decision"
                ],
                "slot_classification_policy_decision": classification[
                    "slot_policy_decision"
                ],
                "classification_outcome": classification[
                    "classification_outcome"
                ],
                "answer": answer,
                "answer_status": answer_status,
                "answer_claims": answer_claims,
            },
            "secondary_snapshots": {
                "gateoverflow": go_snapshot,
                "examside": exam_snapshot,
            },
            "original_source_evidence": {
                "source_reference": source_reference,
                "source_pdf_sha256": _validate_sha256(
                    manifest_paper.get("local_sha256")
                ),
                "source_page": source_page,
                "original_item_content_sha256": None,
                "official_answer_key_sha256": _official_key_hash(manifest_paper),
            },
            "promotion_review": promotion,
            "practice_eligible": False,
        }
        rows.append(row)

    if slot_classification_policy is not None:
        expected_review_keys = set(slot_classification_policy.decisions)
        if base_review_keys != expected_review_keys:
            missing = sorted(base_review_keys - expected_review_keys)
            stale = sorted(expected_review_keys - base_review_keys)
            raise CandidateReconciliationError(
                "question-evidence slot policy does not exactly cover the base "
                f"review population: missing={missing!r}, stale={stale!r}"
            )

    reports = []
    totals = Counter()
    paper_by_id = {str(paper["id"]): paper for paper in papers}
    for paper_id in [str(paper["id"]) for paper in papers]:
        counter = paper_reports[paper_id]
        expected = int(paper_by_id[paper_id]["expected_item_count"])
        if counter["exact"] + counter["ambiguous"] + counter["unmatched"] != expected:
            raise CandidateReconciliationError(
                f"{paper_id}: audit status counts do not sum to {expected}"
            )
        totals.update(counter)
        reports.append(
            {
                "paper_id": paper_id,
                "year": int(paper_by_id[paper_id]["year"]),
                "session": paper_by_id[paper_id].get("session"),
                "expected_slots": expected,
                **{
                    name: counter[name]
                    for name in (
                        "exact",
                        "ambiguous",
                        "unmatched",
                        "canonical_content",
                        "gateoverflow_exact",
                        "examside_exact",
                        "question_candidate",
                        "options_candidate",
                        "answer_candidate",
                        "classification_review_required",
                        "classification_mapped",
                        "classification_out_of_syllabus",
                        "classification_review",
                        "course_classified",
                        "topic_classified",
                        "classification_conflict",
                        "classification_unresolved_conflict",
                        "classification_override_resolved_conflict",
                        "remote_asset_references_not_fetched",
                        "unsafe_remote_asset_references",
                        "active_html_detected",
                    )
                },
                "audit_blockers": (
                    ["2013_booklet_occurrence_bijection_missing"]
                    if paper_id == "gate-cs-2013" and not booklet_2013_verified
                    else []
                ),
            }
        )
    if totals["exact"] + totals["ambiguous"] + totals["unmatched"] != EXPECTED_SLOT_COUNT:
        raise CandidateReconciliationError("global audit status counts are incomplete")
    return rows, {
        "slots": {
            name: totals[name]
            for name in (
                "exact",
                "ambiguous",
                "unmatched",
                "canonical_content",
                "gateoverflow_exact",
                "examside_exact",
                "question_candidate",
                "options_candidate",
                "answer_candidate",
                "classification_review_required",
                "classification_mapped",
                "classification_out_of_syllabus",
                "classification_review",
                "course_classified",
                "topic_classified",
                "classification_conflict",
                "classification_unresolved_conflict",
                "classification_override_resolved_conflict",
                "remote_asset_references_not_fetched",
                "unsafe_remote_asset_references",
                "active_html_detected",
            )
        },
        "blocker_counts": dict(sorted(blocker_counts.items())),
        "classification": {
            "policy_version": classification_policy.policy_version
            if classification_policy
            else None,
            "policy_sha256": classification_policy.source_sha256
            if classification_policy
            else None,
            "source_record_count": classification_policy.observed_record_count
            if classification_policy
            else None,
            "source_signature_count": (
                classification_policy.observed_signature_count
                if classification_policy
                else None
            ),
            "decision_count": len(classification_policy.decisions)
            if classification_policy
            else 0,
            "override_count": len(classification_policy.overrides)
            if classification_policy
            else 0,
            "slot_policy_version": slot_classification_policy.policy_version
            if slot_classification_policy
            else None,
            "slot_policy_sha256": slot_classification_policy.source_sha256
            if slot_classification_policy
            else None,
            "slot_decision_count": len(slot_classification_policy.decisions)
            if slot_classification_policy
            else 0,
            "slot_decision_outcomes": dict(
                slot_classification_policy.outcome_counts
            )
            if slot_classification_policy
            else {},
            "before": {
                name: classification_before[name]
                for name in (
                    "course_classified",
                    "topic_classified",
                    "manual_review",
                    "conflicts",
                    "unresolved_conflicts",
                    "override_resolved_conflicts",
                )
            },
            "after": {
                name: classification_after[name]
                for name in (
                    "course_classified",
                    "topic_classified",
                    "manual_review",
                    "conflicts",
                    "unresolved_conflicts",
                    "override_resolved_conflicts",
                    "mapped",
                    "out_of_syllabus",
                    "review",
                    "slot_decisions_applied",
                )
            },
        },
        "booklet_occurrence_bijection_2013_verified": booklet_2013_verified,
        "papers": reports,
    }


def _assert_output_safety(value: Any) -> None:
    def visit(node: Any) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                if "explanation" in str(key).casefold():
                    raise CandidateReconciliationError(
                        "third-party explanation metadata leaked into staging output"
                    )
                if key == "practice_eligible" and child is not False:
                    raise CandidateReconciliationError(
                        "staging output contains a practice-eligible row"
                    )
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)
        elif isinstance(node, float) and not math.isfinite(node):
            raise CandidateReconciliationError("non-finite number in staging output")

    visit(value)


def build_candidate_artifact(
    *,
    canonical_artifact: dict[str, Any],
    source_manifest: dict[str, Any],
    canonical_topic_inventory: dict[str, set[str]],
    gateoverflow_rows: list[dict[str, Any]],
    gateoverflow_blocks: dict[tuple[str, int, str], list[dict[str, Any]]],
    examside_rows: list[dict[str, Any]],
    page_audit: dict[str, Any],
    source_file_audit: dict[str, Any] | None,
    classification_policy: topic_classification.TopicClassificationPolicy
    | None = None,
    slot_classification_policy: slot_classification.SlotClassificationPolicy
    | None = None,
    original_provenance_by_key: dict[tuple[str, int], dict[str, Any]]
    | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    papers, manifest_by_id, slots, labels_to_ordinals = _canonical_maps(
        canonical_artifact, source_manifest
    )
    go_exact, go_ambiguous, go_report = _map_gateoverflow(
        gateoverflow_rows,
        gateoverflow_blocks,
        papers=papers,
        slots=slots,
        labels_to_ordinals=labels_to_ordinals,
    )
    exam_exact, exam_ambiguous, exam_report = _map_examside(
        examside_rows,
        papers=papers,
        slots=slots,
        labels_to_ordinals=labels_to_ordinals,
        go_exact=go_exact,
    )
    rows, slot_report = _assemble_rows(
        papers=papers,
        manifest_by_id=manifest_by_id,
        slots=slots,
        topic_inventory=canonical_topic_inventory,
        go_exact=go_exact,
        go_ambiguous=go_ambiguous,
        exam_exact=exam_exact,
        exam_ambiguous=exam_ambiguous,
        classification_policy=classification_policy,
        slot_classification_policy=slot_classification_policy,
        original_provenance_by_key=original_provenance_by_key,
    )
    artifact = {
        "schema_version": SCHEMA_VERSION,
        "source_role": "staging_review_candidates_only",
        "database_writes_performed": False,
        "automatic_promotion_allowed": False,
        "paper_count": len(papers),
        "slot_count": len(rows),
        "questions": rows,
    }
    report = {
        "schema_version": SCHEMA_VERSION,
        "paper_count": len(papers),
        "slot_count": len(rows),
        "database_writes_performed": False,
        "automatic_promotion_allowed": False,
        "source_file_integrity": source_file_audit,
        "gateoverflow_page_integrity": page_audit,
        "gateoverflow": go_report,
        "examside": exam_report,
        "reconciliation": slot_report,
        "known_global_blockers": ([
            {
                "code": "2013_booklet_occurrence_bijection_missing",
                "affected_paper": "gate-cs-2013",
                "affected_slots": 65,
                "requirement": (
                    "Record per-item booklet A/B/C/D occurrence labels and source pages, "
                    "then prove a bijection to the 65 canonical items."
                ),
            }
        ] if not slot_report["booklet_occurrence_bijection_2013_verified"] else []) + [
            {
                "code": "original_item_content_hash_missing",
                "affected_slots": sum(
                    "original_item_content_hash_missing"
                    in row["promotion_review"]["blockers"]
                    for row in rows
                ),
                "requirement": (
                    "Promotion requires an original-paper source page, reference, and "
                    "content hash for the exact item."
                ),
            },
            {
                "code": "answer_evidence_policy",
                "requirement": (
                    "An official answer needs a verified key hash; a community-verified "
                    "answer needs two independent agreeing sources."
                ),
            },
        ],
    }
    _assert_output_safety(artifact)
    _assert_output_safety(report)
    return artifact, report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canonical", type=Path, default=DEFAULT_CANONICAL)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--topic-inventory", type=Path, default=DEFAULT_TOPIC_INVENTORY
    )
    parser.add_argument("--topic-aliases", type=Path, default=DEFAULT_TOPIC_ALIASES)
    parser.add_argument(
        "--slot-classifications",
        type=Path,
        default=DEFAULT_SLOT_CLASSIFICATIONS,
    )
    parser.add_argument(
        "--original-provenance",
        type=Path,
        default=DEFAULT_ORIGINAL_PROVENANCE,
    )
    parser.add_argument("--gateoverflow-index", type=Path, default=DEFAULT_GO_INDEX)
    parser.add_argument("--gateoverflow-pages", type=Path, default=DEFAULT_GO_PAGES)
    parser.add_argument("--examside-index", type=Path, default=DEFAULT_EXAMSIDE_INDEX)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--skip-source-file-verification",
        action="store_true",
        help="Tests only: do not resolve/hash the original manifest PDFs.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    canonical_artifact = _read_json(args.canonical.resolve())
    source_manifest = _read_json(args.manifest.resolve())
    topic_inventory_path = args.topic_inventory.resolve()
    topic_inventory = _canonical_topic_inventory(_read_json(topic_inventory_path))
    go_rows = _read_jsonl(args.gateoverflow_index.resolve())
    valid_slot_keys = {
        (str(row.get("source_paper_id") or ""), int(row.get("ordinal")))
        for row in canonical_artifact.get("questions", [])
        if row.get("source_paper_id") and row.get("ordinal") is not None
    }
    try:
        classification_policy = (
            topic_classification.load_topic_classification_policy(
                args.topic_aliases.resolve(),
                inventory=topic_inventory,
                gateoverflow_rows=go_rows,
                valid_slot_keys=valid_slot_keys,
            )
        )
    except topic_classification.TopicClassificationError as exc:
        raise CandidateReconciliationError(str(exc)) from exc
    try:
        slot_classification_policy = (
            slot_classification.load_slot_classification_policy(
                args.slot_classifications.resolve(),
                inventory=topic_inventory,
                inventory_sha256=hashlib.sha256(
                    topic_inventory_path.read_bytes()
                ).hexdigest(),
                base_topic_policy_sha256=classification_policy.source_sha256,
                valid_slot_keys=valid_slot_keys,
            )
        )
    except slot_classification.SlotClassificationError as exc:
        raise CandidateReconciliationError(str(exc)) from exc
    original_provenance_raw = _read_json(args.original_provenance.resolve())
    original_items = original_provenance_raw.get("items")
    if not isinstance(original_items, list):
        raise CandidateReconciliationError(
            "original provenance must contain an items list"
        )
    original_provenance_by_key = {
        (str(item.get("source_paper_id") or ""), int(item.get("canonical_ordinal"))): item
        for item in original_items
        if isinstance(item, dict) and item.get("canonical_ordinal") is not None
    }
    if set(original_provenance_by_key) != valid_slot_keys:
        raise CandidateReconciliationError(
            "original provenance does not exactly cover the canonical slots"
        )
    exam_rows = _read_jsonl(args.examside_index.resolve())
    go_blocks, page_audit = _load_gateoverflow_blocks(
        args.gateoverflow_pages.resolve()
    )

    source_file_audit = None
    if not args.skip_source_file_verification:
        source_file_audit = canonical_builder._verify_manifest_sources(
            source_manifest["papers"], args.manifest.resolve()
        )

    artifact, report = build_candidate_artifact(
        canonical_artifact=canonical_artifact,
        source_manifest=source_manifest,
        canonical_topic_inventory=topic_inventory,
        gateoverflow_rows=go_rows,
        gateoverflow_blocks=go_blocks,
        examside_rows=exam_rows,
        page_audit=page_audit,
        source_file_audit=source_file_audit,
        classification_policy=classification_policy,
        slot_classification_policy=slot_classification_policy,
        original_provenance_by_key=original_provenance_by_key,
    )
    output = args.output.resolve()
    report_path = (
        args.report.resolve()
        if args.report
        else output.with_name(f"{output.stem}.report.json")
    )
    _write_json(output, artifact)
    _write_json(report_path, report)
    totals = report["reconciliation"]["slots"]
    print(
        "Reconciled {slots} canonical slots: {exact} exact, {ambiguous} "
        "ambiguous, {unmatched} unmatched.".format(
            slots=report["slot_count"],
            exact=totals["exact"],
            ambiguous=totals["ambiguous"],
            unmatched=totals["unmatched"],
        )
    )
    print(
        "ExamSIDE rows: {exact} exact, {ambiguous} ambiguous, {unmatched} "
        "unmatched.".format(
            exact=report["examside"]["exact_record_count"],
            ambiguous=report["examside"]["ambiguous_record_count"],
            unmatched=report["examside"]["unmatched_record_count"],
        )
    )
    print(f"Artifact: {output}")
    print(f"Audit: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
