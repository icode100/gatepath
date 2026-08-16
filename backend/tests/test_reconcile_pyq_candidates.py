from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = BACKEND_DIR / "scripts" / "reconcile_pyq_candidates.py"
SPEC = importlib.util.spec_from_file_location("reconcile_pyq_candidates", SCRIPT_PATH)
assert SPEC and SPEC.loader
reconciler = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = reconciler
SPEC.loader.exec_module(reconciler)


def _modern_papers() -> list[dict[str, object]]:
    return [
        {
            "id": "gate-cs-2014-session-1",
            "year": 2014,
            "session_label": "1",
        },
        {
            "id": "gate-cs-2014-session-2",
            "year": 2014,
            "session_label": "2",
        },
        {
            "id": "gate-cs-2014-session-3",
            "year": 2014,
            "session_label": "3",
        },
    ]


def test_session_label_and_nested_slug_resolve_without_guessing() -> None:
    papers = _modern_papers()
    by_year = {2014: papers}
    row = {"year": 2014, "session": "set2", "set_number": 2}

    assert reconciler._reference_paper_id(row, by_year) == "gate-cs-2014-session-2"
    assert (
        reconciler._nested_examside_paper_id(
            {"paper": {"slug": "gate-cse-2014-set-3", "year": 2014, "session": "set3"}},
            papers,
        )
        == "gate-cs-2014-session-3"
    )


def test_explicit_ordinal_must_agree_with_section_and_item_label() -> None:
    paper_id = "gate-cs-2024-set-1"
    slots = {(paper_id, ordinal): {} for ordinal in range(1, 66)}
    years = {paper_id: 2024}
    agreeing = {
        "source_paper_id": paper_id,
        "ordinal": 11,
        "section_code": "CS",
        "item_label": "1",
    }
    key, reasons, present = reconciler._strict_explicit_secondary_key(
        agreeing,
        nested_paper_id=paper_id,
        slots=slots,
        labels_to_ordinals={paper_id: {}},
        paper_years=years,
    )
    assert present is True
    assert key == (paper_id, 11)
    assert reasons == []

    conflict = dict(agreeing, ordinal=12)
    key, reasons, present = reconciler._strict_explicit_secondary_key(
        conflict,
        nested_paper_id=paper_id,
        slots=slots,
        labels_to_ordinals={paper_id: {}},
        paper_years=years,
    )
    assert present is True
    assert key is None
    assert reasons == ["explicit_ordinal_disagrees_with_section_item_label"]


def test_normalized_text_join_is_unique_or_withheld() -> None:
    paper_id = "gate-cs-2025-set-1"
    query = "Which scheduling policy minimizes the average waiting time for this workload?"
    unique = reconciler._candidate_text_matches(
        query,
        {
            (paper_id, 11): query + " A. FCFS B. SJF C. RR D. Priority",
            (paper_id, 12): "A completely different and sufficiently long question statement.",
        },
        paper_id=paper_id,
    )
    assert [match.key for match in unique] == [(paper_id, 11)]
    assert unique[0].method == "normalized_question_prefix"

    ambiguous = reconciler._candidate_text_matches(
        query,
        {
            (paper_id, 11): query + " A. FCFS",
            (paper_id, 12): query + " A. SJF",
        },
        paper_id=paper_id,
    )
    assert {match.key for match in ambiguous} == {(paper_id, 11), (paper_id, 12)}


def test_examside_snapshot_never_copies_explanations_or_fetches_images() -> None:
    row = {
        "question": {
            "source_id": "q1",
            "url": "https://questions.example/q1",
            "question_text": (
                '<p>Inspect this graph.</p><img src="https://cdn.example/g.png" '
                'alt="graph">'
            ),
            "direction_text": None,
            "comprehension_text": None,
            "options": [{"identifier": "A", "content": "<b>One</b>"}],
            "correct_options": ["A"],
            "numerical_answer": None,
            "question_type": "mcq",
            "marks": 1,
            "subject": "algorithms",
            "chapter": "complexity-analysis",
            "has_explanation": True,
            "explanation_sha256": "f" * 64,
        },
        "provenance": {"question_raw_sha256": "a" * 64},
    }
    snapshot = reconciler._examside_snapshot(
        {"row": row, "match_method": "normalized_exact"}
    )

    assert snapshot["course_candidate"] == "ALG"
    assert snapshot["remote_asset_fetch_allowed"] is False
    assert snapshot["rendering_allowed"] is False
    assert snapshot["remote_assets"] == [
        {
            "field": "question_html",
            "url_sha256": reconciler._sha256_text("https://cdn.example/g.png"),
            "scheme": "https",
            "host": "cdn.example",
            "retrieval_status": "not_fetched",
            "trusted_for_rendering": False,
            "url": "https://cdn.example/g.png",
            "alt": "graph",
        }
    ]
    assert "explanation" not in repr(snapshot).casefold()


