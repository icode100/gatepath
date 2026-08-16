from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = BACKEND_DIR.parent
SCRIPT_PATH = BACKEND_DIR / "scripts" / "build_pyq_classification_review_overrides.py"
ARTIFACT_PATH = BACKEND_DIR / "data" / "pyq_classification_review_overrides.json"
SPEC = importlib.util.spec_from_file_location(
    "build_pyq_classification_review_overrides", SCRIPT_PATH
)
assert SPEC and SPEC.loader
builder = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = builder
SPEC.loader.exec_module(builder)


def _load_artifact() -> dict:
    return json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))


def test_real_override_artifact_is_deterministic_complete_and_staging_only() -> None:
    # The authoritative final release has already applied 67 decisions and
    # therefore contains only the 15 intentionally unresolved rows. Rebuilding
    # must use the immutable pre-override base artifact, not this final output.
    final_release_path = REPO_DIR / "tmp" / "pyq" / "build" / "final_pyq_release.json"
    final_release = json.loads(final_release_path.read_text(encoding="utf-8"))
    assert sum(
        row.get("classification_status") == "review_required"
        for row in final_release["questions"]
    ) == 15
    committed = _load_artifact()
    rebuilt = builder.build_overrides()
    builder.validate_artifact(committed)
    assert rebuilt == committed
    assert committed["schema_version"] == builder.SCHEMA_VERSION
    assert committed["counts"]["total"] == builder.EXPECTED_REVIEW_COUNT == 82
    assert committed["counts"]["by_decision"] == {
        "map": 38,
        "out_of_syllabus": 29,
        "review": 15,
    }
    assert committed["database_writes_performed"] is False
    assert committed["production_import_authorized"] is False
    assert committed["automatic_promotion_allowed"] is False
    assert committed["practice_eligible_count"] == 0
    assert "classification_review_base" in committed["input_bindings"]

    checked = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--check"],
        cwd=REPO_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    assert checked.returncode == 0, checked.stderr or checked.stdout


def test_every_binding_and_evidence_hash_reproduces() -> None:
    artifact = _load_artifact()
    for binding in artifact["input_bindings"].values():
        path = REPO_DIR / binding["path"]
        assert path.stat().st_size == binding["bytes"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == binding["sha256"]
        if "embedded_artifact_sha256" in binding:
            payload = json.loads(path.read_text(encoding="utf-8"))
            assert payload["artifact_sha256"] == binding["embedded_artifact_sha256"]
            core = {key: value for key, value in payload.items() if key != "artifact_sha256"}
            assert builder._canonical_sha256(core) == payload["artifact_sha256"]

    identities = set()
    evidence_kinds = Counter()
    for row in artifact["decisions"]:
        identity = (
            row["source_paper_id"],
            row["canonical_parent_ordinal"],
            row["item_label"],
            row["child_item_label"],
        )
        assert identity not in identities
        identities.add(identity)
        evidence = row["evidence"]
        assert hashlib.sha256(evidence["excerpt"].encode("utf-8")).hexdigest() == evidence["excerpt_sha256"]
        assert len(evidence["source_pdf_sha256"]) == 64
        assert evidence["source_pages"]
        evidence_kinds[evidence["kind"]] += 1
    assert evidence_kinds == Counter(artifact["counts"]["by_evidence_kind"])


def test_maps_use_inventory_and_compound_rows_remain_review() -> None:
    artifact = _load_artifact()
    inventory = builder._canonical_inventory(
        json.loads(builder.DEFAULT_TOPIC_INVENTORY.read_text(encoding="utf-8"))
    )
    by_key = {
        f"{row['source_paper_id']}#{row['canonical_parent_ordinal']}": row
        for row in artifact["decisions"]
    }
    for row in artifact["decisions"]:
        if row["decision"] == "map":
            assert row["course"] in inventory
            assert row["topic"] in inventory[row["course"]]
        else:
            assert row["course"] is None
            assert row["topic"] is None

    for key in (
        "gate-cs-1997#5",
        "gate-cs-1999#9",
        "gate-cs-2009#17",
        "gate-cs-2016-session-2#29",
        "gate-cs-2017-session-1#15",
        "gate-cs-2017-session-2#15",
        "gate-cs-2018#18",
        "gate-cs-2020#19",
        "gate-cs-2023#11",
        "gate-cs-2024-set-2#21",
        "gate-cs-2025-set-1#12",
        "gate-cs-2025-set-2#38",
    ):
        assert by_key[key]["decision"] == "review"


def test_shifted_legacy_release_ordinal_is_keyed_by_canonical_parent() -> None:
    artifact = _load_artifact()
    row = next(
        row
        for row in artifact["decisions"]
        if row["source_paper_id"] == "gate-cs-1997"
        and row["canonical_parent_ordinal"] == 52
    )
    assert row["item_label"] == "8"
    assert row["prior_classification"]["final_release_ordinal"] == 53
    assert row["decision"] == "map"
    assert (row["course"], row["topic"]) == ("PDS", "linked-lists")


def test_tampered_excerpt_and_unsafe_guard_fail_closed() -> None:
    artifact = _load_artifact()
    tampered = copy.deepcopy(artifact)
    tampered["decisions"][0]["evidence"]["excerpt"] += " altered"
    tampered_core = {
        key: value for key, value in tampered.items() if key != "artifact_sha256"
    }
    tampered["artifact_sha256"] = builder._canonical_sha256(tampered_core)
    with pytest.raises(builder.ClassificationReviewError, match="Evidence excerpt hash"):
        builder.validate_artifact(tampered)

    unsafe = copy.deepcopy(artifact)
    unsafe["production_import_authorized"] = True
    unsafe_core = {key: value for key, value in unsafe.items() if key != "artifact_sha256"}
    unsafe["artifact_sha256"] = builder._canonical_sha256(unsafe_core)
    with pytest.raises(builder.ClassificationReviewError, match="Unsafe guard"):
        builder.validate_artifact(unsafe)
