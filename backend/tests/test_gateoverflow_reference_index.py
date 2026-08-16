from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "index_gateoverflow_reference.py"
)
SPEC = importlib.util.spec_from_file_location(
    "index_gateoverflow_reference",
    SCRIPT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_parse_volume_joins_heading_book_id_chapter_topic_and_answer() -> None:
    pages = [
        """Table of Contents
1 Computer Networks (2)

1.1.1
1.1.2
Transport Layer: GATE CSE 2021 | Set 2 | Question: 10
Which service is provided by TCP?
A
.
Reliable delivery
B
.
Unreliable delivery
gatecse-2021-set2
computer-networks
transport-layer
one-mark
Answer key
☟
Data Link Layer: GATE CSE 1996 | Question: 2.4
Which field detects an error?
gate1996
computer-networks
data-link-layer
normal
Answer key
☟

Answer Keys
1.1.1
A
1.1.2
C
"""
    ]

    questions, report = MODULE.parse_volume("synthetic", pages)

    assert len(questions) == 2
    first = questions[0]
    assert first["book_id"] == "1.1.1"
    assert first["year"] == 2021
    assert first["session"] == "set2"
    assert first["item_label"] == "10"
    assert first["chapter_title"] == "Computer Networks"
    assert first["course_code"] == "CN"
    assert first["topic_slug"] == "transport-layer"
    assert first["answer"] == "A"
    assert first["answer_join_status"] == "joined"
    assert questions[1]["session"] == "main"
    assert questions[1]["answer"] == "C"
    assert report["answer_joined_count"] == 2


def test_answer_join_withholds_conflicting_values() -> None:
    pages = [
        """Table of Contents
1 Algorithms (1)

1.1.1
Sorting: GATE CSE 2018 | Question: 1
Pick the stable sort.
gatecse-2018
algorithms
sorting
Answer key
☟

Answer Keys
1.1.1
A
1.1.1
B
"""
    ]

    questions, report = MODULE.parse_volume("synthetic", pages)

    assert questions[0]["answer"] is None
    assert questions[0]["answer_join_status"] == "conflict"
    assert report["answer_conflicts"] == {"1.1.1": ["A", "B"]}


def test_page_order_alignment_accounts_for_non_cse_cards_and_ga_section() -> None:
    pages = [
        """Table of Contents
1 General Aptitude: Quantitative Aptitude (3)

1.1.1
1.1.2
1.1.3
Ratio: GATE CSE 2024 | Set 1 | GA | Question: 1
Choose the ratio.
gatecse-2024-set1
general-aptitude
quantitative-aptitude
Answer key
☟
Ratio: GATE IT 2004 | Question: 2
Choose another ratio.
gateit-2004
general-aptitude
quantitative-aptitude
Answer key
☟
GATE CSE 2024 | Set 1 | GA | Question: 2
Choose the number.
gatecse-2024-set1
general-aptitude
quantitative-aptitude
Answer key
☟

Answer Keys
1.1.1
A
1.1.2
B
1.1.3
C
"""
    ]

    questions, report = MODULE.parse_volume("synthetic", pages)

    assert [item["book_id"] for item in questions] == ["1.1.1", "1.1.3"]
    assert [item["answer"] for item in questions] == ["A", "C"]
    assert all(item["section_code"] == "GA" for item in questions)
    assert questions[1]["topic_label"] == "General Aptitude"
    assert report["page_alignment"]["exact_alignment_page_count"] == 1


def test_coverage_keeps_unasserted_old_formats_and_asserts_known_sessions() -> None:
    old_question = {
            "year": 1996,
            "session": "main",
            "item_label": "1.1",
            "book_id": "1.1.1",
            "answer_join_status": "joined",
            "course_code": "CN",
            "topic_slug": "transport-layer",
        }
    recent_questions = [
        {
            "year": 2021,
            "session": "set2",
            "item_label": str(index),
            "book_id": f"1.1.{index}",
            "answer_join_status": "joined",
            "course_code": "CN",
            "topic_slug": "transport-layer",
        }
        for index in range(1, 66)
    ]
    questions = [old_question, *recent_questions]

    report = MODULE.build_coverage(questions, [], [])
    by_year = {item["year"]: item for item in report["years"]}

    old_session = by_year[1996]["sessions"][0]
    assert old_session["expected_question_count"] is None
    assert old_session["count_matches_expected"] is None
    set2 = next(
        item for item in by_year[2021]["sessions"] if item["session"] == "set2"
    )
    assert set2["question_heading_count"] == 65
    assert set2["expected_question_count"] == 65
    assert set2["count_matches_expected"] is True
    # The known but absent Set 1 remains visible in the audit.
    set1 = next(
        item for item in by_year[2021]["sessions"] if item["session"] == "set1"
    )
    assert set1["question_heading_count"] == 0
    assert set1["count_matches_expected"] is False
