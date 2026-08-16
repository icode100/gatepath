from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from collections import Counter
from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = BACKEND_DIR / "scripts" / "pyq_slot_classification.py"
SPEC = importlib.util.spec_from_file_location("pyq_slot_classification", SCRIPT_PATH)
assert SPEC and SPEC.loader
classifier = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = classifier
SPEC.loader.exec_module(classifier)


def _slug(value: str) -> str:
    import unicodedata

    folded = (
        unicodedata.normalize("NFKD", value)
        .encode("ascii", "ignore")
        .decode()
        .casefold()
    )
    return re.sub(r"[^a-z0-9]+", "-", folded).strip("-")


def _inventory() -> dict[str, set[str]]:
    raw = json.loads(
        (BACKEND_DIR / "data/question_bank_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    return {
        code: {_slug(topic) for topic in course["by_topic"]}
        for code, course in raw["courses"].items()
    }


def _valid_keys() -> set[tuple[str, int]]:
    raw = json.loads(
        (BACKEND_DIR / "data/pyq_source_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    return {
        (paper["id"], ordinal)
        for paper in raw["papers"]
        for ordinal in range(1, int(paper["expected_item_count"]) + 1)
    }


def _load_real_policy():
    inventory_path = BACKEND_DIR / "data/question_bank_manifest.json"
    aliases_path = BACKEND_DIR / "data/pyq_topic_aliases.json"
    return classifier.load_slot_classification_policy(
        BACKEND_DIR / "data/pyq_slot_classification_overrides.json",
        inventory=_inventory(),
        inventory_sha256=hashlib.sha256(inventory_path.read_bytes()).hexdigest(),
        base_topic_policy_sha256=hashlib.sha256(aliases_path.read_bytes()).hexdigest(),
        valid_slot_keys=_valid_keys(),
    )


def _runtime_sources(decision):
    evidence = decision.evidence
    if evidence["kind"] == "gateoverflow_question_text":
        return {"question_body_sha256": evidence["text_sha256"]}, None
    provenance = {
        "source_pdf_sha256": evidence["source_pdf_sha256"],
        "source_pages": evidence["source_pages"],
        "text_block_sha256": evidence.get("text_sha256"),
        "rendered_page_evidence": [
            {"sha256": digest}
            for digest in evidence.get("rendered_page_sha256", [])
        ],
        "locator_override_evidence": {
            "evidence_method": evidence.get("evidence_method"),
            "visual_spot_check": evidence.get("visual_spot_check"),
        }
        if evidence["kind"] == "original_pdf_locator_only"
        else None,
    }
    return None, provenance


def test_every_slot_decision_resolves_exact_key_and_canonical_inventory() -> None:
    policy = _load_real_policy()
    inventory = _inventory()

    assert policy.canonical_slot_count == 2712
    assert policy.expected_base_review_count == 433
    assert len(policy.decisions) == 433
    assert Counter(item.decision for item in policy.decisions.values()) == {
        "map": 306,
        "review": 90,
        "out_of_syllabus": 37,
    }

    for key, decision in policy.decisions.items():
        go, original = _runtime_sources(decision)
        resolved = policy.resolve(
            key=key,
            base_review_reasons=list(decision.expected_base_review_reasons),
            gateoverflow_snapshot=go,
            original_provenance=original,
        )
        assert resolved is not None
        assert resolved["decision_key"] == f"{key[0]}#{key[1]}"
        if decision.decision == "map":
            assert decision.canonical_course in inventory
            assert (
                decision.canonical_topic
                in inventory[decision.canonical_course]
            )
        else:
            assert decision.canonical_course is None
            assert decision.canonical_topic is None


def test_slot_resolution_fails_closed_on_reason_or_evidence_drift() -> None:
    policy = _load_real_policy()
    decision = next(
        value
        for value in policy.decisions.values()
        if value.evidence["kind"] == "gateoverflow_question_text"
    )
    go, original = _runtime_sources(decision)

    with pytest.raises(classifier.SlotClassificationError, match="reasons drifted"):
        policy.resolve(
            key=decision.key,
            base_review_reasons=["different_reason"],
            gateoverflow_snapshot=go,
            original_provenance=original,
        )

    assert go is not None
    go["question_body_sha256"] = "0" * 64
    with pytest.raises(classifier.SlotClassificationError, match="text hash drifted"):
        policy.resolve(
            key=decision.key,
            base_review_reasons=list(decision.expected_base_review_reasons),
            gateoverflow_snapshot=go,
            original_provenance=original,
        )


def test_loader_rejects_noncanonical_target(tmp_path: Path) -> None:
    source = BACKEND_DIR / "data/pyq_slot_classification_overrides.json"
    raw = json.loads(source.read_text(encoding="utf-8"))
    first_map = next(
        value
        for value in raw["slot_decisions"].values()
        if value["decision"] == "map"
    )
    first_map["canonical_topic"] = "invented-topic"
    malformed = tmp_path / "slots.json"
    malformed.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(classifier.SlotClassificationError, match="not in the canonical"):
        classifier.load_slot_classification_policy(
            malformed,
            inventory=_inventory(),
            inventory_sha256=raw["scope"]["canonical_inventory_sha256"],
            base_topic_policy_sha256=raw["scope"]["base_topic_policy_sha256"],
            valid_slot_keys=_valid_keys(),
        )
