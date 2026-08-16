from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from pypdf import PdfWriter


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "build_original_question_transcription_overlay.py"
)
SPEC = importlib.util.spec_from_file_location("original_transcription_overlay", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
overlay = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = overlay
SPEC.loader.exec_module(overlay)


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def test_original_pdf_option_parse_preserves_stem_and_all_four_choices() -> None:
    result = overlay._parse_options(
        "Which value is correct?\n(a) one (b) two\n(c) three\n(d) four"
    )

    assert result["status"] == "exact"
    assert result["stem"] == "Which value is correct?"
    assert [row["identifier"] for row in result["options"]] == ["A", "B", "C", "D"]
    assert [row["text"] for row in result["options"]] == ["one", "two", "three", "four"]


def test_option_parse_fails_closed_for_duplicate_or_incomplete_labels() -> None:
    duplicate = overlay._parse_options("Stem (a) x (b) x (c) y (d) z")
    incomplete = overlay._parse_options("Stem (a) x (b) y (d) z")

    assert duplicate["status"] == "review"
    assert "duplicate_option_text" in duplicate["reasons"]
    assert incomplete == {
        "status": "unresolved",
        "reasons": ["explicit_A_to_D_block_not_unique"],
    }


def test_legacy_lettered_subparts_retain_parent_child_identity() -> None:
    inventory = overlay._inventory_lettered_subparts(
        body="Shared setup.\n(a) Find X.\n(b) Draw the graph.\n(c) Prove Y.",
        archive_item={"ordinal": 53, "item_label": "5", "item_type": "descriptive"},
        provenance_item={"evidence_status": "exact_text_block", "source_pages": [3]},
        year=2002,
    )

    assert inventory is not None
    assert inventory["parent_item_label"] == "5"
    assert inventory["parent_canonical_ordinal"] == 53
    assert [row["source_subpart_label"] for row in inventory["children"]] == [
        "5(a)",
        "5(b)",
        "5(c)",
    ]
    assert all(row["parent_item_label"] == "5" for row in inventory["children"])
    assert inventory["status"] == "review"
    assert all(
        row["independently_answerable_status"] == "review"
        for row in inventory["children"]
    )
    assert all(
        "independent_gradability_review_required" in row["review_flags"]
        for row in inventory["children"]
    )
    assert "figure_or_table_review_required" in inventory["children"][1]["review_flags"]


def test_legacy_subparts_fail_closed_when_markers_do_not_start_at_a() -> None:
    inventory = overlay._inventory_lettered_subparts(
        body="Shared setup.\n(b) Part two.\n(c) Part three.",
        archive_item={"ordinal": 51, "item_label": "3", "item_type": "descriptive"},
        provenance_item={"evidence_status": "exact_text_block", "source_pages": [1]},
        year=2001,
    )

    assert inventory is not None
    assert inventory["status"] == "review"
    assert inventory["status_reason"] == "lettered_subparts_not_consecutive_from_a"
    assert inventory["children"] == []


def test_locator_override_requires_matching_slot_pdf_and_render_hash(tmp_path: Path) -> None:
    page_sha = "b" * 64
    source_sha = "a" * 64
    provenance = {"artifact_sha256": "c" * 64}
    provenance_map = {
        ("paper", 1): {
            "item_label": "Q-1",
            "rendered_page_evidence": [
                {
                    "page": 2,
                    "sha256": page_sha,
                    "format": "pgm",
                    "dpi": 144,
                    "color_mode": "gray",
                }
            ],
        }
    }
    manifest_map = {"paper": {"local_sha256": source_sha, "local_page_count": 3}}
    path = tmp_path / "locators.json"
    _write(
        path,
        {
            "locators": [
                {
                    "paper_id": "paper",
                    "canonical_ordinal": 1,
                    "item_label": "Q-1",
                    "source_pdf_sha256": source_sha,
                    "source_page": 2,
                    "evidence_method": "reviewed_scan_marker",
                    "rendered_page_sha256": page_sha,
                    "render_specification": {
                        "format": "pgm",
                        "dpi": 144,
                        "color_mode": "gray",
                    },
                    "review_required": True,
                }
            ]
        },
    )

    rows, binding = overlay._load_locator_overrides(
        path,
        provenance=provenance,
        provenance_map=provenance_map,
        manifest_map=manifest_map,
        source_manifest_sha256="d" * 64,
    )
    assert rows[("paper", 1)]["source_page"] == 2
    assert binding is not None and binding["sha256"] == overlay._sha256_file(path)

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["locators"][0]["rendered_page_sha256"] = "e" * 64
    _write(path, payload)
    with pytest.raises(overlay.OverlayBuildError, match="has not incorporated"):
        overlay._load_locator_overrides(
            path,
            provenance=provenance,
            provenance_map=provenance_map,
            manifest_map=manifest_map,
            source_manifest_sha256="d" * 64,
        )


def test_nested_locator_catalog_flattens_only_checksum_bound_page_evidence(
    tmp_path: Path,
) -> None:
    page_sha = "b" * 64
    source_sha = "a" * 64
    provenance = {"artifact_sha256": "c" * 64}
    provenance_map = {
        ("paper", 1): {
            "item_label": "Q-1",
            "rendered_page_evidence": [
                {
                    "page": 2,
                    "sha256": page_sha,
                    "format": "pgm",
                    "dpi": 144,
                    "color_mode": "gray",
                }
            ],
        }
    }
    manifest_map = {"paper": {"local_sha256": source_sha, "local_page_count": 3}}
    path = tmp_path / "nested-locators.json"
    payload = {
        "locator_count": 1,
        "unresolved_locators": [],
        "papers": [
            {
                "paper_id": "paper",
                "source_pdf_sha256": source_sha,
                "source_page_count": 3,
                "review_required": True,
                "page_evidence": [
                    {
                        "page": 2,
                        "sha256": page_sha,
                        "format": "pgm",
                        "dpi": 144,
                        "color_mode": "gray",
                        "evidence_method": "ocr+visual_review",
                        "visual_spot_check": True,
                    }
                ],
                "locators": [
                    {
                        "canonical_ordinal": 1,
                        "item_label": "Q-1",
                        "source_page": 2,
                    }
                ],
            }
        ],
    }
    _write(path, payload)

    rows, _ = overlay._load_locator_overrides(
        path,
        provenance=provenance,
        provenance_map=provenance_map,
        manifest_map=manifest_map,
        source_manifest_sha256="d" * 64,
    )

    assert rows[("paper", 1)]["source_page"] == 2
    assert rows[("paper", 1)]["evidence_method"] == "ocr+visual_review"

    payload["papers"][0]["page_evidence"] = []
    _write(path, payload)
    with pytest.raises(overlay.OverlayBuildError, match="has no rendered evidence"):
        overlay._load_locator_overrides(
            path,
            provenance=provenance,
            provenance_map=provenance_map,
            manifest_map=manifest_map,
            source_manifest_sha256="d" * 64,
        )


def test_all_source_pdf_verification_checks_hash_and_page_count(tmp_path: Path) -> None:
    source_path = tmp_path / "paper.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    with source_path.open("wb") as stream:
        writer.write(stream)
    source_sha = overlay._sha256_file(source_path)
    record = {
        "source_path": str(source_path),
        "source_pdf_sha256": source_sha,
    }
    provenance_map = {("paper", 1): record}

    verified = overlay._verify_all_source_pdfs(
        provenance_map,
        {"paper": {"local_page_count": 1}},
        {},
    )
    assert verified == {
        "paper_count": 1,
        "unique_pdf_count": 1,
        "all_hashes_verified_from_disk": True,
        "all_page_counts_verified_from_disk": True,
    }

    with pytest.raises(overlay.OverlayBuildError, match="page count mismatch"):
        overlay._verify_all_source_pdfs(
            provenance_map,
            {"paper": {"local_page_count": 2}},
            {},
        )

    with pytest.raises(overlay.OverlayBuildError, match="hash mismatch"):
        overlay._verify_all_source_pdfs(
            {("paper", 1): {**record, "source_pdf_sha256": "0" * 64}},
            {"paper": {"local_page_count": 1}},
            {},
        )


def _synthetic_2712_inputs(tmp_path: Path) -> dict[str, Path]:
    paper_counts = [69] * 38 + [90]
    papers = []
    archive_questions = []
    candidate_questions = []
    provenance_items = []
    for paper_index, count in enumerate(paper_counts, start=1):
        paper_id = f"paper-{paper_index:02d}"
        source_sha = f"{paper_index:064x}"[-64:]
        papers.append(
            {
                "id": paper_id,
                "year": 1900 + paper_index,
                "local_sha256": source_sha,
                "local_page_count": 1,
            }
        )
        for ordinal in range(1, count + 1):
            label = str(ordinal)
            archive_questions.append(
                {
                    "source_paper_id": paper_id,
                    "ordinal": ordinal,
                    "item_label": label,
                    "item_type": "descriptive",
                    "question_md": f"Existing question {paper_id}/{ordinal}",
                    "options": [],
                    "transcription_status": "verified",
                    "review_flags": [],
                }
            )
            candidate_questions.append(
                {
                    "source_paper_id": paper_id,
                    "ordinal": ordinal,
                    "item_label": label,
                    "candidate": {},
                    "candidate_review_reasons": [],
                }
            )
            provenance_items.append(
                {
                    "source_paper_id": paper_id,
                    "canonical_ordinal": ordinal,
                    "item_label": label,
                    "source_label": label,
                    "source_pages": [],
                    "boundary": None,
                    "text_block_sha256": None,
                    "source_pdf_sha256": source_sha,
                    "source_path": "unused.pdf",
                    "page_text_sha256": [],
                    "rendered_page_evidence": [],
                    "evidence_status": "unresolved",
                    "locator_status": "unmatched_marker",
                    "review_flags": ["manual_source_review_required"],
                }
            )

    manifest_path = tmp_path / "manifest.json"
    _write(manifest_path, {"papers": papers})
    provenance_core = {
        "source_manifest_sha256": overlay._sha256_file(manifest_path),
        "canonical_identity": {"paper_count": 39, "item_count": 2712},
        "items": provenance_items,
    }
    provenance = {
        **provenance_core,
        "artifact_sha256": overlay._canonical_json_sha256(provenance_core),
    }
    paths = {
        "archive": tmp_path / "archive.json",
        "candidates": tmp_path / "candidates.json",
        "provenance": tmp_path / "provenance.json",
        "manifest": manifest_path,
    }
    _write(paths["archive"], {"papers": papers, "questions": archive_questions})
    _write(paths["candidates"], {"questions": candidate_questions})
    _write(paths["provenance"], provenance)
    return paths


def test_full_inventory_is_deterministic_staging_only_and_fail_closed(tmp_path: Path) -> None:
    paths = _synthetic_2712_inputs(tmp_path)

    first, first_report = overlay.build_overlay(
        archive_path=paths["archive"],
        candidates_path=paths["candidates"],
        provenance_path=paths["provenance"],
        manifest_path=paths["manifest"],
        verify_source_files=False,
    )
    second, second_report = overlay.build_overlay(
        archive_path=paths["archive"],
        candidates_path=paths["candidates"],
        provenance_path=paths["provenance"],
        manifest_path=paths["manifest"],
        verify_source_files=False,
    )

    assert first == second
    assert first_report == second_report
    assert first["artifact_sha256"] == overlay._canonical_json_sha256(
        {key: value for key, value in first.items() if key != "artifact_sha256"}
    )
    assert first["canonical_identity"] == {"paper_count": 39, "slot_count": 2712}
    assert first_report["status_counts"] == {"exact": 2712}
    assert all(row["status"] == "exact" for row in first["items"])
    serialized = json.dumps(first)
    assert "practice_eligible" not in serialized
    assert '"solution"' not in serialized
    assert '"explanation"' not in serialized


def test_output_safety_rejects_materialization_and_third_party_explanations() -> None:
    with pytest.raises(overlay.OverlayBuildError, match="practice_eligible"):
        overlay._ensure_safe_output({"practice_eligible": False})
    with pytest.raises(overlay.OverlayBuildError, match="explanation"):
        overlay._ensure_safe_output({"secondary": {"explanation": "copied"}})
