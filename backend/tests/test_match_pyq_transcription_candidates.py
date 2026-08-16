from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = BACKEND_DIR / "scripts" / "match_pyq_transcription_candidates.py"
SPEC = importlib.util.spec_from_file_location(
    "match_pyq_transcription_candidates", SCRIPT_PATH
)
assert SPEC and SPEC.loader
matcher = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = matcher
SPEC.loader.exec_module(matcher)


def _evidence() -> object:
    return matcher.TextEvidence(
        kind="original_pdf_text_block",
        text="A checksum-bound question transcription with enough words for comparison.",
        text_sha256="a" * 64,
        provenance={"source_pdf_sha256": "b" * 64},
    )


def _edge(source_id: str, ordinal: int, score: float) -> object:
    return matcher.Edge(
        source_id=source_id,
        slot=("gate-cs-2013", ordinal),
        score=score,
        text_score=score,
        topic_score=1.0,
        evidence=_evidence(),
        secondary_text_score=None,
    )


def test_mutual_match_gate_is_unique_margin_bound_and_deterministic() -> None:
    source_one = [_edge("source-1", 2, 0.70), _edge("source-1", 1, 0.95)]
    source_two = [_edge("source-2", 1, 0.75)]
    accepted, decisions = matcher._select_mutual_matches(
        ["source-3", "source-2", "source-1", "source-1"],
        edges_by_source={"source-1": source_one, "source-2": source_two},
        edges_by_slot={
            ("gate-cs-2013", 1): [source_two[0], source_one[1]],
            ("gate-cs-2013", 2): [source_one[0]],
        },
        minimum_margin=0.08,
    )

    assert [(edge.source_id, edge.slot) for edge in accepted] == [
        ("source-1", ("gate-cs-2013", 1))
    ]
    assert [row["status"] for row in decisions] == [
        "exact_proposed_review",
        "review",
        "unmatched",
    ]
    assert decisions[0]["source_margin"] == 0.25
    assert decisions[0]["slot_margin"] == 0.20
    assert decisions[1]["mutual_best"] is False


def test_close_source_margin_fails_closed_to_review() -> None:
    first = _edge("source-1", 1, 0.90)
    second = _edge("source-1", 2, 0.85)
    accepted, decisions = matcher._select_mutual_matches(
        ["source-1"],
        edges_by_source={"source-1": [first, second]},
        edges_by_slot={first.slot: [first], second.slot: [second]},
        minimum_margin=0.08,
    )
    assert accepted == []
    assert decisions == [
        {
            "source_id": "source-1",
            "status": "review",
            "top_candidates": [
                {
                    "source_paper_id": "gate-cs-2013",
                    "canonical_ordinal": 1,
                    "score": 0.90,
                },
                {
                    "source_paper_id": "gate-cs-2013",
                    "canonical_ordinal": 2,
                    "score": 0.85,
                },
            ],
            "source_margin": 0.05,
            "slot_margin": 1.0,
            "mutual_best": True,
        }
    ]


@pytest.mark.parametrize(
    ("question", "official"),
    [
        (
            {"correct_options": ["A"]},
            {"selected_answer": {"kind": "options", "options": ["A"]}},
        ),
        (
            {"correct_options": ["B", "A"]},
            {"selected_answer": {"kind": "options", "options": ["A", "B"]}},
        ),
        (
            {"numerical_answer": "1.50"},
            {
                "selected_answer": {
                    "kind": "numeric_ranges",
                    "ranges": [{"minimum": "1.49", "maximum": "1.51"}],
                }
            },
        ),
    ],
)
def test_official_answer_agreement(question: dict, official: dict) -> None:
    assert matcher._answer_agrees(question, official) is True


def test_sanitizer_preserves_latex_but_rejects_active_html() -> None:
    text, visual = matcher._plain_text(r"Find \(x^2 + y^2\) when x = 3 and y = 4.")
    assert text == r"Find \(x^2 + y^2\) when x = 3 and y = 4."
    assert visual is False
    with pytest.raises(matcher.TranscriptionMatchError, match="active HTML"):
        matcher._plain_text("<script>alert('unsafe')</script>")


def test_locator_overlay_is_exactly_bound_to_625_canonical_keys() -> None:
    path = BACKEND_DIR / "data" / "pyq_original_locator_overrides.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    candidates: dict[tuple[str, int], dict] = {}
    for paper in raw["papers"]:
        for locator in paper["locators"]:
            candidates[(paper["paper_id"], locator["canonical_ordinal"])] = {
                "item_label": locator["item_label"],
                "original_source_evidence": {
                    "source_pdf_sha256": paper["source_pdf_sha256"]
                },
            }

    locators, binding = matcher._load_locators(path, candidates=candidates)

    assert len(locators) == matcher.EXPECTED_LOCATORS == 625
    assert binding is not None
    assert binding["sha256"] == matcher._sha256_file(path)
    assert all(row["source_page"] >= 1 for row in locators.values())
    assert all(len(row["rendered_page_sha256"]) == 64 for row in locators.values())


def test_output_policy_rejects_promotion_and_solution_fields() -> None:
    with pytest.raises(matcher.TranscriptionMatchError, match="Forbidden output field"):
        matcher._safe_output({"matches": [{"practice_eligible": True}]})
    with pytest.raises(matcher.TranscriptionMatchError, match="Forbidden output field"):
        matcher._safe_output({"matches": [{"solution": "not allowed"}]})
