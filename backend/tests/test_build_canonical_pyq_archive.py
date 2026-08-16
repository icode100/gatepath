from __future__ import annotations

import importlib.util
import hashlib
import sys
from collections import Counter
from copy import deepcopy
from pathlib import Path

import pytest

from app.pyq_archive import _load_document


BACKEND_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = BACKEND_DIR / "scripts" / "build_canonical_pyq_archive.py"
SPEC = importlib.util.spec_from_file_location("build_canonical_pyq_archive", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _build_without_secondary_locators():
    return MODULE.build_archive(
        BACKEND_DIR / "data" / "pyq_source_manifest.json",
        BACKEND_DIR / "data" / "pyq_consolidated.json",
        go_index_path=None,
        examside_index_path=None,
        verify_source_hashes=False,
    )


def _paper_items(artifact: dict, paper_id: str) -> list[dict]:
    return [
        item
        for item in artifact["questions"]
        if item["source_paper_id"] == paper_id
    ]


def test_builder_emits_all_39_papers_and_2712_contiguous_review_slots(
    tmp_path: Path,
) -> None:
    artifact, report = _build_without_secondary_locators()

    assert len(artifact["papers"]) == 39
    assert len(artifact["questions"]) == 2712
    assert report["invariants"] == {
        "expected_paper_count": 39,
        "actual_paper_count": 39,
        "expected_item_count": 2712,
        "actual_item_count": 2712,
        "all_paper_ordinals_contiguous": True,
        "practice_eligible_count": 0,
    }
    counts = Counter(item["source_paper_id"] for item in artifact["questions"])
    for paper in artifact["papers"]:
        assert counts[paper["id"]] == paper["expected_item_count"]
        ordinals = [item["ordinal"] for item in _paper_items(artifact, paper["id"])]
        assert ordinals == list(range(1, paper["expected_item_count"] + 1))
        assert paper["source_status"] == "review_required"
    assert all(
        item["transcription_status"] == "missing"
        for item in artifact["questions"]
        if item["question_md"] is None
    )

    # The staging artifact must also satisfy the importer's strict structural
    # validator before any database-backed dry run is considered.
    path = tmp_path / "archive.json"
    MODULE._write_json(path, artifact)
    validated, _ = _load_document(path)
    assert len(validated.papers) == 39
    assert len(validated.questions) == 2712


def test_builder_uses_verified_legacy_slot_patterns_and_2005_split_items() -> None:
    artifact, _ = _build_without_secondary_locators()

    assert [
        item["item_label"] for item in _paper_items(artifact, "gate-cs-1996")
    ] == [
        *[f"1.{number}" for number in range(1, 26)],
        *[f"2.{number}" for number in range(1, 26)],
        *[str(number) for number in range(3, 28)],
    ]
    assert [
        item["item_label"] for item in _paper_items(artifact, "gate-cs-1997")
    ] == [
        *[f"1.{number}" for number in range(1, 11)],
        *[f"2.{number}" for number in range(1, 6)],
        *[f"3.{number}" for number in range(1, 11)],
        *[f"4.{number}" for number in range(1, 11)],
        *[f"5.{number}" for number in range(1, 6)],
        *[f"6.{number}" for number in range(1, 11)],
        *[str(number) for number in range(7, 25)],
    ]
    labels_2005 = [
        item["item_label"] for item in _paper_items(artifact, "gate-cs-2005")
    ]
    assert labels_2005[:80] == [str(number) for number in range(1, 81)]
    assert labels_2005[80:] == [
        "81a",
        "81b",
        "82a",
        "82b",
        "83a",
        "83b",
        "84a",
        "84b",
        "85a",
        "85b",
    ]
    paired_2005 = _paper_items(artifact, "gate-cs-2005")[80:]
    assert [item["parent_item_label"] for item in paired_2005] == [
        "81",
        "81",
        "82",
        "82",
        "83",
        "83",
        "84",
        "84",
        "85",
        "85",
    ]


def test_builder_normalizes_modern_sections_and_2017_technical_first_source() -> None:
    artifact, report = _build_without_secondary_locators()

    paper_2017 = _paper_items(artifact, "gate-cs-2017-session-2")
    assert [item["item_label"] for item in paper_2017[:12]] == [
        *[f"GA-{number}" for number in range(1, 11)],
        "CS-1",
        "CS-2",
    ]
    consolidated = MODULE._read_json(
        BACKEND_DIR / "data" / "pyq_consolidated.json"
    )["questions"]
    source_2017_q1 = next(
        item
        for item in consolidated
        if item["source_paper"] == "CS2-2017"
        and item["source_question_number"] == 1
    )
    source_2017_q56 = next(
        item
        for item in consolidated
        if item["source_paper"] == "CS2-2017"
        and item["source_question_number"] == 56
    )
    assert paper_2017[10]["question_md"] == source_2017_q1["question"]
    assert paper_2017[0]["question_md"] == source_2017_q56["question"]
    assert paper_2017[10]["legacy_source_ordinals"] == [1]
    assert paper_2017[0]["legacy_source_ordinals"] == [56]

    paper_2018 = _paper_items(artifact, "gate-cs-2018")
    source_2018_q1 = next(
        item
        for item in consolidated
        if item["source_paper"] == "CS-2018"
        and item["source_question_number"] == 1
    )
    assert paper_2018[0]["item_label"] == "GA-1"
    assert paper_2018[0]["question_md"] == source_2018_q1["question"]
    assert report["joins"]["consolidated"]["adopted_count"] == 845
    assert report["joins"]["consolidated"]["verified_safe_count"] == 387

    papers = {paper["id"]: paper for paper in artifact["papers"]}
    assert papers["gate-cs-2017-session-2"]["source_aliases"] == ["CS2-2017"]
    assert papers["gate-cs-2024-set-1"]["source_aliases"] == ["CS1-2024"]


def test_builder_is_deterministic_and_keeps_unmatched_slots_explicit() -> None:
    first, first_report = _build_without_secondary_locators()
    second, second_report = _build_without_secondary_locators()

    assert first == second
    assert first_report == second_report
    assert first["artifact_version"] == second["artifact_version"]
    old_slot = _paper_items(first, "gate-cs-1996")[0]
    assert old_slot["question_md"] is None
    assert old_slot["transcription_status"] == "missing"
    assert {
        "missing_transcription",
        "answer_unresolved",
        "classification_review_required",
    }.issubset(old_slot["review_flags"])


def test_manifest_layout_rejects_compensating_per_paper_count_errors() -> None:
    manifest = MODULE._read_json(BACKEND_DIR / "data" / "pyq_source_manifest.json")
    changed = deepcopy(manifest)
    changed["papers"][0]["expected_item_count"] += 1
    changed["papers"][1]["expected_item_count"] -= 1

    with pytest.raises(MODULE.ArchiveBuildError, match="reviewed 39-paper inventory"):
        MODULE._validate_manifest(changed)


def test_manifest_source_checksum_is_recomputed_before_build(tmp_path: Path) -> None:
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"audited source bytes")
    paper = {
        "id": "gate-cs-test",
        "local_file": source.name,
        "local_file_origin": "manifest_relative",
        "local_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "local_bytes": source.stat().st_size,
    }
    manifest_path = tmp_path / "manifest.json"

    report = MODULE._verify_manifest_sources([paper], manifest_path)
    assert report["performed"] is True
    assert report["declaration_count"] == 1
    assert report["unique_file_count"] == 1

    source.write_bytes(b"tampered source byte")
    with pytest.raises(MODULE.ArchiveBuildError, match="SHA-256 mismatch"):
        MODULE._verify_manifest_sources([paper], manifest_path)


