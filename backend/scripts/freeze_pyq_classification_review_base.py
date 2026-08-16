"""Freeze the immutable pre-override classification projection.

This is a one-way integrity migration for the second-pass classification
contract.  It reconstructs the already assembler-validated pre-override state
from the applied release plus the existing 82-row override, proves that the
reconstructed projection matches the override's original base hash, and emits
a standalone checksum-bound artifact.  Subsequent override builds consume
only that artifact and never the post-override final release.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping


REPO_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_DIR / "backend"
SCRIPT_DIR = BACKEND_DIR / "scripts"
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(SCRIPT_DIR))

import assemble_pyq_release as assembler  # noqa: E402
import build_pyq_classification_review_overrides as overrides  # noqa: E402


DEFAULT_APPLIED_RELEASE = REPO_DIR / "tmp" / "pyq" / "build" / "final_pyq_release.json"
DEFAULT_OVERRIDE = BACKEND_DIR / "data" / "pyq_classification_review_overrides.json"
DEFAULT_OUTPUT = BACKEND_DIR / "data" / "pyq_classification_review_base.json"


class ClassificationBaseFreezeError(RuntimeError):
    pass


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ClassificationBaseFreezeError(f"Cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ClassificationBaseFreezeError(f"{path}: expected object")
    return value


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _binding_from_override(binding: Mapping[str, Any]) -> dict[str, Any]:
    path = REPO_DIR / str(binding.get("path") or "")
    if (
        not path.is_file()
        or _sha256_file(path) != binding.get("sha256")
        or path.stat().st_size != binding.get("bytes")
    ):
        raise ClassificationBaseFreezeError(f"Stale upstream binding: {path}")
    return dict(binding)


def freeze_base(
    *,
    applied_release_path: Path = DEFAULT_APPLIED_RELEASE,
    override_path: Path = DEFAULT_OVERRIDE,
) -> dict[str, Any]:
    release = _read(applied_release_path)
    override = _read(override_path)
    overrides.validate_artifact(override)
    questions = release.get("questions")
    decisions = override.get("decisions")
    if not isinstance(questions, list) or len(questions) != overrides.EXPECTED_EXPANDED_COUNT:
        raise ClassificationBaseFreezeError("Applied release does not contain 2,873 rows")
    if not isinstance(decisions, list) or len(decisions) != overrides.EXPECTED_REVIEW_COUNT:
        raise ClassificationBaseFreezeError("Existing override does not contain 82 rows")

    by_key: dict[tuple[str, int, str], dict[str, Any]] = {}
    for item in questions:
        key = (
            str(item["source_paper_id"]),
            assembler._release_canonical_parent_ordinal(item),
            str(item["item_label"]),
        )
        if key in by_key:
            raise ClassificationBaseFreezeError(f"Applied identity duplicated: {key}")
        by_key[key] = item

    base_questions = copy.deepcopy(questions)
    base_by_key = {
        (
            str(item["source_paper_id"]),
            assembler._release_canonical_parent_ordinal(item),
            str(item["item_label"]),
        ): item
        for item in base_questions
    }
    review_rows: list[dict[str, Any]] = []
    for decision in decisions:
        key = (
            str(decision["source_paper_id"]),
            int(decision["canonical_parent_ordinal"]),
            str(decision["item_label"]),
        )
        item = base_by_key.get(key)
        if item is None:
            raise ClassificationBaseFreezeError(f"Applied release is missing {key}")
        prior = decision.get("prior_classification") or {}
        item["subject_code"] = prior.get("course")
        item["topic_slug"] = prior.get("topic")
        item["syllabus_status"] = prior.get("syllabus_status")
        item["classification_status"] = prior.get("classification_status")
        item["review_flags"] = list(prior.get("review_flags") or [])
        review_rows.append(
            {
                "source_paper_id": key[0],
                "canonical_parent_ordinal": key[1],
                "item_label": key[2],
                "ordinal": int(prior["final_release_ordinal"]),
                "parent_item_label": item.get("parent_item_label"),
                "source_page": item.get("source_page"),
                "subject_code": prior.get("course"),
                "topic_slug": prior.get("topic"),
                "syllabus_status": prior.get("syllabus_status"),
                "classification_status": prior.get("classification_status"),
                "review_flags": list(prior.get("review_flags") or []),
            }
        )
    review_rows.sort(
        key=lambda row: (row["source_paper_id"], row["canonical_parent_ordinal"])
    )
    projection = overrides._classification_projection(base_questions)
    projection_sha = overrides._canonical_sha256(projection)
    expected_identity = override.get("base_review_identity") or {}
    keys = sorted(overrides._key(row) for row in review_rows)
    identity = {
        "expected_count": len(review_rows),
        "classification_projection_sha256": projection_sha,
        "review_key_sha256": overrides._canonical_sha256(keys),
    }
    if identity != expected_identity:
        raise ClassificationBaseFreezeError(
            "Reconstructed pre-override projection does not match the validated base identity"
        )

    upstream_names = (
        "canonical_archive",
        "legacy_subpart_audit",
        "legacy_child_policy",
        "base_parent_policy",
        "topic_inventory",
        "content_verification_ledger",
        "original_pdf_provenance",
    )
    bindings = override.get("input_bindings") or {}
    upstream_bindings = {
        name: _binding_from_override(bindings[name]) for name in upstream_names
    }
    core = {
        "schema_version": overrides.BASE_SCHEMA_VERSION,
        "source_role": "immutable_pre_override_classification_projection",
        "database_writes_performed": False,
        "production_import_authorized": False,
        "automatic_promotion_allowed": False,
        "input_bindings": upstream_bindings,
        "counts": {
            "expanded_records": len(projection),
            "review_rows": len(review_rows),
        },
        "base_review_identity": identity,
        "classification_projection_sha256": projection_sha,
        "classification_projection": projection,
        "review_rows": review_rows,
    }
    return {**core, "artifact_sha256": overrides._canonical_sha256(core)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    artifact = freeze_base()
    overrides._validated_base_snapshot(artifact)
    rendered = json.dumps(artifact, ensure_ascii=False, indent=2) + "\n"
    if args.check:
        if not args.output.is_file() or args.output.read_text(encoding="utf-8") != rendered:
            raise ClassificationBaseFreezeError(f"Stale base artifact: {args.output}")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "counts": artifact["counts"],
                "artifact_sha256": artifact["artifact_sha256"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
