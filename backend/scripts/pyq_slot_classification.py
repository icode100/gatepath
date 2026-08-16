"""Load fail-closed, question-evidence-bound PYQ slot classifications.

The topic-alias policy classifies only unambiguous source labels.  This module
handles the remaining slots one question at a time.  A decision is accepted
only when its canonical key, the base review reasons, the pinned topic-policy
hash, the canonical-inventory hash, and its cited text/provenance hash all
still match.  Drift therefore reopens review instead of silently reclassifying
an item.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "1.0"
KEY_RE = re.compile(r"^(?P<paper>gate-cs-[a-z0-9-]+)#(?P<ordinal>[1-9]\d*)$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class SlotClassificationError(ValueError):
    """Raised when a slot policy or its cited evidence has drifted."""


@dataclass(frozen=True, slots=True)
class SlotDecision:
    paper_id: str
    ordinal: int
    decision: str
    canonical_course: str | None
    canonical_topic: str | None
    reason_code: str
    reason: str
    expected_base_review_reasons: tuple[str, ...]
    evidence: Mapping[str, Any]

    @property
    def key(self) -> tuple[str, int]:
        return self.paper_id, self.ordinal


@dataclass(frozen=True, slots=True)
class SlotClassificationPolicy:
    schema_version: str
    policy_version: str
    source_sha256: str
    canonical_slot_count: int
    expected_base_review_count: int
    decisions: Mapping[tuple[str, int], SlotDecision]
    outcome_counts: Mapping[str, int]

    def resolve(
        self,
        *,
        key: tuple[str, int],
        base_review_reasons: list[str],
        gateoverflow_snapshot: Mapping[str, Any] | None,
        original_provenance: Mapping[str, Any] | None,
    ) -> dict[str, Any] | None:
        decision = self.decisions.get(key)
        if decision is None:
            return None
        observed_reasons = tuple(sorted(set(base_review_reasons)))
        if observed_reasons != decision.expected_base_review_reasons:
            raise SlotClassificationError(
                f"{key[0]}#{key[1]}: base classification reasons drifted; "
                f"expected {decision.expected_base_review_reasons!r}, got "
                f"{observed_reasons!r}"
            )
        _validate_runtime_evidence(
            decision,
            gateoverflow_snapshot=gateoverflow_snapshot,
            original_provenance=original_provenance,
        )
        return {
            "decision": decision.decision,
            "course": decision.canonical_course,
            "topic": decision.canonical_topic,
            "source": "question_evidence_slot_policy",
            "decision_key": f"{decision.paper_id}#{decision.ordinal}",
            "reason_code": decision.reason_code,
            "reason": decision.reason,
            "evidence": dict(decision.evidence),
        }


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _require_sha256(value: Any, *, context: str) -> str:
    digest = str(value or "").strip().casefold()
    if SHA256_RE.fullmatch(digest) is None:
        raise SlotClassificationError(f"{context}: expected a SHA-256 digest")
    return digest


def _normalized_inventory(
    inventory: Mapping[str, set[str]],
) -> dict[str, set[str]]:
    return {
        str(course).strip().upper(): {
            str(topic).strip().casefold() for topic in topics
        }
        for course, topics in inventory.items()
    }


def _compile_decisions(
    raw: Mapping[str, Any],
    *,
    inventory: Mapping[str, set[str]],
    valid_slot_keys: set[tuple[str, int]],
) -> dict[tuple[str, int], SlotDecision]:
    values = raw.get("slot_decisions")
    if not isinstance(values, dict) or not values:
        raise SlotClassificationError("slot_decisions must be a non-empty object")
    compiled: dict[tuple[str, int], SlotDecision] = {}
    normalized_inventory = _normalized_inventory(inventory)
    for raw_key, value in values.items():
        context = f"slot_decisions[{raw_key!r}]"
        match = KEY_RE.fullmatch(str(raw_key))
        if match is None or not isinstance(value, dict):
            raise SlotClassificationError(f"{context}: malformed slot decision")
        key = match.group("paper"), int(match.group("ordinal"))
        if key not in valid_slot_keys:
            raise SlotClassificationError(
                f"{context}: key does not identify a canonical PYQ slot"
            )
        decision = str(value.get("decision") or "").strip().casefold()
        if decision not in {"map", "out_of_syllabus", "review"}:
            raise SlotClassificationError(
                f"{context}: decision must be map, out_of_syllabus, or review"
            )
        course = value.get("canonical_course")
        topic = value.get("canonical_topic")
        if decision == "map":
            course = str(course or "").strip().upper()
            topic = str(topic or "").strip().casefold()
            if course not in normalized_inventory or topic not in normalized_inventory[course]:
                raise SlotClassificationError(
                    f"{context}: target {course}/{topic} is not in the canonical inventory"
                )
        elif course is not None or topic is not None:
            raise SlotClassificationError(
                f"{context}: non-map decisions cannot carry a canonical target"
            )
        else:
            course = topic = None

        reason_code = str(value.get("reason_code") or "").strip()
        reason = str(value.get("reason") or "").strip()
        if not reason_code or not reason:
            raise SlotClassificationError(
                f"{context}: reason_code and reason are required"
            )
        expected = value.get("expected_base_review_reasons")
        if not isinstance(expected, list) or not expected or any(
            not isinstance(item, str) or not item.strip() for item in expected
        ):
            raise SlotClassificationError(
                f"{context}: expected_base_review_reasons must be non-empty strings"
            )
        normalized_expected = tuple(sorted(set(item.strip() for item in expected)))
        if len(normalized_expected) != len(expected):
            raise SlotClassificationError(
                f"{context}: expected_base_review_reasons contains duplicates"
            )
        evidence = value.get("evidence")
        if not isinstance(evidence, dict):
            raise SlotClassificationError(f"{context}: evidence is required")
        _validate_static_evidence(evidence, decision=decision, context=context)
        compiled[key] = SlotDecision(
            paper_id=key[0],
            ordinal=key[1],
            decision=decision,
            canonical_course=course,
            canonical_topic=topic,
            reason_code=reason_code,
            reason=reason,
            expected_base_review_reasons=normalized_expected,
            evidence=dict(evidence),
        )
    return compiled


def _validate_static_evidence(
    evidence: Mapping[str, Any], *, decision: str, context: str
) -> None:
    kind = str(evidence.get("kind") or "").strip()
    supported = {
        "gateoverflow_question_text",
        "original_pdf_text_block",
        "original_pdf_locator_only",
    }
    if kind not in supported:
        raise SlotClassificationError(f"{context}: unsupported evidence kind {kind!r}")
    snippet = evidence.get("snippet")
    if kind != "original_pdf_locator_only":
        if not isinstance(snippet, str) or not snippet.strip():
            raise SlotClassificationError(f"{context}: text evidence needs a snippet")
        _require_sha256(evidence.get("text_sha256"), context=context)
    else:
        if decision != "review":
            raise SlotClassificationError(
                f"{context}: locator-only evidence can support only a review decision"
            )
    if kind.startswith("original_pdf_"):
        _require_sha256(evidence.get("source_pdf_sha256"), context=context)
        pages = evidence.get("source_pages")
        if not isinstance(pages, list) or any(
            not isinstance(page, int) or page < 1 for page in pages
        ):
            raise SlotClassificationError(f"{context}: source_pages is invalid")
        if kind == "original_pdf_locator_only" and not pages:
            raise SlotClassificationError(
                f"{context}: locator source_pages must be non-empty"
            )
    if kind == "original_pdf_locator_only":
        hashes = evidence.get("rendered_page_sha256")
        if not isinstance(hashes, list) or not hashes:
            raise SlotClassificationError(
                f"{context}: rendered_page_sha256 must be a non-empty list"
            )
        for digest in hashes:
            _require_sha256(digest, context=context)
        method = evidence.get("evidence_method")
        if not isinstance(method, str) or not method.strip():
            raise SlotClassificationError(
                f"{context}: locator evidence_method is required"
            )
        if not isinstance(evidence.get("visual_spot_check"), bool):
            raise SlotClassificationError(
                f"{context}: locator visual_spot_check must be boolean"
            )


def _validate_runtime_evidence(
    decision: SlotDecision,
    *,
    gateoverflow_snapshot: Mapping[str, Any] | None,
    original_provenance: Mapping[str, Any] | None,
) -> None:
    evidence = decision.evidence
    context = f"{decision.paper_id}#{decision.ordinal}"
    kind = evidence["kind"]
    if kind == "gateoverflow_question_text":
        if gateoverflow_snapshot is None:
            raise SlotClassificationError(
                f"{context}: cited GateOverflow question is no longer joined"
            )
        observed = str(gateoverflow_snapshot.get("question_body_sha256") or "")
        if observed != evidence["text_sha256"]:
            raise SlotClassificationError(
                f"{context}: GateOverflow question text hash drifted"
            )
        return
    if original_provenance is None:
        raise SlotClassificationError(
            f"{context}: cited original-paper provenance is unavailable"
        )
    if original_provenance.get("source_pdf_sha256") != evidence["source_pdf_sha256"]:
        raise SlotClassificationError(f"{context}: original PDF hash drifted")
    if list(original_provenance.get("source_pages") or []) != list(
        evidence.get("source_pages") or []
    ):
        raise SlotClassificationError(f"{context}: original source pages drifted")
    if kind == "original_pdf_text_block":
        if original_provenance.get("text_block_sha256") != evidence["text_sha256"]:
            raise SlotClassificationError(
                f"{context}: original question text-block hash drifted"
            )
    else:
        observed_hashes = [
            item.get("sha256")
            for item in original_provenance.get("rendered_page_evidence") or []
        ]
        if observed_hashes != list(evidence.get("rendered_page_sha256") or []):
            raise SlotClassificationError(
                f"{context}: rendered original-page evidence drifted"
            )
        locator_evidence = original_provenance.get("locator_override_evidence")
        if isinstance(locator_evidence, dict):
            observed_method = locator_evidence.get("evidence_method")
            observed_spot_check = locator_evidence.get("visual_spot_check")
        else:
            observed_method = original_provenance.get("locator_status")
            observed_spot_check = False
        if observed_method != evidence.get("evidence_method"):
            raise SlotClassificationError(
                f"{context}: reviewed locator evidence method drifted"
            )
        if observed_spot_check is not evidence.get("visual_spot_check"):
            raise SlotClassificationError(
                f"{context}: reviewed locator visual-check status drifted"
            )


def load_slot_classification_policy(
    path: Path,
    *,
    inventory: Mapping[str, set[str]],
    inventory_sha256: str,
    base_topic_policy_sha256: str,
    valid_slot_keys: set[tuple[str, int]],
) -> SlotClassificationPolicy:
    payload = path.read_bytes()
    try:
        raw = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SlotClassificationError(f"{path}: invalid UTF-8 JSON") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != SCHEMA_VERSION:
        raise SlotClassificationError(
            f"{path}: schema_version must be {SCHEMA_VERSION!r}"
        )
    version = str(raw.get("policy_version") or "").strip()
    scope = raw.get("scope")
    if not version or not isinstance(scope, dict):
        raise SlotClassificationError(f"{path}: policy_version and scope are required")
    try:
        canonical_slot_count = int(scope.get("canonical_slot_count"))
        expected_review_count = int(scope.get("expected_base_review_count"))
    except (TypeError, ValueError) as exc:
        raise SlotClassificationError(f"{path}: scope counts are invalid") from exc
    if canonical_slot_count != len(valid_slot_keys):
        raise SlotClassificationError(
            f"{path}: canonical slot count drifted from {canonical_slot_count} "
            f"to {len(valid_slot_keys)}"
        )
    if _require_sha256(
        scope.get("base_topic_policy_sha256"), context=str(path)
    ) != base_topic_policy_sha256:
        raise SlotClassificationError(f"{path}: base topic policy hash drifted")
    if _require_sha256(
        scope.get("canonical_inventory_sha256"), context=str(path)
    ) != inventory_sha256:
        raise SlotClassificationError(f"{path}: canonical inventory hash drifted")

    decisions = _compile_decisions(
        raw, inventory=inventory, valid_slot_keys=valid_slot_keys
    )
    if len(decisions) != expected_review_count:
        raise SlotClassificationError(
            f"{path}: found {len(decisions)} decisions, expected "
            f"{expected_review_count}"
        )
    counts = Counter(decision.decision for decision in decisions.values())
    return SlotClassificationPolicy(
        schema_version=SCHEMA_VERSION,
        policy_version=version,
        source_sha256=_sha256_bytes(payload),
        canonical_slot_count=canonical_slot_count,
        expected_base_review_count=expected_review_count,
        decisions=decisions,
        outcome_counts=dict(counts),
    )
