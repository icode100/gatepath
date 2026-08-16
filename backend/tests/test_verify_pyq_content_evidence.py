from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = BACKEND_DIR / "scripts" / "verify_pyq_content_evidence.py"
SPEC = importlib.util.spec_from_file_location("verify_pyq_content_evidence", SCRIPT_PATH)
assert SPEC and SPEC.loader
verifier = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = verifier
SPEC.loader.exec_module(verifier)


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        (r"Find $x^2$.", "formula_or_latex_requires_visual_review"),
        ("#include <stdio.h>\nint main() {", "code_layout_requires_visual_review"),
        ("Use the figure shown below.", "prompt_depends_on_visual_asset"),
        ("<img src='remote.png'>", "html_or_embedded_markup"),
        ("Question [image: graph]", "remote_visual_asset_not_copied"),
    ],
)
def test_ambiguity_gate_fails_closed(text: str, reason: str) -> None:
    assert reason in verifier._ambiguity_reasons(text)


def test_plain_prose_has_no_automatic_ambiguity() -> None:
    assert verifier._ambiguity_reasons(
        "Register renaming is done in pipelined processors."
    ) == []


def test_asset_ready_clears_only_satisfied_visual_dependencies() -> None:
    figure = {"dependence_status": "asset_ready"}
    assert verifier._asset_blockers(
        candidate={"question_text": "Use the figure shown below."},
        overlay={
            "review_flags": [
                "remote_visual_asset_not_copied",
                "upstream_visual_or_missing_content_signal",
            ],
            "status_reason": "source_text_contains_visual_or_layout_risk",
        },
        provenance={"review_flags": []},
        match=None,
        figure=figure,
    ) == []

    field = {
        "blockers": [
            "figure_or_table_review_required",
            "prompt_depends_on_visual_asset",
            "remote_visual_asset_not_copied",
            "upstream_visual_or_missing_content_signal",
            "formula_or_latex_requires_visual_review",
            "source_text_contains_visual_or_layout_risk",
        ]
    }
    verifier._clear_satisfied_asset_dependencies(field, figure=figure)
    assert field["blockers"] == [
        "formula_or_latex_requires_visual_review",
        "source_text_contains_visual_or_layout_risk",
    ]


def test_review_required_figure_still_blocks_visual_dependency() -> None:
    blockers = verifier._asset_blockers(
        candidate={"question_text": "Use the figure shown below."},
        overlay={"review_flags": []},
        provenance={"review_flags": []},
        match=None,
        figure={"dependence_status": "review_required"},
    )
    assert "prompt_level_visual_reference" in blockers
    assert "original_pdf_figure_review_required" in blockers


def test_safe_output_rejects_solutions_answers_and_promotion_fields() -> None:
    for key in ("solution", "explanation", "correct_answer", "practice_eligible"):
        with pytest.raises(verifier.ContentVerificationError, match="Forbidden output"):
            verifier._safe_output({"items": [{key: "not allowed"}]})


def test_real_staging_ledger_is_complete_hash_bound_and_improves_stems() -> None:
    artifact, report = verifier.build_verification()

    assert len(artifact["items"]) == verifier.EXPECTED_PARENT_SLOTS == 2712
    assert report["summary"]["input_overlay_exact_slots"] == 773
    assert report["summary"]["base_exact_verified_stems"] == 647
    assert report["summary"]["new_cross_source_verified_stems"] > 0
    assert report["summary"]["stems"]["verified"] > 647
    assert all(report["invariants"].values())
    assert artifact["practice_eligible_count"] == 0
    assert artifact["production_import_authorized"] is False
    assert artifact["automatic_promotion_allowed"] is False

    cross_source = [
        row
        for row in artifact["items"]
        if row["stem"]["verification_method"]
        == "mutually_unique_cross_source_original_page"
    ]
    assert len(cross_source) == report["summary"]["new_cross_source_verified_stems"]
    assert all(not verifier._ambiguity_reasons(row["stem"]["content"]) for row in cross_source)
    assert all(
        row["options"]["verification_method"]
        in {None, "mutually_unique_cross_source_original_page"}
        for row in cross_source
    )


def test_exact_options_require_four_distinct_labeled_values() -> None:
    assert verifier._normalized_options(
        [
            {"id": "A", "text": "one"},
            {"id": "B", "text": "two"},
            {"id": "C", "text": "three"},
            {"id": "D", "text": "four"},
        ]
    )
    assert verifier._normalized_options(
        [
            {"id": "A", "text": "same"},
            {"id": "B", "text": "same"},
            {"id": "C", "text": "three"},
            {"id": "D", "text": "four"},
        ]
    ) == []