def test_builder_preserves_key_checksum_but_manifest_metadata_cannot_promote_answers() -> None:
    artifact, _ = _build_without_secondary_locators()
    papers = {paper["id"]: paper for paper in artifact["papers"]}
    manifest = MODULE._read_json(BACKEND_DIR / "data" / "pyq_source_manifest.json")
    source_papers = {paper["id"]: paper for paper in manifest["papers"]}

    assert papers["gate-cs-2011"]["answer_key_sha256"] == source_papers[
        "gate-cs-2011"
    ]["answer_key_local_sha256"]
    safe_2018 = next(
        item
        for item in _paper_items(artifact, "gate-cs-2018")
        if item["transcription_status"] == "verified"
    )
    assert safe_2018["answer_status"] == "unresolved"
    assert "answer_candidate_requires_checksum_reconciliation" in safe_2018["review_flags"]
    safe_official = next(
        item
        for item in _paper_items(artifact, "gate-cs-2021-session-2")
        if item["transcription_status"] == "verified"
    )
    assert safe_official["answer_status"] == "unresolved"
    assert "answer_candidate_requires_checksum_reconciliation" in safe_official["review_flags"]
    assert safe_2018["practice_eligible"] is False
    assert safe_official["practice_eligible"] is False


def test_sanitized_secondary_locator_never_copies_question_or_explanation() -> None:
    item = {
        "source_paper_id": "gate-cs-2024-set-1",
        "item_label": "GA-1",
        "ordinal": 1,
        "source_references": [],
        "review_flags": [],
    }
    slots = {(item["source_paper_id"], item["ordinal"]): item}
    rows = [
        {
            "source_paper_id": "gate-cs-2024-set-1",
            "global_ordinal": 1,
            "question_id": "secondary-123",
            "url": "https://questions.example.test/secondary-123",
            "question": "Third-party transcription must not be copied.",
            "options": ["A", "B"],
            "answer": "A",
            "explanation": "Third-party explanation must not be copied.",
        }
    ]
    stats: dict[str, Counter[str]] = {item["source_paper_id"]: Counter()}

    report = MODULE._attach_examside_sanitized(
        slots,
        [{"id": item["source_paper_id"], "year": 2024}],
        {item["source_paper_id"]: {}},
        rows,
        stats,
    )

    assert report["exact_locator_count"] == 1
    assert report["records_with_ignored_content_fields"] == 1
    serialized = str(item)
    assert "Third-party transcription" not in serialized
    assert "Third-party explanation" not in serialized
    assert item["source_references"][0]["kind"] == "examside_sanitized_locator"
    assert "secondary_locator_requires_source_crosscheck" in item["review_flags"]


