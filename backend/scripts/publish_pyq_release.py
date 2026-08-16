"""Publish the frozen PYQ release to stable tracked backend/data paths.

The extraction pipeline intentionally builds in ``tmp/``.  Production must not
depend on those workspace-only paths, so this gate validates the exact frozen
five-artifact checkpoint, rebases only package paths, recomputes every
dependent checksum, and writes deterministic tracked JSON files plus a compact
publication proof.  Unpublished lineage is represented by checksum-only
logical identifiers--never by fake local paths.  Question, paper,
classification, answer, asset, and promotion identities are otherwise
unchanged.  No database is opened.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence


REPO_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_DIR / "backend"
DATA_DIR = BACKEND_DIR / "data"
BUILD_DIR = REPO_DIR / "tmp" / "pyq" / "build"
PUBLIC_DIR = REPO_DIR / "public"
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(BACKEND_DIR / "scripts"))

import assemble_pyq_release as release_policy  # noqa: E402
import build_pyq_practice_promotion as promotion_policy  # noqa: E402
from app.pyq_archive import PyqArchiveDocument, _validate_document  # noqa: E402


DEFAULT_STAGING = BUILD_DIR / "final_pyq_release.json"
DEFAULT_STAGING_REPORT = BUILD_DIR / "final_pyq_release.report.json"
DEFAULT_PROMOTION = BUILD_DIR / "promoted_pyq_release.json"
DEFAULT_ALLOWLIST = BUILD_DIR / "promoted_pyq_release.allowlist.json"
DEFAULT_PROMOTION_REPORT = BUILD_DIR / "promoted_pyq_release.report.json"
DEFAULT_ASSET_MANIFEST = DATA_DIR / "pyq_question_assets.json"

DEFAULT_PUBLISHED_STAGING = DATA_DIR / "gate_cs_pyq_archive_1996_2025.json"
DEFAULT_PUBLISHED_STAGING_REPORT = (
    DATA_DIR / "gate_cs_pyq_archive_1996_2025.report.json"
)
DEFAULT_PUBLISHED_PROMOTION = DATA_DIR / "gate_cs_pyq_practice_1996_2025.json"
DEFAULT_PUBLISHED_ALLOWLIST = (
    DATA_DIR / "gate_cs_pyq_practice_1996_2025.allowlist.json"
)
DEFAULT_PUBLISHED_PROMOTION_REPORT = (
    DATA_DIR / "gate_cs_pyq_practice_1996_2025.report.json"
)
DEFAULT_PUBLISHED_PROOF = DATA_DIR / "gate_cs_pyq_publication_1996_2025.proof.json"

PUBLISHER_VERSION = "1.1.0"
PROOF_SCHEMA_VERSION = "1.0-pyq-publication-proof"
LOGICAL_LINEAGE_AVAILABILITY = "checksum_only_not_in_published_package"

FROZEN_FILE_SHA256 = {
    "staging": "86c35b4d75ff443d0adc03ab9cbc5d4045ffec96355d5c5e9a94244541764376",
    "staging_report": "3f79ba79670fb2a6b24f3f9a29dcb73f86f81ab741381121bba0e48b3413a25e",
    "promotion": "63fc50e070488e5720f3fc2d81a82e83111764a03cc002f3ae5b3e96bb2fbe9a",
    "allowlist": "8d8f572ca83ff4f95f247ceb9bf895abe061947b42f6c9a370d33c649d1a5a8c",
    "promotion_report": "a834c32bb1dfe5dab8f1de4e6e030e6034bc90c90c9f3546be35a414dfcde086",
}
FROZEN_EMBEDDED_SHA256 = {
    "staging": "13d2a714efcca47e1ad70923e916751d03dd2cb7f6ba83475277406d05973124",
    "staging_report": "f89fdbfe4428c5c55d0ce13c5c3c38dc46f4064f1761a049ddcd02aeb91a6bba",
    "promotion": "e541deac27b50178ca70a5323f15dfc256b58b615561da56e124e88afa73904c",
    "allowlist": "d4f917fa6d2d930a685f81e7986b7f52fc9ddd6d79020ae34d1a4ddb9a0d5fa5",
    "promotion_report": "20f4b48b35b5319a4c5f1b0cf1b6b76890c0300d1b9badca8bd3e8d32a2687b1",
}
FROZEN_PUBLISHED_PROOF_FILE_SHA256 = (
    "3b44c74015805496edb5b6d9f1a8012825df723c1a1abd042e79f6d7b5e02fee"
)
FROZEN_PUBLISHED_PROOF_ARTIFACT_SHA256 = (
    "55c519bd4ba104fe6248961886fc1c2bef0dc13e14e1d9e434ccd29571d12ad6"
)

EXPECTED_PAPERS = 39
EXPECTED_ARCHIVE_RECORDS = 2873
EXPECTED_PRACTICE_RECORDS = 177
EXPECTED_DEPLOYED_ASSET_REFS = 9
STABLE_ASSET_PREFIX = PurePosixPath("question-assets/pyq")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
WINDOWS_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:[\\/]")


class PublicationError(RuntimeError):
    """Raised when frozen or published PYQ evidence drifts."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublicationError(f"Cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PublicationError(f"{path}: expected a JSON object")
    return value


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise PublicationError(f"Cannot hash {path}: {exc}") from exc
    return digest.hexdigest()


