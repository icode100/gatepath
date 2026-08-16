from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest
from PIL import Image


BACKEND_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = BACKEND_DIR / "scripts" / "index_pyq_figure_assets.py"
CROP_PATH = BACKEND_DIR / "data" / "pyq_figure_crop_overrides.json"
MANIFEST_PATH = BACKEND_DIR / "data" / "pyq_source_manifest.json"
LEGACY_PATH = BACKEND_DIR / "data" / "legacy_pyq_subparts_1996_2002.json"
SPEC = importlib.util.spec_from_file_location("index_pyq_figure_assets", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_visual_phrase_detection_is_conservative() -> None:
    assert "named_visual_shown" in MODULE.detect_visual_signals(
        ["The miss rate is shown in the figure below."],
    )
    assert "visual_option_reference" in MODULE.detect_visual_signals(
        ["Which of the following circuits implements the function?"],
    )
    assert MODULE.detect_visual_signals(
        ["An undirected graph has 12 vertices and 18 edges."],
    ) == []


def test_secondary_html_is_only_a_boolean_locator_signal() -> None:
    signals = MODULE.detect_visual_signals(
        ["Determine the result."], remote_visual_hint=True
    )

    assert signals == ["secondary_remote_visual_locator_hint"]
    assert "http" not in str(signals)


@pytest.mark.parametrize(
    ("signals", "pages", "has_crop", "expected"),
    [
        ([], [1], False, ("not_required", "not_detected")),
        (["named_visual_shown"], [1], False, ("review_required", "confirmed")),
        (["named_visual_shown"], [], False, ("missing", "confirmed")),
        (["named_visual_shown"], [1], True, ("asset_ready", "confirmed")),
        (
            ["objective_options_not_safely_transcribed"],
            [1],
            False,
            ("review_required", "potential"),
        ),
    ],
)
def test_status_gate_fails_closed(
    signals: list[str], pages: list[int], has_crop: bool, expected: tuple[str, str]
) -> None:
    assert MODULE.decide_dependence_status(
        signals=signals,
        source_pages=pages,
        has_complete_reviewed_crop=has_crop,
    ) == expected


def test_checksum_bound_no_asset_review_can_clear_a_signal_without_a_crop() -> None:
    assert MODULE.decide_dependence_status(
        signals=["named_visual_shown"],
        source_pages=[1],
        has_complete_reviewed_crop=False,
        visually_reviewed_no_asset_required=True,
    ) == ("not_required", "not_detected")
    with pytest.raises(MODULE.FigureAssetError):
        MODULE.decide_dependence_status(
            signals=["named_visual_shown"],
            source_pages=[1],
            has_complete_reviewed_crop=True,
            visually_reviewed_no_asset_required=True,
        )


def test_crop_box_must_be_inside_reviewed_page() -> None:
    assert MODULE._validate_crop_box([10, 20, 90, 80], [100, 100]) == (
        10,
        20,
        90,
        80,
    )
    with pytest.raises(MODULE.FigureAssetError):
        MODULE._validate_crop_box([-1, 20, 90, 80], [100, 100])
    with pytest.raises(MODULE.FigureAssetError):
        MODULE._validate_crop_box([10, 20, 110, 80], [100, 100])
    with pytest.raises(MODULE.FigureAssetError):
        MODULE._validate_crop_box([10, 20, 20, 30], [100, 100])


def test_crop_output_is_hash_bound_and_deterministic(tmp_path: Path) -> None:
    page = tmp_path / "page.png"
    image = Image.new("RGB", (160, 120), "white")
    for x in range(50, 110):
        for y in range(35, 85):
            image.putpixel((x, y), (0, 0, 0))
    image.save(page, format="PNG", optimize=False, compress_level=9)
    crop = {
        "source_paper_id": "gate-cs-2099",
        "canonical_ordinal": 1,
        "child_item_label": None,
        "source_pdf_sha256": "a" * 64,
        "source_page": 1,
        "source_page_pixel_size": [160, 120],
        "visual_reviewed_source_page_render_sha256": MODULE._sha256_file(page),
        "crop_box_pixels": [40, 25, 120, 95],
        "asset_role": "stem_diagram",
        "visual_kind": "synthetic_test",
        "alt_text": "A black rectangle used to test deterministic image cropping.",
        "caption": "Synthetic deterministic crop test fixture.",
        "review_status": "visually_reviewed_exact_bounds",
    }
    render_spec = {"dpi": 216}

    first = MODULE._extract_crop(
        crop,
        rendered_page=page,
        asset_dir=tmp_path / "assets",
        render_specification=render_spec,
    )
    second = MODULE._extract_crop(
        crop,
        rendered_page=page,
        asset_dir=tmp_path / "assets",
        render_specification=render_spec,
    )

    assert first == second
    assert first["pixel_width"] == 80
    assert first["pixel_height"] == 70
    assert first["crop_box_pdf_points"] == [13.333, 8.333, 40.0, 31.667]
    assert re.fullmatch(r"[0-9a-f]{64}", first["sha256"])
    assert Path(first["relative_path"]).is_file()
    assert (tmp_path / "assets" / "gate-cs-2099").is_dir()


def test_tracked_crop_overrides_are_staging_only_and_manifest_bound() -> None:
    crops = json.loads(CROP_PATH.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    hashes = {paper["id"]: paper["local_sha256"] for paper in manifest["papers"]}

    assert crops["production_import_authorized"] is False
    assert crops["practice_eligible_count"] == 0
    assert crops["review_required"] is True
    assert crops["render_specification"]["dpi"] == 216
    assert len(crops["crops"]) >= 6
    assert len(
        {
            (
                row["source_paper_id"],
                row["canonical_ordinal"],
                row["child_item_label"],
                row["asset_role"],
            )
            for row in crops["crops"]
        }
    ) == len(crops["crops"])
    assert all(
        row["source_pdf_sha256"] == hashes[row["source_paper_id"]]
        for row in crops["crops"]
    )
    assert all(
        row["review_status"] == "visually_reviewed_exact_bounds"
        for row in crops["crops"]
    )
    no_asset_reviews = crops.get("no_asset_reviews") or []
    assert len(no_asset_reviews) == 11
    assert len(
        {
            (
                row["source_paper_id"],
                row["canonical_ordinal"],
                row["child_item_label"],
            )
            for row in no_asset_reviews
        }
    ) == len(no_asset_reviews)
    assert all(
        row["source_pdf_sha256"] == hashes[row["source_paper_id"]]
        for row in no_asset_reviews
    )
    assert all(
        row["disposition"] == "no_external_asset_required"
        and row["review_status"] == "visually_reviewed_original_pages"
        and row["reviewed_source_pages"]
        and all(
            re.fullmatch(
                r"[0-9a-f]{64}",
                page["visual_reviewed_source_page_render_sha256"],
            )
            for page in row["reviewed_source_pages"]
        )
        for row in no_asset_reviews
    )
    paper_reviews = crops.get("paper_no_asset_reviews") or []
    assert len(paper_reviews) == 2
    assert {row["source_paper_id"] for row in paper_reviews} == {
        "gate-cs-2024-set-1",
        "gate-cs-2024-set-2",
    }
    assert sum(len(row["canonical_parent_ordinals"]) for row in paper_reviews) == 68
    assert {
        row["source_paper_id"]: len(row["reviewed_source_pages"])
        for row in paper_reviews
    } == {"gate-cs-2024-set-1": 36, "gate-cs-2024-set-2": 40}
    crop_keys = {
        (row["source_paper_id"], row["canonical_ordinal"])
        for row in crops["crops"]
    }
    paper_review_keys = {
        (row["source_paper_id"], ordinal)
        for row in paper_reviews
        for ordinal in row["canonical_parent_ordinals"]
    }
    assert crop_keys.isdisjoint(paper_review_keys)
    assert all(
        row["source_pdf_sha256"] == hashes[row["source_paper_id"]]
        and row["disposition"]
        == "no_external_asset_required_for_listed_parents"
        and row["review_status"] == "visually_reviewed_all_original_pages"
        and len(row["reviewed_source_pages"])
        == len(
            {
                page["source_page"] for page in row["reviewed_source_pages"]
            }
        )
        and all(
            re.fullmatch(
                r"[0-9a-f]{64}",
                page["visual_reviewed_source_page_render_sha256"],
            )
            for page in row["reviewed_source_pages"]
        )
        for row in paper_reviews
    )


def test_all_272_expanded_children_are_in_visual_audit_scope() -> None:
    legacy = json.loads(LEGACY_PATH.read_text(encoding="utf-8"))
    MODULE._validate_embedded_hash(legacy, label="legacy subparts")
    children = MODULE._load_children(legacy)

    assert len(children) == 272
    assert len({key[:2] for key in children}) == 111
    assert all(child["materialization_status"] == "exact" for child in children.values())


def test_script_has_no_database_or_remote_asset_fetch_path() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8").casefold()

    assert "sqlalchemy" not in source
    assert "app.database" not in source
    assert "requests.get" not in source
    assert "urllib.request" not in source
    assert "database_writes_performed\": false" in source
    assert "production_import_authorized\": false" in source
    assert "practice_eligible_count\": 0" in source
