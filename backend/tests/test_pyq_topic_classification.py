from __future__ import annotations

import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = BACKEND_DIR / "scripts" / "pyq_topic_classification.py"
SPEC = importlib.util.spec_from_file_location("pyq_topic_classification", SCRIPT_PATH)
assert SPEC and SPEC.loader
classifier = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = classifier
SPEC.loader.exec_module(classifier)


def _inventory() -> dict[str, set[str]]:
    raw = json.loads(
        (BACKEND_DIR / "data" / "question_bank_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    import re
    import unicodedata

    def slug(value: str) -> str:
        folded = (
            unicodedata.normalize("NFKD", value)
            .encode("ascii", "ignore")
            .decode()
            .casefold()
        )
        return re.sub(r"[^a-z0-9]+", "-", folded).strip("-")

    return {
        code: {slug(topic) for topic in course["by_topic"]}
        for code, course in raw["courses"].items()
    }


def _synthetic_observed_rows(raw_policy: dict) -> list[dict]:
    signatures = []
    for group in raw_policy["decision_groups"]:
        for topic in group["source_topics"]:
            signatures.append(
                {
                    "year": 2020,
                    "course_code": group["source_course"],
                    "topic_slug": topic,
                    "course_mapping_agrees": group[
                        "source_course_mapping_agrees"
                    ],
                }
            )
    assert len(signatures) == 419
    # The policy pins both the distinct signatures and the 2,607 source rows.
    return signatures + [dict(signatures[0]) for _ in range(2607 - 419)]


def _load_real_policy():
    path = BACKEND_DIR / "data" / "pyq_topic_aliases.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    valid_keys = set()
    for raw_key in raw["question_overrides"]:
        paper_id, ordinal = raw_key.rsplit("#", 1)
        valid_keys.add((paper_id, int(ordinal)))
    return classifier.load_topic_classification_policy(
        path,
        inventory=_inventory(),
        gateoverflow_rows=_synthetic_observed_rows(raw),
        valid_slot_keys=valid_keys,
    )


def test_real_policy_explicitly_covers_every_pinned_signature() -> None:
    policy = _load_real_policy()

    assert policy.observed_record_count == 2607
    assert policy.observed_signature_count == 419
    assert len(policy.decisions) == 419
    assert Counter(item.decision for item in policy.decisions.values()) == {
        "map": 355,
        "manual_review": 64,
    }
    assert len(policy.overrides) == 51


def test_manual_label_is_not_silently_forced_and_override_is_evidence_bound() -> None:
    policy = _load_real_policy()

    broad = policy.resolve(
        paper_id="gate-cs-2019",
        ordinal=1,
        source_course="CN",
        source_topic="sliding-window",
        source_course_mapping_agrees=True,
    )
    assert broad["decision"] == "manual_review"
    assert broad["course"] is None
    assert broad["topic"] is None

    override = policy.resolve(
        paper_id="gate-cs-2025-set-1",
        ordinal=17,
        source_course=None,
        source_topic="onto",
        source_course_mapping_agrees=True,
    )
    assert (override["course"], override["topic"]) == (
        "EM",
        "discrete-mathematics",
    )
    assert override["source"] == "gateoverflow_question_override"
    assert override["evidence"]["kind"] == "question_text"

    with pytest.raises(
        classifier.TopicClassificationError,
        match="question override expected source signature",
    ):
        policy.resolve(
            paper_id="gate-cs-2025-set-1",
            ordinal=17,
            source_course="CN",
            source_topic="onto",
            source_course_mapping_agrees=True,
        )


def test_loader_fails_closed_when_a_new_source_signature_appears(tmp_path: Path) -> None:
    source = BACKEND_DIR / "data" / "pyq_topic_aliases.json"
    raw = json.loads(source.read_text(encoding="utf-8"))
    rows = _synthetic_observed_rows(raw)
    rows[-1] = {
        "year": 2020,
        "course_code": "ALG",
        "topic_slug": "new-unreviewed-topic",
        "course_mapping_agrees": True,
    }

    with pytest.raises(
        classifier.TopicClassificationError,
        match="observed 420 source signatures, expected 419",
    ):
        classifier.load_topic_classification_policy(
            source,
            inventory=_inventory(),
            gateoverflow_rows=rows,
            valid_slot_keys={
                (key.rsplit("#", 1)[0], int(key.rsplit("#", 1)[1]))
                for key in raw["question_overrides"]
            },
        )


def test_loader_rejects_noncanonical_target(tmp_path: Path) -> None:
    source = BACKEND_DIR / "data" / "pyq_topic_aliases.json"
    raw = json.loads(source.read_text(encoding="utf-8"))
    raw["decision_groups"][0]["canonical_topic"] = "invented-topic"
    malformed = tmp_path / "aliases.json"
    malformed.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(
        classifier.TopicClassificationError,
        match="is not in the inventory",
    ):
        classifier.load_topic_classification_policy(
            malformed,
            inventory=_inventory(),
            gateoverflow_rows=_synthetic_observed_rows(raw),
        )
