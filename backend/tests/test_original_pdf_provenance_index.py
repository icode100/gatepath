from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import SimpleNamespace


BACKEND_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = BACKEND_DIR / "scripts" / "index_original_pdf_provenance.py"
SPEC = importlib.util.spec_from_file_location("index_original_pdf_provenance", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _canonical_items() -> list[dict]:
    return [
        {
            "ordinal": ordinal,
            "item_label": (
                f"GA-{ordinal}" if ordinal <= 10 else f"CS-{ordinal - 10}"
            ),
        }
        for ordinal in range(1, 66)
    ]


def _page(number: int, raw: str) -> object:
    normalized = MODULE._normalize_text(raw)
    return MODULE.PageText(
        page=number,
        raw=raw,
        normalized=normalized,
        normalized_sha256=MODULE._sha256_text(normalized) if normalized else None,
    )


def test_source_targets_preserve_2017_printed_order_and_legacy_mapping() -> None:
    targets = MODULE._source_targets(
        {"id": "gate-cs-2017-session-1", "year": 2017},
        _canonical_items(),
    )

    assert [target.source_label for target in targets] == [
        str(number) for number in range(1, 66)
    ]
    assert targets[0].item_label == "CS-1"
    assert targets[54].item_label == "CS-55"
    assert targets[55].item_label == "GA-1"
    assert targets[64].item_label == "GA-10"


def test_recent_global_numbering_and_2021_section_local_numbering_are_explicit() -> None:
    items = _canonical_items()
    targets_2021 = MODULE._source_targets({"year": 2021}, items)
    targets_2022 = MODULE._source_targets({"year": 2022}, items)

    assert [target.source_label for target in targets_2021[:12]] == [
        *[str(number) for number in range(1, 11)],
        "1",
        "2",
    ]
    assert [target.source_label for target in targets_2022[:12]] == [
        str(number) for number in range(1, 13)
    ]


def test_section_restart_selects_first_exact_monotonic_run() -> None:
    targets = [
        MODULE.Target(1, "GA-1", "1"),
        MODULE.Target(2, "GA-2", "2"),
        MODULE.Target(3, "CS-1", "1"),
        MODULE.Target(4, "CS-2", "2"),
    ]
    pages = [
        _page(1, "Q.1 General one\nQ.2 General two\n"),
        _page(2, "Q.1 Technical one\nQ.2 Technical two\n"),
    ]
    candidates = MODULE._candidate_markers(
        pages, targets, year=2018, page_range=(1, 2)
    )
    selected, ambiguous = MODULE._select_monotonic_markers(candidates, targets)

    assert ambiguous == set()
    assert [(selected[index].page, selected[index].source_label) for index in range(4)] == [
        (1, "1"),
        (1, "2"),
        (2, "1"),
        (2, "2"),
    ]


def test_instruction_ranges_and_numbered_instructions_are_not_question_markers() -> None:
    targets = [MODULE.Target(1, "1", "1"), MODULE.Target(12, "12", "12")]
    page = _page(
        1,
        "Q. 1 - Q. 5 carry one mark each.\n"
        "1. Do not open the seal before instructed.\n"
        "12. Before the start of the examination, write your name.\n"
        "Q.1 Actual first question?\n"
        "Q.12 Actual twelfth question?\n",
    )

    candidates = MODULE._candidate_markers(
        [page], targets, year=2012, page_range=(1, 1)
    )

    assert len(candidates[0]) == 1
    assert candidates[0][0].matched_text == "Q.1"
    assert len(candidates[1]) == 1
    assert candidates[1][0].matched_text == "Q.12"


def test_2005_compound_labels_accept_parenthesized_parts_only() -> None:
    pattern_a = MODULE._marker_pattern("81a", year=2005)
    pattern_b = MODULE._marker_pattern("81b", year=2005)

    assert pattern_a.search("81 (a) First linked item")
    assert pattern_b.search("81(b) Second linked item")
    assert not pattern_a.search("81. Ordinary parent item")


def test_normalized_block_hash_is_deterministic_without_serializing_source_text() -> None:
    pages = {
        1: _page(1, "Q.1   Alpha\nline\nQ.2 Beta\n"),
    }
    first = MODULE.Marker(0, "1", 1, 0, 3, "Q.1")
    second_start = pages[1].raw.index("Q.2")
    second = MODULE.Marker(1, "2", 1, second_start, second_start + 3, "Q.2")

    block, touched, boundary = MODULE._block_for_marker(first, second, pages, 1)

    assert block == "Q.1 Alpha\nline"
    assert touched == [1]
    assert boundary["end_offset"] == second_start
    assert re.fullmatch(r"[0-9a-f]{64}", MODULE._sha256_text(block))


def test_verified_bundle_ranges_do_not_include_answer_keys_or_other_sessions() -> None:
    pages = [_page(number, "") for number in range(1, 61)]

    assert MODULE._question_page_range(
        {"id": "gate-cs-2016-session-1"},
        pages,
        (1, 45),
        booklet_a_range=(2, 15),
    )[0] == (1, 20)
    assert MODULE._question_page_range(
        {"id": "gate-cs-2016-session-2"},
        pages,
        (1, 45),
        booklet_a_range=(2, 15),
    )[0] == (23, 43)
    assert MODULE._question_page_range(
        {"id": "gate-cs-2013"},
        pages,
        (1, 60),
        booklet_a_range=(2, 15),
    )[0] == (2, 15)
    assert MODULE._question_page_range(
        {"id": "gate-cs-2021-session-1"},
        pages,
        (1, 43),
        booklet_a_range=(2, 15),
    )[0] == (1, 40)


def test_reviewed_ocr_page_fallback_requires_exact_source_hash_and_copies_no_text() -> None:
    builder = SimpleNamespace(
        CONSOLIDATED_PAPER_IDS={"CS-2019": "gate-cs-2019"},
        _consolidated_ordinal=lambda row: int(row["source_question_number"]),
    )
    payload = {
        "questions": [
            {
                "source_paper": "CS-2019",
                "source_question_number": 1,
                "source_page": 7,
                "extraction_method": "rapidocr_onnxruntime+visual_review",
                "question": "must not be copied",
                "explanation": "must not be copied",
            }
        ]
    }
    exact_hash = MODULE.REVIEWED_OCR_LOCATOR_SOURCE_SHA256["CS-2019"]

    assert MODULE._reviewed_ocr_page_locators(
        payload,
        paper_id="gate-cs-2019",
        source_sha256="0" * 64,
        builder=builder,
    ) == {}
    locators = MODULE._reviewed_ocr_page_locators(
        payload,
        paper_id="gate-cs-2019",
        source_sha256=exact_hash,
        builder=builder,
    )
    record = {
        "source_paper_id": "gate-cs-2019",
        "canonical_ordinal": 1,
        "locator_status": "unmatched_marker",
        "source_pages": [],
        "boundary": None,
        "text_block_sha256": None,
        "normalized_character_count": 0,
    }

    assert MODULE._apply_reviewed_ocr_page_locators([record], locators, (1, 16)) == 1
    assert record["source_pages"] == [7]
    assert record["locator_status"] == "hash_matched_reviewed_ocr_page"
    assert "must not be copied" not in str(record)


def test_indexer_is_staging_only_and_has_no_database_imports() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert 'record["practice_eligible"] = False' in source
    assert 'record["production_import_authorized"] = False' in source
    assert "sqlalchemy" not in source.casefold()
    assert "app.database" not in source.casefold()
