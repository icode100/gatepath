from __future__ import annotations

import json
from pathlib import Path

from scripts.verify_pyq_paper_sources import (
    DEFAULT_EVIDENCE,
    METHOD_PRIMARY,
    METHOD_SECONDARY,
    _canonical_json_sha256,
    build_source_verification,
    decide_verification,
)


def _official(*, exact: bool = True, pages: bool = True, items: bool = True) -> dict:
    return {
        "authority": "primary_official",
        "source_domain": "gate2027.iitm.ac.in",
        "byte_identical_to_bound_source": exact,
        "page_structure_agrees": pages,
        "item_structure_agrees": items,
        "qualifies_primary_official_byte_identity": exact and pages and items,
        "qualifies_cross_validated_republication_candidate": False,
    }


def _secondary(domain: str) -> dict:
    return {
        "authority": "secondary_republication",
        "source_domain": domain,
        "byte_identical_to_bound_source": True,
        "page_structure_agrees": True,
        "item_structure_agrees": True,
        "qualifies_primary_official_byte_identity": False,
        "qualifies_cross_validated_republication_candidate": True,
    }


def test_exact_independent_official_artifact_verifies() -> None:
    decision, method, blockers, flags = decide_verification(
        local_integrity_ok=True,
        counts_ok=True,
        evidence=[_official()],
        manifest_authority="secondary_mirror_of_original",
    )
    assert decision == "verified"
    assert method == METHOD_PRIMARY
    assert blockers == []
    assert "independent_official_artifact_byte_identical" in flags


def test_official_url_or_byte_different_artifact_never_verifies() -> None:
    decision, method, blockers, _ = decide_verification(
        local_integrity_ok=True,
        counts_ok=True,
        evidence=[_official(exact=False)],
        manifest_authority="primary_official",
    )
    assert decision == "review"
    assert method == METHOD_PRIMARY
    assert "official_artifact_not_byte_identical_to_bound_source" in blockers
    assert "no_qualifying_official_byte_identity_evidence" in blockers


def test_single_or_same_domain_republication_never_verifies() -> None:
    for evidence in (
        [_secondary("mirror-one.example")],
        [_secondary("mirror-one.example"), _secondary("mirror-one.example")],
    ):
        decision, method, blockers, _ = decide_verification(
            local_integrity_ok=True,
            counts_ok=True,
            evidence=evidence,
            manifest_authority="secondary_republication",
        )
        assert decision == "review"
        assert method == METHOD_SECONDARY
        assert "fewer_than_two_qualifying_independent_republication_domains" in blockers


def test_two_distinct_exact_republication_domains_verify() -> None:
    decision, method, blockers, flags = decide_verification(
        local_integrity_ok=True,
        counts_ok=True,
        evidence=[_secondary("one.example"), _secondary("two.example")],
        manifest_authority="secondary_republication",
    )
    assert decision == "verified"
    assert method == METHOD_SECONDARY
    assert blockers == []
    assert "two_independent_republication_domains_confirmed" in flags


def test_local_integrity_or_count_failure_rejects_even_with_official_evidence() -> None:
    decision, method, blockers, _ = decide_verification(
        local_integrity_ok=False,
        counts_ok=False,
        evidence=[_official()],
        manifest_authority="primary_official",
    )
    assert decision == "rejected"
    assert method == METHOD_PRIMARY
    assert blockers == [
        "bound_local_source_integrity_failed",
        "manifest_canonical_provenance_count_mismatch",
    ]


def test_evidence_catalog_is_staging_only_and_has_no_answer_content() -> None:
    payload = json.loads(DEFAULT_EVIDENCE.read_text(encoding="utf-8"))
    assert payload["production_import_authorized"] is False
    assert payload["database_write_authorized"] is False
    assert payload["promotion_authorized"] is False
    serialized = json.dumps(payload).casefold()
    assert '"answer"' not in serialized
    assert '"solution"' not in serialized
    assert all(row["independently_acquired"] is True for row in payload["entries"])


def test_real_39_paper_source_gate_is_hash_bound_and_fail_closed() -> None:
    artifact, report = build_source_verification()
    assert artifact["invariants"] == {
        "expected_paper_count": 39,
        "actual_paper_count": 39,
        "expected_parent_item_count": 2712,
        "canonical_parent_item_count": 2712,
        "provenance_parent_item_count": 2712,
        "all_papers_have_false_staging_guards": True,
    }
    assert artifact["decision_counts"] == {"review": 33, "verified": 6}
    assert report["summary"]["verified_count"] == 6
    assert report["summary"]["review_count"] == 33
    assert report["summary"]["rejected_count"] == 0
    assert report["summary"]["primary_official_byte_identity_count"] == 6
    assert report["summary"]["cross_validated_republication_count"] == 0
    assert all(
        row["decision"] in {"verified", "review", "rejected"}
        and row["method"] in {METHOD_PRIMARY, METHOD_SECONDARY}
        and not any(row["staging_guard"].values())
        and row["local_source"]["identity_matches_manifest_and_provenance"]
        and row["counts"]["counts_agree"]
        for row in artifact["papers"]
    )
    core = {key: value for key, value in artifact.items() if key != "artifact_sha256"}
    assert artifact["artifact_sha256"] == _canonical_json_sha256(core)


def test_real_builder_is_deterministic() -> None:
    first_artifact, first_report = build_source_verification()
    second_artifact, second_report = build_source_verification()
    assert first_artifact == second_artifact
    assert first_report == second_report


def test_report_contains_exact_per_paper_counts_and_paths() -> None:
    artifact, report = build_source_verification()
    by_id = {row["source_paper_id"]: row for row in artifact["papers"]}
    for summary in report["papers"]:
        row = by_id[summary["source_paper_id"]]
        assert Path(row["local_source"]["absolute_path"]).is_absolute()
        assert len(row["local_source"]["sha256"]) == 64
        assert summary["expected_item_count"] == summary["observed_item_count"]
        assert summary["expected_item_count"] == summary["canonical_item_count"]
        assert summary["expected_item_count"] == summary["provenance_item_count"]
