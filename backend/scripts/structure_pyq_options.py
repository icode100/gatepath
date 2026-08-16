"""Conservatively structure explicit PYQ option blocks in a staging artifact.

This script is deliberately downstream of ``reconcile_pyq_candidates.py``.  It
reads the ignored candidate artifact, inspects only exact GateOverflow
question-body snapshots, and writes another ignored review artifact.  It never
opens a database and never makes a question practice eligible.

Only an unambiguous, ordered four-label block is accepted.  Extraction gaps,
book-section spillover, answer/solution text, unsafe HTML, empty choices, and
duplicate choices are withheld for manual transcription from the original
paper.  Third-party explanations are neither read nor copied.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import re
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path
from typing import Any


REPO_DIR = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = (
    REPO_DIR / "tmp" / "pyq" / "build" / "canonical_pyq_candidates.json"
)
DEFAULT_OUTPUT = (
    REPO_DIR
    / "tmp"
    / "pyq"
    / "build"
    / "canonical_pyq_candidates_structured.json"
)
SCHEMA_VERSION = "1.0-staging-option-structure"
EXPECTED_PAPER_COUNT = 39
EXPECTED_SLOT_COUNT = 2712
OBJECTIVE_TYPES = {"mcq", "msq"}
CANONICAL_IDENTIFIERS = ("A", "B", "C", "D")

ACTIVE_HTML_RE = re.compile(
    r"<\s*(?:script|iframe|object|embed)\b|\son[a-z]+\s*=|javascript\s*:",
    re.IGNORECASE,
)
ANSWER_OR_SOLUTION_RE = re.compile(
    r"(?im)^\s*(?:answer(?:\s+key)?|solution|explanation)\s*:?[ \t]*$"
)
GATE_METADATA_RE = re.compile(
    r"(?im)^[ \t]*gate(?:cse?|cs)?[ \t_-]*(?:19|20)\d{2}"
    r"(?:[ \t_-]*(?:set|session)[ \t_-]*\d+)?[ \t]*$"
)
BOOK_SECTION_RE = re.compile(
    r"(?m)^\s*\d{1,2}\.\d{1,3}(?:\.\d{1,3})?\s*$"
)
# In the extracted reference books, inline formula images leave a trailing
# space followed by a newline and then surrounding prose (for example,
# ``Let \n and``).  Normal pdftotext line wraps do not carry that trailing
# space.  Accepting such a block would silently create incomplete choices.
MISSING_INLINE_CONTENT_RE = re.compile(r"(?<!\.)[ \t]+\n[ \t]*(?=\S)")
MISSING_OPERATOR_LINE_BREAK_RE = re.compile(
    r"(?m)\b[A-Za-z0-9][ \t]*\n[ \t]+(?=[A-Za-z])"
)
FOREIGN_EXAM_TAG_RE = re.compile(
    r"(?im)^\s*(?:isro|ugc\s*net|barc|drdo)[ \t_-]*\d{4}(?:[ \t_-]*\d+)?\s*$"
)
DANGLING_MATH_OBJECT_RE = re.compile(
    r"(?i)\b(?:for|of|about)\s+the\s+"
    r"(?:language|matrix|function|expression|graph|grammar|relation|set)\s*$"
)


def _marker_pattern(labels: str) -> re.Pattern[str]:
    escaped = re.escape(labels)
    return re.compile(
        rf"(?m)"
        rf"^[ \t]*(?:\((?P<paren>[{escaped}])\)|"
        rf"(?P<inline>[{escaped}])[.)])[ \t]*(?:\n|[ \t]+)"
        rf"|^[ \t]*(?P<split>[{escaped}])[ \t]*\n"
        rf"[ \t]*\.[ \t]*(?:\n|$)",
        re.IGNORECASE,
    )


LETTER_MARKER_RE = _marker_pattern("ABCD")
NUMBER_MARKER_RE = _marker_pattern("1234")


class OptionStructureError(ValueError):
    """Raised when the input or derived staging artifact is unsafe."""


def _read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _match_label(match: re.Match[str]) -> str:
    for name in ("paren", "inline", "split"):
        value = match.group(name)
        if value:
            return value.upper()
    raise OptionStructureError("option marker did not capture a label")


def _normalized_choice(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _trim_metadata_tail(body: str) -> tuple[str, dict[str, Any]]:
    match = GATE_METADATA_RE.search(body)
    if match is None:
        return body.rstrip(), {"present": False, "marker": None}
    return body[: match.start()].rstrip(), {
        "present": True,
        "marker": match.group(0).strip(),
    }


def _choice_matches(
    body: str, pattern: re.Pattern[str]
) -> list[tuple[re.Match[str], str]]:
    return [(match, _match_label(match)) for match in pattern.finditer(body)]


def parse_explicit_four_choices(body: Any) -> dict[str, Any]:
    """Parse a single explicit four-choice block or explain why it is withheld.

    The returned ``stem`` and ``content_text`` values preserve the source text
    other than newline normalization and boundary whitespace trimming.
    ``content_html`` is escaped because the source is plain PDF extraction, not
    trusted markup; LaTeX delimiters and code characters remain in
    ``content_text`` without interpretation.
    """

    if not isinstance(body, str) or not body.strip():
        return {"status": "unmatched", "reasons": ["empty_source_body"]}
    normalized_body = body.replace("\r\n", "\n").replace("\r", "\n")
    if ACTIVE_HTML_RE.search(normalized_body):
        return {"status": "ambiguous", "reasons": ["unsafe_active_html"]}
    if ANSWER_OR_SOLUTION_RE.search(normalized_body):
        return {
            "status": "ambiguous",
            "reasons": ["answer_or_solution_text_present"],
        }

    question_region, tail = _trim_metadata_tail(normalized_body)
    letter_matches = _choice_matches(question_region, LETTER_MARKER_RE)
    number_matches = _choice_matches(question_region, NUMBER_MARKER_RE)
    populated_schemes = [
        ("letters", CANONICAL_IDENTIFIERS, letter_matches),
        ("numbers", ("1", "2", "3", "4"), number_matches),
    ]
    populated_schemes = [entry for entry in populated_schemes if entry[2]]
    if not populated_schemes:
        return {
            "status": "unmatched",
            "reasons": ["no_explicit_choice_labels"],
            "metadata_tail": tail,
        }
    if len(populated_schemes) != 1:
        return {
            "status": "ambiguous",
            "reasons": ["multiple_choice_label_schemes"],
            "metadata_tail": tail,
        }

    scheme, expected_labels, matches = populated_schemes[0]
    labels = tuple(label for _, label in matches)
    if len(matches) != 4 or labels != expected_labels:
        return {
            "status": "ambiguous",
            "reasons": ["choice_labels_not_exactly_once_in_order"],
            "label_scheme": scheme,
            "observed_labels": list(labels),
            "metadata_tail": tail,
        }

    stem = question_region[: matches[0][0].start()].strip()
    if not stem:
        return {
            "status": "ambiguous",
            "reasons": ["empty_question_stem"],
            "label_scheme": scheme,
            "metadata_tail": tail,
        }

    choices: list[dict[str, Any]] = []
    reasons: list[str] = []
    for index, (match, printed_identifier) in enumerate(matches):
        end = matches[index + 1][0].start() if index < 3 else len(question_region)
        content_text = question_region[match.end() : end].strip()
        if not content_text or not re.search(r"\S", content_text):
            reasons.append("empty_choice_content")
        if BOOK_SECTION_RE.search(content_text):
            reasons.append("book_section_spillover_in_choice")
        if MISSING_INLINE_CONTENT_RE.search(content_text):
            reasons.append("possible_unextracted_inline_content_in_choice")
        if MISSING_OPERATOR_LINE_BREAK_RE.search(content_text):
            reasons.append("possible_unextracted_operator_in_choice")
        content_html = html.escape(content_text, quote=False)
        choices.append(
            {
                "identifier": CANONICAL_IDENTIFIERS[index],
                "source_identifier": printed_identifier,
                "content_html": content_html,
                "content_text": content_text,
                "content_html_sha256": _sha256_text(content_html),
                "source_content_sha256": _sha256_text(content_text),
            }
        )

    if MISSING_INLINE_CONTENT_RE.search(stem):
        reasons.append("possible_unextracted_inline_content_in_stem")
    if FOREIGN_EXAM_TAG_RE.search(stem):
        reasons.append("foreign_exam_editorial_tag_in_stem")
    if DANGLING_MATH_OBJECT_RE.search(stem):
        reasons.append("possible_unextracted_terminal_math_object")
    normalized_choices = [_normalized_choice(row["content_text"]) for row in choices]
    if len(set(normalized_choices)) != 4:
        reasons.append("duplicate_choice_content")
    if any(
        not normalized or re.fullmatch(r"[\W_]+", normalized, re.UNICODE)
        for normalized in normalized_choices
    ):
        reasons.append("choice_content_has_no_semantic_token")
    if reasons:
        return {
            "status": "ambiguous",
            "reasons": sorted(set(reasons)),
            "label_scheme": scheme,
            "metadata_tail": tail,
        }

    return {
        "status": "exact",
        "reasons": [],
        "label_scheme": scheme,
        "stem": stem,
        "stem_sha256": _sha256_text(stem),
        "options": choices,
        "metadata_tail": tail,
        "source_body_sha256": _sha256_text(normalized_body),
    }


def _explicit_answer_labels(value: Any) -> list[str] | None:
    values: list[Any]
    if isinstance(value, str):
        stripped = value.strip().upper()
        if re.fullmatch(r"[A-D1-4]", stripped):
            values = [stripped]
        elif re.fullmatch(r"[A-D1-4](?:\s*[,;]\s*[A-D1-4])+", stripped):
            values = re.split(r"\s*[,;]\s*", stripped)
        else:
            return None
    elif isinstance(value, list) and value:
        values = value
    else:
        return None
    labels = [str(item).strip().upper() for item in values]
    if not labels or any(not re.fullmatch(r"[A-D1-4]", label) for label in labels):
        return None
    if len(set(labels)) != len(labels):
        return None
    return labels


def _objective_type(candidate: dict[str, Any]) -> tuple[str | None, str | None]:
    item_type = str(candidate.get("item_type") or "unknown").strip().casefold()
    if item_type in OBJECTIVE_TYPES:
        return item_type, None
    if item_type != "unknown":
        return None, "known_non_objective_item_type"
    labels = _explicit_answer_labels(candidate.get("answer"))
    if labels is None:
        return None, "objective_type_not_proven"
    return ("mcq" if len(labels) == 1 else "msq"), None


def _validate_existing_options(options: Any) -> list[str]:
    if not isinstance(options, list) or not options:
        return ["existing_options_missing"]
    reasons: list[str] = []
    if len(options) != 4:
        reasons.append("existing_options_not_exactly_four")
    identifiers = [
        str(option.get("identifier") or option.get("id") or "").strip().upper()
        if isinstance(option, dict)
        else ""
        for option in options
    ]
    if tuple(identifiers) != CANONICAL_IDENTIFIERS:
        reasons.append("existing_option_identifiers_invalid")
    contents: list[str] = []
    for option in options:
        if not isinstance(option, dict):
            reasons.append("existing_option_not_an_object")
            continue
        # Canonical skeletons use ``id``/``text`` while sanitized ExamSIDE
        # candidates use ``identifier``/``content_text``.  Both are existing
        # staging schemas and must be validated without rewriting either.
        content = option.get("content_text")
        if content is None:
            content = option.get("text")
        if not isinstance(content, str) or not content.strip():
            reasons.append("existing_option_content_empty")
            continue
        contents.append(_normalized_choice(content))
        html_value = option.get("content_html")
        if isinstance(html_value, str) and ACTIVE_HTML_RE.search(html_value):
            reasons.append("existing_option_active_html")
    if len(contents) == 4 and len(set(contents)) != 4:
        reasons.append("existing_option_content_duplicate")
    return sorted(set(reasons))


def _validate_go_body_hash(snapshot: dict[str, Any], body: str) -> None:
    expected = snapshot.get("question_body_sha256")
    actual = _sha256_text(body)
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise OptionStructureError("GateOverflow question body hash is missing")
    if actual != expected:
        raise OptionStructureError("GateOverflow question body hash mismatch")


def _append_review_reason(row: dict[str, Any], reason: str) -> None:
    current = row.get("candidate_review_reasons")
    values = list(current) if isinstance(current, list) else []
    values.append(f"option_structure:{reason}")
    row["candidate_review_reasons"] = sorted(set(values))


def enrich_candidate_artifact(
    artifact: dict[str, Any], *, expected_slot_count: int | None = EXPECTED_SLOT_COUNT
) -> tuple[dict[str, Any], dict[str, Any]]:
    questions = artifact.get("questions")
    if not isinstance(questions, list):
        raise OptionStructureError("candidate artifact questions are missing")
    if expected_slot_count is not None and len(questions) != expected_slot_count:
        raise OptionStructureError(
            f"candidate artifact must contain {expected_slot_count} slots"
        )

    output = deepcopy(artifact)
    output["schema_version"] = SCHEMA_VERSION
    output["source_role"] = "staging_review_candidates_with_structured_options_only"
    output["database_writes_performed"] = False
    output["automatic_promotion_allowed"] = False

    before = Counter()
    after = Counter()
    outcomes = Counter()
    reason_counts = Counter()
    paper_counts: dict[str, Counter[str]] = defaultdict(Counter)
    representative_rows: list[dict[str, Any]] = []

    for row in output["questions"]:
        if not isinstance(row, dict):
            raise OptionStructureError("candidate question row is not an object")
        if row.get("practice_eligible") is not False:
            raise OptionStructureError("input contains a practice-eligible row")
        candidate = row.get("candidate")
        if not isinstance(candidate, dict):
            raise OptionStructureError("candidate question payload is missing")
        paper_id = str(row.get("source_paper_id") or "")
        options = candidate.get("options")
        options = options if isinstance(options, list) else []
        before["nonempty_option_sets"] += int(bool(options))
        before["valid_four_option_sets"] += int(
            bool(options) and not _validate_existing_options(options)
        )

        option_parse: dict[str, Any]
        if options:
            problems = _validate_existing_options(options)
            if problems:
                candidate["options"] = []
                candidate["options_source"] = None
                option_parse = {
                    "status": "withheld",
                    "source": "existing_candidate_options",
                    "reasons": problems,
                    "rendering_allowed": False,
                }
                for problem in problems:
                    _append_review_reason(row, problem)
                    reason_counts[problem] += 1
                outcomes["existing_withheld"] += 1
                paper_counts[paper_id]["existing_withheld"] += 1
            else:
                option_parse = {
                    "status": "existing_exact",
                    "source": candidate.get("options_source"),
                    "reasons": [],
                    "rendering_allowed": False,
                }
                outcomes["existing_exact"] += 1
                paper_counts[paper_id]["existing_exact"] += 1
        else:
            snapshots = row.get("secondary_snapshots")
            go_snapshot = (
                snapshots.get("gateoverflow") if isinstance(snapshots, dict) else None
            )
            body = (
                go_snapshot.get("question_body_text")
                if isinstance(go_snapshot, dict)
                else None
            )
            if not isinstance(body, str) or not body.strip():
                option_parse = {
                    "status": "unmatched",
                    "source": "gateoverflow_exact_label_join",
                    "reasons": ["exact_gateoverflow_body_missing"],
                    "rendering_allowed": False,
                }
                outcomes["parser_unmatched"] += 1
                reason_counts["exact_gateoverflow_body_missing"] += 1
                paper_counts[paper_id]["parser_unmatched"] += 1
            else:
                _validate_go_body_hash(go_snapshot, body)
                parsed = parse_explicit_four_choices(body)
                objective_type, type_problem = _objective_type(candidate)
                problems = list(parsed.get("reasons") or [])
                if parsed.get("status") == "exact" and type_problem:
                    problems.append(type_problem)
                if parsed.get("status") == "exact" and not problems:
                    candidate["options"] = parsed["options"]
                    candidate["options_source"] = (
                        "gateoverflow_exact_explicit_four_choice_parse"
                    )
                    if str(candidate.get("item_type") or "unknown").casefold() == "unknown":
                        candidate["item_type"] = objective_type
                        candidate["item_type_source"] = (
                            "explicit_answer_labels+gateoverflow_four_choice_parse"
                        )
                    if candidate.get("question_source") == "gateoverflow_exact_label_join":
                        candidate["question_text"] = parsed["stem"]
                        candidate["question_text_sha256"] = parsed["stem_sha256"]
                        candidate["question_structure_source"] = (
                            "gateoverflow_explicit_four_choice_boundaries"
                        )
                    option_parse = {
                        "status": "parser_exact",
                        "source": "gateoverflow_exact_label_join",
                        "reasons": [],
                        "label_scheme": parsed["label_scheme"],
                        "source_body_sha256": parsed["source_body_sha256"],
                        "stem_sha256": parsed["stem_sha256"],
                        "metadata_tail": parsed["metadata_tail"],
                        "rendering_allowed": False,
                    }
                    outcomes["parser_exact_added"] += 1
                    paper_counts[paper_id]["parser_exact_added"] += 1
                    if len(representative_rows) < 16:
                        representative_rows.append(
                            {
                                "source_paper_id": paper_id,
                                "ordinal": int(row.get("ordinal") or 0),
                                "item_label": row.get("item_label"),
                                "volume": go_snapshot.get("volume"),
                                "book_page": go_snapshot.get("book_page"),
                                "question_body_sha256": go_snapshot.get(
                                    "question_body_sha256"
                                ),
                                "label_scheme": parsed["label_scheme"],
                            }
                        )
                else:
                    final_status = (
                        "ambiguous"
                        if parsed.get("status") == "ambiguous"
                        or (parsed.get("status") == "exact" and type_problem)
                        else "unmatched"
                    )
                    option_parse = {
                        "status": final_status,
                        "source": "gateoverflow_exact_label_join",
                        "reasons": sorted(set(problems)),
                        "label_scheme": parsed.get("label_scheme"),
                        "metadata_tail": parsed.get("metadata_tail"),
                        "rendering_allowed": False,
                    }
                    for problem in option_parse["reasons"]:
                        reason_counts[problem] += 1
                    outcomes[f"parser_{final_status}"] += 1
                    paper_counts[paper_id][f"parser_{final_status}"] += 1

        candidate["option_parse"] = option_parse
        final_options = candidate.get("options")
        if final_options:
            if len(final_options) != 4:
                raise OptionStructureError(
                    f"{paper_id}:{row.get('ordinal')}: output option count is not four"
                )
            final_type = str(candidate.get("item_type") or "").casefold()
            if final_type not in OBJECTIVE_TYPES:
                raise OptionStructureError(
                    f"{paper_id}:{row.get('ordinal')}: options lack objective type"
                )
            after["structured_option_sets"] += 1
            after[f"{final_type}_option_sets"] += 1

    _assert_output_safety(output)
    if sum(outcomes.values()) != len(output["questions"]):
        raise OptionStructureError("option-parse outcomes do not cover every slot")
    report_papers = []
    for paper_id in sorted(paper_counts):
        counts = paper_counts[paper_id]
        report_papers.append(
            {
                "source_paper_id": paper_id,
                **{key: counts[key] for key in sorted(counts)},
            }
        )
    report = {
        "schema_version": SCHEMA_VERSION,
        "database_writes_performed": False,
        "automatic_promotion_allowed": False,
        "slot_count": len(output["questions"]),
        "coverage": {
            "before_nonempty_option_sets": before["nonempty_option_sets"],
            "before_valid_four_option_sets": before["valid_four_option_sets"],
            "after_structured_option_sets": after["structured_option_sets"],
            "after_mcq_option_sets": after["mcq_option_sets"],
            "after_msq_option_sets": after["msq_option_sets"],
            "net_valid_option_sets_added": (
                after["structured_option_sets"] - before["valid_four_option_sets"]
            ),
        },
        "outcomes": dict(sorted(outcomes.items())),
        "withheld_reason_counts": dict(sorted(reason_counts.items())),
        "papers": report_papers,
        "representative_source_qa_candidates": representative_rows,
        "method": {
            "accepted_labels": ["A-D", "a-d", "(A)-(D)", "1-4", "(1)-(4)"],
            "required_choice_count": 4,
            "boundary": (
                "first and only ordered explicit label sequence; optional gate-year "
                "metadata tail removed"
            ),
            "hard_rejections": [
                "out-of-order, repeated, mixed, missing, or truncated labels",
                "empty or duplicate choice content",
                "possible unextracted inline formula/image content",
                "possible missing operator or terminal mathematical object",
                "foreign-exam editorial tags",
                "book-section spillover",
                "answer, solution, or explanation text",
                "unsafe active HTML",
                "objective question type not independently established",
            ],
            "content_handling": (
                "plain source text and LaTeX delimiters are preserved; HTML output is "
                "escaped and never marked renderable"
            ),
        },
    }
    return output, report


def _assert_output_safety(value: Any) -> None:
    def visit(node: Any) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                if "explanation" in str(key).casefold():
                    raise OptionStructureError(
                        "third-party explanation metadata leaked into output"
                    )
                if key == "practice_eligible" and child is not False:
                    raise OptionStructureError(
                        "staging output contains a practice-eligible row"
                    )
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)
        elif isinstance(node, float) and not math.isfinite(node):
            raise OptionStructureError("non-finite number in staging output")

    visit(value)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = args.input.resolve()
    output_path = args.output.resolve()
    artifact = _read_json(input_path)
    enriched, report = enrich_candidate_artifact(artifact)
    enriched["input_artifact_sha256"] = _sha256_file(input_path)
    _assert_output_safety(enriched)
    _write_json(output_path, enriched)
    report["input_artifact_sha256"] = enriched["input_artifact_sha256"]
    report["output_artifact_sha256"] = _sha256_file(output_path)
    report_path = output_path.with_suffix(".report.json")
    _write_json(report_path, report)
    coverage = report["coverage"]
    print(
        "Structured {after_structured_option_sets} option sets "
        "({net_valid_option_sets_added:+d} net verified sets; "
        "{before_valid_four_option_sets} valid before).".format(**coverage)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
