from __future__ import annotations

import importlib.util
import sys
from copy import deepcopy
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = BACKEND_DIR / "scripts" / "validate_pyq_release_readiness.py"
SPEC = importlib.util.spec_from_file_location(
    "validate_pyq_release_readiness", SCRIPT_PATH
)
assert SPEC and SPEC.loader
validator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = validator
SPEC.loader.exec_module(validator)


def _ready_artifact() -> dict:
    source_hash = "a" * 64
    artifact = {
        "schema_version": "1.0",
        "artifact_version": "test-release",
        "papers": [
            {
                "id": "gate-cs-test",
                "exam_code": "GATE",
                "paper_code": "CS",
                "year": 2025,
                "session_label": "1",
                "display_name": "GATE CS test",
                "expected_item_count": 1,
                "source_url": "https://example.test/paper.pdf",
                "answer_key_url": "https://example.test/key.pdf",
                "source_pdf_sha256": source_hash,
                "answer_key_sha256": "b" * 64,
                "source_aliases": [],
                "source_status": "verified",
                "notes": "fixture",
            }
        ],
        "questions": [
            {
                "source_paper_id": "gate-cs-test",
                "item_label": "1",
                "ordinal": 1,
                "source_page": 2,
                "marks": 1,
                "item_type": "mcq",
                "question_md": "Which statement is true?",
                "options": [
                    {"id": "A", "text": "First"},
                    {"id": "B", "text": "Second"},
                ],
                "accepted_answers": ["A"],
                "solution_md": "The first statement follows directly.",
                "subject_code": "CN",
                "topic_slug": "transport-layer",
                "syllabus_status": "in_syllabus",
                "transcription_status": "verified",
                "answer_status": "official",
                "classification_status": "verified",
                "practice_eligible": True,
                "review_flags": [],
                "assets": [],
                "source_references": [
                    {
                        "kind": "official_question_paper_item",
                        "url": "https://example.test/paper.pdf#page=2",
                        "sha256": source_hash,
                        "note": "exact item block",
                    }
                ],
                "extraction_method": "fixture",
                "extraction_confidence": 1,
                "content_sha256": None,
            }
        ],
    }
    item = validator.ArchiveQuestion.model_validate(artifact["questions"][0])
    artifact["questions"][0]["content_sha256"] = (
        validator.archive_content_sha256(item)
    )
    return artifact


def _rehash(question: dict) -> None:
    question["content_sha256"] = validator.archive_content_sha256(
        validator.ArchiveQuestion.model_validate(
            {**question, "content_sha256": None}
        )
    )


def test_complete_verified_artifact_is_release_ready() -> None:
    report = validator.validate_release_readiness(
        _ready_artifact(), expected_paper_count=1, expected_record_count=1
    )

    assert report["release_ready"] is True
    assert report["problems"] == {}
    assert report["counts"]["practice_eligible"] == 1


def test_placeholder_question_is_blocked_without_mutating_input() -> None:
    artifact = _ready_artifact()
    original = deepcopy(artifact)
    question = artifact["questions"][0]
    question.update(
        {
            "question_md": None,
            "options": [],
            "accepted_answers": None,
            "solution_md": None,
            "transcription_status": "missing",
            "answer_status": "unresolved",
            "classification_status": "review_required",
            "syllabus_status": "review_required",
            "practice_eligible": False,
            "review_flags": ["missing_transcription"],
            "source_page": None,
            "source_references": [],
            "content_sha256": None,
        }
    )
    mutated_snapshot = deepcopy(artifact)

    report = validator.validate_release_readiness(
        artifact, expected_paper_count=1, expected_record_count=1
    )

    assert report["release_ready"] is False
    assert report["problems"]["question_text_missing"] == 1
    assert report["problems"]["objective_answer_not_verified"] == 1
    assert report["problems"]["original_item_reference_missing"] == 1
    assert artifact == mutated_snapshot
    assert artifact != original


