from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "validate_legacy_pyq_subparts.py"
)
SPEC = importlib.util.spec_from_file_location("legacy_pyq_subparts_validator", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
validator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = validator
SPEC.loader.exec_module(validator)


def _load_audit() -> dict[str, object]:
    return json.loads(validator.DEFAULT_AUDIT.read_text(encoding="utf-8"))


def _write_rehashed(path: Path, payload: dict[str, object]) -> None:
    core = {key: value for key, value in payload.items() if key != "artifact_sha256"}
    payload["artifact_sha256"] = validator._canonical_sha256(core)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_complete_legacy_audit_reproduces_all_counts() -> None:
    report = validator.validate_audit()

    assert report["summary"] == {
        "paper_count": 7,
        "descriptive_parent_count": 148,
        "canonical_slot_count": 502,
        "final_split_database_record_count": 663,
        "corpus_delta": 161,
        "residual_review_row_count": 0,
        "split_parent_count": 111,
        "materialized_child_record_count": 272,
        "expansion_ready_child_count": 272,
    }
    assert {
        row["paper_id"]: row["final_split_database_record_count"]
        for row in report["papers"]
    } == {
        "gate-cs-1996": 95,
        "gate-cs-1997": 85,
        "gate-cs-1998": 100,
        "gate-cs-1999": 87,
        "gate-cs-2000": 96,
        "gate-cs-2001": 99,
        "gate-cs-2002": 101,
    }
    audit = _load_audit()
    children = [
        child
        for paper in audit["papers"]
        for decision in paper["decisions"]
        for child in decision["child_records"]
    ]
    assert len(children) == 272
    assert all(child["materialization_status"] == "exact" for child in children)
    assert all(child["review_flags"] == [] for child in children)
    assert all(
        child["marks"] is not None
        or child["marks_status"]
        in {
            "not_determinable_from_bounded_child_span",
            "visible_only_as_parent_aggregate",
        }
        for child in children
    )


def test_cross_page_footer_removal_preserves_prompts_and_shared_context() -> None:
    audit = _load_audit()

    def decision(paper_id: str, item_label: str) -> dict[str, object]:
        paper = next(row for row in audit["papers"] if row["paper_id"] == paper_id)
        return next(
            row for row in paper["decisions"] if row["parent_item_label"] == item_label
        )

    prompt_expectations = {
        ("gate-cs-1996", "24", "24(a)"): "Q1 Q2 Q3 State",
        ("gate-cs-1998", "7", "7(a)"): "Express the following in SQL",
        ("gate-cs-1998", "14", "14(a)"): "What is L(G1)?",
        ("gate-cs-1999", "3", "3(a)"): "Mr. X offers the following proof",
        ("gate-cs-1999", "20", "20(b)"): "both the processes are sleeping",
        ("gate-cs-2000", "20", "20(a)"): "Writer ()",
    }
    for (paper_id, parent_label, child_label), expected in prompt_expectations.items():
        row = decision(paper_id, parent_label)
        child = next(
            child for child in row["child_records"] if child["child_item_label"] == child_label
        )
        assert expected in child["prompt_text"]

    context_expectations = {
        ("gate-cs-1996", "19"): "writeln('point 3: ', b)",
        ("gate-cs-1996", "26"): "260 Mbyte 1.0",
        ("gate-cs-2000", "11"): "S3: INC A",
        ("gate-cs-2000", "18"): "begin\nx:=5;",
        ("gate-cs-2001", "11"): "The desired output",
    }
    for (paper_id, parent_label), expected in context_expectations.items():
        row = decision(paper_id, parent_label)
        shared = row["child_records"][0]["shared_context"]["additional_shared_text"]
        assert expected in shared

    avl = decision("gate-cs-1998", "21")
    avl_b = next(child for child in avl["child_records"] if child["child_item_label"] == "21(b)")
    assert not avl_b["prompt_text"].rstrip().endswith("(c)")


def test_duplicate_or_missing_parent_fails_closed(tmp_path: Path) -> None:
    payload = _load_audit()
    mutated = copy.deepcopy(payload)
    decisions = mutated["papers"][0]["decisions"]
    decisions[-1] = copy.deepcopy(decisions[0])
    path = tmp_path / "duplicate.json"
    _write_rehashed(path, mutated)

    with pytest.raises(validator.LegacySubpartAuditError, match="Duplicate audited parent"):
        validator.validate_audit(audit_path=path)


def test_child_identity_and_input_binding_are_checksum_guarded(tmp_path: Path) -> None:
    payload = _load_audit()
    mutated = copy.deepcopy(payload)
    split = next(
        row
        for paper in mutated["papers"]
        for row in paper["decisions"]
        if row["decision"] == "split"
    )
    split["child_labels"][0] = "unrelated(a)"
    path = tmp_path / "bad-child.json"
    _write_rehashed(path, mutated)
    with pytest.raises(validator.LegacySubpartAuditError, match="does not name its parent"):
        validator.validate_audit(audit_path=path)

    mutated = copy.deepcopy(payload)
    mutated["input_bindings"]["canonical_archive_sha256"] = "0" * 64
    path = tmp_path / "bad-binding.json"
    _write_rehashed(path, mutated)
    with pytest.raises(validator.LegacySubpartAuditError, match="Input binding mismatch"):
        validator.validate_audit(audit_path=path)


def test_secondary_resolution_requires_complete_checksum_bound_evidence(
    tmp_path: Path,
) -> None:
    payload = _load_audit()
    mutated = copy.deepcopy(payload)
    resolved = next(
        row
        for paper in mutated["papers"]
        for row in paper["decisions"]
        if row.get("primary_source_defect")
    )
    resolved["corroborating_sources"] = []
    path = tmp_path / "missing-secondary.json"
    _write_rehashed(path, mutated)

    with pytest.raises(
        validator.LegacySubpartAuditError,
        match="requires corroborating evidence",
    ):
        validator.validate_audit(audit_path=path)


def test_staging_audit_cannot_enable_import_or_practice_materialization(
    tmp_path: Path,
) -> None:
    payload = _load_audit()
    mutated = copy.deepcopy(payload)
    mutated["production_import_authorized"] = True
    path = tmp_path / "import-authorized.json"
    _write_rehashed(path, mutated)
    with pytest.raises(validator.LegacySubpartAuditError, match="production import"):
        validator.validate_audit(audit_path=path)

    mutated = copy.deepcopy(payload)
    mutated["papers"][0]["decisions"][0]["practice_eligible"] = False
    path = tmp_path / "practice-field.json"
    _write_rehashed(path, mutated)
    with pytest.raises(validator.LegacySubpartAuditError, match="Forbidden field"):
        validator.validate_audit(audit_path=path)