def _render(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _atomic_write(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(value)
    temporary.replace(path)


def _repo_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_DIR).as_posix()
    except ValueError as exc:
        raise PublicationError(f"Published output escapes the repository: {path}") from exc


def _binding_for_rendered(path: Path, value: bytes) -> dict[str, Any]:
    return {
        "path": _repo_relative(path),
        "sha256": _sha256_bytes(value),
        "bytes": len(value),
    }


def _verify_frozen_file(path: Path, expected_sha256: str, *, name: str) -> None:
    observed = _sha256_file(path)
    if observed != expected_sha256:
        raise PublicationError(
            f"Frozen {name} file hash drifted: expected {expected_sha256}, got {observed}"
        )


def _validate_embedded_hash(
    payload: Mapping[str, Any], field: str, expected: str, *, name: str
) -> None:
    if payload.get(field) != expected:
        raise PublicationError(f"Frozen {name} embedded hash drifted")
    core = {key: value for key, value in payload.items() if key != field}
    if _canonical_sha256(core) != expected:
        raise PublicationError(f"Frozen {name} content does not match its embedded hash")


def _published_lineage_binding(raw: Mapping[str, Any]) -> dict[str, Any]:
    path_value = raw.get("path")
    digest = str(raw.get("sha256") or "").casefold()
    size = raw.get("bytes")
    if (
        not isinstance(path_value, str)
        or not path_value
        or "\\" in path_value
        or not HASH_RE.fullmatch(digest)
        or not isinstance(size, int)
        or size <= 0
    ):
        raise PublicationError(f"Malformed lineage binding: {raw!r}")
    path = PurePosixPath(path_value)
    if path.is_absolute() or ".." in path.parts or WINDOWS_ABSOLUTE_RE.match(path_value):
        raise PublicationError(f"Unsafe lineage path: {path_value!r}")
    if path.parts[:2] not in {("backend", "data"), ("tmp", "pyq")}:
        raise PublicationError(f"Unexpected non-stable lineage path: {path_value!r}")
    return {
        "lineage_id": f"sha256:{digest}",
        "sha256": digest,
        "bytes": size,
        "availability": LOGICAL_LINEAGE_AVAILABILITY,
    }


def _stable_asset_path(paper_id: str, digest: str) -> str:
    if not paper_id or "/" in paper_id or "\\" in paper_id:
        raise PublicationError(f"Malformed asset paper id: {paper_id!r}")
    if not HASH_RE.fullmatch(digest):
        raise PublicationError(f"Malformed asset hash: {digest!r}")
    return (STABLE_ASSET_PREFIX / paper_id / f"{digest}.png").as_posix()


def _rebase_archive_assets(archive: Mapping[str, Any]) -> dict[str, Any]:
    published = copy.deepcopy(archive)
    questions = published.get("questions")
    if not isinstance(questions, list):
        raise PublicationError("Archive questions are missing")
    for item in questions:
        if not isinstance(item, dict):
            raise PublicationError("Archive question is malformed")
        paper_id = str(item.get("source_paper_id") or "")
        assets = item.get("assets")
        if not isinstance(assets, list):
            raise PublicationError(f"{paper_id}#{item.get('ordinal')}: assets are malformed")
        for asset in assets:
            if not isinstance(asset, dict):
                raise PublicationError(
                    f"{paper_id}#{item.get('ordinal')}: asset is malformed"
                )
            digest = str(asset.get("sha256") or "").casefold()
            asset["path"] = _stable_asset_path(paper_id, digest)
        item["content_sha256"] = release_policy._content_sha256(item)
    return published


def _rebase_staging_report(
    report: Mapping[str, Any], published_archive: Mapping[str, Any]
) -> dict[str, Any]:
    result = copy.deepcopy(report)
    bindings = result.get("input_bindings")
    if not isinstance(bindings, dict):
        raise PublicationError("Staging report input bindings are missing")
    for name, binding in tuple(bindings.items()):
        if not isinstance(binding, dict):
            raise PublicationError("Staging report binding is malformed")
        bindings[name] = _published_lineage_binding(binding)
    result["artifact_sha256"] = _canonical_sha256(published_archive)
    result.pop("report_sha256", None)
    result["report_sha256"] = _canonical_sha256(result)
    return result


def _selected_records(
    source_allowlist: Mapping[str, Any],
    published_staging: Mapping[str, Any],
    published_promotion: Mapping[str, Any],
) -> list[dict[str, Any]]:
    source_questions = published_staging.get("questions")
    promoted_questions = published_promotion.get("questions")
    records = source_allowlist.get("records")
    if (
        not isinstance(source_questions, list)
        or not isinstance(promoted_questions, list)
        or not isinstance(records, list)
    ):
        raise PublicationError("Promotion questions or allowlist records are malformed")
    source_by_key = {
        (str(item["source_paper_id"]), int(item["ordinal"])): item
        for item in source_questions
    }
    promoted_by_key = {
        (str(item["source_paper_id"]), int(item["ordinal"])): item
        for item in promoted_questions
    }
    result: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, Mapping):
            raise PublicationError("Promotion allowlist record is malformed")
        key = (str(record.get("source_paper_id") or ""), int(record.get("ordinal") or 0))
        source_item = source_by_key.get(key)
        promoted_item = promoted_by_key.get(key)
        if (
            source_item is None
            or promoted_item is None
            or source_item.get("item_label") != record.get("item_label")
            or promoted_item.get("item_label") != record.get("item_label")
        ):
            raise PublicationError(f"Promotion allowlist identity drifted: {key}")
        if source_item.get("practice_eligible") is not False:
            raise PublicationError(f"Staging item is unexpectedly promoted: {key}")
        if promoted_item.get("practice_eligible") is not True:
            raise PublicationError(f"Allowlisted item is not practice eligible: {key}")
        result.append(
            {
                "source_paper_id": key[0],
                "ordinal": key[1],
                "item_label": source_item["item_label"],
                "source_content_sha256": source_item["content_sha256"],
            }
        )
    eligible_keys = {
        (str(item["source_paper_id"]), int(item["ordinal"]))
        for item in promoted_questions
        if item.get("practice_eligible") is True
    }
    if eligible_keys != {(row["source_paper_id"], row["ordinal"]) for row in result}:
        raise PublicationError("Published promotion and allowlist identity sets differ")
    return result