def test_descriptive_item_can_be_archived_without_becoming_practice_eligible() -> None:
    artifact = _ready_artifact()
    question = artifact["questions"][0]
    question.update(
        {
            "item_type": "descriptive",
            "options": [],
            "accepted_answers": None,
            "answer_status": "not_applicable",
            "solution_md": None,
            "practice_eligible": False,
            "review_flags": [],
        }
    )
    _rehash(question)

    report = validator.validate_release_readiness(
        artifact, expected_paper_count=1, expected_record_count=1
    )

    assert report["release_ready"] is True
    assert report["counts"]["archive_only"] == 0
    assert report["counts"]["practice_ineligible"] == 1


def test_explicit_review_flag_is_a_release_blocker() -> None:
    artifact = _ready_artifact()
    artifact["questions"][0]["practice_eligible"] = False
    artifact["questions"][0]["review_flags"] = ["manual_review_required"]
    _rehash(artifact["questions"][0])

    report = validator.validate_release_readiness(
        artifact, expected_paper_count=1, expected_record_count=1
    )

    assert report["release_ready"] is False
    assert report["problems"]["manual_review_required"] == 1


def test_missing_or_duplicate_final_archive_records_are_reported() -> None:
    artifact = _ready_artifact()
    artifact["papers"][0]["expected_item_count"] = 2
    duplicate = deepcopy(artifact["questions"][0])
    duplicate["item_label"] = "1-duplicate"
    artifact["questions"].append(duplicate)

    report = validator.validate_release_readiness(
        artifact, expected_paper_count=1, expected_record_count=2
    )

    assert report["release_ready"] is False
    assert report["problems"]["duplicate_paper_ordinal"] == 1
    assert report["problems"]["missing_archive_records"] == 1


def test_expanded_final_ordinals_use_audited_paper_record_count() -> None:
    artifact = _ready_artifact()
    artifact["papers"][0]["expected_item_count"] = 2
    child = deepcopy(artifact["questions"][0])
    child["item_label"] = "1(a)"
    child["ordinal"] = 2
    child["parent_item_label"] = "1"
    child["extraction_method"] = "audited_legacy_child_exact"
    child["source_references"].append(
        {
            "kind": "canonical_parent_slot",
            "url": None,
            "sha256": None,
            "note": "canonical_parent_ordinal=1; parent_item_label=1",
        }
    )
    _rehash(child)
    artifact["questions"].append(child)

    report = validator.validate_release_readiness(
        artifact, expected_paper_count=1, expected_record_count=2
    )

    assert report["release_ready"] is True
    assert report["counts"]["archive_records"] == 2
    assert report["counts"]["declared_archive_records"] == 2
    assert report["counts"]["missing_archive_records"] == 0
    assert report["counts"]["unexpected_archive_records"] == 0


def test_expanded_child_without_parent_reference_fails_closed() -> None:
    artifact = _ready_artifact()
    artifact["questions"][0]["parent_item_label"] = "parent"
    artifact["questions"][0]["extraction_method"] = "audited_legacy_child_exact"
    _rehash(artifact["questions"][0])

    report = validator.validate_release_readiness(
        artifact, expected_paper_count=1, expected_record_count=1
    )

    assert report["release_ready"] is False
    assert report["problems"]["expanded_parent_reference_missing"] == 1


def test_declared_and_actual_record_counts_are_independent_invariants() -> None:
    artifact = _ready_artifact()

    report = validator.validate_release_readiness(
        artifact, expected_paper_count=1, expected_record_count=2
    )

    assert report["problems"]["declared_record_count_mismatch"] == 1
    assert report["problems"]["archive_record_count_mismatch"] == 1
    assert "record_count_vs_paper_declarations_mismatch" not in report["problems"]


def test_tampered_content_is_rejected_by_archive_hash_contract() -> None:
    artifact = _ready_artifact()
    artifact["questions"][0]["question_md"] = "Tampered after hashing"

    report = validator.validate_release_readiness(
        artifact, expected_paper_count=1, expected_record_count=1
    )

    assert report["release_ready"] is False
    assert report["problems"]["archive_item_content_hash_mismatch"] == 1
