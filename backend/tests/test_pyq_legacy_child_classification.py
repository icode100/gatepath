from __future__ import annotations

import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = BACKEND_DIR / "scripts" / "pyq_legacy_child_classification.py"
POLICY_PATH = BACKEND_DIR / "data" / "pyq_legacy_child_classifications.json"
AUDIT_PATH = BACKEND_DIR / "data" / "legacy_pyq_subparts_1996_2002.json"
INVENTORY_PATH = BACKEND_DIR / "data" / "question_bank_manifest.json"
SPEC = importlib.util.spec_from_file_location(
    "pyq_legacy_child_classification", SCRIPT_PATH
)
assert SPEC and SPEC.loader
classifier = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = classifier
SPEC.loader.exec_module(classifier)


def _load(path: Path = POLICY_PATH):
    return classifier.load_legacy_child_classification_policy(
        path,
        subpart_audit_path=AUDIT_PATH,
        inventory_path=INVENTORY_PATH,
    )


def test_all_272_materialized_children_have_checksum_bound_decisions() -> None:
    policy = _load()

    assert len(policy.decisions) == classifier.EXPECTED_CHILDREN == 272
    assert policy.outcome_counts == {
        "mapped": 270,
        "out_of_syllabus": 2,
        "review": 0,
    }
    comparisons = Counter(row.parent_comparison for row in policy.decisions.values())
    assert sum(comparisons.values()) == 272
    assert comparisons["differs_from_parent"] > 0
    assert comparisons["parent_unresolved"] > 0
    assert all(len(row.evidence_sha256) == 64 for row in policy.decisions.values())
    assert all(row.evidence_excerpt for row in policy.decisions.values())


@pytest.mark.parametrize(
    ("key", "decision", "course", "topic", "comparison"),
    [
        (
            ("gate-cs-1997", 55, "11(a)"),
            "map",
            "TOC",
            "context-free-grammars",
            "differs_from_parent",
        ),
        (
            ("gate-cs-1998", 60, "7(b)"),
            "map",
            "OS",
            "memory-and-virtual-memory",
            "differs_from_parent",
        ),
        (
            ("gate-cs-2001", 69, "21(a)"),
            "map",
            "DBMS",
            "relational-model",
            "parent_unresolved",
        ),
        (
            ("gate-cs-2002", 53, "5(a)"),
            "map",
            "EM",
            "linear-algebra",
            "parent_unresolved",
        ),
        (
            ("gate-cs-2000", 61, "14(a)"),
            "out_of_syllabus",
            None,
            None,
            "same_as_parent",
        ),
    ],
)
def test_independent_child_evidence_can_differ_from_parent(
    key: tuple[str, int, str],
    decision: str,
    course: str | None,
    topic: str | None,
    comparison: str,
) -> None:
    row = _load().decisions[key]
    assert (row.decision, row.course, row.topic) == (decision, course, topic)
    assert row.parent_comparison == comparison


def test_policy_fails_closed_when_child_evidence_hash_is_mutated(tmp_path: Path) -> None:
    raw = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    raw["child_decisions"][0]["evidence_sha256"] = "0" * 64
    path = tmp_path / "mutated-evidence.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(classifier.LegacyChildClassificationError, match="evidence binding drifted"):
        _load(path)


def test_policy_rejects_topic_outside_canonical_inventory(tmp_path: Path) -> None:
    raw = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    row = next(item for item in raw["child_decisions"] if item["decision"] == "map")
    row["canonical_topic"] = "invented-topic"
    path = tmp_path / "mutated-topic.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(classifier.LegacyChildClassificationError, match="absent from canonical inventory"):
        _load(path)
