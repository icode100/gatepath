from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = BACKEND_DIR / "scripts" / "structure_pyq_options.py"
SPEC = importlib.util.spec_from_file_location("structure_pyq_options", SCRIPT_PATH)
assert SPEC and SPEC.loader
parser = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = parser
SPEC.loader.exec_module(parser)


def _hash(value: str) -> str:
    return parser._sha256_text(value)


def _row(
    body: str | None,
    *,
    item_type: str = "mcq",
    answer: object = "B",
    options: list[dict] | None = None,
) -> dict:
    snapshot = None
    if body is not None:
        snapshot = {
            "volume": "filter1_volume1",
            "book_page": 12,
            "question_body_text": body,
            "question_body_sha256": _hash(body),
        }
    return {
        "source_paper_id": "gate-cs-2000",
        "item_label": "1",
        "ordinal": 1,
        "candidate_review_reasons": [],
        "candidate": {
            "question_text": body,
            "question_text_sha256": _hash(body) if body else None,
            "question_source": "gateoverflow_exact_label_join" if body else None,
            "options": options or [],
            "options_source": "fixture" if options else None,
            "item_type": item_type,
            "item_type_source": "fixture" if item_type != "unknown" else None,
            "answer": answer,
        },
        "secondary_snapshots": {"gateoverflow": snapshot, "examside": None},
        "practice_eligible": False,
    }


def _artifact(*rows: dict) -> dict:
    return {
        "schema_version": "fixture",
        "source_role": "staging_review_candidates_only",
        "database_writes_performed": False,
        "automatic_promotion_allowed": False,
        "questions": list(rows),
    }


def _existing_options(count: int = 4) -> list[dict]:
    return [
        {
            "identifier": chr(ord("A") + index),
            "content_text": f"Choice {index + 1}",
            "content_html": f"Choice {index + 1}",
            "content_html_sha256": _hash(f"Choice {index + 1}"),
        }
        for index in range(count)
    ]


def test_split_letter_labels_trim_metadata_and_preserve_safe_text() -> None:
    body = (
        "For $x \\in S$, choose the valid code fragment.\n"
        "A\n. \n`x < 4`\n"
        "B\n. \n$\\Theta(n)$\n"
        "C\n. \n<code>x &lt; y</code>\n"
        "D\n. \nNone of these\n"
        "gatecse2025-set1\nalgorithms\nnormal"
    )

    result = parser.parse_explicit_four_choices(body)

    assert result["status"] == "exact"
    assert result["stem"] == "For $x \\in S$, choose the valid code fragment."
    assert [row["identifier"] for row in result["options"]] == list("ABCD")
    assert result["options"][1]["content_text"] == "$\\Theta(n)$"
    assert result["options"][2]["content_text"] == "<code>x &lt; y</code>"
    assert result["options"][2]["content_html"].startswith("&lt;code&gt;")
    assert result["metadata_tail"] == {
        "present": True,
        "marker": "gatecse2025-set1",
    }


def test_parenthesized_numeric_labels_are_position_mapped_without_loss() -> None:
    body = "Pick one:\n(1) Alpha\n(2) Beta\n(3) Gamma\n(4) Delta"

    result = parser.parse_explicit_four_choices(body)

    assert result["status"] == "exact"
    assert result["label_scheme"] == "numbers"
    assert [row["identifier"] for row in result["options"]] == list("ABCD")
    assert [row["source_identifier"] for row in result["options"]] == list(
        "1234"
    )


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        (
            "Question?\nA. One\nB. Two\nC. Three\nA. Again\nD. Four",
            "choice_labels_not_exactly_once_in_order",
        ),
        (
            "Question?\nA. One\nB. Two\nC. Three\nD. Four\n5.3.2",
            "book_section_spillover_in_choice",
        ),
        (
            "Let \n and y be values.\nA. One\nB. Two\nC. Three\nD. Four",
            "possible_unextracted_inline_content_in_stem",
        ),
        (
            "Which is true?\nA. B\n tree\nB. Two\nC. Three\nD. Four",
            "possible_unextracted_operator_in_choice",
        ),
        (
            "ISRO2016-23\nChoose.\nA. One\nB. Two\nC. Three\nD. Four",
            "foreign_exam_editorial_tag_in_stem",
        ),
        (
            "Which is true for the language\nA. One\nB. Two\nC. Three\nD. Four",
            "possible_unextracted_terminal_math_object",
        ),
        (
            "Question?\nA. One\nB. Two\nC. Same\nD. Same",
            "duplicate_choice_content",
        ),
        (
            "Question?\nA. One\nB. Two\nC. Three\nD. Four\nSolution:\nWork",
            "answer_or_solution_text_present",
        ),
    ],
)
def test_ambiguous_or_leaking_blocks_are_withheld(body: str, reason: str) -> None:
    result = parser.parse_explicit_four_choices(body)

    assert result["status"] == "ambiguous"
    assert reason in result["reasons"]
    assert "options" not in result


