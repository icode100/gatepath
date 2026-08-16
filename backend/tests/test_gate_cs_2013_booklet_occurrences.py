from __future__ import annotations

import importlib.util
import json
import sys
from collections import Counter
from copy import deepcopy
from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = BACKEND_DIR / "scripts" / "build_canonical_pyq_archive.py"
MAPPING_PATH = BACKEND_DIR / "data" / "gate_cs_2013_booklet_occurrences.json"
SPEC = importlib.util.spec_from_file_location(
    "build_canonical_pyq_archive_2013_tests", SCRIPT_PATH
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _manifest_paper() -> dict:
    manifest = MODULE._read_json(BACKEND_DIR / "data" / "pyq_source_manifest.json")
    return next(paper for paper in manifest["papers"] if paper["id"] == "gate-cs-2013")


def _mapping():
    return MODULE._load_2013_booklet_occurrences(MAPPING_PATH, _manifest_paper())


def test_occurrence_artifact_is_four_complete_bijections_over_one_paper() -> None:
    mapping = _mapping()

    assert mapping.paper_id == "gate-cs-2013"
    assert mapping.canonical_booklet_code == "A"
    assert len(mapping.by_canonical_ordinal) == 65
    assert len(mapping.canonical_ordinal_by_occurrence) == 260
    assert mapping.canonical_ordinal_by_occurrence[("A", "1")] == 1
    assert mapping.canonical_ordinal_by_occurrence[("B", "1")] == 24
    assert mapping.canonical_ordinal_by_occurrence[("C", "1")] == 13
    assert mapping.canonical_ordinal_by_occurrence[("D", "1")] == 12

    for code in "ABCD":
        canonical_ordinals = {
            mapping.canonical_ordinal_by_occurrence[(code, str(label))]
            for label in range(1, 66)
        }
        assert canonical_ordinals == set(range(1, 66))
    assert {
        occurrence.booklet_code
        for occurrence in mapping.by_canonical_ordinal[1]
    } == set("ABCD")


def test_bare_2013_booklet_label_cannot_join_a_canonical_answer() -> None:
    mapping = _mapping()
    labels = {"gate-cs-2013": {str(number): number for number in range(1, 66)}}

    assert (
        MODULE._reference_slot_key(
            {"item_label": "1"},
            "gate-cs-2013",
            2013,
            labels,
            mapping,
        )
        is None
    )
    assert MODULE._reference_slot_key(
        {"item_label": "1", "booklet_code": "B"},
        "gate-cs-2013",
        2013,
        labels,
        mapping,
    ) == ("gate-cs-2013", 24)
    assert MODULE._reference_slot_key(
        {"item_label": "1", "question": {"booklet_code": "CS-C"}},
        "gate-cs-2013",
        2013,
        labels,
        mapping,
    ) == ("gate-cs-2013", 13)

    slots = {
        ("gate-cs-2013", ordinal): {"ordinal": ordinal}
        for ordinal in range(1, 66)
    }
    assert (
        MODULE._explicit_secondary_key(
            {"manifest_paper_id": "gate-cs-2013", "ordinal": 1},
            slots,
            labels,
            {"gate-cs-2013": 2013},
            mapping,
        )
        is None
    )
    assert MODULE._explicit_secondary_key(
        {
            "manifest_paper_id": "gate-cs-2013",
            "ordinal": 1,
            "booklet_code": "D",
        },
        slots,
        labels,
        {"gate-cs-2013": 2013},
        mapping,
    ) == ("gate-cs-2013", 12)
    # ``global_ordinal`` is explicitly canonical, so it does not need a
    # booklet code and remains distinct from a booklet-local ``ordinal``.
    assert MODULE._explicit_secondary_key(
        {"manifest_paper_id": "gate-cs-2013", "global_ordinal": 1},
        slots,
        labels,
        {"gate-cs-2013": 2013},
        mapping,
    ) == ("gate-cs-2013", 1)


def test_builder_keeps_2013_single_and_attaches_260_staging_occurrences() -> None:
    artifact, report = MODULE.build_archive(
        BACKEND_DIR / "data" / "pyq_source_manifest.json",
        BACKEND_DIR / "data" / "pyq_consolidated.json",
        go_index_path=None,
        examside_index_path=None,
        verify_source_hashes=False,
    )
    papers_2013 = [paper for paper in artifact["papers"] if paper["year"] == 2013]
    assert len(papers_2013) == 1
    assert papers_2013[0]["id"] == "gate-cs-2013"
    assert papers_2013[0]["expected_item_count"] == 65

    items = [
        item
        for item in artifact["questions"]
        if item["source_paper_id"] == "gate-cs-2013"
    ]
    assert len(items) == 65
    assert not any(item["practice_eligible"] for item in items)
    for item in items:
        occurrences = [
            reference
            for reference in item["source_references"]
            if reference["kind"] == "booklet_occurrence"
        ]
        assert len(occurrences) == 4
        decoded = [json.loads(reference["note"]) for reference in occurrences]
        assert {row["booklet_code"] for row in decoded} == set("ABCD")
        canonical = next(row for row in decoded if row["booklet_code"] == "A")
        assert canonical["item_label"] == item["item_label"]
        assert canonical["source_page"] == item["source_page"]
        assert "booklet_occurrence_mapping_staging_only" in item["review_flags"]

    assert report["joins"]["booklet_occurrences_2013"] == {
        "paper_id": "gate-cs-2013",
        "canonical_booklet_code": "A",
        "canonical_item_count": 65,
        "occurrence_count": 260,
        "booklet_codes": ["A", "B", "C", "D"],
        "all_booklets_bijective": True,
        "staging_only": True,
    }
    stats = next(row for row in report["papers"] if row["paper_id"] == "gate-cs-2013")
    assert stats["canonical_items_mapped"] == 65
    assert stats["booklet_occurrences_attached"] == 260


def test_corrupt_or_incomplete_booklet_permutation_blocks_build(tmp_path: Path) -> None:
    payload = MODULE._read_json(MAPPING_PATH)
    duplicate = deepcopy(payload)
    duplicate["items"][1]["occurrences"][1]["item_label"] = "1"
    duplicate_path = tmp_path / "duplicate.json"
    MODULE._write_json(duplicate_path, duplicate)
    with pytest.raises(MODULE.ArchiveBuildError, match="Duplicate 2013 booklet occurrence"):
        MODULE._load_2013_booklet_occurrences(duplicate_path, _manifest_paper())

    incomplete = deepcopy(payload)
    incomplete["items"].pop()
    incomplete_path = tmp_path / "incomplete.json"
    MODULE._write_json(incomplete_path, incomplete)
    with pytest.raises(MODULE.ArchiveBuildError, match="65 canonical items"):
        MODULE._load_2013_booklet_occurrences(incomplete_path, _manifest_paper())


def test_gateoverflow_2013_locator_without_booklet_code_stays_unmatched() -> None:
    mapping = _mapping()
    item = {
        "source_paper_id": "gate-cs-2013",
        "item_label": "1",
        "ordinal": 1,
        "source_references": [],
        "review_flags": [],
    }
    slots = {("gate-cs-2013", 1): item}
    stats = {"gate-cs-2013": Counter()}
    report = MODULE._attach_gateoverflow(
        slots,
        [{"id": "gate-cs-2013", "year": 2013, "session": "single-canonical-paper"}],
        {"gate-cs-2013": {"1": 1}},
        [{"year": 2013, "item_label": "1", "session": "main"}],
        stats,
        mapping,
    )

    assert report["unmatched_record_count"] == 1
    assert report["exact_locator_count"] == 0
    assert item["source_references"] == []
