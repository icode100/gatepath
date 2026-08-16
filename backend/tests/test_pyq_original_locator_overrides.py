from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = BACKEND_DIR / "scripts" / "index_original_pdf_provenance.py"
SPEC = importlib.util.spec_from_file_location("locator_override_indexer", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _catalog() -> dict:
    return {
        "schema_version": "1.0",
        "scope": "test",
        "production_import_authorized": False,
        "practice_eligible_count": 0,
        "review_required": True,
        "render_specification": {
            "format": "pgm",
            "dpi": 144,
            "color_mode": "gray",
            "renderer": "pdftoppm",
        },
        "locator_count": 1,
        "papers": [
            {
                "paper_id": "gate-cs-test",
                "source_pdf_sha256": "a" * 64,
                "source_page_count": 2,
                "review_required": True,
                "page_evidence": [
                    {
                        "page": 1,
                        "sha256": "b" * 64,
                        "format": "pgm",
                        "dpi": 144,
                        "color_mode": "gray",
                        "evidence_method": "ocr+visual_review",
                        "visual_spot_check": True,
                        "item_labels": ["1"],
                    }
                ],
                "locators": [
                    {
                        "canonical_ordinal": 1,
                        "item_label": "1",
                        "source_page": 1,
                    }
                ],
            }
        ],
        "unresolved_locators": [],
    }


def _load(tmp_path: Path, payload: dict) -> tuple[dict, dict]:
    path = tmp_path / "locator-overrides.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return MODULE._validated_locator_override_catalog(path)


def _record(*, status: str = "unmatched_marker", label: str = "1") -> dict:
    return {
        "source_paper_id": "gate-cs-test",
        "canonical_ordinal": 1,
        "item_label": label,
        "locator_status": status,
        "source_pages": [],
        "boundary": None,
        "text_block_sha256": None,
        "normalized_character_count": 0,
    }


def _apply(record: dict, paper: dict, *, renderer=None, paper_id="gate-cs-test") -> int:
    return MODULE._apply_explicit_locator_overrides(
        [record],
        paper,
        paper_id=paper_id,
        source=Path("test.pdf"),
        source_sha256="a" * 64,
        source_page_count=2,
        page_range=(1, 2),
        render_cache=renderer,
    )


def test_committed_overlay_is_a_complete_unique_625_key_inventory() -> None:
    payload, by_paper = MODULE._validated_locator_override_catalog(
        MODULE.DEFAULT_LOCATOR_OVERRIDES
    )
    keys = [
        (paper["paper_id"], row["canonical_ordinal"], row["item_label"])
        for paper in by_paper.values()
        for row in paper["locators"]
    ]

    assert payload["locator_count"] == 625
    assert len(by_paper) == 15
    assert len(keys) == len(set(keys)) == 625
    assert payload["unresolved_locators"] == []
    assert payload["production_import_authorized"] is False
    assert payload["practice_eligible_count"] == 0


def test_exact_key_override_applies_page_evidence_without_promoting_item(
    tmp_path: Path,
) -> None:
    _, by_paper = _load(tmp_path, _catalog())
    record = _record()

    assert _apply(record, by_paper["gate-cs-test"]) == 1
    assert record["source_pages"] == [1]
    assert record["locator_status"] == "hash_matched_reviewed_original_page_override"
    assert record["locator_override_evidence"]["rendered_page_evidence"]["sha256"] == (
        "b" * 64
    )
    assert "practice_eligible" not in record


def test_duplicate_locator_key_is_rejected(tmp_path: Path) -> None:
    payload = _catalog()
    payload["papers"][0]["locators"].append(
        copy.deepcopy(payload["papers"][0]["locators"][0])
    )
    payload["locator_count"] = 2

    with pytest.raises(MODULE.ProvenanceIndexError, match="duplicate locator key"):
        _load(tmp_path, payload)


def test_out_of_range_page_is_rejected(tmp_path: Path) -> None:
    payload = _catalog()
    payload["papers"][0]["page_evidence"][0]["page"] = 3
    payload["papers"][0]["locators"][0]["source_page"] = 3

    with pytest.raises(MODULE.ProvenanceIndexError, match="outside 1..2"):
        _load(tmp_path, payload)


def test_tampered_render_hash_is_rejected(tmp_path: Path) -> None:
    _, by_paper = _load(tmp_path, _catalog())

    class TamperedRenderer:
        def page_sha256(self, source: Path, page: int) -> str:
            return "c" * 64

    with pytest.raises(MODULE.ProvenanceIndexError, match="evidence hash mismatch"):
        _apply(_record(), by_paper["gate-cs-test"], renderer=TamperedRenderer())


def test_source_sha_and_cross_paper_identity_are_rejected(tmp_path: Path) -> None:
    _, by_paper = _load(tmp_path, _catalog())
    paper = by_paper["gate-cs-test"]
    tampered = copy.deepcopy(paper)
    tampered["source_pdf_sha256"] = "d" * 64

    with pytest.raises(MODULE.ProvenanceIndexError, match="source SHA-256 mismatch"):
        _apply(_record(), tampered)
    with pytest.raises(MODULE.ProvenanceIndexError, match="Cross-paper"):
        _apply(_record(), paper, paper_id="gate-cs-other")


def test_override_cannot_silently_replace_an_automatic_marker(tmp_path: Path) -> None:
    _, by_paper = _load(tmp_path, _catalog())

    with pytest.raises(MODULE.ProvenanceIndexError, match="conflicts with automatic"):
        _apply(_record(status="marker_located"), by_paper["gate-cs-test"])


def test_label_mismatch_is_rejected_as_an_incomplete_cross_identity_key(
    tmp_path: Path,
) -> None:
    _, by_paper = _load(tmp_path, _catalog())

    with pytest.raises(MODULE.ProvenanceIndexError, match="conflicts with automatic"):
        _apply(_record(label="GA-1"), by_paper["gate-cs-test"])
