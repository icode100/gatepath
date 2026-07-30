"""Validate the exactly-845 GATE 2017-2025 consolidated audit."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


BACKEND_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = Path(__file__).resolve().parent
DEFAULT_PATH = BACKEND_DIR / "data" / "pyq_consolidated.json"
sys.path.insert(0, str(SCRIPTS_DIR))

from generate_question_bank import SUBJECTS, TOPICS_BY_COURSE  # noqa: E402
from extract_pyqs import (  # noqa: E402
    REVIEWED_FORCE_REVIEW,
    REVIEWED_TOPIC_OVERRIDES,
    quality_gate_regression_errors,
    record_quality_flags,
    record_quality_gate_regression_errors,
)


EXPECTED_PAPERS = {
    "CS1-2017",
    "CS2-2017",
    "CS-2018",
    "CS-2019",
    "CS-2020",
    "CS1-2021",
    "CS2-2021",
    "CS-2022",
    "CS-2023",
    "CS1-2024",
    "CS2-2024",
    "CS1-2025",
    "CS2-2025",
}
REQUIRED_USER_KEYS = {"question", "options", "course", "topic", "correct_answer"}
BOILERPLATE = re.compile(
    r"(?:q\.?\s*\d+\s*[-\u2013\u2014]\s*q\.?\s*\d+.*?carry\s+"
    r"(?:one|two)|answer\s+key|key\s*/\s*range|question\s+type|"
    r"page\s+\d+\s+of\s+\d+)",
    re.IGNORECASE,
)
COMPACT_MARKS_BOILERPLATE = re.compile(
    r"q\.?\s*(?:\d+\s*[-\u2013\u2014]\s*q\.?\s*)?\d+\s*"
    r"carry\s*(?:one|two)\s*marks?\s*each",
    re.IGNORECASE,
)


def validate(path: Path) -> tuple[list[str], dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("questions") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        return ["Top-level questions must be a list"], {}
    errors: list[str] = []
    errors.extend(
        f"quality gate regression: {error}"
        for error in (
            quality_gate_regression_errors()
            + record_quality_gate_regression_errors()
        )
    )
    ids: Counter[str] = Counter()
    paper_numbers: dict[str, set[int]] = defaultdict(set)
    paper_counts: Counter[str] = Counter()
    year_counts: Counter[int] = Counter()
    safe_by_paper: Counter[str] = Counter()
    safe_by_year: Counter[int] = Counter()
    review_reasons: Counter[str] = Counter()
    valid_topics = {
        (subject.code, topic.name, topic.slug)
        for subject in SUBJECTS
        for topic in TOPICS_BY_COURSE[subject.code]
    }

    for index, record in enumerate(records):
        label = f"questions[{index}]"
        if not isinstance(record, dict):
            errors.append(f"{label} must be an object")
            continue
        missing = REQUIRED_USER_KEYS - record.keys()
        if missing:
            errors.append(f"{label} missing required user keys {sorted(missing)}")
        external_id = record.get("external_id")
        ids[str(external_id)] += 1
        paper = record.get("source_paper")
        number = record.get("source_question_number")
        year = record.get("source_year")
        if paper not in EXPECTED_PAPERS:
            errors.append(f"{label} unknown paper {paper!r}")
        if not isinstance(number, int) or not 1 <= number <= 65:
            errors.append(f"{label} source_question_number must be 1..65")
        else:
            paper_numbers[str(paper)].add(number)
        paper_counts[str(paper)] += 1
        if not isinstance(year, int) or not 2017 <= year <= 2025:
            errors.append(f"{label} source_year outside 2017..2025")
        else:
            year_counts[year] += 1

        safe = record.get("safe_for_quiz") is True
        status = record.get("status")
        reviewed_key = (str(paper), number)
        expected_topic = REVIEWED_TOPIC_OVERRIDES.get(reviewed_key)
        if expected_topic is not None and (
            record.get("course"),
            record.get("topic"),
            record.get("topic_slug"),
        ) != expected_topic:
            errors.append(
                f"{label} does not match reviewed topic override {expected_topic}"
            )
        forced_reason = REVIEWED_FORCE_REVIEW.get(reviewed_key)
        if forced_reason is not None:
            if safe:
                errors.append(f"{label} reviewed force-review record is quiz-safe")
            if forced_reason not in (record.get("review_flags") or []):
                errors.append(
                    f"{label} missing reviewed force-review reason {forced_reason}"
                )
        if safe != (status == "verified"):
            errors.append(f"{label} safe_for_quiz/status disagree")
        if safe:
            safe_by_paper[str(paper)] += 1
            if isinstance(year, int):
                safe_by_year[year] += 1
            question = record.get("question")
            if not isinstance(question, str) or len(question.strip()) < 20:
                errors.append(f"{label} verified question text is incomplete")
            serialized = str(question) + " " + " ".join(
                str(option.get("text", ""))
                for option in record.get("options", [])
                if isinstance(option, dict)
            )
            if BOILERPLATE.search(serialized) or COMPACT_MARKS_BOILERPLATE.search(
                serialized
            ):
                errors.append(f"{label} verified text contains paper/key boilerplate")
            quality_flags = record_quality_flags(
                str(question),
                [
                    option
                    for option in record.get("options", [])
                    if isinstance(option, dict)
                ],
                extraction_method=record.get("extraction_method"),
            )
            if quality_flags:
                errors.append(
                    f"{label} verified text failed quality gate: "
                    f"{','.join(quality_flags)}"
                )
            if re.match(
                r"^\s*(?:Q\.?\s*(?:No\.?\s*)?|Question\s+Number\s*:)\d+",
                str(question),
                re.IGNORECASE,
            ):
                errors.append(f"{label} verified text retains question-number prefix")
            topic_key = (
                record.get("course"),
                record.get("topic"),
                record.get("topic_slug"),
            )
            if topic_key not in valid_topics:
                errors.append(f"{label} verified topic does not match seeded syllabus")
            qtype = record.get("question_type")
            options = record.get("options")
            answer = record.get("correct_answer")
            if qtype in {"mcq", "msq"}:
                if not isinstance(options, list) or len(options) != 4:
                    errors.append(f"{label} verified {qtype} requires four options")
                option_ids = [
                    option.get("id") for option in options if isinstance(option, dict)
                ]
                if option_ids != ["A", "B", "C", "D"]:
                    errors.append(f"{label} verified option IDs must be A-D")
                if qtype == "mcq" and answer not in option_ids:
                    errors.append(f"{label} verified MCQ answer is invalid")
                if qtype == "msq" and (
                    not isinstance(answer, list)
                    or not answer
                    or any(item not in option_ids for item in answer)
                ):
                    errors.append(f"{label} verified MSQ answer is invalid")
            elif qtype == "nat":
                if options != []:
                    errors.append(f"{label} verified NAT must not have options")
                if not (
                    isinstance(answer, (int, float))
                    or (
                        isinstance(answer, dict)
                        and set(answer) == {"min", "max"}
                        and answer["min"] <= answer["max"]
                    )
                ):
                    errors.append(f"{label} verified NAT answer/range is invalid")
            else:
                errors.append(f"{label} verified question_type is invalid")
        else:
            flags = record.get("review_flags")
            if not isinstance(flags, list) or not flags:
                errors.append(f"{label} review-required record needs review_flags")
            else:
                review_reasons.update(flags)

    duplicate_ids = [identifier for identifier, count in ids.items() if count > 1]
    if duplicate_ids:
        errors.append(f"Duplicate external IDs: {duplicate_ids[:10]}")
    if len(records) != 845:
        errors.append(f"Expected exactly 845 records, found {len(records)}")
    if set(paper_counts) != EXPECTED_PAPERS:
        errors.append("Paper set does not match the 13 supplied 2017-2025 papers")
    for paper in sorted(EXPECTED_PAPERS):
        if paper_counts[paper] != 65:
            errors.append(f"{paper} has {paper_counts[paper]} records, expected 65")
        missing_numbers = set(range(1, 66)) - paper_numbers[paper]
        if missing_numbers:
            errors.append(f"{paper} missing question numbers {sorted(missing_numbers)}")

    summary = {
        "valid": not errors,
        "consolidated_record_count": len(records),
        "safe_question_count": sum(safe_by_paper.values()),
        "review_required_count": len(records) - sum(safe_by_paper.values()),
        "records_by_paper": dict(sorted(paper_counts.items())),
        "safe_by_paper": dict(sorted(safe_by_paper.items())),
        "records_by_year": {str(k): v for k, v in sorted(year_counts.items())},
        "safe_by_year": {str(k): v for k, v in sorted(safe_by_year.items())},
        "review_flags": dict(review_reasons.most_common()),
        "duplicate_external_ids": len(duplicate_ids),
        "error_count": len(errors),
    }
    return errors, summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path, default=DEFAULT_PATH)
    args = parser.parse_args()
    errors, summary = validate(args.path.resolve())
    print(json.dumps(summary, indent=2))
    for error in errors:
        print(f"ERROR: {error}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