def test_topic_candidates_are_checked_against_gatepath_inventory() -> None:
    inventory = {"ALG": {"complexity-analysis"}, "PDS": {"programming-in-c"}}
    assert reconciler._inventory_topic_candidate(
        course="ALG", topic="complexity-analysis", inventory=inventory
    ) == ("complexity-analysis", None)
    assert reconciler._inventory_topic_candidate(
        course="PDS", topic="complexity-analysis", inventory=inventory
    ) == (None, "topic_candidate_not_in_canonical_inventory")
    assert reconciler._inventory_topic_candidate(
        course="SE", topic="testing", inventory=inventory
    ) == (None, "course_candidate_not_in_canonical_inventory")


def test_topic_policy_withholds_broad_labels_but_keeps_the_agreeing_course() -> None:
    decision = reconciler.topic_classification.TopicDecision(
        decision="manual_review",
        source_course="CN",
        source_topic="sliding-window",
        source_course_mapping_agrees=True,
        canonical_course=None,
        canonical_topic=None,
        reason_code="layer_ambiguous_network_label",
        reason="Needs question-level evidence.",
    )
    policy = reconciler.topic_classification.TopicClassificationPolicy(
        schema_version="1.0",
        policy_version="test",
        source_sha256="a" * 64,
        decisions={decision.signature: decision},
        overrides={},
        observed_record_count=1,
        observed_signature_count=1,
    )

    result = reconciler._policy_classification(
        key=("gate-cs-2025-set-1", 11),
        canonical={"classification_status": "review_required"},
        go_snapshot={
            "source_course_candidate": "CN",
            "source_topic_candidate": "sliding-window",
            "source_course_mapping_agrees": True,
        },
        exam_snapshot=None,
        inventory={"CN": {"data-link-layer", "transport-layer"}},
        policy=policy,
    )

    assert result["course"] == "CN"
    assert result["topic"] is None
    assert result["reasons"] == [
        "gateoverflow_topic_policy:layer_ambiguous_network_label"
    ]


def test_conflicting_verified_and_alias_claims_are_withheld_for_review() -> None:
    decision = reconciler.topic_classification.TopicDecision(
        decision="map",
        source_course="ALG",
        source_topic="recursion",
        source_course_mapping_agrees=True,
        canonical_course="ALG",
        canonical_topic="complexity-analysis",
        reason_code="unambiguous_source_topic_alias",
        reason="Complexity label.",
    )
    policy = reconciler.topic_classification.TopicClassificationPolicy(
        schema_version="1.0",
        policy_version="test",
        source_sha256="a" * 64,
        decisions={decision.signature: decision},
        overrides={},
        observed_record_count=1,
        observed_signature_count=1,
    )

    result = reconciler._policy_classification(
        key=("gate-cs-2025-set-1", 11),
        canonical={
            "classification_status": "verified",
            "subject_code": "PDS",
            "topic_slug": "recursion",
        },
        go_snapshot={
            "source_course_candidate": "ALG",
            "source_topic_candidate": "recursion",
            "source_course_mapping_agrees": True,
        },
        exam_snapshot=None,
        inventory={"ALG": {"complexity-analysis"}, "PDS": {"recursion"}},
        policy=policy,
    )

    assert result["course"] is None
    assert result["topic"] is None
    assert result["conflict"] is True
    assert result["unresolved_conflict"] is True
    assert result["reasons"] == ["classification_candidates_disagree"]