def _rebase_promotion_metadata(
    source_allowlist: Mapping[str, Any],
    source_report: Mapping[str, Any],
    published_staging: Mapping[str, Any],
    published_staging_report: Mapping[str, Any],
    published_promotion: dict[str, Any],
    *,
    staging_binding: Mapping[str, Any],
    staging_report_binding: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    records = _selected_records(
        source_allowlist, published_staging, published_promotion
    )
    selection_sha256 = _canonical_sha256(records)
    source_release_sha256 = _canonical_sha256(published_staging)
    published_promotion["artifact_version"] = (
        f"gate-cs-pyq-practice-{source_release_sha256[:12]}-"
        f"{selection_sha256[:12]}"
    )
    promoted_sha256 = _canonical_sha256(published_promotion)
    source_bindings = {
        "staging_release": dict(staging_binding),
        "staging_release_report": dict(staging_report_binding),
    }

    allowlist = copy.deepcopy(source_allowlist)
    allowlist.update(
        {
            "input_bindings": source_bindings,
            "source_release_artifact_sha256": source_release_sha256,
            "source_release_report_sha256": published_staging_report[
                "report_sha256"
            ],
            "promoted_archive_artifact_sha256": promoted_sha256,
            "selection_sha256": selection_sha256,
            "records": records,
        }
    )
    allowlist.pop("artifact_sha256", None)
    allowlist["artifact_sha256"] = _canonical_sha256(allowlist)

    report = copy.deepcopy(source_report)
    report.update(
        {
            "input_bindings": source_bindings,
            "source_release_artifact_sha256": source_release_sha256,
            "source_release_report_sha256": published_staging_report[
                "report_sha256"
            ],
            "promoted_archive_artifact_sha256": promoted_sha256,
            "allowlist_artifact_sha256": allowlist["artifact_sha256"],
            "selection_sha256": selection_sha256,
        }
    )
    report.pop("report_sha256", None)
    report["report_sha256"] = _canonical_sha256(report)
    return allowlist, report


def _normalized_question(item: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(item)
    result.pop("content_sha256", None)
    for asset in result.get("assets") or []:
        asset.pop("path", None)
    return result


def _assert_archive_equivalent(
    source: Mapping[str, Any], published: Mapping[str, Any], *, allow_version_change: bool
) -> None:
    if source.get("schema_version") != published.get("schema_version"):
        raise PublicationError("Published archive schema drifted")
    if not allow_version_change and source.get("artifact_version") != published.get(
        "artifact_version"
    ):
        raise PublicationError("Published staging version drifted")
    if source.get("papers") != published.get("papers"):
        raise PublicationError("Published paper corpus drifted")
    source_questions = source.get("questions")
    published_questions = published.get("questions")
    if not isinstance(source_questions, list) or not isinstance(published_questions, list):
        raise PublicationError("Published archive questions are malformed")
    if [_normalized_question(item) for item in source_questions] != [
        _normalized_question(item) for item in published_questions
    ]:
        raise PublicationError("Published question, decision, or asset corpus drifted")


def _assert_report_equivalent(
    source: Mapping[str, Any], published: Mapping[str, Any], *, promotion: bool
) -> None:
    ignored = {
        "input_bindings",
        "report_sha256",
        "source_release_artifact_sha256",
        "source_release_report_sha256",
        "promoted_archive_artifact_sha256",
        "allowlist_artifact_sha256",
        "selection_sha256",
    }
    if not promotion:
        ignored = {"input_bindings", "report_sha256", "artifact_sha256"}
    if {key: value for key, value in source.items() if key not in ignored} != {
        key: value for key, value in published.items() if key not in ignored
    }:
        raise PublicationError("Published report decisions or counts drifted")


def _assert_allowlist_equivalent(
    source: Mapping[str, Any], published: Mapping[str, Any]
) -> None:
    source_records = source.get("records")
    published_records = published.get("records")
    if not isinstance(source_records, list) or not isinstance(published_records, list):
        raise PublicationError("Published allowlist records are malformed")
    identity = lambda row: (  # noqa: E731
        row.get("source_paper_id"),
        row.get("ordinal"),
        row.get("item_label"),
    )
    if [identity(row) for row in source_records] != [
        identity(row) for row in published_records
    ]:
        raise PublicationError("Published allowlist identities drifted")
    ignored = {
        "input_bindings",
        "source_release_artifact_sha256",
        "source_release_report_sha256",
        "promoted_archive_artifact_sha256",
        "selection_sha256",
        "records",
        "artifact_sha256",
    }
    if {key: value for key, value in source.items() if key not in ignored} != {
        key: value for key, value in published.items() if key not in ignored
    }:
        raise PublicationError("Published allowlist policy drifted")


def _walk_strings(value: Any) -> Sequence[str]:
    strings: list[str] = []
    if isinstance(value, str):
        strings.append(value)
    elif isinstance(value, Mapping):
        for key, child in value.items():
            strings.extend(_walk_strings(key))
            strings.extend(_walk_strings(child))
    elif isinstance(value, list):
        for child in value:
            strings.extend(_walk_strings(child))
    return strings


def _assert_portable_paths(payloads: Sequence[Mapping[str, Any]]) -> None:
    for payload in payloads:
        for value in _walk_strings(payload):
            if (
                "tmp/" in value
                or "tmp\\" in value
                or WINDOWS_ABSOLUTE_RE.match(value)
                or value.startswith("/home/")
                or value.startswith("/Users/")
            ):
                raise PublicationError(f"Published artifact contains a temporary path: {value}")


def _equivalence_pair(source: Any, published: Any) -> dict[str, Any]:
    source_sha256 = _canonical_sha256(source)
    published_sha256 = _canonical_sha256(published)
    if source_sha256 != published_sha256:
        raise PublicationError("Publication proof corpus-equivalence drifted")
    return {
        "frozen_sha256": source_sha256,
        "published_sha256": published_sha256,
        "equivalent": True,
    }


def _report_projection(report: Mapping[str, Any], *, promotion: bool) -> dict[str, Any]:
    ignored = {
        "input_bindings",
        "report_sha256",
        "source_release_artifact_sha256",
        "source_release_report_sha256",
        "promoted_archive_artifact_sha256",
        "allowlist_artifact_sha256",
        "selection_sha256",
    }
    if not promotion:
        ignored = {"input_bindings", "report_sha256", "artifact_sha256"}
    return {key: copy.deepcopy(value) for key, value in report.items() if key not in ignored}


def _allowlist_projection(allowlist: Mapping[str, Any]) -> dict[str, Any]:
    records = allowlist.get("records")
    if not isinstance(records, list):
        raise PublicationError("Promotion allowlist records are malformed")
    identities = [
        {
            "source_paper_id": row.get("source_paper_id"),
            "ordinal": row.get("ordinal"),
            "item_label": row.get("item_label"),
        }
        for row in records
    ]
    ignored = {
        "input_bindings",
        "source_release_artifact_sha256",
        "source_release_report_sha256",
        "promoted_archive_artifact_sha256",
        "selection_sha256",
        "records",
        "artifact_sha256",
    }
    return {
        "policy": {
            key: copy.deepcopy(value)
            for key, value in allowlist.items()
            if key not in ignored
        },
        "identities": identities,
    }


def _asset_rebinding_map(
    source_archive: Mapping[str, Any], published_archive: Mapping[str, Any]
) -> list[dict[str, Any]]:
    source_questions = source_archive.get("questions")
    published_questions = published_archive.get("questions")
    if not isinstance(source_questions, list) or not isinstance(published_questions, list):
        raise PublicationError("Asset rebinding archive questions are malformed")
    published_by_key = {
        (str(row.get("source_paper_id") or ""), int(row.get("ordinal") or 0)): row
        for row in published_questions
    }
    result: list[dict[str, Any]] = []
    for source_item in source_questions:
        key = (
            str(source_item.get("source_paper_id") or ""),
            int(source_item.get("ordinal") or 0),
        )
        published_item = published_by_key.get(key)
        if not isinstance(published_item, Mapping):
            raise PublicationError(f"Asset rebinding identity missing: {key}")
        source_assets = source_item.get("assets") or []
        published_assets = published_item.get("assets") or []
        if len(source_assets) != len(published_assets):
            raise PublicationError(f"Asset rebinding count drifted: {key}")
        for source_asset, published_asset in zip(
            source_assets, published_assets, strict=True
        ):
            digest = str(source_asset.get("sha256") or "").casefold()
            role = str(source_asset.get("kind") or "")
            if (
                digest != str(published_asset.get("sha256") or "").casefold()
                or role != str(published_asset.get("kind") or "")
            ):
                raise PublicationError(f"Asset rebinding identity drifted: {key}")
            target = _stable_asset_path(key[0], digest)
            if published_asset.get("path") != target:
                raise PublicationError(f"Asset rebinding target drifted: {key}")
            result.append(
                {
                    "source_paper_id": key[0],
                    "ordinal": key[1],
                    "item_label": source_item.get("item_label"),
                    "role": role,
                    "asset_lineage_id": f"sha256:{digest}",
                    "target_path": target,
                }
            )
    return result


def _lineage_rebinding_map(
    source_report: Mapping[str, Any], published_report: Mapping[str, Any]
) -> list[dict[str, Any]]:
    source_bindings = source_report.get("input_bindings")
    published_bindings = published_report.get("input_bindings")
    if not isinstance(source_bindings, Mapping) or not isinstance(
        published_bindings, Mapping
    ):
        raise PublicationError("Publication proof lineage bindings are missing")
    if set(source_bindings) != set(published_bindings):
        raise PublicationError("Publication proof lineage key set drifted")
    result: list[dict[str, Any]] = []
    for name in sorted(source_bindings):
        source = source_bindings[name]
        published = published_bindings[name]
        if not isinstance(source, Mapping) or not isinstance(published, Mapping):
            raise PublicationError("Publication proof lineage binding is malformed")
        digest = str(source.get("sha256") or "").casefold()
        size = source.get("bytes")
        if published.get("sha256") != digest or published.get("bytes") != size:
            raise PublicationError(f"Publication proof lineage drifted: {name}")
        if "lineage_id" in published:
            result.append(
                {
                    "name": name,
                    "mode": "checksum_only",
                    "source_lineage_id": f"sha256:{digest}",
                    "published_lineage_id": published.get("lineage_id"),
                    "sha256": digest,
                    "bytes": size,
                }
            )
        else:
            result.append(
                {
                    "name": name,
                    "mode": "tracked_file",
                    "published_path": published.get("path"),
                    "sha256": digest,
                    "bytes": size,
                }
            )
    return result


def _rendered_output_binding(
    path: Path,
    payload: Mapping[str, Any],
    *,
    content_sha256: str,
    content_hash_role: str,
) -> dict[str, Any]:
    rendered = _render(payload)
    return {
        "path": _repo_relative(path),
        "file_sha256": _sha256_bytes(rendered),
        "bytes": len(rendered),
        "content_sha256": content_sha256,
        "content_hash_role": content_hash_role,
    }


def _build_publication_proof(
    *,
    source_paths: Mapping[str, Path],
    source_staging: Mapping[str, Any],
    source_staging_report: Mapping[str, Any],
    source_promotion: Mapping[str, Any],
    source_allowlist: Mapping[str, Any],
    source_promotion_report: Mapping[str, Any],
    published_paths: Mapping[str, Path],
    published_staging: Mapping[str, Any],
    published_staging_report: Mapping[str, Any],
    published_promotion: Mapping[str, Any],
    published_allowlist: Mapping[str, Any],
    published_promotion_report: Mapping[str, Any],
) -> dict[str, Any]:
    frozen_payloads = {
        "staging": (source_staging, _canonical_sha256(source_staging), "canonical_json"),
        "staging_report": (
            source_staging_report,
            str(source_staging_report.get("report_sha256") or ""),
            "embedded_report_sha256",
        ),
        "promotion": (
            source_promotion,
            _canonical_sha256(source_promotion),
            "canonical_json",
        ),
        "allowlist": (
            source_allowlist,
            str(source_allowlist.get("artifact_sha256") or ""),
            "embedded_artifact_sha256",
        ),
        "promotion_report": (
            source_promotion_report,
            str(source_promotion_report.get("report_sha256") or ""),
            "embedded_report_sha256",
        ),
    }
    frozen_sources: dict[str, Any] = {}
    for name, (_, content_sha256, hash_role) in frozen_payloads.items():
        frozen_sources[name] = {
            "file_sha256": FROZEN_FILE_SHA256[name],
            "bytes": source_paths[name].stat().st_size,
            "content_sha256": content_sha256,
            "content_hash_role": hash_role,
        }

    published_outputs = {
        "staging": _rendered_output_binding(
            published_paths["staging"],
            published_staging,
            content_sha256=_canonical_sha256(published_staging),
            content_hash_role="canonical_json",
        ),
        "staging_report": _rendered_output_binding(
            published_paths["staging_report"],
            published_staging_report,
            content_sha256=str(published_staging_report["report_sha256"]),
            content_hash_role="embedded_report_sha256",
        ),
        "promotion": _rendered_output_binding(
            published_paths["promotion"],
            published_promotion,
            content_sha256=_canonical_sha256(published_promotion),
            content_hash_role="canonical_json",
        ),
        "allowlist": _rendered_output_binding(
            published_paths["allowlist"],
            published_allowlist,
            content_sha256=str(published_allowlist["artifact_sha256"]),
            content_hash_role="embedded_artifact_sha256",
        ),
        "promotion_report": _rendered_output_binding(
            published_paths["promotion_report"],
            published_promotion_report,
            content_sha256=str(published_promotion_report["report_sha256"]),
            content_hash_role="embedded_report_sha256",
        ),
    }
    corpus_equivalence = {
        "staging_papers": _equivalence_pair(
            source_staging.get("papers"), published_staging.get("papers")
        ),
        "staging_questions": _equivalence_pair(
            [_normalized_question(row) for row in source_staging.get("questions") or []],
            [
                _normalized_question(row)
                for row in published_staging.get("questions") or []
            ],
        ),
        "promotion_papers": _equivalence_pair(
            source_promotion.get("papers"), published_promotion.get("papers")
        ),
        "promotion_questions": _equivalence_pair(
            [
                _normalized_question(row)
                for row in source_promotion.get("questions") or []
            ],
            [
                _normalized_question(row)
                for row in published_promotion.get("questions") or []
            ],
        ),
        "staging_report_decisions": _equivalence_pair(
            _report_projection(source_staging_report, promotion=False),
            _report_projection(published_staging_report, promotion=False),
        ),
        "promotion_allowlist_policy_and_identities": _equivalence_pair(
            _allowlist_projection(source_allowlist),
            _allowlist_projection(published_allowlist),
        ),
        "promotion_report_decisions": _equivalence_pair(
            _report_projection(source_promotion_report, promotion=True),
            _report_projection(published_promotion_report, promotion=True),
        ),
    }
    asset_rebindings = _asset_rebinding_map(source_staging, published_staging)
    proof_core = {
        "schema_version": PROOF_SCHEMA_VERSION,
        "publisher_version": PUBLISHER_VERSION,
        "database_writes_performed": False,
        "production_import_authorized": False,
        "automatic_promotion_allowed": False,
        "source_lineage_files_published": False,
        "frozen_sources": frozen_sources,
        "published_outputs": published_outputs,
        "lineage_rebindings": _lineage_rebinding_map(
            source_staging_report, published_staging_report
        ),
        "asset_rebindings": asset_rebindings,
        "corpus_equivalence": corpus_equivalence,
        "counts": {
            "papers": EXPECTED_PAPERS,
            "archive_records": EXPECTED_ARCHIVE_RECORDS,
            "practice_eligible": EXPECTED_PRACTICE_RECORDS,
            "asset_references_rebased": len(asset_rebindings),
            "promoted_asset_references": EXPECTED_DEPLOYED_ASSET_REFS,
        },
    }
    artifact_sha256 = _canonical_sha256(proof_core)
    if artifact_sha256 != FROZEN_PUBLISHED_PROOF_ARTIFACT_SHA256:
        raise PublicationError("Published proof content drifted from the frozen package")
    proof = {**proof_core, "artifact_sha256": artifact_sha256}
    if _sha256_bytes(_render(proof)) != FROZEN_PUBLISHED_PROOF_FILE_SHA256:
        raise PublicationError("Published proof file rendering drifted")
    return proof


def _asset_manifest_map(
    manifest: Mapping[str, Any], *, public_root: Path
) -> dict[tuple[str, str, str, str], str]:
    embedded = manifest.get("artifact_sha256")
    if not isinstance(embedded, str) or not HASH_RE.fullmatch(embedded):
        raise PublicationError("Asset manifest embedded hash is missing")
    core = {key: value for key, value in manifest.items() if key != "artifact_sha256"}
    if _canonical_sha256(core) != embedded:
        raise PublicationError("Asset manifest embedded hash drifted")
    if manifest.get("schema_version") != "1.0-deployable-promoted-pyq-assets":
        raise PublicationError("Asset manifest schema drifted")
    if manifest.get("counts") != {
        "question_asset_references": EXPECTED_DEPLOYED_ASSET_REFS,
        "unique_png_files": EXPECTED_DEPLOYED_ASSET_REFS,
        "source_questions": EXPECTED_DEPLOYED_ASSET_REFS,
    }:
        raise PublicationError("Asset manifest counts drifted")
    if manifest.get("guards") != {
        "practice_eligible_only": True,
        "archive_or_review_assets_included": False,
        "same_origin_png_only": True,
        "checksum_verified_before_and_after_copy": True,
    }:
        raise PublicationError("Asset manifest guards drifted")
    result: dict[tuple[str, str, str, str], str] = {}
    assets = manifest.get("assets")
    if not isinstance(assets, list):
        raise PublicationError("Asset manifest records are missing")
    for row in assets:
        if not isinstance(row, Mapping):
            raise PublicationError("Asset manifest record is malformed")
        digest = str(row.get("sha256") or "").casefold()
        paper_id = str(row.get("source_paper_id") or "")
        item_label = str(row.get("item_label") or "")
        role = str(row.get("role") or "")
        stable = _stable_asset_path(paper_id, digest)
        if row.get("public_url") != "/" + stable:
            raise PublicationError(f"Asset manifest public route drifted: {paper_id}/{item_label}")
        target = public_root / PurePosixPath(stable)
        if not target.is_file() or _sha256_file(target) != digest:
            raise PublicationError(f"Published practice asset is missing or stale: {target}")
        key = paper_id, item_label, role, digest
        if key in result:
            raise PublicationError(f"Asset manifest identity duplicated: {key}")
        result[key] = stable
    return result


def _validate_runtime_asset_visibility(
    published_promotion: Mapping[str, Any],
    deployed: Mapping[tuple[str, str, str, str], str],
    *,
    public_root: Path,
) -> None:
    promoted_refs = 0
    for item in published_promotion.get("questions") or []:
        assets = item.get("assets") or []
        for asset in assets:
            digest = str(asset.get("sha256") or "").casefold()
            key = (
                str(item.get("source_paper_id") or ""),
                str(item.get("item_label") or ""),
                str(asset.get("kind") or ""),
                digest,
            )
            stable = _stable_asset_path(key[0], digest)
            if asset.get("path") != stable:
                raise PublicationError(f"Published asset path drifted: {key}")
            exists = (public_root / PurePosixPath(stable)).is_file()
            if item.get("practice_eligible") is True:
                promoted_refs += 1
                if deployed.get(key) != stable or not exists:
                    raise PublicationError(
                        f"Practice row would expose a missing asset: {key}"
                    )
            elif not exists and item.get("practice_eligible") is not False:
                raise PublicationError(
                    f"Undeployed archive asset is not fail-closed: {key}"
                )
    if promoted_refs != EXPECTED_DEPLOYED_ASSET_REFS:
        raise PublicationError("Promoted asset reference count drifted")


def _published_lineage_map(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    bindings = report.get("input_bindings")
    if not isinstance(bindings, Mapping):
        raise PublicationError("Published report input bindings are missing")
    result: list[dict[str, Any]] = []
    for name in sorted(bindings):
        binding = bindings[name]
        if not isinstance(binding, Mapping):
            raise PublicationError(f"Published lineage binding is malformed: {name}")
        digest = str(binding.get("sha256") or "").casefold()
        size = binding.get("bytes")
        if not HASH_RE.fullmatch(digest) or not isinstance(size, int) or size <= 0:
            raise PublicationError(f"Published lineage checksum is malformed: {name}")
        if "lineage_id" in binding:
            if set(binding) != {"lineage_id", "sha256", "bytes", "availability"}:
                raise PublicationError(f"Logical lineage fields drifted: {name}")
            if (
                binding.get("lineage_id") != f"sha256:{digest}"
                or binding.get("availability") != LOGICAL_LINEAGE_AVAILABILITY
            ):
                raise PublicationError(f"Logical lineage identity drifted: {name}")
            result.append(
                {
                    "name": name,
                    "mode": "checksum_only",
                    "source_lineage_id": f"sha256:{digest}",
                    "published_lineage_id": f"sha256:{digest}",
                    "sha256": digest,
                    "bytes": size,
                }
            )
            continue
        if set(binding) != {"path", "sha256", "bytes"}:
            raise PublicationError(f"Tracked lineage fields drifted: {name}")
        raw_path = binding.get("path")
        if not isinstance(raw_path, str) or not raw_path.startswith("backend/data/"):
            raise PublicationError(f"Tracked lineage path is not stable: {name}")
        path = (REPO_DIR / PurePosixPath(raw_path)).resolve()
        try:
            path.relative_to(DATA_DIR.resolve())
        except ValueError as exc:
            raise PublicationError(f"Tracked lineage escapes backend/data: {name}") from exc
        if (
            not path.is_file()
            or path.stat().st_size != size
            or _sha256_file(path) != digest
        ):
            raise PublicationError(f"Tracked lineage file drifted: {name}")
        result.append(
            {
                "name": name,
                "mode": "tracked_file",
                "published_path": raw_path,
                "sha256": digest,
                "bytes": size,
            }
        )
    return result


def _validate_published_asset_files(
    promotion: Mapping[str, Any], *, public_root: Path
) -> int:
    root = public_root.resolve(strict=True)
    promoted_refs = 0
    for item in promotion.get("questions") or []:
        if item.get("practice_eligible") is not True:
            continue
        paper_id = str(item.get("source_paper_id") or "")
        for asset in item.get("assets") or []:
            digest = str(asset.get("sha256") or "").casefold()
            stable = _stable_asset_path(paper_id, digest)
            if asset.get("path") != stable:
                raise PublicationError(
                    f"Published practice asset route drifted: {paper_id}/{item.get('item_label')}"
                )
            candidate = public_root / PurePosixPath(stable)
            cursor = public_root
            for part in PurePosixPath(stable).parts:
                cursor = cursor / part
                if cursor.is_symlink():
                    raise PublicationError("Published practice asset contains a symlink")
            try:
                target = candidate.resolve(strict=True)
                target.relative_to(root)
            except (OSError, ValueError) as exc:
                raise PublicationError("Published practice asset is missing or unsafe") from exc
            if not target.is_file() or _sha256_file(target) != digest:
                raise PublicationError("Published practice asset checksum drifted")
            header = target.read_bytes()[:24]
            if (
                len(header) < 24
                or header[:8] != b"\x89PNG\r\n\x1a\n"
                or header[12:16] != b"IHDR"
                or not 0 < int.from_bytes(header[16:20], "big") <= 100_000
                or not 0 < int.from_bytes(header[20:24], "big") <= 100_000
            ):
                raise PublicationError("Published practice asset is not a safe PNG")
            promoted_refs += 1
    if promoted_refs != EXPECTED_DEPLOYED_ASSET_REFS:
        raise PublicationError("Published practice asset count drifted")
    return promoted_refs


def validate_published_package(
    *,
    staging_path: Path = DEFAULT_PUBLISHED_STAGING,
    staging_report_path: Path = DEFAULT_PUBLISHED_STAGING_REPORT,
    promotion_path: Path = DEFAULT_PUBLISHED_PROMOTION,
    allowlist_path: Path = DEFAULT_PUBLISHED_ALLOWLIST,
    promotion_report_path: Path = DEFAULT_PUBLISHED_PROMOTION_REPORT,
    proof_path: Path = DEFAULT_PUBLISHED_PROOF,
    public_root: Path = PUBLIC_DIR,
) -> dict[str, Any]:
    paths = {
        "staging": staging_path.resolve(),
        "staging_report": staging_report_path.resolve(),
        "promotion": promotion_path.resolve(),
        "allowlist": allowlist_path.resolve(),
        "promotion_report": promotion_report_path.resolve(),
    }
    for path in (*paths.values(), proof_path.resolve()):
        _repo_relative(path)
    payloads = {name: _read_json(path) for name, path in paths.items()}
    proof = _read_json(proof_path.resolve())
    if _sha256_file(proof_path.resolve()) != FROZEN_PUBLISHED_PROOF_FILE_SHA256:
        raise PublicationError("Published proof file hash drifted")
    _assert_portable_paths((*payloads.values(), proof))
    if proof.get("schema_version") != PROOF_SCHEMA_VERSION:
        raise PublicationError("Published proof schema drifted")
    if proof.get("publisher_version") != PUBLISHER_VERSION:
        raise PublicationError("Published proof publisher version drifted")
    if any(
        proof.get(name) is not False
        for name in (
            "database_writes_performed",
            "production_import_authorized",
            "automatic_promotion_allowed",
            "source_lineage_files_published",
        )
    ):
        raise PublicationError("Published proof guard drifted")
    proof_core = {key: value for key, value in proof.items() if key != "artifact_sha256"}
    if (
        proof.get("artifact_sha256") != FROZEN_PUBLISHED_PROOF_ARTIFACT_SHA256
        or proof.get("artifact_sha256") != _canonical_sha256(proof_core)
    ):
        raise PublicationError("Published proof embedded hash drifted")

    expected_frozen_content = {
        "staging": (FROZEN_EMBEDDED_SHA256["staging"], "canonical_json"),
        "staging_report": (
            FROZEN_EMBEDDED_SHA256["staging_report"],
            "embedded_report_sha256",
        ),
        "promotion": (FROZEN_EMBEDDED_SHA256["promotion"], "canonical_json"),
        "allowlist": (
            FROZEN_EMBEDDED_SHA256["allowlist"],
            "embedded_artifact_sha256",
        ),
        "promotion_report": (
            FROZEN_EMBEDDED_SHA256["promotion_report"],
            "embedded_report_sha256",
        ),
    }
    frozen_sources = proof.get("frozen_sources")
    if not isinstance(frozen_sources, Mapping) or set(frozen_sources) != set(
        FROZEN_FILE_SHA256
    ):
        raise PublicationError("Published proof frozen source set drifted")
    for name, expected_file_sha256 in FROZEN_FILE_SHA256.items():
        binding = frozen_sources[name]
        expected_content_sha256, expected_role = expected_frozen_content[name]
        if (
            not isinstance(binding, Mapping)
            or binding.get("file_sha256") != expected_file_sha256
            or binding.get("content_sha256") != expected_content_sha256
            or binding.get("content_hash_role") != expected_role
            or not isinstance(binding.get("bytes"), int)
            or binding["bytes"] <= 0
        ):
            raise PublicationError(f"Published proof frozen binding drifted: {name}")

    try:
        staging_document = PyqArchiveDocument.model_validate(payloads["staging"])
        promotion_document = PyqArchiveDocument.model_validate(payloads["promotion"])
        _validate_document(staging_document)
        _validate_document(promotion_document)
    except Exception as exc:
        raise PublicationError(f"Published package archive is invalid: {exc}") from exc
    if (
        len(staging_document.papers) != EXPECTED_PAPERS
        or len(promotion_document.papers) != EXPECTED_PAPERS
        or len(staging_document.questions) != EXPECTED_ARCHIVE_RECORDS
        or len(promotion_document.questions) != EXPECTED_ARCHIVE_RECORDS
        or any(item.practice_eligible for item in staging_document.questions)
        or sum(item.practice_eligible for item in promotion_document.questions)
        != EXPECTED_PRACTICE_RECORDS
    ):
        raise PublicationError("Published package inventory drifted")

    staging_report = payloads["staging_report"]
    promotion = payloads["promotion"]
    allowlist = payloads["allowlist"]
    promotion_report = payloads["promotion_report"]
    if staging_report.get("artifact_sha256") != _canonical_sha256(payloads["staging"]):
        raise PublicationError("Published staging report artifact binding drifted")
    _validate_embedded_hash(
        staging_report,
        "report_sha256",
        str(staging_report.get("report_sha256") or ""),
        name="published staging report",
    )
    _validate_embedded_hash(
        allowlist,
        "artifact_sha256",
        str(allowlist.get("artifact_sha256") or ""),
        name="published allowlist",
    )
    _validate_embedded_hash(
        promotion_report,
        "report_sha256",
        str(promotion_report.get("report_sha256") or ""),
        name="published promotion report",
    )
    if allowlist.get("promoted_archive_artifact_sha256") != _canonical_sha256(
        promotion
    ):
        raise PublicationError("Published allowlist promotion binding drifted")

    selected = _selected_records(allowlist, payloads["staging"], promotion)
    if allowlist.get("selection_sha256") != _canonical_sha256(selected):
        raise PublicationError("Published allowlist selection binding drifted")
    if promotion_report.get("selection_sha256") != allowlist.get("selection_sha256"):
        raise PublicationError("Published promotion report selection drifted")
    if promotion_report.get("allowlist_artifact_sha256") != allowlist.get(
        "artifact_sha256"
    ):
        raise PublicationError("Published promotion report allowlist binding drifted")

    outputs = proof.get("published_outputs")
    if not isinstance(outputs, Mapping) or set(outputs) != set(paths):
        raise PublicationError("Published proof output set drifted")
    content_values = {
        "staging": (_canonical_sha256(payloads["staging"]), "canonical_json"),
        "staging_report": (
            staging_report.get("report_sha256"),
            "embedded_report_sha256",
        ),
        "promotion": (_canonical_sha256(promotion), "canonical_json"),
        "allowlist": (
            allowlist.get("artifact_sha256"),
            "embedded_artifact_sha256",
        ),
        "promotion_report": (
            promotion_report.get("report_sha256"),
            "embedded_report_sha256",
        ),
    }
    for name, path in paths.items():
        binding = outputs[name]
        content_sha256, hash_role = content_values[name]
        if (
            not isinstance(binding, Mapping)
            or binding.get("path") != _repo_relative(path)
            or binding.get("file_sha256") != _sha256_file(path)
            or binding.get("bytes") != path.stat().st_size
            or binding.get("content_sha256") != content_sha256
            or binding.get("content_hash_role") != hash_role
        ):
            raise PublicationError(f"Published proof output binding drifted: {name}")

    if proof.get("lineage_rebindings") != _published_lineage_map(staging_report):
        raise PublicationError("Published proof lineage rebinding map drifted")
    observed_equivalence = {
        "staging_papers": payloads["staging"].get("papers"),
        "staging_questions": [
            _normalized_question(row) for row in payloads["staging"].get("questions") or []
        ],
        "promotion_papers": promotion.get("papers"),
        "promotion_questions": [
            _normalized_question(row) for row in promotion.get("questions") or []
        ],
        "staging_report_decisions": _report_projection(
            staging_report, promotion=False
        ),
        "promotion_allowlist_policy_and_identities": _allowlist_projection(
            allowlist
        ),
        "promotion_report_decisions": _report_projection(
            promotion_report, promotion=True
        ),
    }
    equivalence = proof.get("corpus_equivalence")
    if not isinstance(equivalence, Mapping) or set(equivalence) != set(
        observed_equivalence
    ):
        raise PublicationError("Published proof equivalence set drifted")
    for name, observed in observed_equivalence.items():
        digest = _canonical_sha256(observed)
        row = equivalence[name]
        if row != {
            "frozen_sha256": digest,
            "published_sha256": digest,
            "equivalent": True,
        }:
            raise PublicationError(f"Published proof equivalence drifted: {name}")
    if proof.get("asset_rebindings") != _asset_rebinding_map(
        payloads["staging"], payloads["staging"]
    ):
        raise PublicationError("Published proof asset rebinding map drifted")
    promoted_asset_count = _validate_published_asset_files(
        promotion, public_root=public_root
    )
    expected_counts = {
        "papers": EXPECTED_PAPERS,
        "archive_records": EXPECTED_ARCHIVE_RECORDS,
        "practice_eligible": EXPECTED_PRACTICE_RECORDS,
        "asset_references_rebased": len(proof.get("asset_rebindings") or []),
        "promoted_asset_references": promoted_asset_count,
    }
    if proof.get("counts") != expected_counts:
        raise PublicationError("Published proof counts drifted")
    return {
        "database_writes_performed": False,
        "papers": EXPECTED_PAPERS,
        "archive_records": EXPECTED_ARCHIVE_RECORDS,
        "practice_eligible": EXPECTED_PRACTICE_RECORDS,
        "promoted_asset_references": promoted_asset_count,
        "proof_artifact_sha256": proof["artifact_sha256"],
    }


def build_publication(
    *,
    staging_path: Path = DEFAULT_STAGING,
    staging_report_path: Path = DEFAULT_STAGING_REPORT,
    promotion_path: Path = DEFAULT_PROMOTION,
    allowlist_path: Path = DEFAULT_ALLOWLIST,
    promotion_report_path: Path = DEFAULT_PROMOTION_REPORT,
    asset_manifest_path: Path = DEFAULT_ASSET_MANIFEST,
    published_staging_path: Path = DEFAULT_PUBLISHED_STAGING,
    published_staging_report_path: Path = DEFAULT_PUBLISHED_STAGING_REPORT,
    published_promotion_path: Path = DEFAULT_PUBLISHED_PROMOTION,
    published_allowlist_path: Path = DEFAULT_PUBLISHED_ALLOWLIST,
    published_promotion_report_path: Path = DEFAULT_PUBLISHED_PROMOTION_REPORT,
    published_proof_path: Path = DEFAULT_PUBLISHED_PROOF,
    public_root: Path = PUBLIC_DIR,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    source_paths = {
        "staging": staging_path.resolve(),
        "staging_report": staging_report_path.resolve(),
        "promotion": promotion_path.resolve(),
        "allowlist": allowlist_path.resolve(),
        "promotion_report": promotion_report_path.resolve(),
        "asset_manifest": asset_manifest_path.resolve(),
    }
    for name, expected_sha256 in FROZEN_FILE_SHA256.items():
        _verify_frozen_file(source_paths[name], expected_sha256, name=name)

    staging = _read_json(source_paths["staging"])
    staging_report = _read_json(source_paths["staging_report"])
    source_promotion = _read_json(source_paths["promotion"])
    source_allowlist = _read_json(source_paths["allowlist"])
    source_promotion_report = _read_json(source_paths["promotion_report"])
    asset_manifest = _read_json(source_paths["asset_manifest"])
    try:
        staging_document = PyqArchiveDocument.model_validate(staging)
        _validate_document(staging_document)
        promotion_document = PyqArchiveDocument.model_validate(source_promotion)
        _validate_document(promotion_document)
    except Exception as exc:
        raise PublicationError(f"Frozen archive schema validation failed: {exc}") from exc
    if (
        len(staging_document.papers) != EXPECTED_PAPERS
        or len(staging_document.questions) != EXPECTED_ARCHIVE_RECORDS
        or len(promotion_document.questions) != EXPECTED_ARCHIVE_RECORDS
        or sum(item.practice_eligible for item in promotion_document.questions)
        != EXPECTED_PRACTICE_RECORDS
    ):
        raise PublicationError("Frozen archive inventory drifted")
    try:
        promotion_policy._validate_release_report(
            staging,
            staging_report,
            expected_papers=EXPECTED_PAPERS,
            expected_records=EXPECTED_ARCHIVE_RECORDS,
        )
        rebuilt = promotion_policy.build_promotion(
            release_path=source_paths["staging"],
            release_report_path=source_paths["staging_report"],
        )
    except Exception as exc:
        raise PublicationError(f"Frozen promotion validation failed: {exc}") from exc
    if rebuilt != (source_promotion, source_allowlist, source_promotion_report):
        raise PublicationError("Frozen promotion artifacts are not reproducible")
    if _canonical_sha256(staging) != FROZEN_EMBEDDED_SHA256["staging"]:
        raise PublicationError("Frozen staging canonical hash drifted")
    if _canonical_sha256(source_promotion) != FROZEN_EMBEDDED_SHA256["promotion"]:
        raise PublicationError("Frozen promotion canonical hash drifted")
    _validate_embedded_hash(
        staging_report,
        "report_sha256",
        FROZEN_EMBEDDED_SHA256["staging_report"],
        name="staging report",
    )
    _validate_embedded_hash(
        source_allowlist,
        "artifact_sha256",
        FROZEN_EMBEDDED_SHA256["allowlist"],
        name="promotion allowlist",
    )
    _validate_embedded_hash(
        source_promotion_report,
        "report_sha256",
        FROZEN_EMBEDDED_SHA256["promotion_report"],
        name="promotion report",
    )
    deployed = _asset_manifest_map(asset_manifest, public_root=public_root)

    published_staging = _rebase_archive_assets(staging)
    published_staging_report = _rebase_staging_report(
        staging_report, published_staging
    )
    staging_bytes = _render(published_staging)
    staging_report_bytes = _render(published_staging_report)
    staging_binding = _binding_for_rendered(published_staging_path, staging_bytes)
    staging_report_binding = _binding_for_rendered(
        published_staging_report_path, staging_report_bytes
    )

    published_promotion = _rebase_archive_assets(source_promotion)
    published_allowlist, published_promotion_report = _rebase_promotion_metadata(
        source_allowlist,
        source_promotion_report,
        published_staging,
        published_staging_report,
        published_promotion,
        staging_binding=staging_binding,
        staging_report_binding=staging_report_binding,
    )

    _assert_archive_equivalent(staging, published_staging, allow_version_change=False)
    _assert_archive_equivalent(
        source_promotion, published_promotion, allow_version_change=True
    )
    _assert_report_equivalent(
        staging_report, published_staging_report, promotion=False
    )
    _assert_allowlist_equivalent(source_allowlist, published_allowlist)
    _assert_report_equivalent(
        source_promotion_report, published_promotion_report, promotion=True
    )
    _assert_portable_paths(
        (
            published_staging,
            published_staging_report,
            published_promotion,
            published_allowlist,
            published_promotion_report,
        )
    )
    _validate_runtime_asset_visibility(
        published_promotion, deployed, public_root=public_root
    )
    try:
        for archive in (published_staging, published_promotion):
            document = PyqArchiveDocument.model_validate(archive)
            _validate_document(document)
    except Exception as exc:
        raise PublicationError(f"Published archive schema validation failed: {exc}") from exc
    if published_staging_report["artifact_sha256"] != _canonical_sha256(
        published_staging
    ):
        raise PublicationError("Published staging artifact hash drifted")
    if published_allowlist["promoted_archive_artifact_sha256"] != _canonical_sha256(
        published_promotion
    ):
        raise PublicationError("Published promoted artifact hash drifted")
    published_paths = {
        "staging": published_staging_path.resolve(),
        "staging_report": published_staging_report_path.resolve(),
        "promotion": published_promotion_path.resolve(),
        "allowlist": published_allowlist_path.resolve(),
        "promotion_report": published_promotion_report_path.resolve(),
    }
    for path in (*published_paths.values(), published_proof_path.resolve()):
        _repo_relative(path)
    published_proof = _build_publication_proof(
        source_paths=source_paths,
        source_staging=staging,
        source_staging_report=staging_report,
        source_promotion=source_promotion,
        source_allowlist=source_allowlist,
        source_promotion_report=source_promotion_report,
        published_paths=published_paths,
        published_staging=published_staging,
        published_staging_report=published_staging_report,
        published_promotion=published_promotion,
        published_allowlist=published_allowlist,
        published_promotion_report=published_promotion_report,
    )
    _assert_portable_paths((published_proof,))
    return (
        published_staging,
        published_staging_report,
        published_promotion,
        published_allowlist,
        published_promotion_report,
        published_proof,
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staging", type=Path, default=DEFAULT_STAGING)
    parser.add_argument("--staging-report", type=Path, default=DEFAULT_STAGING_REPORT)
    parser.add_argument("--promotion", type=Path, default=DEFAULT_PROMOTION)
    parser.add_argument("--allowlist", type=Path, default=DEFAULT_ALLOWLIST)
    parser.add_argument(
        "--promotion-report", type=Path, default=DEFAULT_PROMOTION_REPORT
    )
    parser.add_argument("--asset-manifest", type=Path, default=DEFAULT_ASSET_MANIFEST)
    parser.add_argument("--output-staging", type=Path, default=DEFAULT_PUBLISHED_STAGING)
    parser.add_argument(
        "--output-staging-report",
        type=Path,
        default=DEFAULT_PUBLISHED_STAGING_REPORT,
    )
    parser.add_argument(
        "--output-promotion", type=Path, default=DEFAULT_PUBLISHED_PROMOTION
    )
    parser.add_argument(
        "--output-allowlist", type=Path, default=DEFAULT_PUBLISHED_ALLOWLIST
    )
    parser.add_argument(
        "--output-promotion-report",
        type=Path,
        default=DEFAULT_PUBLISHED_PROMOTION_REPORT,
    )
    parser.add_argument("--output-proof", type=Path, default=DEFAULT_PUBLISHED_PROOF)
    parser.add_argument("--check", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    output_paths = (
        args.output_staging.resolve(),
        args.output_staging_report.resolve(),
        args.output_promotion.resolve(),
        args.output_allowlist.resolve(),
        args.output_promotion_report.resolve(),
        args.output_proof.resolve(),
    )
    # Validate every destination before reading expensive source artifacts and,
    # critically, before the first atomic write.
    for path in output_paths:
        _repo_relative(path)
    payloads = build_publication(
        staging_path=args.staging,
        staging_report_path=args.staging_report,
        promotion_path=args.promotion,
        allowlist_path=args.allowlist,
        promotion_report_path=args.promotion_report,
        asset_manifest_path=args.asset_manifest,
        published_staging_path=output_paths[0],
        published_staging_report_path=output_paths[1],
        published_promotion_path=output_paths[2],
        published_allowlist_path=output_paths[3],
        published_promotion_report_path=output_paths[4],
        published_proof_path=output_paths[5],
    )
    rendered = tuple(_render(payload) for payload in payloads)
    if args.check:
        stale = [
            str(path)
            for path, value in zip(output_paths, rendered, strict=True)
            if not path.is_file() or path.read_bytes() != value
        ]
        if stale:
            raise PublicationError(f"Published PYQ artifacts are stale: {stale}")
    else:
        for path, value in zip(output_paths, rendered, strict=True):
            _atomic_write(path, value)
    summary = {
        "database_writes_performed": False,
        "outputs": {
            _repo_relative(path): {
                "sha256": _sha256_bytes(value),
                "bytes": len(value),
            }
            for path, value in zip(output_paths, rendered, strict=True)
        },
        "counts": {
            "papers": len(payloads[0]["papers"]),
            "archive_records": len(payloads[0]["questions"]),
            "practice_eligible": sum(
                item["practice_eligible"] for item in payloads[2]["questions"]
            ),
            "promoted_asset_references": sum(
                len(item["assets"])
                for item in payloads[2]["questions"]
                if item["practice_eligible"]
            ),
            "publication_proof": 1,
        },
        "check_only": args.check,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
