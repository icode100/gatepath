"""Copy only promotion-approved PYQ PNGs into the deployable web root.

The release archive is authoritative: an image is copied only when its
question is ``practice_eligible`` and the release item contains an approved
asset reference.  Archive-only and review assets are ignored even when a crop
exists under ``tmp/``.  No-argument operation is bound to the tracked
publication, report, and proof; ignored staging inputs require ``--staging``
or a complete explicit path set.  Every copied byte is checked against the
release SHA-256 before and after the copy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPOSITORY_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(BACKEND_DIR / "scripts"))

from app.pyq_archive import (  # noqa: E402
    PyqArchiveDocument,
    _validate_document,
)
from app.question_assets import (  # noqa: E402
    public_question_asset,
    source_asset_parts,
)
import publish_pyq_release as publication  # noqa: E402


STAGING_RELEASE = (
    REPOSITORY_ROOT / "tmp" / "pyq" / "build" / "promoted_pyq_release.json"
)
STAGING_ALLOWLIST = (
    REPOSITORY_ROOT
    / "tmp"
    / "pyq"
    / "build"
    / "promoted_pyq_release.allowlist.json"
)
STAGING_PROMOTION_REPORT = (
    REPOSITORY_ROOT / "tmp" / "pyq" / "build" / "promoted_pyq_release.report.json"
)
DEFAULT_RELEASE = BACKEND_DIR / "data" / "gate_cs_pyq_practice_1996_2025.json"
DEFAULT_ALLOWLIST = (
    BACKEND_DIR / "data" / "gate_cs_pyq_practice_1996_2025.allowlist.json"
)
DEFAULT_PROMOTION_REPORT = (
    BACKEND_DIR / "data" / "gate_cs_pyq_practice_1996_2025.report.json"
)
DEFAULT_PUBLICATION_PROOF = (
    BACKEND_DIR / "data" / "gate_cs_pyq_publication_1996_2025.proof.json"
)
DEFAULT_PUBLIC_ROOT = REPOSITORY_ROOT / "public" / "question-assets" / "pyq"
DEFAULT_MANIFEST = BACKEND_DIR / "data" / "pyq_question_assets.json"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class QuestionAssetMaterializationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PlannedAsset:
    source_paper_id: str
    item_label: str
    role: str
    source_path: Path
    public_path: Path
    public_url: str
    alt_text: str
    sha256: str


@dataclass(frozen=True, slots=True)
class MaterializationSources:
    release_path: Path
    allowlist_path: Path
    promotion_report_path: Path
    publication_proof_path: Path | None
    staging: bool


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def _load_release(path: Path) -> tuple[PyqArchiveDocument, dict[str, Any], str]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise QuestionAssetMaterializationError(
            f"release artifact cannot be read: {path}"
        ) from exc
    try:
        payload = json.loads(raw)
        document = PyqArchiveDocument.model_validate(payload)
        _validate_document(document)
    except (json.JSONDecodeError, ValueError) as exc:
        raise QuestionAssetMaterializationError(
            f"release artifact is invalid: {exc}"
        ) from exc
    return document, payload, hashlib.sha256(raw).hexdigest()


def _bound_json(
    binding: Any,
    *,
    name: str,
    repository_root: Path,
) -> dict[str, Any]:
    if not isinstance(binding, dict) or set(binding) != {"path", "sha256", "bytes"}:
        raise QuestionAssetMaterializationError(
            f"promotion allowlist {name} binding is invalid"
        )
    raw_path = binding.get("path")
    if (
        not isinstance(raw_path, str)
        or not raw_path
        or "\\" in raw_path
        or Path(raw_path).is_absolute()
        or ".." in Path(raw_path).parts
    ):
        raise QuestionAssetMaterializationError(
            f"promotion allowlist {name} path is unsafe"
        )
    root = repository_root.resolve()
    path = root.joinpath(*Path(raw_path).parts).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise QuestionAssetMaterializationError(
            f"promotion allowlist {name} path escapes the repository"
        ) from exc
    if not path.is_file():
        raise QuestionAssetMaterializationError(
            f"promotion allowlist {name} input is missing: {path}"
        )
    raw = path.read_bytes()
    if (
        binding.get("bytes") != len(raw)
        or binding.get("sha256") != hashlib.sha256(raw).hexdigest()
    ):
        raise QuestionAssetMaterializationError(
            f"promotion allowlist {name} input binding is stale"
        )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise QuestionAssetMaterializationError(
            f"promotion allowlist {name} input is not JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise QuestionAssetMaterializationError(
            f"promotion allowlist {name} input must be an object"
        )
    return payload


def _validate_allowlist(
    path: Path,
    *,
    release_payload: dict[str, Any],
    document: PyqArchiveDocument,
    repository_root: Path,
) -> tuple[dict[str, Any], str]:
    try:
        raw = path.read_bytes()
        allowlist = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise QuestionAssetMaterializationError(
            f"promotion allowlist cannot be read: {path}"
        ) from exc
    if not isinstance(allowlist, dict):
        raise QuestionAssetMaterializationError("promotion allowlist must be an object")
    embedded = allowlist.get("artifact_sha256")
    core = {key: value for key, value in allowlist.items() if key != "artifact_sha256"}
    if embedded != _canonical_sha256(core):
        raise QuestionAssetMaterializationError("promotion allowlist checksum is invalid")
    required_guards = {
        "database_writes_performed": False,
        "production_import_authorized": True,
        "practice_materialization_authorized": True,
        "unlisted_promotion_authorized": False,
        "selection_policy_fail_closed": True,
    }
    if allowlist.get("schema_version") != "1.0-pyq-practice-promotion-allowlist":
        raise QuestionAssetMaterializationError("promotion allowlist schema is invalid")
    if allowlist.get("source_role") != "exact_production_practice_materialization_authorization":
        raise QuestionAssetMaterializationError("promotion allowlist source role is invalid")
    if any(allowlist.get(key) is not expected for key, expected in required_guards.items()):
        raise QuestionAssetMaterializationError("promotion allowlist guards are invalid")
    bindings = allowlist.get("input_bindings")
    if not isinstance(bindings, dict) or set(bindings) != {
        "staging_release",
        "staging_release_report",
    }:
        raise QuestionAssetMaterializationError(
            "promotion allowlist input bindings are invalid"
        )
    source_release = _bound_json(
        bindings["staging_release"],
        name="staging release",
        repository_root=repository_root,
    )
    source_report = _bound_json(
        bindings["staging_release_report"],
        name="staging release report",
        repository_root=repository_root,
    )
    try:
        source_document = PyqArchiveDocument.model_validate(source_release)
        _validate_document(source_document)
    except ValueError as exc:
        raise QuestionAssetMaterializationError(
            f"bound staging release is invalid: {exc}"
        ) from exc
    if any(item.practice_eligible for item in source_document.questions):
        raise QuestionAssetMaterializationError(
            "bound staging release already contains promoted rows"
        )
    source_release_sha256 = _canonical_sha256(source_release)
    if allowlist.get("source_release_artifact_sha256") != source_release_sha256:
        raise QuestionAssetMaterializationError(
            "promotion allowlist source release checksum is invalid"
        )
    report_core = {
        key: value for key, value in source_report.items() if key != "report_sha256"
    }
    if (
        source_report.get("schema_version") != "1.0-staging-final-pyq-release"
        or source_report.get("artifact_version") != source_release.get("artifact_version")
        or source_report.get("artifact_sha256") != source_release_sha256
        or source_report.get("report_sha256") != _canonical_sha256(report_core)
        or allowlist.get("source_release_report_sha256")
        != source_report.get("report_sha256")
        or any(
            source_report.get(field) is not False
            for field in (
                "database_writes_performed",
                "production_import_authorized",
                "automatic_promotion_allowed",
            )
        )
    ):
        raise QuestionAssetMaterializationError(
            "promotion allowlist source release report is invalid"
        )
    report_counts = source_report.get("counts")
    if (
        not isinstance(report_counts, dict)
        or report_counts.get("expanded_archive_records") != len(source_document.questions)
        or report_counts.get("archival_complete") != len(source_document.questions)
        or report_counts.get("practice_eligible") != 0
    ):
        raise QuestionAssetMaterializationError(
            "promotion allowlist source release report counts are invalid"
        )
    if allowlist.get("promoted_archive_artifact_sha256") != _canonical_sha256(
        release_payload
    ):
        raise QuestionAssetMaterializationError(
            "promotion allowlist is not bound to the promoted archive"
        )
    records = allowlist.get("records")
    if not isinstance(records, list):
        raise QuestionAssetMaterializationError("promotion allowlist records are invalid")
    if allowlist.get("selection_sha256") != _canonical_sha256(records):
        raise QuestionAssetMaterializationError("promotion selection checksum is invalid")
    try:
        if any(
            not isinstance(item, dict)
            or set(item)
            != {
                "source_paper_id",
                "ordinal",
                "item_label",
                "source_content_sha256",
            }
            for item in records
        ):
            raise ValueError("record fields")
        allowlisted = {
            (str(item["source_paper_id"]), int(item["ordinal"])) for item in records
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise QuestionAssetMaterializationError(
            "promotion allowlist contains an invalid identity"
        ) from exc
    if len(allowlisted) != len(records):
        raise QuestionAssetMaterializationError("promotion allowlist identities are duplicated")
    promoted = {
        (item.source_paper_id, item.ordinal)
        for item in document.questions
        if item.practice_eligible
    }
    promoted_by_key = {
        (item.source_paper_id, item.ordinal): item
        for item in document.questions
        if item.practice_eligible
    }
    source_by_key = {
        (item.source_paper_id, item.ordinal): item
        for item in source_document.questions
    }
    label_mismatch = False
    for record in records:
        key = (str(record["source_paper_id"]), int(record["ordinal"]))
        promoted_item = promoted_by_key.get(key)
        source_item = source_by_key.get(key)
        source_content_sha256 = str(record.get("source_content_sha256") or "")
        if (
            promoted_item is None
            or source_item is None
            or str(record.get("item_label")) != promoted_item.item_label
            or str(record.get("item_label")) != source_item.item_label
            or source_item.content_sha256 is None
            or source_item.content_sha256.lower() != source_content_sha256
        ):
            label_mismatch = True
            break
    if label_mismatch:
        raise QuestionAssetMaterializationError(
            "promotion allowlist item labels/content hashes do not match its bound releases"
        )
    if (
        allowlisted != promoted
        or allowlist.get("practice_eligible_count") != len(promoted)
        or allowlist.get("archive_record_count") != len(document.questions)
    ):
        raise QuestionAssetMaterializationError(
            "promoted archive does not exactly match the production allowlist"
        )
    return allowlist, hashlib.sha256(raw).hexdigest()


def _validate_promotion_report(
    path: Path,
    *,
    release_payload: dict[str, Any],
    document: PyqArchiveDocument,
    allowlist: dict[str, Any],
) -> None:
    try:
        report = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise QuestionAssetMaterializationError(
            f"promotion report cannot be read: {path}"
        ) from exc
    if not isinstance(report, dict):
        raise QuestionAssetMaterializationError("promotion report must be an object")
    core = {key: value for key, value in report.items() if key != "report_sha256"}
    promoted_count = sum(item.practice_eligible for item in document.questions)
    expected_counts = {
        "papers": len(document.papers),
        "archive_records_preserved": len(document.questions),
        "practice_eligible": promoted_count,
        "archive_only": len(document.questions) - promoted_count,
    }
    if (
        report.get("schema_version") != "1.0-pyq-practice-promotion-report"
        or report.get("report_sha256") != _canonical_sha256(core)
        or report.get("database_writes_performed") is not False
        or report.get("production_import_authorized") is not True
        or report.get("practice_materialization_authorized") is not True
        or report.get("input_bindings") != allowlist.get("input_bindings")
        or report.get("source_release_artifact_sha256")
        != allowlist.get("source_release_artifact_sha256")
        or report.get("source_release_report_sha256")
        != allowlist.get("source_release_report_sha256")
        or report.get("promoted_archive_artifact_sha256")
        != _canonical_sha256(release_payload)
        or report.get("promoted_archive_artifact_sha256")
        != allowlist.get("promoted_archive_artifact_sha256")
        or report.get("allowlist_artifact_sha256")
        != allowlist.get("artifact_sha256")
        or report.get("selection_sha256") != allowlist.get("selection_sha256")
        or report.get("counts") != expected_counts
        or report.get("invariants")
        != {
            "all_archive_records_preserved": True,
            "only_allowlisted_rows_promoted": True,
            "database_writes_disabled": True,
        }
    ):
        raise QuestionAssetMaterializationError(
            "promotion report is stale or inconsistent with the tracked package"
        )


def _validate_tracked_publication(
    *,
    release_path: Path,
    allowlist_path: Path,
    promotion_report_path: Path,
    publication_proof_path: Path,
    repository_root: Path,
) -> None:
    try:
        proof = json.loads(publication_proof_path.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise QuestionAssetMaterializationError(
            f"publication proof cannot be read: {publication_proof_path}"
        ) from exc
    if not isinstance(proof, dict):
        raise QuestionAssetMaterializationError("publication proof must be an object")
    outputs = proof.get("published_outputs")
    if not isinstance(outputs, dict):
        raise QuestionAssetMaterializationError(
            "publication proof output bindings are missing"
        )

    def bound_path(name: str) -> Path:
        binding = outputs.get(name)
        raw_path = binding.get("path") if isinstance(binding, dict) else None
        if (
            not isinstance(raw_path, str)
            or not raw_path
            or "\\" in raw_path
            or Path(raw_path).is_absolute()
            or ".." in Path(raw_path).parts
        ):
            raise QuestionAssetMaterializationError(
                f"publication proof {name} path is unsafe"
            )
        root = repository_root.resolve()
        resolved = root.joinpath(*Path(raw_path).parts).resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise QuestionAssetMaterializationError(
                f"publication proof {name} path escapes the repository"
            ) from exc
        return resolved

    expected = {
        "promotion": release_path.resolve(),
        "allowlist": allowlist_path.resolve(),
        "promotion_report": promotion_report_path.resolve(),
    }
    if any(bound_path(name) != path for name, path in expected.items()):
        raise QuestionAssetMaterializationError(
            "materializer paths do not match the publication proof"
        )
    try:
        publication.validate_published_package(
            staging_path=bound_path("staging"),
            staging_report_path=bound_path("staging_report"),
            promotion_path=expected["promotion"],
            allowlist_path=expected["allowlist"],
            promotion_report_path=expected["promotion_report"],
            proof_path=publication_proof_path.resolve(),
            public_root=repository_root.resolve() / "public",
        )
    except publication.PublicationError as exc:
        raise QuestionAssetMaterializationError(
            f"tracked publication proof validation failed: {exc}"
        ) from exc


def build_plan(
    document: PyqArchiveDocument,
    *,
    repository_root: Path,
    public_root: Path,
) -> list[PlannedAsset]:
    root = repository_root.resolve()
    public = public_root.resolve()
    plan: list[PlannedAsset] = []
    public_identities: dict[Path, tuple[str, str]] = {}
    for question in document.questions:
        # This is the decisive exclusion gate. Existing crops for archive and
        # review rows are deliberately neither read nor copied.
        if not question.practice_eligible:
            continue
        for asset in question.assets:
            projected = public_question_asset(
                asset,
                paper_id=question.source_paper_id,
            )
            source = root.joinpath(
                *source_asset_parts(asset, paper_id=question.source_paper_id)
            ).resolve()
            try:
                source.relative_to(root)
            except ValueError as exc:
                raise QuestionAssetMaterializationError(
                    f"source asset escapes the repository: {source}"
                ) from exc
            if not source.is_file():
                raise QuestionAssetMaterializationError(
                    f"approved source asset is missing: {source}"
                )
            if source.read_bytes()[: len(PNG_SIGNATURE)] != PNG_SIGNATURE:
                raise QuestionAssetMaterializationError(
                    f"approved source asset is not a PNG: {source}"
                )
            actual_sha256 = _sha256(source)
            if actual_sha256 != projected["sha256"]:
                raise QuestionAssetMaterializationError(
                    f"approved source asset checksum mismatch: {source}"
                )
            destination = public / question.source_paper_id / f"{actual_sha256}.png"
            identity = (str(source), actual_sha256)
            previous = public_identities.get(destination)
            if previous is not None and previous != identity:
                raise QuestionAssetMaterializationError(
                    f"two source assets collide at {destination}"
                )
            public_identities[destination] = identity
            plan.append(
                PlannedAsset(
                    source_paper_id=question.source_paper_id,
                    item_label=question.item_label,
                    role=projected["role"],
                    source_path=source,
                    public_path=destination,
                    public_url=projected["url"],
                    alt_text=projected["alt_text"],
                    sha256=actual_sha256,
                )
            )
    if not plan:
        raise QuestionAssetMaterializationError(
            "release contains no promoted question assets; refusing an empty materialization"
        )
    return sorted(
        plan,
        key=lambda item: (
            item.source_paper_id,
            item.item_label,
            item.role,
            item.sha256,
        ),
    )


def _manifest_payload(
    plan: list[PlannedAsset],
    *,
    release_path: Path,
    release_sha256: str,
    allowlist_path: Path,
    allowlist_sha256: str,
    repository_root: Path,
) -> dict[str, Any]:
    unique_files = {item.public_path for item in plan}
    core: dict[str, Any] = {
        "schema_version": "1.0-deployable-promoted-pyq-assets",
        "release_binding": {
            "path": release_path.resolve().relative_to(repository_root.resolve()).as_posix(),
            "sha256": release_sha256,
        },
        "promotion_allowlist_binding": {
            "path": allowlist_path.resolve().relative_to(
                repository_root.resolve()
            ).as_posix(),
            "sha256": allowlist_sha256,
        },
        "counts": {
            "question_asset_references": len(plan),
            "unique_png_files": len(unique_files),
            "source_questions": len(
                {(item.source_paper_id, item.item_label) for item in plan}
            ),
        },
        "assets": [
            {
                "source_paper_id": item.source_paper_id,
                "item_label": item.item_label,
                "role": item.role,
                "source_path": item.source_path.relative_to(
                    repository_root.resolve()
                ).as_posix(),
                "public_url": item.public_url,
                "alt_text": item.alt_text,
                "sha256": item.sha256,
            }
            for item in plan
        ],
        "guards": {
            "practice_eligible_only": True,
            "archive_or_review_assets_included": False,
            "same_origin_png_only": True,
            "checksum_verified_before_and_after_copy": True,
        },
    }
    canonical = json.dumps(
        core, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return {**core, "artifact_sha256": hashlib.sha256(canonical).hexdigest()}


def _encoded(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def materialize(
    *,
    release_path: Path,
    allowlist_path: Path,
    public_root: Path,
    manifest_path: Path,
    repository_root: Path,
    check: bool,
    promotion_report_path: Path | None = None,
    publication_proof_path: Path | None = None,
) -> dict[str, Any]:
    if publication_proof_path is not None:
        if promotion_report_path is None:
            raise QuestionAssetMaterializationError(
                "publication proof requires the bound promotion report"
            )
        _validate_tracked_publication(
            release_path=release_path,
            allowlist_path=allowlist_path,
            promotion_report_path=promotion_report_path,
            publication_proof_path=publication_proof_path,
            repository_root=repository_root,
        )
    document, release_payload, release_sha256 = _load_release(release_path)
    allowlist, allowlist_sha256 = _validate_allowlist(
        allowlist_path,
        release_payload=release_payload,
        document=document,
        repository_root=repository_root,
    )
    if promotion_report_path is not None:
        _validate_promotion_report(
            promotion_report_path,
            release_payload=release_payload,
            document=document,
            allowlist=allowlist,
        )
    plan = build_plan(
        document,
        repository_root=repository_root,
        public_root=public_root,
    )
    expected_files = {item.public_path.resolve() for item in plan}
    existing_files = (
        {path.resolve() for path in public_root.rglob("*.png")}
        if public_root.exists()
        else set()
    )
    unexpected = sorted(existing_files - expected_files)
    if unexpected:
        raise QuestionAssetMaterializationError(
            "deployable asset directory contains unapproved PNGs: "
            + ", ".join(str(path) for path in unexpected)
        )

    manifest = _manifest_payload(
        plan,
        release_path=release_path,
        release_sha256=release_sha256,
        allowlist_path=allowlist_path,
        allowlist_sha256=allowlist_sha256,
        repository_root=repository_root,
    )
    expected_manifest = _encoded(manifest)
    if check:
        missing_or_changed = [
            item.public_path
            for item in plan
            if not item.public_path.is_file()
            or _sha256(item.public_path) != item.sha256
        ]
        if missing_or_changed:
            raise QuestionAssetMaterializationError(
                "deployable PNGs are missing or changed: "
                + ", ".join(str(path) for path in missing_or_changed)
            )
        if not manifest_path.is_file() or manifest_path.read_bytes() != expected_manifest:
            raise QuestionAssetMaterializationError(
                f"asset manifest is missing or stale: {manifest_path}"
            )
        return manifest

    for item in plan:
        item.public_path.parent.mkdir(parents=True, exist_ok=True)
        # A tracked publication already points at the immutable public file.
        # Preserve the same validation/copy contract without asking shutil to
        # copy a file onto itself.
        if item.source_path.resolve() != item.public_path.resolve():
            shutil.copyfile(item.source_path, item.public_path)
        if _sha256(item.public_path) != item.sha256:
            raise QuestionAssetMaterializationError(
                f"copied asset checksum mismatch: {item.public_path}"
            )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_bytes(expected_manifest)
    return manifest


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--staging",
        action="store_true",
        help=(
            "Explicitly use the ignored tmp promotion checkpoint. Without this "
            "flag, no-argument operation is bound to the tracked publication."
        ),
    )
    parser.add_argument("--release", type=Path)
    parser.add_argument("--allowlist", type=Path)
    parser.add_argument("--promotion-report", type=Path)
    parser.add_argument("--publication-proof", type=Path)
    parser.add_argument("--public-root", type=Path, default=DEFAULT_PUBLIC_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify committed assets and manifest without writing files.",
    )
    return parser.parse_args(argv)


def _resolve_cli_sources(args: argparse.Namespace) -> MaterializationSources:
    explicit = {
        "release": args.release,
        "allowlist": args.allowlist,
        "promotion_report": args.promotion_report,
        "publication_proof": args.publication_proof,
    }
    if args.staging:
        if any(value is not None for value in explicit.values()):
            raise QuestionAssetMaterializationError(
                "--staging cannot be combined with explicit package paths"
            )
        return MaterializationSources(
            release_path=STAGING_RELEASE.resolve(),
            allowlist_path=STAGING_ALLOWLIST.resolve(),
            promotion_report_path=STAGING_PROMOTION_REPORT.resolve(),
            publication_proof_path=None,
            staging=True,
        )
    if not any(value is not None for value in explicit.values()):
        return MaterializationSources(
            release_path=DEFAULT_RELEASE.resolve(),
            allowlist_path=DEFAULT_ALLOWLIST.resolve(),
            promotion_report_path=DEFAULT_PROMOTION_REPORT.resolve(),
            publication_proof_path=DEFAULT_PUBLICATION_PROOF.resolve(),
            staging=False,
        )
    required = (args.release, args.allowlist, args.promotion_report)
    if any(value is None for value in required):
        raise QuestionAssetMaterializationError(
            "explicit mode requires --release, --allowlist, and --promotion-report"
        )
    release_path = args.release.resolve()
    allowlist_path = args.allowlist.resolve()
    promotion_report_path = args.promotion_report.resolve()
    tmp_root = (REPOSITORY_ROOT / "tmp").resolve()
    source_paths = (release_path, allowlist_path, promotion_report_path)
    under_tmp = [path.is_relative_to(tmp_root) for path in source_paths]
    if any(under_tmp):
        if not all(under_tmp) or args.publication_proof is not None:
            raise QuestionAssetMaterializationError(
                "explicit staging mode requires all three source paths under tmp "
                "and must not use a publication proof"
            )
        return MaterializationSources(
            release_path=release_path,
            allowlist_path=allowlist_path,
            promotion_report_path=promotion_report_path,
            publication_proof_path=None,
            staging=True,
        )
    if args.publication_proof is None:
        raise QuestionAssetMaterializationError(
            "explicit published paths require --publication-proof"
        )
    return MaterializationSources(
        release_path=release_path,
        allowlist_path=allowlist_path,
        promotion_report_path=promotion_report_path,
        publication_proof_path=args.publication_proof.resolve(),
        staging=False,
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        sources = _resolve_cli_sources(args)
        manifest = materialize(
            release_path=sources.release_path,
            allowlist_path=sources.allowlist_path,
            public_root=args.public_root.resolve(),
            manifest_path=args.manifest.resolve(),
            repository_root=REPOSITORY_ROOT,
            check=args.check,
            promotion_report_path=sources.promotion_report_path,
            publication_proof_path=sources.publication_proof_path,
        )
    except QuestionAssetMaterializationError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(manifest["counts"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