def test_promotion_evidence_requires_source_tuple_and_answer_proof() -> None:
    official = reconciler.evaluate_promotion_evidence(
        source_page=12,
        source_reference="paper.pdf",
        original_content_sha256="a" * 64,
        answer_status="official",
        official_key_sha256=None,
        community_answer_sources=[],
    )
    assert official["source_evidence"]["requirements_met"] is True
    assert official["answer_evidence"]["requirements_met"] is False
    assert "official_answer_key_hash_missing" in official["blockers"]
    assert official["automatic_promotion_allowed"] is False

    community = reconciler.evaluate_promotion_evidence(
        source_page=12,
        source_reference="paper.pdf",
        original_content_sha256="a" * 64,
        answer_status="community_corroborated_candidate",
        official_key_sha256=None,
        community_answer_sources=["gateoverflow", "examside"],
        is_2013_canonical=True,
    )
    assert community["answer_evidence"]["requirements_met"] is True
    assert "2013_booklet_occurrence_bijection_missing" in community["blockers"]
    assert community["practice_eligible"] is False


def test_manifest_rejects_answer_key_that_visibly_belongs_to_another_year() -> None:
    with pytest.raises(
        reconciler.CandidateReconciliationError,
        match="answer-key filename visibly belongs to 2025",
    ):
        reconciler._validate_manifest_key_identity(
            [
                {
                    "id": "gate-cs-2022",
                    "year": 2022,
                    "answer_key_local_file": (
                        "tmp/pyq/sources/gate-cs-2025-session-1-official-key.pdf"
                    ),
                }
            ]
        )

    reconciler._validate_manifest_key_identity(
        [
            {
                "id": "gate-cs-2025-set-1",
                "year": 2025,
                "answer_key_local_file": (
                    "tmp/pyq/sources/gate-cs-2025-session-1-official-key.pdf"
                ),
                "answer_key_url": (
                    "https://gate2025.iitr.ac.in/doc/2025/2025_Key/CS1_Keys.pdf"
                ),
            }
        ]
    )


def _empty_full_inventory() -> tuple[dict, dict]:
    papers = []
    questions = []
    manifest_papers = []
    for paper_id, year, session, expected in reconciler.canonical_builder.EXPECTED_PAPER_LAYOUT:
        papers.append(
            {
                "id": paper_id,
                "year": year,
                "session_label": session,
                "expected_item_count": expected,
            }
        )
        manifest_papers.append(
            {
                "id": paper_id,
                "year": year,
                "session": session,
                "expected_item_count": expected,
                "local_file": f"{paper_id}.pdf",
                "local_sha256": "b" * 64,
            }
        )
        for ordinal in range(1, expected + 1):
            questions.append(
                {
                    "source_paper_id": paper_id,
                    "item_label": str(ordinal),
                    "ordinal": ordinal,
                    "practice_eligible": False,
                    "question_md": None,
                    "options": [],
                    "accepted_answers": None,
                    "item_type": "unknown",
                    "subject_code": None,
                    "topic_slug": None,
                    "marks": None,
                    "source_page": None,
                    "answer_status": "unresolved",
                }
            )
    return {"papers": papers, "questions": questions}, {"papers": manifest_papers}


def test_audit_always_contains_all_39_papers_and_all_2712_slots() -> None:
    canonical, manifest = _empty_full_inventory()
    artifact, report = reconciler.build_candidate_artifact(
        canonical_artifact=canonical,
        source_manifest=manifest,
        canonical_topic_inventory={"ALG": {"complexity-analysis"}},
        gateoverflow_rows=[],
        gateoverflow_blocks={},
        examside_rows=[],
        page_audit={"all_page_hashes_verified": True},
        source_file_audit=None,
    )

    assert artifact["paper_count"] == 39
    assert artifact["slot_count"] == 2712
    assert len(report["reconciliation"]["papers"]) == 39
    assert report["reconciliation"]["slots"]["unmatched"] == 2712
    assert all(row["practice_eligible"] is False for row in artifact["questions"])
    paper_2013 = next(
        row
        for row in report["reconciliation"]["papers"]
        if row["paper_id"] == "gate-cs-2013"
    )
    assert paper_2013["audit_blockers"] == [
        "2013_booklet_occurrence_bijection_missing"
    ]
    reconciler._assert_output_safety(artifact)


