"""Load and validate the auditable GateOverflow-to-GatePath topic policy.

This module deliberately treats classification as data.  Every source
course/topic signature in the pinned 1996--2025 GateOverflow locator index
must have one explicit decision: map it to a syllabus topic, or retain it for
manual review with a reason.  Broad labels are never guessed at runtime.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = "1.0"
OVERRIDE_KEY_RE = re.compile(r"^(?P<paper>gate-cs-[a-z0-9-]+)#(?P<ordinal>[1-9]\d*)$")


class TopicClassificationError(ValueError):
    """Raised when the classification policy is incomplete or inconsistent."""


@dataclass(frozen=True, slots=True)
class TopicDecision:
    decision: str
    source_course: str | None
    source_topic: str
    source_course_mapping_agrees: bool
    canonical_course: str | None
    canonical_topic: str | None
    reason_code: str
    reason: str

    @property
    def signature(self) -> tuple[str | None, str, bool]:
        return (
            self.source_course,
            self.source_topic,
            self.source_course_mapping_agrees,
        )


@dataclass(frozen=True, slots=True)
class QuestionOverride:
    paper_id: str
    ordinal: int
    expected_source_course: str | None
    expected_source_topic: str
    expected_source_course_mapping_agrees: bool
    canonical_course: str
    canonical_topic: str
    reason_code: str
    reason: str
    evidence_kind: str
    evidence_summary: str

    @property
    def key(self) -> tuple[str, int]:
        return (self.paper_id, self.ordinal)

    @property
    def expected_signature(self) -> tuple[str | None, str, bool]:
        return (
            self.expected_source_course,
            self.expected_source_topic,
            self.expected_source_course_mapping_agrees,
        )


@dataclass(frozen=True, slots=True)
class TopicClassificationPolicy:
    schema_version: str
    policy_version: str
    source_sha256: str
    decisions: Mapping[tuple[str | None, str, bool], TopicDecision]
    overrides: Mapping[tuple[str, int], QuestionOverride]
    observed_record_count: int
    observed_signature_count: int

    def resolve(
        self,
        *,
        paper_id: str,
        ordinal: int,
        source_course: Any,
        source_topic: Any,
        source_course_mapping_agrees: Any,
    ) -> dict[str, Any]:
        signature = _source_signature(
            source_course,
            source_topic,
            source_course_mapping_agrees,
        )
        override = self.overrides.get((paper_id, ordinal))
        if override is not None:
            if signature != override.expected_signature:
                raise TopicClassificationError(
                    f"{paper_id}#{ordinal}: question override expected source "
                    f"signature {override.expected_signature!r}, got {signature!r}"
                )
            return {
                "decision": "map",
                "course": override.canonical_course,
                "topic": override.canonical_topic,
                "source": "gateoverflow_question_override",
                "decision_key": f"{paper_id}#{ordinal}",
                "reason_code": override.reason_code,
                "reason": override.reason,
                "evidence": {
                    "kind": override.evidence_kind,
                    "summary": override.evidence_summary,
                },
            }

        decision = self.decisions.get(signature)
        if decision is None:
            raise TopicClassificationError(
                f"uncovered GateOverflow source signature {signature!r}"
            )
        return {
            "decision": decision.decision,
            "course": decision.canonical_course,
            "topic": decision.canonical_topic,
            "source": "gateoverflow_topic_policy",
            "decision_key": _signature_label(signature),
            "reason_code": decision.reason_code,
            "reason": decision.reason,
            "evidence": None,
        }


def _normalized_course(value: Any) -> str | None:
    code = str(value or "").strip().upper()
    return code or None


def _normalized_topic(value: Any) -> str:
    topic = str(value or "").strip().casefold()
    if not topic:
        raise TopicClassificationError("source topic must be a non-empty slug")
    return topic


def _source_signature(
    course: Any, topic: Any, course_mapping_agrees: Any
) -> tuple[str | None, str, bool]:
    if not isinstance(course_mapping_agrees, bool):
        raise TopicClassificationError(
            "source_course_mapping_agrees must be an explicit boolean"
        )
    return (
        _normalized_course(course),
        _normalized_topic(topic),
        course_mapping_agrees,
    )

def _signature_label(signature: tuple[str | None, str, bool]) -> str:
    course, topic, agrees = signature
    return f"{course or '<null>'}|{topic}|{'agree' if agrees else 'disagree'}"


def _require_reason(group: Mapping[str, Any], *, context: str) -> tuple[str, str]:
    reason_code = str(group.get("reason_code") or "").strip()
    reason = str(group.get("reason") or "").strip()
    if not reason_code or not reason:
        raise TopicClassificationError(
            f"{context}: reason_code and reason are required"
        )
    return reason_code, reason


def _validate_target(
    *,
    course: Any,
    topic: Any,
    inventory: Mapping[str, set[str]],
    context: str,
) -> tuple[str, str]:
    code = _normalized_course(course)
    slug = _normalized_topic(topic)
    if code is None or code not in inventory:
        raise TopicClassificationError(
            f"{context}: canonical course {code!r} is not in the inventory"
        )
    if slug not in inventory[code]:
        raise TopicClassificationError(
            f"{context}: canonical topic {code}/{slug} is not in the inventory"
        )
    return code, slug


def _compile_groups(
    raw: Mapping[str, Any],
    inventory: Mapping[str, set[str]],
) -> dict[tuple[str | None, str, bool], TopicDecision]:
    decisions: dict[tuple[str | None, str, bool], TopicDecision] = {}
    groups = raw.get("decision_groups")
    if not isinstance(groups, list) or not groups:
        raise TopicClassificationError("decision_groups must be a non-empty list")

    for index, group in enumerate(groups):
        context = f"decision_groups[{index}]"
        if not isinstance(group, dict):
            raise TopicClassificationError(f"{context}: expected an object")
        decision = str(group.get("decision") or "").strip().casefold()
        if decision not in {"map", "manual_review"}:
            raise TopicClassificationError(
                f"{context}: decision must be map or manual_review"
            )
        agrees = group.get("source_course_mapping_agrees")
        if not isinstance(agrees, bool):
            raise TopicClassificationError(
                f"{context}: source_course_mapping_agrees must be boolean"
            )
        source_course = _normalized_course(group.get("source_course"))
        topics = group.get("source_topics")
        if not isinstance(topics, list) or not topics:
            raise TopicClassificationError(
                f"{context}: source_topics must be a non-empty list"
            )
        normalized_topics = [_normalized_topic(topic) for topic in topics]
        if len(set(normalized_topics)) != len(normalized_topics):
            raise TopicClassificationError(
                f"{context}: source_topics contains duplicates"
            )
        reason_code, reason = _require_reason(group, context=context)

        canonical_course: str | None = None
        canonical_topic: str | None = None
        if decision == "map":
            canonical_course, canonical_topic = _validate_target(
                course=group.get("canonical_course"),
                topic=group.get("canonical_topic"),
                inventory=inventory,
                context=context,
            )
        elif group.get("canonical_course") is not None or group.get(
            "canonical_topic"
        ) is not None:
            raise TopicClassificationError(
                f"{context}: manual_review cannot carry a canonical target"
            )

        for source_topic in normalized_topics:
            topic_decision = TopicDecision(
                decision=decision,
                source_course=source_course,
                source_topic=source_topic,
                source_course_mapping_agrees=agrees,
                canonical_course=canonical_course,
                canonical_topic=canonical_topic,
                reason_code=reason_code,
                reason=reason,
            )
            if topic_decision.signature in decisions:
                raise TopicClassificationError(
                    f"duplicate source decision for "
                    f"{_signature_label(topic_decision.signature)}"
                )
            decisions[topic_decision.signature] = topic_decision
    return decisions


def _compile_overrides(
    raw: Mapping[str, Any],
    inventory: Mapping[str, set[str]],
    *,
    valid_slot_keys: set[tuple[str, int]] | None,
) -> dict[tuple[str, int], QuestionOverride]:
    overrides_raw = raw.get("question_overrides", {})
    if not isinstance(overrides_raw, dict):
        raise TopicClassificationError("question_overrides must be an object")
    overrides: dict[tuple[str, int], QuestionOverride] = {}
    for raw_key, value in overrides_raw.items():
        match = OVERRIDE_KEY_RE.fullmatch(str(raw_key))
        if match is None or not isinstance(value, dict):
            raise TopicClassificationError(
                f"question_overrides[{raw_key!r}] is malformed"
            )
        paper_id = match.group("paper")
        ordinal = int(match.group("ordinal"))
        key = (paper_id, ordinal)
        if valid_slot_keys is not None and key not in valid_slot_keys:
            raise TopicClassificationError(
                f"question_overrides[{raw_key!r}] does not name a canonical slot"
            )
        expected = value.get("expected_source")
        if not isinstance(expected, dict):
            raise TopicClassificationError(
                f"question_overrides[{raw_key!r}]: expected_source is required"
            )
        signature = _source_signature(
            expected.get("course"),
            expected.get("topic"),
            expected.get("course_mapping_agrees"),
        )
        canonical_course, canonical_topic = _validate_target(
            course=value.get("canonical_course"),
            topic=value.get("canonical_topic"),
            inventory=inventory,
            context=f"question_overrides[{raw_key!r}]",
        )
        reason_code, reason = _require_reason(
            value, context=f"question_overrides[{raw_key!r}]"
        )
        evidence = value.get("evidence")
        if not isinstance(evidence, dict):
            raise TopicClassificationError(
                f"question_overrides[{raw_key!r}]: evidence is required"
            )
        evidence_kind = str(evidence.get("kind") or "").strip()
        evidence_summary = str(evidence.get("summary") or "").strip()
        if evidence_kind not in {"question_text", "original_paper"} or not evidence_summary:
            raise TopicClassificationError(
                f"question_overrides[{raw_key!r}]: evidence must include a "
                "supported kind and non-empty summary"
            )
        override = QuestionOverride(
            paper_id=paper_id,
            ordinal=ordinal,
            expected_source_course=signature[0],
            expected_source_topic=signature[1],
            expected_source_course_mapping_agrees=signature[2],
            canonical_course=canonical_course,
            canonical_topic=canonical_topic,
            reason_code=reason_code,
            reason=reason,
            evidence_kind=evidence_kind,
            evidence_summary=evidence_summary,
        )
        overrides[key] = override
    return overrides


def _observed_signatures(
    rows: Iterable[Mapping[str, Any]], *, year_min: int, year_max: int
) -> tuple[Counter[tuple[str | None, str, bool]], int]:
    signatures: Counter[tuple[str | None, str, bool]] = Counter()
    record_count = 0
    for row in rows:
        try:
            year = int(row.get("year"))
        except (TypeError, ValueError) as exc:
            raise TopicClassificationError("GateOverflow row has invalid year") from exc
        if not year_min <= year <= year_max:
            continue
        signature = _source_signature(
            row.get("course_code"),
            row.get("topic_slug"),
            row.get("course_mapping_agrees"),
        )
        signatures[signature] += 1
        record_count += 1
    return signatures, record_count


def load_topic_classification_policy(
    path: Path,
    *,
    inventory: Mapping[str, set[str]],
    gateoverflow_rows: Iterable[Mapping[str, Any]],
    valid_slot_keys: set[tuple[str, int]] | None = None,
) -> TopicClassificationPolicy:
    payload = path.read_bytes()
    try:
        raw = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TopicClassificationError(f"{path}: invalid UTF-8 JSON") from exc
    if not isinstance(raw, dict):
        raise TopicClassificationError(f"{path}: expected a JSON object")
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise TopicClassificationError(
            f"{path}: schema_version must be {SCHEMA_VERSION!r}"
        )
    policy_version = str(raw.get("policy_version") or "").strip()
    if not policy_version:
        raise TopicClassificationError(f"{path}: policy_version is required")
    scope = raw.get("scope")
    if not isinstance(scope, dict):
        raise TopicClassificationError(f"{path}: scope is required")
    try:
        year_min = int(scope.get("year_min"))
        year_max = int(scope.get("year_max"))
        expected_records = int(scope.get("expected_source_record_count"))
        expected_signatures = int(scope.get("expected_source_signature_count"))
    except (TypeError, ValueError) as exc:
        raise TopicClassificationError(f"{path}: scope counts are invalid") from exc
    if (year_min, year_max) != (1996, 2025):
        raise TopicClassificationError(
            f"{path}: classification scope must be exactly 1996--2025"
        )

    decisions = _compile_groups(raw, inventory)
    overrides = _compile_overrides(
        raw, inventory, valid_slot_keys=valid_slot_keys
    )
    observed, observed_record_count = _observed_signatures(
        gateoverflow_rows, year_min=year_min, year_max=year_max
    )
    if observed_record_count != expected_records:
        raise TopicClassificationError(
            f"{path}: observed {observed_record_count} source records, expected "
            f"{expected_records}"
        )
    if len(observed) != expected_signatures:
        raise TopicClassificationError(
            f"{path}: observed {len(observed)} source signatures, expected "
            f"{expected_signatures}"
        )
    missing = set(observed) - set(decisions)
    stale = set(decisions) - set(observed)
    if missing or stale:
        details = []
        if missing:
            details.append(
                "missing=" + ",".join(_signature_label(item) for item in sorted(
                    missing, key=lambda item: (str(item[0]), item[1], item[2])
                ))
            )
        if stale:
            details.append(
                "stale=" + ",".join(_signature_label(item) for item in sorted(
                    stale, key=lambda item: (str(item[0]), item[1], item[2])
                ))
            )
        raise TopicClassificationError(
            f"{path}: policy does not exactly cover observed signatures: "
            + "; ".join(details)
        )

    for override in overrides.values():
        decision = decisions.get(override.expected_signature)
        if decision is None:
            raise TopicClassificationError(
                f"{override.paper_id}#{override.ordinal}: override source signature "
                "is not covered by the policy"
            )
        if decision.decision != "manual_review":
            raise TopicClassificationError(
                f"{override.paper_id}#{override.ordinal}: overrides are permitted "
                "only for manual-review source signatures"
            )

    return TopicClassificationPolicy(
        schema_version=SCHEMA_VERSION,
        policy_version=policy_version,
        source_sha256=hashlib.sha256(payload).hexdigest(),
        decisions=decisions,
        overrides=overrides,
        observed_record_count=observed_record_count,
        observed_signature_count=len(observed),
    )
