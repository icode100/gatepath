"""Validate that an expanded GATE CS PYQ archive is ready for release.

This command is intentionally stricter than the archive import schema.  The
importer may store review-first placeholders, whereas a release artifact must
contain every original item with page-addressed provenance, a verified
transcription, and a final syllabus classification.  Objective questions must
also have a verified answer before they can be presented as solved PYQs.

The validator never opens a database and never mutates its input artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.pyq_archive import (  # noqa: E402
    ArchiveQuestion,
    PyqArchiveDocument,
    _content_sha256 as archive_content_sha256,
)


EXPECTED_PAPER_COUNT = 39
EXPECTED_ARCHIVE_RECORD_COUNT = 2873
OBJECTIVE_TYPES = {"mcq", "msq", "nat"}
VERIFIED_ANSWER_STATUSES = {"official", "community_verified"}
ORIGINAL_ITEM_REFERENCE_KINDS = {
    "original_pdf_item",
    "official_question_paper_item",
}
SHA256_RE = re.compile(r"[0-9a-f]{64}")


def _sha256(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().casefold()
    return normalized if SHA256_RE.fullmatch(normalized) else None


def _item_problem_codes(item: ArchiveQuestion) -> list[str]:
    problems: list[str] = []
    if not item.question_md:
        problems.append("question_text_missing")
    if item.transcription_status != "verified":
        problems.append("transcription_not_verified")
    if item.source_page is None:
        problems.append("original_source_page_missing")
    if _sha256(item.content_sha256) is None:
        problems.append("archive_item_content_hash_missing")
    elif item.content_sha256.casefold() != archive_content_sha256(item):
        problems.append("archive_item_content_hash_mismatch")
    if not any(
        reference.kind in ORIGINAL_ITEM_REFERENCE_KINDS
        and _sha256(reference.sha256) is not None
        for reference in item.source_references
    ):
        problems.append("original_item_reference_missing")
    if item.item_type == "unknown":
        problems.append("item_type_unresolved")
    if item.marks is None:
        problems.append("marks_missing")
    if item.classification_status not in {"verified", "out_of_syllabus"}:
        problems.append("classification_not_verified")
    if item.syllabus_status not in {"in_syllabus", "out_of_syllabus"}:
        problems.append("syllabus_status_not_final")
    if not item.subject_code or not item.topic_slug:
        problems.append("course_or_topic_missing")
    if item.item_type in OBJECTIVE_TYPES:
        if item.answer_status not in VERIFIED_ANSWER_STATUSES:
            problems.append("objective_answer_not_verified")
        if item.accepted_answers is None:
            problems.append("objective_answer_missing")
        if item.item_type in {"mcq", "msq"} and len(item.options) < 2:
            problems.append("objective_options_missing")
        if item.item_type == "nat" and item.options:
            problems.append("nat_has_options")
    # Upstream review flags are explicit fail-closed gates.  Keeping their
    # stable codes in the report makes it possible to reconcile this validator
    # exactly with the staging release assembler.
    problems.extend(item.review_flags)
    if item.extraction_method == "audited_legacy_child_exact":
        if not item.parent_item_label or not any(
            reference.kind == "canonical_parent_slot"
            for reference in item.source_references
        ):
            problems.append("expanded_parent_reference_missing")
    return sorted(set(problems))


def validate_release_readiness(
    raw: dict[str, Any],
    *,
    expected_paper_count: int = EXPECTED_PAPER_COUNT,
    expected_record_count: int = EXPECTED_ARCHIVE_RECORD_COUNT,
) -> dict[str, Any]:
    """Return a deterministic completeness report for one immutable artifact."""

    document = PyqArchiveDocument.model_validate(raw)
    paper_ids = [paper.id for paper in document.papers]
    paper_by_id = {paper.id: paper for paper in document.papers}
    problems_by_code: Counter[str] = Counter()
    problems_by_paper: dict[str, Counter[str]] = defaultdict(Counter)
    rows_with_problems = 0
    eligible = 0
    practice_ineligible = 0

    if len(document.papers) != expected_paper_count:
        problems_by_code["paper_count_mismatch"] += abs(
            len(document.papers) - expected_paper_count
        ) or 1
    duplicate_paper_ids = len(paper_ids) - len(paper_by_id)
    if duplicate_paper_ids:
        problems_by_code["duplicate_paper_id"] += duplicate_paper_ids

    declared_record_count = sum(
        paper.expected_item_count for paper in document.papers
    )
    if declared_record_count != expected_record_count:
        problems_by_code["declared_record_count_mismatch"] += abs(
            declared_record_count - expected_record_count
        ) or 1
    if len(document.questions) != expected_record_count:
        problems_by_code["archive_record_count_mismatch"] += abs(
            len(document.questions) - expected_record_count
        ) or 1
    if len(document.questions) != declared_record_count:
        problems_by_code["record_count_vs_paper_declarations_mismatch"] += abs(
            len(document.questions) - declared_record_count
        ) or 1

    counts_by_paper = Counter(item.source_paper_id for item in document.questions)
    for paper in document.papers:
        if counts_by_paper[paper.id] != paper.expected_item_count:
            problems_by_code["paper_item_count_mismatch"] += 1
            problems_by_paper[paper.id]["paper_item_count_mismatch"] += 1
        if paper.source_status != "verified":
            problems_by_code["paper_source_not_verified"] += 1
            problems_by_paper[paper.id]["paper_source_not_verified"] += 1
        if _sha256(paper.source_pdf_sha256) is None:
            problems_by_code["paper_source_hash_missing"] += 1
            problems_by_paper[paper.id]["paper_source_hash_missing"] += 1

    seen: set[tuple[str, int]] = set()
    seen_labels: set[tuple[str, str]] = set()
    for item in document.questions:
        key = (item.source_paper_id, item.ordinal)
        if key in seen:
            problems_by_code["duplicate_paper_ordinal"] += 1
            problems_by_paper[item.source_paper_id]["duplicate_paper_ordinal"] += 1
        seen.add(key)
        label_key = (item.source_paper_id, item.item_label.casefold())
        if label_key in seen_labels:
            problems_by_code["duplicate_paper_item_label"] += 1
            problems_by_paper[item.source_paper_id][
                "duplicate_paper_item_label"
            ] += 1
        seen_labels.add(label_key)
        paper = paper_by_id.get(item.source_paper_id)
        if paper is None:
            problems_by_code["unknown_source_paper"] += 1
            problems_by_paper[item.source_paper_id]["unknown_source_paper"] += 1
        elif item.ordinal > paper.expected_item_count:
            problems_by_code["ordinal_out_of_range"] += 1
            problems_by_paper[item.source_paper_id]["ordinal_out_of_range"] += 1

        item_problems = _item_problem_codes(item)
        if item_problems:
            rows_with_problems += 1
        for code in item_problems:
            problems_by_code[code] += 1
            problems_by_paper[item.source_paper_id][code] += 1
        if item.practice_eligible:
            eligible += 1
        else:
            practice_ineligible += 1

    expected_keys = {
        (paper.id, ordinal)
        for paper in document.papers
        for ordinal in range(1, paper.expected_item_count + 1)
    }
    missing_keys = expected_keys - seen
    unexpected_keys = seen - expected_keys
    if missing_keys:
        problems_by_code["missing_archive_records"] += len(missing_keys)
    if unexpected_keys:
        problems_by_code["unexpected_archive_records"] += len(unexpected_keys)

    ready = not problems_by_code
    return {
        "schema_version": "1.0",
        "artifact_version": document.artifact_version,
        "artifact_sha256": hashlib.sha256(
            json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest(),
        "release_ready": ready,
        "database_writes_performed": False,
        "counts": {
            "papers": len(document.papers),
            "archive_records": len(document.questions),
            "declared_archive_records": declared_record_count,
            "release_ready_records": len(document.questions) - rows_with_problems,
            "rows_with_problems": rows_with_problems,
            "practice_eligible": eligible,
            "practice_ineligible": practice_ineligible,
            "archive_only": rows_with_problems,
            "missing_archive_records": len(missing_keys),
            "unexpected_archive_records": len(unexpected_keys),
        },
        "problems": dict(sorted(problems_by_code.items())),
        "papers_with_problems": [
            {
                "paper_id": paper_id,
                "problems": dict(sorted(counter.items())),
            }
            for paper_id, counter in sorted(problems_by_paper.items())
            if counter
        ],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--report", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    artifact_path = args.artifact.resolve()
    raw = json.loads(artifact_path.read_text(encoding="utf-8"))
    report = validate_release_readiness(raw)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        report_path = args.report.resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(rendered, encoding="utf-8", newline="\n")
    print(rendered, end="")
    return 0 if report["release_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
