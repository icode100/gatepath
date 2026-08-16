"""Load checksum-bound classifications for materialized legacy PYQ children.

The 1996--2002 descriptive audit expands 111 canonical parent slots into 272
independently answerable child records.  This module treats every child as a
separate classification decision: no runtime inheritance from the parent is
allowed.  Decisions are pinned to the exact prompt, shared context, source
pages, and rendered-page evidence in the versioned subpart audit.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


REPO_DIR = Path(__file__).resolve().parents[2]
DEFAULT_POLICY = (
    REPO_DIR / "backend" / "data" / "pyq_legacy_child_classifications.json"
)
DEFAULT_SUBPART_AUDIT = (
    REPO_DIR / "backend" / "data" / "legacy_pyq_subparts_1996_2002.json"
)
DEFAULT_INVENTORY = REPO_DIR / "backend" / "data" / "question_bank_manifest.json"
EXPECTED_CHILDREN = 272
EXPECTED_SPLIT_PARENTS = 111
SCHEMA_VERSION = "1.0"
HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class LegacyChildClassificationError(ValueError):
    """Raised when child classification data or evidence has drifted."""


@dataclass(frozen=True, slots=True)
class LegacyChildDecision:
    paper_id: str
    parent_canonical_ordinal: int
    child_item_label: str
    decision: str
    course: str | None
    topic: str | None
    reason_code: str
    reason: str
    evidence_sha256: str
    evidence_excerpt: str
    parent_comparison: str


@dataclass(frozen=True, slots=True)
class LegacyChildClassificationPolicy:
    policy_version: str
    source_sha256: str
    subpart_audit_sha256: str
    inventory_sha256: str
    decisions: Mapping[tuple[str, int, str], LegacyChildDecision]
    outcome_counts: Mapping[str, int]


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return _sha256_text(encoded)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LegacyChildClassificationError(f"Cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise LegacyChildClassificationError(f"{path}: expected a JSON object")
    return value


def _slug(value: str) -> str:
    folded = (
        unicodedata.normalize("NFKD", value)
        .encode("ascii", "ignore")
        .decode("ascii")
        .casefold()
    )
    return re.sub(r"[^a-z0-9]+", "-", folded).strip("-")


def _inventory(path: Path) -> dict[str, set[str]]:
    raw = _read_json(path)
    courses = raw.get("courses")
    if not isinstance(courses, dict):
        raise LegacyChildClassificationError("Canonical topic inventory is missing")
    result: dict[str, set[str]] = {}
    for code, course in courses.items():
        topics = course.get("by_topic") if isinstance(course, dict) else None
        if not isinstance(topics, dict) or not topics:
            raise LegacyChildClassificationError(f"Inventory course {code} has no topics")
        result[str(code)] = {_slug(str(topic)) for topic in topics}
    return result


def _child_key(
    paper_id: str, parent_canonical_ordinal: Any, child_item_label: Any
) -> tuple[str, int, str]:
    if (
        not paper_id
        or not isinstance(parent_canonical_ordinal, int)
        or parent_canonical_ordinal < 1
        or not isinstance(child_item_label, str)
        or not child_item_label.strip()
    ):
        raise LegacyChildClassificationError(
            f"Invalid child key {paper_id!r}/{parent_canonical_ordinal!r}/"
            f"{child_item_label!r}"
        )
    return paper_id, parent_canonical_ordinal, child_item_label.strip()


def _normalize_excerpt(value: str) -> str:
    return " ".join(value.split())[:320]


def child_evidence(child: Mapping[str, Any], *, key: tuple[str, int, str]) -> tuple[str, str]:
    prompt = child.get("prompt_text")
    prompt_sha = child.get("prompt_text_sha256")
    if (
        not isinstance(prompt, str)
        or not prompt.strip()
        or prompt_sha != _sha256_text(prompt)
    ):
        raise LegacyChildClassificationError(f"{key}: prompt hash drifted")
    shared = child.get("shared_context")
    if not isinstance(shared, dict):
        raise LegacyChildClassificationError(f"{key}: shared context is missing")
    shared_text = shared.get("additional_shared_text") or ""
    shared_text_sha = shared.get("additional_shared_text_sha256")
    if not isinstance(shared_text, str) or (
        shared_text and shared_text_sha != _sha256_text(shared_text)
    ):
        raise LegacyChildClassificationError(f"{key}: shared context hash drifted")
    source_pages = child.get("source_pages")
    if (
        not isinstance(source_pages, list)
        or not source_pages
        or any(not isinstance(page, int) or page < 1 for page in source_pages)
    ):
        raise LegacyChildClassificationError(f"{key}: source pages are invalid")
    render_hashes: list[str] = []
    for rendered in child.get("rendered_page_evidence") or []:
        digest = (
            rendered.get("rendered_page_sha256")
            if isinstance(rendered, dict)
            else None
        )
        if not isinstance(digest, str) or HASH_RE.fullmatch(digest) is None:
            raise LegacyChildClassificationError(f"{key}: rendered page hash is invalid")
        render_hashes.append(digest)
    if not render_hashes:
        raise LegacyChildClassificationError(f"{key}: rendered page evidence is missing")
    payload = {
        "paper_id": key[0],
        "parent_canonical_ordinal": key[1],
        "child_item_label": key[2],
        "prompt_text_sha256": prompt_sha,
        "prompt_source": child.get("prompt_source"),
        "prompt_evidence_sha256": _canonical_json_sha256(
            child.get("prompt_evidence") or {}
        ),
        "shared_context_sha256": _canonical_json_sha256(shared),
        "source_pages": source_pages,
        "rendered_page_sha256": render_hashes,
    }
    excerpt = _normalize_excerpt(
        f"{prompt} Context: {shared_text}" if shared_text else prompt
    )
    return _canonical_json_sha256(payload), excerpt


def _source_children(
    audit: Mapping[str, Any],
) -> dict[tuple[str, int, str], dict[str, Any]]:
    result: dict[tuple[str, int, str], dict[str, Any]] = {}
    split_parents = 0
    for paper in audit.get("papers") or []:
        if not isinstance(paper, dict):
            raise LegacyChildClassificationError("Malformed audit paper")
        paper_id = str(paper.get("paper_id") or "")
        for parent in paper.get("decisions") or []:
            if not isinstance(parent, dict):
                raise LegacyChildClassificationError(f"{paper_id}: malformed parent")
            children = parent.get("child_records") or []
            if children:
                split_parents += 1
            for child in children:
                if not isinstance(child, dict):
                    raise LegacyChildClassificationError(f"{paper_id}: malformed child")
                key = _child_key(
                    paper_id,
                    parent.get("parent_canonical_ordinal"),
                    child.get("child_item_label"),
                )
                if key in result:
                    raise LegacyChildClassificationError(f"Duplicate child key {key}")
                result[key] = child
    if len(result) != EXPECTED_CHILDREN or split_parents != EXPECTED_SPLIT_PARENTS:
        raise LegacyChildClassificationError(
            f"Legacy audit has {len(result)} children/{split_parents} split parents; "
            f"expected {EXPECTED_CHILDREN}/{EXPECTED_SPLIT_PARENTS}"
        )
    return result


def load_legacy_child_classification_policy(
    path: Path = DEFAULT_POLICY,
    *,
    subpart_audit_path: Path = DEFAULT_SUBPART_AUDIT,
    inventory_path: Path = DEFAULT_INVENTORY,
) -> LegacyChildClassificationPolicy:
    raw = _read_json(path)
    audit = _read_json(subpart_audit_path)
    inventory = _inventory(inventory_path)
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise LegacyChildClassificationError("Child policy schema version drifted")
    if raw.get("database_writes_performed") is not False:
        raise LegacyChildClassificationError("Child policy must remain staging-only")
    if raw.get("production_import_authorized") is not False:
        raise LegacyChildClassificationError("Child policy cannot authorize import")
    scope = raw.get("scope")
    if not isinstance(scope, dict):
        raise LegacyChildClassificationError("Child policy scope is missing")
    audit_sha = _sha256_file(subpart_audit_path)
    inventory_sha = _sha256_file(inventory_path)
    if (
        scope.get("materialized_child_count") != EXPECTED_CHILDREN
        or scope.get("split_parent_count") != EXPECTED_SPLIT_PARENTS
        or scope.get("legacy_subpart_audit_sha256") != audit_sha
        or scope.get("canonical_inventory_sha256") != inventory_sha
    ):
        raise LegacyChildClassificationError("Child policy input bindings drifted")

    source = _source_children(audit)
    rows = raw.get("child_decisions")
    if not isinstance(rows, list):
        raise LegacyChildClassificationError("Child decisions are missing")
    decisions: dict[tuple[str, int, str], LegacyChildDecision] = {}
    outcomes: Counter[str] = Counter()
    for row in rows:
        if not isinstance(row, dict):
            raise LegacyChildClassificationError("Malformed child decision")
        key = _child_key(
            str(row.get("paper_id") or ""),
            row.get("parent_canonical_ordinal"),
            row.get("child_item_label"),
        )
        if key in decisions or key not in source:
            raise LegacyChildClassificationError(f"Duplicate or unknown child {key}")
        evidence_sha, excerpt = child_evidence(source[key], key=key)
        if row.get("evidence_sha256") != evidence_sha or row.get("evidence_excerpt") != excerpt:
            raise LegacyChildClassificationError(f"{key}: evidence binding drifted")
        decision = row.get("decision")
        course = row.get("canonical_course")
        topic = row.get("canonical_topic")
        if decision == "map":
            if course not in inventory or topic not in inventory[course]:
                raise LegacyChildClassificationError(
                    f"{key}: {course}/{topic} is absent from canonical inventory"
                )
        elif decision in {"out_of_syllabus", "review"}:
            if course is not None or topic is not None:
                raise LegacyChildClassificationError(
                    f"{key}: non-map decision cannot carry a topic"
                )
        else:
            raise LegacyChildClassificationError(f"{key}: invalid decision {decision!r}")
        reason_code = row.get("reason_code")
        reason = row.get("reason")
        comparison = row.get("parent_comparison")
        if (
            not isinstance(reason_code, str)
            or not reason_code
            or not isinstance(reason, str)
            or not reason
            or comparison
            not in {"same_as_parent", "differs_from_parent", "parent_unresolved"}
        ):
            raise LegacyChildClassificationError(f"{key}: audit rationale is incomplete")
        decisions[key] = LegacyChildDecision(
            paper_id=key[0],
            parent_canonical_ordinal=key[1],
            child_item_label=key[2],
            decision=decision,
            course=course,
            topic=topic,
            reason_code=reason_code,
            reason=reason,
            evidence_sha256=evidence_sha,
            evidence_excerpt=excerpt,
            parent_comparison=comparison,
        )
        outcomes[decision] += 1

    if set(decisions) != set(source):
        missing = sorted(set(source) - set(decisions))[:5]
        extra = sorted(set(decisions) - set(source))[:5]
        raise LegacyChildClassificationError(
            f"Child policy coverage mismatch; missing={missing}, extra={extra}"
        )
    expected_summary = raw.get("summary")
    observed_summary = {
        "mapped": outcomes["map"],
        "out_of_syllabus": outcomes["out_of_syllabus"],
        "review": outcomes["review"],
    }
    if expected_summary != observed_summary:
        raise LegacyChildClassificationError(
            f"Child outcome summary drifted: {observed_summary}"
        )
    return LegacyChildClassificationPolicy(
        policy_version=str(raw.get("policy_version") or ""),
        source_sha256=_sha256_file(path),
        subpart_audit_sha256=audit_sha,
        inventory_sha256=inventory_sha,
        decisions=decisions,
        outcome_counts=observed_summary,
    )