def test_verified_2013_booklet_bijection_clears_the_obsolete_blocker() -> None:
    canonical, manifest = _empty_full_inventory()
    occurrence_map = json.loads(
        (
            BACKEND_DIR / "data" / "gate_cs_2013_booklet_occurrences.json"
        ).read_text(encoding="utf-8")
    )
    slots_2013 = {
        int(item["canonical_ordinal"]): item for item in occurrence_map["items"]
    }
    for row in canonical["questions"]:
        if row["source_paper_id"] != "gate-cs-2013":
            continue
        mapped = slots_2013[int(row["ordinal"])]
        row["source_references"] = [
            {
                "kind": "booklet_occurrence",
                "url": None,
                "sha256": occurrence_map["source_pdf_sha256"],
                "note": json.dumps(
                    occurrence,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            }
            for occurrence in mapped["occurrences"]
        ]
        row["source_page"] = next(
            occurrence["source_page"]
            for occurrence in mapped["occurrences"]
            if occurrence["booklet_code"] == "A"
        )

    artifact, report = reconciler.build_candidate_artifact(
        canonical_artifact=canonical,
        source_manifest=manifest,
        canonical_topic_inventory={"ALG": {"complexity-analysis"}},
        gateoverflow_rows=[],
        gateoverflow_blocks={},
        examside_rows=[],
        page_audit={"all_page_hashes_verified": True},
        source_file_audit=None,
    )

    reconciliation = report["reconciliation"]
    assert reconciliation["booklet_occurrence_bijection_2013_verified"] is True
    paper_2013 = next(
        paper
        for paper in reconciliation["papers"]
        if paper["paper_id"] == "gate-cs-2013"
    )
    assert paper_2013["audit_blockers"] == []
    assert "2013_booklet_occurrence_bijection_missing" not in {
        blocker["code"] for blocker in report["known_global_blockers"]
    }
    assert all(
        "2013_booklet_occurrence_bijection_missing"
        not in row["promotion_review"]["blockers"]
        for row in artifact["questions"]
        if row["source_paper_id"] == "gate-cs-2013"
    )


def test_tampered_2013_occurrence_map_remains_blocked() -> None:
    canonical, manifest = _empty_full_inventory()
    rows_2013 = [
        row
        for row in canonical["questions"]
        if row["source_paper_id"] == "gate-cs-2013"
    ]
    for row in rows_2013:
        ordinal = int(row["ordinal"])
        row["source_page"] = 3
        row["source_references"] = [
            {
                "kind": "booklet_occurrence",
                "sha256": "a" * 64,
                "note": json.dumps(
                    {
                        "booklet_code": code,
                        "item_label": str(ordinal),
                        "source_page": 3,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            }
            for code in ("A", "B", "C", "D")
        ]
    rows_2013[-1]["source_references"][-1]["note"] = json.dumps(
        {"booklet_code": "D", "item_label": "64", "source_page": 3},
        sort_keys=True,
        separators=(",", ":"),
    )

    _, report = reconciler.build_candidate_artifact(
        canonical_artifact=canonical,
        source_manifest=manifest,
        canonical_topic_inventory={"ALG": {"complexity-analysis"}},
        gateoverflow_rows=[],
        gateoverflow_blocks={},
        examside_rows=[],
        page_audit={"all_page_hashes_verified": True},
        source_file_audit=None,
    )

    assert (
        report["reconciliation"]["booklet_occurrence_bijection_2013_verified"]
        is False
    )
    assert report["reconciliation"]["blocker_counts"][
        "2013_booklet_occurrence_bijection_missing"
    ] == 65


def test_output_safety_rejects_explanation_metadata_and_eligibility() -> None:
    with pytest.raises(reconciler.CandidateReconciliationError):
        reconciler._assert_output_safety({"explanation_sha256": "a" * 64})
    with pytest.raises(reconciler.CandidateReconciliationError):
        reconciler._assert_output_safety({"practice_eligible": True})