def test_existing_valid_options_are_preserved_and_malformed_sets_withheld() -> None:
    good = _row(None, options=_existing_options())
    bad = _row(None, options=_existing_options(3))
    bad["ordinal"] = 2

    output, report = parser.enrich_candidate_artifact(
        _artifact(good, bad), expected_slot_count=None
    )

    assert len(output["questions"][0]["candidate"]["options"]) == 4
    assert output["questions"][0]["candidate"]["option_parse"]["status"] == (
        "existing_exact"
    )
    assert output["questions"][1]["candidate"]["options"] == []
    assert output["questions"][1]["candidate"]["option_parse"]["status"] == (
        "withheld"
    )
    assert report["coverage"]["before_nonempty_option_sets"] == 2
    assert report["coverage"]["before_valid_four_option_sets"] == 1
    assert report["coverage"]["after_structured_option_sets"] == 1


def test_existing_canonical_id_text_schema_is_also_valid() -> None:
    options = [
        {"id": label, "text": f"Canonical {label}"}
        for label in "ABCD"
    ]
    output, report = parser.enrich_candidate_artifact(
        _artifact(_row(None, options=options)), expected_slot_count=None
    )

    assert output["questions"][0]["candidate"]["options"] == options
    assert output["questions"][0]["candidate"]["option_parse"]["status"] == (
        "existing_exact"
    )
    assert report["coverage"]["before_valid_four_option_sets"] == 1


def test_exact_parse_removes_options_from_go_stem_and_infers_objective_type() -> None:
    body = "Choose the scheduler.\nA. FCFS\nB. SJF\nC. RR\nD. EDF"
    row = _row(body, item_type="unknown", answer="B")

    output, report = parser.enrich_candidate_artifact(
        _artifact(row), expected_slot_count=None
    )
    candidate = output["questions"][0]["candidate"]

    assert candidate["question_text"] == "Choose the scheduler."
    assert "A. FCFS" not in candidate["question_text"]
    assert candidate["item_type"] == "mcq"
    assert len(candidate["options"]) == 4
    assert candidate["option_parse"]["status"] == "parser_exact"
    assert report["coverage"]["net_valid_option_sets_added"] == 1


def test_parse_requires_independent_objective_type_proof() -> None:
    body = "Choose.\nA. One\nB. Two\nC. Three\nD. Four"
    row = _row(body, item_type="unknown", answer=None)

    output, report = parser.enrich_candidate_artifact(
        _artifact(row), expected_slot_count=None
    )

    candidate = output["questions"][0]["candidate"]
    assert candidate["options"] == []
    assert candidate["option_parse"]["status"] == "ambiguous"
    assert candidate["option_parse"]["reasons"] == ["objective_type_not_proven"]
    assert report["withheld_reason_counts"]["objective_type_not_proven"] == 1


def test_missing_gateoverflow_body_is_counted_as_unmatched() -> None:
    output, report = parser.enrich_candidate_artifact(
        _artifact(_row(None)), expected_slot_count=None
    )

    assert output["questions"][0]["candidate"]["option_parse"]["status"] == (
        "unmatched"
    )
    assert report["outcomes"]["parser_unmatched"] == 1
    assert report["withheld_reason_counts"]["exact_gateoverflow_body_missing"] == 1


def test_source_hash_mismatch_and_practice_eligibility_fail_closed() -> None:
    body = "Choose.\nA. One\nB. Two\nC. Three\nD. Four"
    bad_hash = _row(body)
    bad_hash["secondary_snapshots"]["gateoverflow"]["question_body_sha256"] = (
        "0" * 64
    )
    with pytest.raises(parser.OptionStructureError, match="hash mismatch"):
        parser.enrich_candidate_artifact(_artifact(bad_hash), expected_slot_count=None)

    eligible = _row(body)
    eligible["practice_eligible"] = True
    with pytest.raises(parser.OptionStructureError, match="practice-eligible"):
        parser.enrich_candidate_artifact(_artifact(eligible), expected_slot_count=None)


def test_output_safety_rejects_explanation_keys() -> None:
    with pytest.raises(parser.OptionStructureError, match="explanation"):
        parser._assert_output_safety({"explanation_text": "must not leak"})