def test_nested_examside_record_joins_only_by_unique_exact_full_text() -> None:
    item = {
        "source_paper_id": "gate-cs-2024-set-1",
        "item_label": "GA-1",
        "ordinal": 1,
        "question_md": "Which unique full question can be joined without guessing?",
        "source_references": [],
        "review_flags": [],
    }
    slots = {(item["source_paper_id"], item["ordinal"]): item}
    row = {
        "paper": {
            "slug": "gate-cse-2024-set-1",
            "year": 2024,
            "session": "set1",
        },
        "question": {
            "source_id": "nested-1",
            "url": "https://questions.example.test/nested-1",
            "question_text": (
                "<p>Which unique full question can be joined without guessing?</p>"
            ),
            "options": [{"identifier": "A", "content": "One"}],
            "correct_options": ["A"],
            "explanation_sha256": "a" * 64,
        },
        "provenance": {"question_raw_sha256": "b" * 64},
    }
    stats: dict[str, Counter[str]] = {item["source_paper_id"]: Counter()}

    report = MODULE._attach_examside_sanitized(
        slots,
        [{"id": item["source_paper_id"], "year": 2024, "session": "set-1"}],
        {item["source_paper_id"]: {}},
        [row],
        stats,
    )

    assert report["exact_locator_count"] == 1
    assert report["unmatched_record_count"] == 0
    reference = item["source_references"][0]
    assert reference["url"].endswith("/nested-1")
    assert reference["sha256"] == "b" * 64
    assert "options" not in reference
    assert "correct_options" not in reference
