"""Strict offline validation for backend/data/question_bank.json."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


BACKEND_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = Path(__file__).resolve().parent
DEFAULT_PATH = BACKEND_DIR / "data" / "question_bank.json"
sys.path.insert(0, str(SCRIPTS_DIR))

from extract_pyqs import (  # noqa: E402
    REVIEWED_FORCE_REVIEW,
    REVIEWED_TOPIC_OVERRIDES,
    quality_gate_regression_errors,
    record_quality_flags,
    record_quality_gate_regression_errors,
)
from generate_question_bank import TOPICS, original_semantic_digest  # noqa: E402


TECHNICAL_CODES = {"EM", "DL", "COA", "PDS", "ALG", "TOC", "CD", "OS", "DBMS", "CN"}
VALID_TYPES = {"mcq", "msq", "nat"}
VALID_DIFFICULTIES = {"easy", "medium", "hard"}
VALID_SOURCES = {"original", "previous_year"}
PYQ_BOILERPLATE = re.compile(
    r"(?:q\.?\s*\d+\s*[-\u2013\u2014]\s*q\.?\s*\d+.*?carry\s+"
    r"(?:one|two)|answer\s+key|key\s*/\s*range|question\s+type|"
    r"page\s+\d+\s+of\s+\d+)",
    re.IGNORECASE,
)
PYQ_COMPACT_MARKS_BOILERPLATE = re.compile(
    r"q\.?\s*(?:\d+\s*[-\u2013\u2014]\s*q\.?\s*)?\d+\s*"
    r"carry\s*(?:one|two)\s*marks?\s*each",
    re.IGNORECASE,
)
REQUIRED = {
    "external_id",
    "question",
    "options",
    "course",
    "topic",
    "correct_answer",
    "question_type",
    "difficulty",
    "marks",
    "explanation",
    "numerical_tolerance",
    "source_kind",
}


def _canonical(record: dict[str, Any]) -> str:
    normalized = {
        "question": " ".join(str(record.get("question", "")).lower().split()),
        "options": record.get("options", []),
    }
    return hashlib.sha256(
        json.dumps(normalized, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def validate_bank(path: Path) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    errors.extend(
        f"quality gate regression: {error}"
        for error in (
            quality_gate_regression_errors()
            + record_quality_gate_regression_errors()
        )
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return ["Top-level value must be an object"], {}
    if payload.get("schema_version") != "1.0":
        errors.append("schema_version must be '1.0'")
    for key in ("bank_version", "generated_at"):
        if not payload.get(key):
            errors.append(f"Top-level {key} is required")
    questions = payload.get("questions")
    if not isinstance(questions, list):
        return errors + ["Top-level questions must be a list"], {}
    revision_notes = payload.get("revision_notes")
    if not isinstance(revision_notes, list):
        errors.append("Top-level revision_notes must be a list")
        revision_notes = []

    expected_note_topics = {(topic.course, topic.name) for topic in TOPICS}
    note_topics: Counter[tuple[str, str]] = Counter()
    for index, note in enumerate(revision_notes):
        label = f"revision_notes[{index}]"
        if not isinstance(note, dict):
            errors.append(f"{label} must be an object")
            continue
        course = str(note.get("course", "")).strip()
        topic = str(note.get("topic", "")).strip()
        note_topics[(course, topic)] += 1
        if (course, topic) in expected_note_topics:
            for field in ("title", "summary", "reasoning_pattern"):
                if not str(note.get(field, "")).strip():
                    errors.append(f"{label} {field} is required")
            for field in ("key_points", "common_traps"):
                values = note.get(field)
                if (
                    not isinstance(values, list)
                    or len(values) < 3
                    or len({str(value).strip() for value in values if str(value).strip()}) < 3
                ):
                    errors.append(
                        f"{label} requires at least three distinct {field}"
                    )
    actual_note_topics = {key for key, count in note_topics.items() if count > 0}
    missing_note_topics = sorted(expected_note_topics - actual_note_topics)
    unexpected_note_topics = sorted(actual_note_topics - expected_note_topics)
    duplicate_note_topics = sorted(
        key for key, count in note_topics.items()
        if count > 1
    )
    if missing_note_topics:
        errors.append(
            "Canonical topics missing revision notes: "
            + "; ".join(f"{course}/{topic}" for course, topic in missing_note_topics)
        )
    if unexpected_note_topics:
        errors.append(
            "Revision notes outside canonical topics: "
            + "; ".join(
                f"{course}/{topic}" for course, topic in unexpected_note_topics
            )
        )
    if duplicate_note_topics:
        errors.append(
            "Duplicate canonical revision notes: "
            + "; ".join(
                f"{course}/{topic}" for course, topic in duplicate_note_topics
            )
        )

    ids: Counter[str] = Counter()
    content: Counter[str] = Counter()
    course_counts: Counter[str] = Counter()
    type_counts: dict[str, Counter[str]] = defaultdict(Counter)
    marks_counts: dict[str, Counter[int]] = defaultdict(Counter)
    topic_types: dict[tuple[str, str], set[str]] = defaultdict(set)
    pyq_years: Counter[int] = Counter()
    generated_semantic_variants: dict[str, set[str]] = defaultdict(set)

    for index, record in enumerate(questions):
        label = f"questions[{index}]"
        if not isinstance(record, dict):
            errors.append(f"{label} must be an object")
            continue
        missing = REQUIRED - record.keys()
        if missing:
            errors.append(f"{label} missing fields: {sorted(missing)}")
            continue
        external_id = record["external_id"]
        if not isinstance(external_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]+", external_id):
            errors.append(f"{label} external_id must be a stable lowercase identifier")
        ids[str(external_id)] += 1
        content[_canonical(record)] += 1
        course = record["course"]
        course_counts[course] += 1
        qtype = record["question_type"]
        type_counts[course][qtype] += 1
        marks_counts[course][record["marks"]] += 1
        topic_types[(course, record["topic"])].add(qtype)
        if record["source_kind"] == "original":
            generated_semantic_variants[course].add(
                original_semantic_digest(record)
            )

        if qtype not in VALID_TYPES:
            errors.append(f"{label} has invalid question_type {qtype!r}")
        if record["difficulty"] not in VALID_DIFFICULTIES:
            errors.append(f"{label} has invalid difficulty")
        if record["source_kind"] not in VALID_SOURCES:
            errors.append(f"{label} has invalid source_kind")
        if record["marks"] not in (1, 2):
            errors.append(f"{label} marks must be 1 or 2")
        if not str(record["question"]).strip():
            errors.append(f"{label} question is empty")
        if len(str(record["explanation"]).strip()) < 20:
            errors.append(f"{label} explanation is too short")

        options = record["options"]
        answer = record["correct_answer"]
        if qtype in {"mcq", "msq"}:
            if not isinstance(options, list) or len(options) != 4:
                errors.append(f"{label} {qtype} must have exactly four options")
                continue
            option_ids = [option.get("id") for option in options if isinstance(option, dict)]
            if option_ids != ["A", "B", "C", "D"]:
                errors.append(f"{label} option IDs must be A, B, C, D in order")
            if qtype == "mcq" and answer not in option_ids:
                errors.append(f"{label} MCQ answer must be one option ID")
            if qtype == "msq":
                if (
                    not isinstance(answer, list)
                    or not answer
                    or len(answer) != len(set(answer))
                    or any(item not in option_ids for item in answer)
                ):
                    errors.append(f"{label} MSQ answer must be a nonempty unique option-ID list")
        elif qtype == "nat":
            if options != []:
                errors.append(f"{label} NAT options must be empty")
            valid_numeric = isinstance(answer, (int, float)) and not isinstance(
                answer, bool
            )
            valid_range = (
                isinstance(answer, dict)
                and set(answer) == {"min", "max"}
                and isinstance(answer.get("min"), (int, float))
                and not isinstance(answer.get("min"), bool)
                and isinstance(answer.get("max"), (int, float))
                and not isinstance(answer.get("max"), bool)
                and answer["min"] <= answer["max"]
            )
            if not (valid_numeric or valid_range):
                errors.append(f"{label} NAT answer must be numeric or a valid range")

        if record["source_kind"] == "previous_year":
            required_provenance = {
                "source_year",
                "source_paper",
                "source_question_number",
                "source_url",
                "answer_key_url",
            }
            missing_provenance = [
                field for field in required_provenance if not record.get(field)
            ]
            if missing_provenance:
                errors.append(
                    f"{label} previous-year provenance missing {sorted(missing_provenance)}"
                )
            elif isinstance(record["source_year"], int):
                pyq_years[record["source_year"]] += 1
            reviewed_key = (
                str(record.get("source_paper")),
                record.get("source_question_number"),
            )
            if reviewed_key in REVIEWED_FORCE_REVIEW:
                errors.append(
                    f"{label} reviewed force-review record entered live bank"
                )
            expected_topic = REVIEWED_TOPIC_OVERRIDES.get(reviewed_key)
            if expected_topic is not None and (
                record.get("course"),
                record.get("topic"),
                record.get("topic_slug"),
            ) != expected_topic:
                errors.append(
                    f"{label} does not match reviewed topic override "
                    f"{expected_topic}"
                )
            option_text = " ".join(
                str(option.get("text", ""))
                for option in options
                if isinstance(option, dict)
            )
            transcription = f"{record['question']} {option_text}"
            if PYQ_BOILERPLATE.search(
                transcription
            ) or PYQ_COMPACT_MARKS_BOILERPLATE.search(transcription):
                errors.append(f"{label} contains paper/header/key boilerplate")
            quality_flags = record_quality_flags(
                str(record["question"]),
                [
                    option
                    for option in options
                    if isinstance(option, dict)
                ],
                extraction_method=record.get("extraction_method"),
            )
            if quality_flags:
                errors.append(
                    f"{label} failed PYQ transcription quality gate: "
                    f"{','.join(quality_flags)}"
                )
            if re.match(
                r"^\s*(?:Q\.?\s*(?:No\.?\s*)?|Question\s+Number\s*:)\d+",
                str(record["question"]),
                re.IGNORECASE,
            ):
                errors.append(f"{label} retains a question-number prefix")

    duplicate_ids = [key for key, count in ids.items() if count > 1]
    duplicate_content = [key for key, count in content.items() if count > 1]
    if duplicate_ids:
        errors.append(f"Duplicate external IDs: {duplicate_ids[:5]}")
    if duplicate_content:
        errors.append(f"Duplicate question+option records: {len(duplicate_content)}")

    for course in sorted(TECHNICAL_CODES):
        if course_counts[course] < 200:
            errors.append(f"{course} has {course_counts[course]} questions; requires >=200")
        for qtype in VALID_TYPES:
            if type_counts[course][qtype] < 20:
                errors.append(
                    f"{course} has {type_counts[course][qtype]} {qtype}; requires >=20"
                )
        for mark in (1, 2):
            if marks_counts[course][mark] == 0:
                errors.append(f"{course} has no {mark}-mark questions")
        if len(generated_semantic_variants[course]) < 210:
            errors.append(
                f"{course} has {len(generated_semantic_variants[course])} "
                "distinct generated semantic variants; requires >=210"
            )

    incomplete_topic_types = [
        f"{course}/{topic}: {sorted(types)}"
        for (course, topic), types in topic_types.items()
        if course in TECHNICAL_CODES and types != VALID_TYPES
    ]
    if incomplete_topic_types:
        errors.append(
            "Technical topics missing a question type: "
            + "; ".join(incomplete_topic_types[:10])
        )

    summary = {
        "valid": not errors,
        "question_count": len(questions),
        "by_course": dict(sorted(course_counts.items())),
        "by_course_and_type": {
            course: dict(sorted(counts.items()))
            for course, counts in sorted(type_counts.items())
        },
        "by_course_and_marks": {
            course: {str(mark): count for mark, count in sorted(counts.items())}
            for course, counts in sorted(marks_counts.items())
        },
        "previous_year_by_year": {
            str(year): count for year, count in sorted(pyq_years.items())
        },
        "revision_note_count": len(actual_note_topics & expected_note_topics),
        "generated_semantic_variants": {
            course: len(digests)
            for course, digests in sorted(
                generated_semantic_variants.items()
            )
        },
        "duplicate_external_ids": len(duplicate_ids),
        "duplicate_content_records": len(duplicate_content),
        "error_count": len(errors),
    }
    return errors, summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path, default=DEFAULT_PATH)
    args = parser.parse_args()
    errors, summary = validate_bank(args.path.resolve())
    print(json.dumps(summary, indent=2))
    for error in errors:
        print(f"ERROR: {error}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
