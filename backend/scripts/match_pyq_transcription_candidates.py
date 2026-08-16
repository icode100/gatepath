"""Propose high-confidence, staging-only PYQ transcription matches.

The matcher joins *remaining* sanitized ExamSIDE rows to canonical PYQ slots.
It requires independent evidence from the official answer-key index, the
verified canonical course/topic classification, and either a hash-bound
original-PDF text block or optional checksum-verified page OCR.  Only mutual
best matches with clear margins are emitted as proposed review content.

This module never opens a database, never copies explanations or solutions,
never marks a question practice-eligible, and never authorizes promotion.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable, Mapping


REPO_DIR = Path(__file__).resolve().parents[2]
BUILD_DIR = REPO_DIR / "tmp" / "pyq" / "build"
DEFAULT_CANDIDATES = BUILD_DIR / "canonical_pyq_candidates.json"
DEFAULT_OVERLAY = BUILD_DIR / "original_question_transcription_overlay.json"
DEFAULT_ANSWERS = (
    REPO_DIR
    / "tmp"
    / "pyq"
    / "reference"
    / "answer-keys"
    / "pyq_answer_key_index.json"
)
DEFAULT_EXAMSIDE = (
    REPO_DIR
    / "tmp"
    / "pyq"
    / "reference"
    / "examside"
    / "examside_reference_index.jsonl"
)
DEFAULT_LOCATORS = REPO_DIR / "backend" / "data" / "pyq_original_locator_overrides.json"
DEFAULT_OCR_ROOT = REPO_DIR / "tmp" / "pyq" / "locator-qa"
DEFAULT_OUTPUT = BUILD_DIR / "pyq_transcription_matches.json"

SCHEMA_VERSION = "1.0-staging-high-confidence-transcription-matches"
EXPECTED_SLOTS = 2712
EXPECTED_LOCATORS = 625
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
ACTIVE_HTML_RE = re.compile(
    r"<\s*(?:script|iframe|object|embed)\b|\son[a-z]+\s*=|javascript\s*:",
    re.IGNORECASE,
)
NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")
RANGE_RE = re.compile(
    r"^\s*(-?\d+(?:\.\d+)?)\s*(?:to|-)\s*"
    r"(-?\d+(?:\.\d+)?)\.?\s*$",
    re.IGNORECASE,
)
FORBIDDEN_KEYS = {
    "practice_eligible",
    "solution",
    "solution_md",
    "explanation",
    "explanation_html",
}
TYPE_MAP = {"mcq": "MCQ", "mcqm": "MSQ", "integer": "NAT"}
COURSE_MAP = {
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
TOPIC_STOP_WORDS = {
    "a",
    "an",
    "and",
    "of",
    "the",
    "to",
    "in",
    "for",
    "language",
    "languages",
    "notation",
    "notations",
    "system",
    "systems",
}


class TranscriptionMatchError(ValueError):
    """Raised when inputs drift or evidence is insufficiently constrained."""


@dataclass(frozen=True, slots=True)
class TextEvidence:
    kind: str
    text: str
    text_sha256: str
    provenance: Mapping[str, Any]
    confidence: float | None = None


@dataclass(frozen=True, slots=True)
class Edge:
    source_id: str
    slot: tuple[str, int]
    score: float
    text_score: float
    topic_score: float
    evidence: TextEvidence
    secondary_text_score: float | None


class _PlainTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.visual_reference = False

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        folded = tag.casefold()
        if folded == "img":
            self.visual_reference = True
            alt = dict(attrs).get("alt")
            if alt:
                self.parts.append(f" [image: {alt}] ")
        elif folded in {"br", "p", "div", "li", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"p", "div", "li", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def text(self) -> str:
        value = html.unescape("".join(self.parts))
        lines = [" ".join(line.split()) for line in value.splitlines()]
        return "\n".join(line for line in lines if line).strip()


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


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TranscriptionMatchError(f"Cannot read JSON input {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise TranscriptionMatchError(f"{path}: expected a JSON object")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise TranscriptionMatchError(f"Cannot read JSONL input {path}: {exc}") from exc
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise TranscriptionMatchError(f"{path}:{number}: invalid JSON") from exc
        if not isinstance(value, dict):
            raise TranscriptionMatchError(f"{path}:{number}: row is not an object")
        rows.append(value)
    return rows


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _input_binding(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(REPO_DIR)).replace("\\", "/")
        if path.is_relative_to(REPO_DIR)
        else str(path),
        "sha256": _sha256_file(path),
        "bytes": path.stat().st_size,
    }


def _validate_embedded_hash(value: dict[str, Any], *, label: str) -> None:
    expected = value.get("artifact_sha256")
    if expected is None:
        return
    if not isinstance(expected, str) or HASH_RE.fullmatch(expected) is None:
        raise TranscriptionMatchError(f"{label}: malformed artifact_sha256")
    core = {key: child for key, child in value.items() if key != "artifact_sha256"}
    if _canonical_json_sha256(core) != expected:
        raise TranscriptionMatchError(f"{label}: embedded artifact hash mismatch")


def _slot_key(row: Mapping[str, Any], ordinal_name: str) -> tuple[str, int]:
    paper = str(row.get("source_paper_id") or row.get("paper_id") or "").strip()
    ordinal = row.get(ordinal_name)
    if not paper or not isinstance(ordinal, int) or ordinal < 1:
        raise TranscriptionMatchError(f"Invalid slot identity {paper!r}/{ordinal!r}")
    return paper, ordinal


def _unique_slots(
    rows: Any, *, ordinal_name: str, label: str
) -> dict[tuple[str, int], dict[str, Any]]:
    if not isinstance(rows, list):
        raise TranscriptionMatchError(f"{label}: missing item list")
    result: dict[tuple[str, int], dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise TranscriptionMatchError(f"{label}: row is not an object")
        key = _slot_key(row, ordinal_name)
        if key in result:
            raise TranscriptionMatchError(f"{label}: duplicate slot {key}")
        result[key] = row
    return result


def _plain_text(value: Any) -> tuple[str | None, bool]:
    if not isinstance(value, str) or not value.strip():
        return None, False
    if ACTIVE_HTML_RE.search(value):
        raise TranscriptionMatchError("ExamSIDE row contains active HTML")
    parser = _PlainTextParser()
    parser.feed(value)
    parser.close()
    text = parser.text()
    return (text or None), parser.visual_reference


def _tokens(value: str) -> list[str]:
    folded = unicodedata.normalize("NFKC", value or "").casefold()
    return re.findall(r"[a-z]+(?:'[a-z]+)?|\d+(?:\.\d+)?", folded)


def _topic_tokens(value: str) -> set[str]:
    return {token for token in _tokens(value) if token not in TOPIC_STOP_WORDS}


def _topic_similarity(canonical: str, source: str) -> float:
    left, right = _topic_tokens(canonical), _topic_tokens(source)
    if not left or not right:
        return 0.0
    overlap = len(left & right)
    containment = overlap / min(len(left), len(right))
    jaccard = overlap / len(left | right)
    return round(max(containment * 0.9, jaccard), 6)


def _text_similarity(candidate: str, evidence: str) -> tuple[float, float, float]:
    left, right = _tokens(candidate), _tokens(evidence)
    if len(left) < 6 or len(right) < 6:
        return 0.0, 0.0, 0.0
    left_counts, right_counts = Counter(left), Counter(right)
    overlap = sum((left_counts & right_counts).values())
    coverage = overlap / len(left)
    sequence = SequenceMatcher(None, left, right, autojunk=False)
    ratio = sequence.ratio()
    longest = sequence.find_longest_match().size / len(left)
    score = max(ratio, 0.55 * coverage + 0.45 * longest)
    return round(score, 6), round(coverage, 6), round(longest, 6)


def _parse_decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError, AttributeError):
        return None


def _candidate_numeric_interval(value: Any) -> tuple[Decimal, Decimal] | None:
    text = str(value or "").strip()
    scalar = NUMBER_RE.fullmatch(text)
    if scalar:
        number = _parse_decimal(text)
        return (number, number) if number is not None else None
    match = RANGE_RE.fullmatch(text)
    if not match:
        return None
    minimum, maximum = _parse_decimal(match.group(1)), _parse_decimal(match.group(2))
    if minimum is None or maximum is None or minimum > maximum:
        return None
    return minimum, maximum


def _answer_agrees(question: Mapping[str, Any], official: Mapping[str, Any]) -> bool:
    selected = official.get("selected_answer")
    if not isinstance(selected, dict):
        return False
    kind = selected.get("kind")
    if kind == "options":
        expected = tuple(sorted(str(value).upper() for value in selected.get("options") or []))
        observed = tuple(
            sorted(str(value).upper() for value in question.get("correct_options") or [])
        )
        return bool(expected) and observed == expected
    if kind == "numeric_ranges":
        observed = _candidate_numeric_interval(question.get("numerical_answer"))
        if observed is None:
            return False
        for interval in selected.get("ranges") or []:
            if not isinstance(interval, dict):
                continue
            minimum = _parse_decimal(interval.get("minimum"))
            maximum = _parse_decimal(interval.get("maximum"))
            if minimum is not None and maximum is not None:
                if minimum <= observed[0] <= observed[1] <= maximum:
                    return True
    return False


def _paper_id(row: Mapping[str, Any], paper_ids: set[str]) -> str | None:
    paper = row.get("paper") if isinstance(row.get("paper"), dict) else {}
    slug = str(paper.get("slug") or "").strip().casefold()
    direct = slug.replace("gate-cse-", "gate-cs-", 1)
    if direct in paper_ids:
        return direct
    year_match = re.search(r"(?:19|20)\d{2}", slug)
    if year_match is None:
        try:
            year = int(paper.get("year"))
        except (TypeError, ValueError):
            return None
    else:
        year = int(year_match.group())
    candidates = sorted(paper_id for paper_id in paper_ids if f"-{year}" in paper_id)
    if len(candidates) == 1:
        return candidates[0]
    wanted_match = re.search(r"(?:set|session)[-_ ]?(\d+)", slug)
    if wanted_match is None:
        wanted_match = re.search(r"(\d+)\s*$", str(paper.get("session") or ""))
    if wanted_match:
        wanted = int(wanted_match.group(1))
        matched = [
            candidate
            for candidate in candidates
            if re.search(rf"(?:set|session)-{wanted}$", candidate)
        ]
        return matched[0] if len(matched) == 1 else None
    return None


def _load_locators(
    path: Path | None,
    *,
    candidates: Mapping[tuple[str, int], Mapping[str, Any]],
) -> tuple[dict[tuple[str, int], dict[str, Any]], dict[str, Any] | None]:
    if path is None or not path.is_file():
        return {}, None
    raw = _read_json(path)
    if (
        raw.get("locator_count") != EXPECTED_LOCATORS
        or raw.get("review_required") is not True
        or raw.get("production_import_authorized") is not False
        or raw.get("practice_eligible_count") != 0
        or raw.get("unresolved_locators") != []
    ):
        raise TranscriptionMatchError("Locator overlay staging invariants failed")
    render_spec = raw.get("render_specification")
    if render_spec != {
        "format": "pgm",
        "dpi": 144,
        "color_mode": "gray",
        "renderer": "pdftoppm",
    }:
        raise TranscriptionMatchError("Locator overlay render specification drifted")
    result: dict[tuple[str, int], dict[str, Any]] = {}
    papers = raw.get("papers")
    if not isinstance(papers, list):
        raise TranscriptionMatchError("Locator overlay papers are missing")
    for paper in papers:
        if not isinstance(paper, dict) or paper.get("review_required") is not True:
            raise TranscriptionMatchError("Locator paper must remain review-required")
        paper_id = str(paper.get("paper_id") or "")
        source_sha = str(paper.get("source_pdf_sha256") or "").casefold()
        if HASH_RE.fullmatch(source_sha) is None:
            raise TranscriptionMatchError(f"{paper_id}: malformed source PDF hash")
        page_count = paper.get("source_page_count")
        pages: dict[int, dict[str, Any]] = {}
        for evidence in paper.get("page_evidence") or []:
            page = evidence.get("page") if isinstance(evidence, dict) else None
            if (
                not isinstance(page, int)
                or page in pages
                or HASH_RE.fullmatch(str(evidence.get("sha256") or "")) is None
                or any(evidence.get(key) != render_spec[key] for key in ("format", "dpi", "color_mode"))
            ):
                raise TranscriptionMatchError(f"{paper_id}: invalid page evidence")
            pages[page] = evidence
        for locator in paper.get("locators") or []:
            if not isinstance(locator, dict):
                raise TranscriptionMatchError(f"{paper_id}: invalid locator")
            key = (paper_id, int(locator.get("canonical_ordinal")))
            if key in result or key not in candidates:
                raise TranscriptionMatchError(f"Duplicate or unknown locator {key}")
            candidate = candidates[key]
            if str(locator.get("item_label") or "") != str(candidate.get("item_label") or ""):
                raise TranscriptionMatchError(f"{key}: locator item label drifted")
            page = locator.get("source_page")
            if not isinstance(page, int) or page not in pages or not 1 <= page <= int(page_count):
                raise TranscriptionMatchError(f"{key}: locator page is invalid")
            if locator["item_label"] not in (pages[page].get("item_labels") or []):
                raise TranscriptionMatchError(f"{key}: locator label absent from page evidence")
            original = candidate.get("original_source_evidence") or {}
            if original.get("source_pdf_sha256") != source_sha:
                raise TranscriptionMatchError(f"{key}: locator/candidate PDF hash mismatch")
            result[key] = {
                "source_page": page,
                "source_pdf_sha256": source_sha,
                "rendered_page_sha256": pages[page]["sha256"],
                "evidence_method": pages[page].get("evidence_method"),
            }
    if len(result) != EXPECTED_LOCATORS:
        raise TranscriptionMatchError(
            f"Locator overlay contains {len(result)} keys, expected {EXPECTED_LOCATORS}"
        )
    return result, _input_binding(path)


def _load_ocr(
    root: Path | None,
    *,
    locators: Mapping[tuple[str, int], Mapping[str, Any]],
) -> tuple[dict[tuple[str, int], TextEvidence], list[dict[str, Any]]]:
    if root is None or not root.is_dir() or not locators:
        return {}, []
    by_paper: dict[str, set[int]] = defaultdict(set)
    for (paper_id, _), locator in locators.items():
        by_paper[paper_id].add(int(locator["source_page"]))
    page_text: dict[tuple[str, int], TextEvidence] = {}
    bindings: list[dict[str, Any]] = []
    for paper_id, wanted_pages in sorted(by_paper.items()):
        candidates = [
            root / f"{paper_id}-144dpi" / "ocr.json",
            root / paper_id / "ocr.json",
        ]
        path = next((candidate for candidate in candidates if candidate.is_file()), None)
        if path is None:
            continue
        raw = _read_json(path)
        expected_pdf_sha = next(
            str(locator["source_pdf_sha256"])
            for key, locator in locators.items()
            if key[0] == paper_id
        )
        if (
            raw.get("paper_id") != paper_id
            or raw.get("source_pdf_sha256") != expected_pdf_sha
            or raw.get("render_dpi") != 144
        ):
            raise TranscriptionMatchError(f"{paper_id}: OCR identity drifted")
        bindings.append(_input_binding(path))
        seen_pages: set[int] = set()
        for page in raw.get("pages") or []:
            if not isinstance(page, dict) or not isinstance(page.get("page"), int):
                raise TranscriptionMatchError(f"{paper_id}: malformed OCR page")
            page_number = int(page["page"])
            if page_number in seen_pages:
                raise TranscriptionMatchError(f"{paper_id}: duplicate OCR page {page_number}")
            seen_pages.add(page_number)
            if page_number not in wanted_pages:
                continue
            image_name = str(page.get("image") or "")
            image_path = path.parent / image_name
            image_sha = str(page.get("image_sha256") or "").casefold()
            if (
                not image_path.is_file()
                or HASH_RE.fullmatch(image_sha) is None
                or _sha256_file(image_path) != image_sha
            ):
                raise TranscriptionMatchError(
                    f"{paper_id}/page-{page_number}: OCR image hash mismatch"
                )
            lines = page.get("lines") or []
            normalized: list[tuple[float, float, str, float]] = []
            for line in lines:
                if not isinstance(line, dict):
                    continue
                text = str(line.get("text") or "").strip()
                confidence = line.get("confidence")
                box = line.get("box") or []
                if not text or not isinstance(confidence, (int, float)) or confidence < 0.45:
                    continue
                try:
                    top = min(float(point[1]) for point in box)
                    left = min(float(point[0]) for point in box)
                except (TypeError, ValueError, IndexError):
                    continue
                normalized.append((top, left, text, float(confidence)))
            normalized.sort()
            text = "\n".join(item[2] for item in normalized)
            if not text:
                continue
            mean_confidence = sum(item[3] for item in normalized) / len(normalized)
            page_text[(paper_id, page_number)] = TextEvidence(
                kind="checksum_bound_ocr_page",
                text=text,
                text_sha256=_sha256_text(text),
                confidence=round(mean_confidence, 6),
                provenance={
                    "ocr_json_sha256": bindings[-1]["sha256"],
                    "ocr_image_sha256": image_sha,
                    "source_pdf_sha256": expected_pdf_sha,
                    "source_page": page_number,
                },
            )
    result: dict[tuple[str, int], TextEvidence] = {}
    for key, locator in locators.items():
        evidence = page_text.get((key[0], int(locator["source_page"])))
        if evidence is not None:
            result[key] = evidence
    return result, bindings


def _overlay_evidence(item: Mapping[str, Any]) -> TextEvidence | None:
    proposed = item.get("proposed_overlay")
    if not isinstance(proposed, dict):
        return None
    text = proposed.get("question_text")
    digest = proposed.get("question_text_sha256")
    if not isinstance(text, str) or not text.strip() or digest != _sha256_text(text):
        return None
    original = item.get("original_source_evidence") or {}
    if original.get("evidence_status") != "exact_text_block":
        return None
    block_hash = str(original.get("text_block_sha256") or "")
    pdf_hash = str(original.get("source_pdf_sha256") or "")
    if HASH_RE.fullmatch(block_hash) is None or HASH_RE.fullmatch(pdf_hash) is None:
        raise TranscriptionMatchError("Original overlay text evidence is not hash-bound")
    return TextEvidence(
        kind="original_pdf_text_block",
        text=text,
        text_sha256=digest,
        provenance={
            "source_pdf_sha256": pdf_hash,
            "source_pages": list(original.get("source_pages") or []),
            "text_block_sha256": block_hash,
        },
    )


def _candidate_content(question: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    text, visual = _plain_text(question.get("question_text"))
    if text is None:
        raise TranscriptionMatchError("Matched ExamSIDE row has no sanitized question text")
    flags = ["remote_visual_asset_not_copied"] if visual else []
    options: list[dict[str, Any]] = []
    for option in question.get("options") or []:
        if not isinstance(option, dict):
            continue
        identifier = str(option.get("identifier") or "").strip().upper()
        content, option_visual = _plain_text(option.get("content"))
        if identifier not in {"A", "B", "C", "D"} or content is None:
            continue
        if option_visual:
            flags.append("remote_visual_asset_not_copied")
        options.append(
            {"id": identifier, "text": content, "text_sha256": _sha256_text(content)}
        )
    if options and [row["id"] for row in options] != ["A", "B", "C", "D"]:
        flags.append("incomplete_option_set_not_proposed")
        options = []
    return {
        "question_text": text,
        "question_text_sha256": _sha256_text(text),
        "options": options or None,
        "options_sha256": _canonical_json_sha256(options) if options else None,
    }, sorted(set(flags))


def _safe_output(value: Any, path: str = "root") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_KEYS:
                raise TranscriptionMatchError(f"Forbidden output field {path}.{key}")
            _safe_output(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _safe_output(child, f"{path}[{index}]")


def _margin(edges: list[Edge]) -> float:
    if len(edges) < 2:
        return 1.0
    return round(edges[0].score - edges[1].score, 6)


def _select_mutual_matches(
    source_ids: Iterable[str],
    *,
    edges_by_source: Mapping[str, list[Edge]],
    edges_by_slot: Mapping[tuple[str, int], list[Edge]],
    minimum_margin: float,
) -> tuple[list[Edge], list[dict[str, Any]]]:
    """Select only mutual, uniquely separated edges.

    This small pure function makes the decisive fail-closed gate independently
    testable.  Callers must exclude already-joined secondary rows before
    passing ``source_ids``.
    """

    if minimum_margin < 0:
        raise TranscriptionMatchError("minimum_margin cannot be negative")
    accepted: list[Edge] = []
    decisions: list[dict[str, Any]] = []
    for source_id in sorted(set(source_ids)):
        values = sorted(
            edges_by_source.get(source_id, []),
            key=lambda edge: (-edge.score, edge.slot),
        )
        if not values:
            decisions.append({"source_id": source_id, "status": "unmatched"})
            continue
        top = values[0]
        slot_values = sorted(
            edges_by_slot.get(top.slot, []),
            key=lambda edge: (-edge.score, edge.source_id),
        )
        if not slot_values:
            raise TranscriptionMatchError(
                f"Edge index drift: {source_id} -> {top.slot} is absent from slot index"
            )
        source_margin = _margin(values)
        slot_margin = _margin(slot_values)
        mutual = slot_values[0].source_id == source_id
        if mutual and source_margin >= minimum_margin and slot_margin >= minimum_margin:
            accepted.append(top)
            decisions.append(
                {
                    "source_id": source_id,
                    "status": "exact_proposed_review",
                    "source_paper_id": top.slot[0],
                    "canonical_ordinal": top.slot[1],
                    "score": top.score,
                    "source_margin": source_margin,
                    "slot_margin": slot_margin,
                }
            )
        else:
            decisions.append(
                {
                    "source_id": source_id,
                    "status": "review",
                    "top_candidates": [
                        {
                            "source_paper_id": edge.slot[0],
                            "canonical_ordinal": edge.slot[1],
                            "score": edge.score,
                        }
                        for edge in values[:2]
                    ],
                    "source_margin": source_margin,
                    "slot_margin": slot_margin,
                    "mutual_best": mutual,
                }
            )
    return accepted, decisions


def build_matches(
    *,
    candidates_path: Path = DEFAULT_CANDIDATES,
    overlay_path: Path = DEFAULT_OVERLAY,
    answers_path: Path = DEFAULT_ANSWERS,
    examside_path: Path = DEFAULT_EXAMSIDE,
    locators_path: Path | None = DEFAULT_LOCATORS,
    ocr_root: Path | None = DEFAULT_OCR_ROOT,
    minimum_margin: float = 0.08,
) -> tuple[dict[str, Any], dict[str, Any]]:
    candidates_raw = _read_json(candidates_path)
    overlay_raw = _read_json(overlay_path)
    answers_raw = _read_json(answers_path)
    examside_rows = _read_jsonl(examside_path)
    _validate_embedded_hash(overlay_raw, label="original transcription overlay")
    candidates = _unique_slots(
        candidates_raw.get("questions"), ordinal_name="ordinal", label="canonical candidates"
    )
    overlay = _unique_slots(
        overlay_raw.get("items"),
        ordinal_name="canonical_ordinal",
        label="original transcription overlay",
    )
    if len(candidates) != EXPECTED_SLOTS or set(candidates) != set(overlay):
        raise TranscriptionMatchError("Canonical candidates/overlay are not the same 2,712 slots")
    paper_ids = {key[0] for key in candidates}
    if len(paper_ids) != 39:
        raise TranscriptionMatchError("Canonical candidates must cover 39 papers")

    answers = {
        _slot_key(row, "canonical_ordinal"): row
        for row in answers_raw.get("resolutions") or []
        if isinstance(row, dict) and row.get("status") == "official"
    }
    if len(answers) != int(answers_raw.get("summary", {}).get("official_resolution_count", -1)):
        raise TranscriptionMatchError("Official answer index resolution count drifted")
    locators, locator_binding = _load_locators(locators_path, candidates=candidates)
    ocr_evidence, ocr_bindings = _load_ocr(ocr_root, locators=locators)

    joined_source_ids = {
        str(snapshot.get("source_id"))
        for row in candidates.values()
        for snapshot in [(row.get("secondary_snapshots") or {}).get("examside")]
        if isinstance(snapshot, dict) and snapshot.get("source_id")
    }
    overlay_text = {
        key: evidence
        for key, item in overlay.items()
        if (evidence := _overlay_evidence(item)) is not None
    }
    target_slots = {
        key
        for key, row in candidates.items()
        if key in answers
        and (row.get("candidate") or {}).get("classification_outcome") == "mapped"
        and (row.get("candidate") or {}).get("course")
        and (row.get("candidate") or {}).get("topic")
        and ((row.get("secondary_snapshots") or {}).get("examside") is None)
        and (
            bool((overlay[key].get("gap_before") or {}).get("question_stem_missing"))
            or bool((overlay[key].get("gap_before") or {}).get("objective_options_missing"))
        )
        and (key in overlay_text or key in ocr_evidence)
    }

    source_rows: dict[str, dict[str, Any]] = {}
    source_papers: dict[str, str | None] = {}
    source_content: dict[str, dict[str, Any]] = {}
    source_flags: dict[str, list[str]] = {}
    input_rejections: Counter[str] = Counter()
    for row in examside_rows:
        question = row.get("question") if isinstance(row.get("question"), dict) else {}
        source_id = str(question.get("source_id") or "").strip()
        if not source_id or source_id in source_rows:
            raise TranscriptionMatchError(f"Duplicate or missing ExamSIDE source_id {source_id!r}")
        source_rows[source_id] = row
        source_papers[source_id] = _paper_id(row, paper_ids)
        if source_id in joined_source_ids:
            input_rejections["already_joined"] += 1
            continue
        try:
            content, flags = _candidate_content(question)
        except TranscriptionMatchError:
            input_rejections["unsafe_or_missing_question_content"] += 1
            continue
        source_content[source_id] = content
        source_flags[source_id] = flags

    edges_by_source: dict[str, list[Edge]] = defaultdict(list)
    edges_by_slot: dict[tuple[str, int], list[Edge]] = defaultdict(list)
    constraint_rejections: Counter[str] = Counter()
    for source_id, content in source_content.items():
        row = source_rows[source_id]
        question = row["question"]
        paper_id = source_papers[source_id]
        if paper_id is None:
            input_rejections["paper_not_resolved"] += 1
            continue
        source_type = TYPE_MAP.get(str(question.get("question_type") or "").casefold())
        source_marks = question.get("marks")
        source_course = COURSE_MAP.get(str(question.get("subject") or "").casefold())
        source_topic = str(question.get("chapter") or question.get("topic") or "")
        if bool(question.get("is_out_of_syllabus")):
            input_rejections["source_marked_out_of_syllabus"] += 1
            continue
        for key in sorted(slot for slot in target_slots if slot[0] == paper_id):
            canonical = candidates[key].get("candidate") or {}
            official = answers[key]
            if source_type != official.get("selected_question_type"):
                constraint_rejections["question_type_mismatch"] += 1
                continue
            if not isinstance(source_marks, int) or source_marks != official.get("selected_marks"):
                constraint_rejections["marks_mismatch"] += 1
                continue
            if not _answer_agrees(question, official):
                constraint_rejections["official_answer_mismatch"] += 1
                continue
            if source_course != canonical.get("course"):
                constraint_rejections["course_mismatch"] += 1
                continue
            topic_score = _topic_similarity(str(canonical.get("topic")), source_topic)
            if topic_score < 0.35:
                constraint_rejections["topic_evidence_weak"] += 1
                continue

            evidences = [
                evidence
                for evidence in (overlay_text.get(key), ocr_evidence.get(key))
                if evidence is not None
            ]
            scored: list[tuple[float, float, float, TextEvidence]] = []
            for evidence in evidences:
                score, coverage, longest = _text_similarity(
                    content["question_text"], evidence.text
                )
                if evidence.kind == "original_pdf_text_block":
                    accepted = score >= 0.74 and coverage >= 0.68
                else:
                    accepted = (
                        score >= 0.62
                        and coverage >= 0.58
                        and longest >= 0.20
                        and (evidence.confidence or 0) >= 0.70
                    )
                if accepted:
                    scored.append((score, coverage, longest, evidence))
            if not scored:
                constraint_rejections["original_text_similarity_weak"] += 1
                continue
            scored.sort(key=lambda value: (-value[0], value[3].kind))
            text_score, _, _, primary = scored[0]
            secondary = scored[1][0] if len(scored) > 1 else None
            existing_text = canonical.get("question_text")
            secondary_text_score = None
            if isinstance(existing_text, str) and existing_text.strip():
                secondary_text_score = _text_similarity(
                    content["question_text"], existing_text
                )[0]
                if secondary_text_score < 0.30:
                    constraint_rejections["existing_secondary_text_conflict"] += 1
                    continue
            score = round(0.90 * text_score + 0.10 * topic_score, 6)
            edge = Edge(
                source_id=source_id,
                slot=key,
                score=score,
                text_score=text_score,
                topic_score=topic_score,
                evidence=primary,
                secondary_text_score=secondary_text_score,
            )
            edges_by_source[source_id].append(edge)
            edges_by_slot[key].append(edge)

    for values in edges_by_source.values():
        values.sort(key=lambda edge: (-edge.score, edge.slot))
    for values in edges_by_slot.values():
        values.sort(key=lambda edge: (-edge.score, edge.source_id))

    accepted, decisions = _select_mutual_matches(
        (source_id for source_id in source_rows if source_id not in joined_source_ids),
        edges_by_source=edges_by_source,
        edges_by_slot=edges_by_slot,
        minimum_margin=minimum_margin,
    )

    matches: list[dict[str, Any]] = []
    for edge in sorted(accepted, key=lambda value: value.slot):
        row = source_rows[edge.source_id]
        question = row["question"]
        content = source_content[edge.source_id]
        canonical = candidates[edge.slot].get("candidate") or {}
        official = answers[edge.slot]
        gaps = overlay[edge.slot].get("gap_before") or {}
        proposed = {
            "question_text": content["question_text"]
            if gaps.get("question_stem_missing")
            else None,
            "question_text_sha256": content["question_text_sha256"]
            if gaps.get("question_stem_missing")
            else None,
            "options": content["options"]
            if gaps.get("objective_options_missing")
            else None,
            "options_sha256": content["options_sha256"]
            if gaps.get("objective_options_missing")
            else None,
        }
        proposed = {key: value for key, value in proposed.items() if value is not None}
        provenance = row.get("provenance") if isinstance(row.get("provenance"), dict) else {}
        raw_hash = str(provenance.get("question_raw_sha256") or "").casefold()
        if HASH_RE.fullmatch(raw_hash) is None:
            raise TranscriptionMatchError(f"{edge.source_id}: missing raw response hash")
        matches.append(
            {
                "source_paper_id": edge.slot[0],
                "canonical_ordinal": edge.slot[1],
                "item_label": candidates[edge.slot].get("item_label"),
                "match_status": "exact_proposed_review",
                "manual_review_required": True,
                "proposed_review_content": proposed or None,
                "review_flags": source_flags[edge.source_id],
                "evidence": {
                    "examside_source_id": edge.source_id,
                    "examside_raw_response_sha256": raw_hash,
                    "official_answer_agreement": True,
                    "official_resolution_claim_ids": list(official.get("claim_ids") or []),
                    "question_type": official.get("selected_question_type"),
                    "marks": official.get("selected_marks"),
                    "canonical_course": canonical.get("course"),
                    "canonical_topic": canonical.get("topic"),
                    "source_topic": question.get("chapter") or question.get("topic"),
                    "score": edge.score,
                    "text_similarity": edge.text_score,
                    "topic_similarity": edge.topic_score,
                    "existing_secondary_text_similarity": edge.secondary_text_score,
                    "original_text_evidence": {
                        "kind": edge.evidence.kind,
                        "text_sha256": edge.evidence.text_sha256,
                        "confidence": edge.evidence.confidence,
                        **dict(edge.evidence.provenance),
                    },
                },
            }
        )

    decision_counts = Counter(row["status"] for row in decisions)
    existing_exact = len(joined_source_ids)
    question_count = sum(
        bool((row.get("proposed_review_content") or {}).get("question_text"))
        for row in matches
    )
    option_count = sum(
        bool((row.get("proposed_review_content") or {}).get("options"))
        for row in matches
    )
    artifact_core = {
        "schema_version": SCHEMA_VERSION,
        "source_role": "staging_secondary_transcription_match_review_only",
        "database_writes_performed": False,
        "production_import_authorized": False,
        "automatic_promotion_allowed": False,
        "input_bindings": {
            "canonical_candidates": _input_binding(candidates_path),
            "original_transcription_overlay": _input_binding(overlay_path),
            "official_answer_index": _input_binding(answers_path),
            "examside_sanitized_index": _input_binding(examside_path),
            "original_locator_overrides": locator_binding,
            "ocr_candidates": ocr_bindings,
        },
        "matching_policy": {
            "requires_same_paper": True,
            "requires_official_answer_type_marks": True,
            "requires_verified_course_topic": True,
            "requires_original_pdf_text_or_checksum_bound_ocr": True,
            "requires_mutual_unique_best": True,
            "minimum_margin": minimum_margin,
        },
        "matches": matches,
        "decisions": decisions,
    }
    _safe_output(artifact_core)
    artifact_sha = _canonical_json_sha256(artifact_core)
    artifact = {**artifact_core, "artifact_sha256": artifact_sha}
    report = {
        "schema_version": SCHEMA_VERSION,
        "artifact_sha256": artifact_sha,
        "inputs": {
            "canonical_slot_count": len(candidates),
            "examside_record_count": len(examside_rows),
            "existing_exact_examside_joins": existing_exact,
            "official_resolution_count": len(answers),
            "eligible_target_slot_count": len(target_slots),
            "locator_count": len(locators),
            "ocr_bound_slot_count": len(ocr_evidence),
            "original_text_bound_slot_count": len(overlay_text),
        },
        "outcomes": {
            "exact_proposed_review": decision_counts["exact_proposed_review"],
            "review": decision_counts["review"],
            "unmatched": decision_counts["unmatched"],
            "new_exact_slot_joins": len(matches),
            "question_stems_recovered_for_review": question_count,
            "objective_option_sets_recovered_for_review": option_count,
            "exact_examside_joins_after_review_acceptance": existing_exact + len(matches),
        },
        "input_rejections": dict(sorted(input_rejections.items())),
        "constraint_rejections": dict(sorted(constraint_rejections.items())),
        "matches_by_paper": dict(
            sorted(Counter(row["source_paper_id"] for row in matches).items())
        ),
        "invariants": {
            "unique_source_rows": len({row["source_id"] for row in decisions})
            == len(decisions),
            "unique_target_slots": len(
                {(row["source_paper_id"], row["canonical_ordinal"]) for row in matches}
            )
            == len(matches),
            "all_matches_require_review": all(
                row["manual_review_required"] is True for row in matches
            ),
            "no_database_or_promotion": artifact["database_writes_performed"] is False
            and artifact["production_import_authorized"] is False
            and artifact["automatic_promotion_allowed"] is False,
            "all_match_content_hashes_valid": all(
                not (content := row.get("proposed_review_content"))
                or (
                    not content.get("question_text")
                    or content.get("question_text_sha256")
                    == _sha256_text(content["question_text"])
                )
                for row in matches
            ),
        },
    }
    if not all(report["invariants"].values()):
        raise TranscriptionMatchError(f"Matcher invariants failed: {report['invariants']}")
    return artifact, report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--overlay", type=Path, default=DEFAULT_OVERLAY)
    parser.add_argument("--answers", type=Path, default=DEFAULT_ANSWERS)
    parser.add_argument("--examside", type=Path, default=DEFAULT_EXAMSIDE)
    parser.add_argument("--locators", type=Path, default=DEFAULT_LOCATORS)
    parser.add_argument("--ocr-root", type=Path, default=DEFAULT_OCR_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--minimum-margin", type=float, default=0.08)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    artifact, report = build_matches(
        candidates_path=args.candidates.resolve(),
        overlay_path=args.overlay.resolve(),
        answers_path=args.answers.resolve(),
        examside_path=args.examside.resolve(),
        locators_path=args.locators.resolve() if args.locators else None,
        ocr_root=args.ocr_root.resolve() if args.ocr_root else None,
        minimum_margin=args.minimum_margin,
    )
    output = args.output.resolve()
    report_path = (
        args.report.resolve()
        if args.report
        else output.with_name(f"{output.stem}.report.json")
    )
    _write_json(output, artifact)
    _write_json(report_path, report)
    print(json.dumps({**report["outcomes"], "output": str(output), "report": str(report_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
