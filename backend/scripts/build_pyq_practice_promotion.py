"""Build an exact, fail-closed PYQ practice-promotion artifact.

The canonical release remains the immutable 2,873-row archive.  This command
copies every row, flips ``practice_eligible`` only for records that pass the
release assembler's complete auto-grade policy plus local asset validation,
and emits a checksum-bound production allowlist.  It never opens a database.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
REPO_DIR = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import assemble_pyq_release as release_policy  # noqa: E402
from app.pyq_archive import PyqArchiveDocument, _validate_document  # noqa: E402


DEFAULT_RELEASE = REPO_DIR / "tmp" / "pyq" / "build" / "final_pyq_release.json"
DEFAULT_RELEASE_REPORT = (
    REPO_DIR / "tmp" / "pyq" / "build" / "final_pyq_release.report.json"
)
DEFAULT_OUTPUT = REPO_DIR / "tmp" / "pyq" / "build" / "promoted_pyq_release.json"
DEFAULT_ALLOWLIST = (
    REPO_DIR / "tmp" / "pyq" / "build" / "promoted_pyq_release.allowlist.json"
)
DEFAULT_REPORT = (
    REPO_DIR / "tmp" / "pyq" / "build" / "promoted_pyq_release.report.json"
)
EXPECTED_PAPERS = 39
EXPECTED_RECORDS = 2873
HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class PromotionBuildError(ValueError):
    """Raised when immutable release evidence cannot authorize promotion."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PromotionBuildError(f"Cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PromotionBuildError(f"{path}: expected a JSON object")
    return value


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise PromotionBuildError(f"Cannot hash {path}: {exc}") from exc
    return digest.hexdigest()


def _binding(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(REPO_DIR).as_posix()
        rendered = relative
    except ValueError:
        rendered = str(resolved)
    return {
        "path": rendered,
        "sha256": _sha256_file(resolved),
        "bytes": resolved.stat().st_size,
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def _validate_release_report(
    release: Mapping[str, Any],
    report: Mapping[str, Any],
    *,
    expected_papers: int,
    expected_records: int,
) -> None:
    if report.get("schema_version") != release_policy.REPORT_SCHEMA_VERSION:
        raise PromotionBuildError("release report schema drifted")
    for guard in (
        "database_writes_performed",
        "production_import_authorized",
        "automatic_promotion_allowed",
    ):
        if report.get(guard) is not False:
            raise PromotionBuildError(f"release report guard drifted: {guard}")
    report_core = {key: value for key, value in report.items() if key != "report_sha256"}
    if report.get("report_sha256") != _canonical_sha256(report_core):
        raise PromotionBuildError("release report embedded hash drifted")
    if report.get("artifact_version") != release.get("artifact_version"):
        raise PromotionBuildError("release/report versions differ")
    if report.get("artifact_sha256") != _canonical_sha256(release):
        raise PromotionBuildError("release/report artifact hash drifted")
    counts = report.get("counts")
    if not isinstance(counts, Mapping) or any(
        counts.get(name) != expected
        for name, expected in (
            ("papers", expected_papers),
            ("expanded_archive_records", expected_records),
            ("archival_complete", expected_records),
            ("practice_eligible", 0),
        )
    ):
        raise PromotionBuildError("release report count identity drifted")
    bindings = report.get("input_bindings")
    if not isinstance(bindings, Mapping):
        raise PromotionBuildError("release report input bindings are missing")
    if any(
        isinstance(binding, Mapping) and "lineage_id" in binding
        for binding in bindings.values()
    ):
        raise PromotionBuildError(
            "published release uses checksum-only logical source lineage; "
            "direct promotion rebuilding is unsupported. Validate the tracked "
            "package with scripts/validate_published_pyq_package.py instead"
        )
    try:
        release_policy._validate_recursive_input_bindings(
            bindings, context="practice promotion source release"
        )
    except release_policy.ReleaseAssemblyError as exc:
        raise PromotionBuildError(str(exc)) from exc


def _asset_problem_codes(item: Mapping[str, Any]) -> list[str]:
    assets = item.get("assets") or []
    if not assets:
        return []
    paper_id = str(item.get("source_paper_id") or "")
    expected_prefix = Path("tmp") / "pyq" / "build" / "figure-assets" / paper_id
    references = item.get("source_references") or []
    figure_notes = " ".join(
        str(reference.get("note") or "")
        for reference in references
        if isinstance(reference, Mapping)
        and reference.get("kind") == "verified_figure_asset_index"
        and isinstance(reference.get("sha256"), str)
        and HASH_RE.fullmatch(str(reference["sha256"]).casefold())
    )
    problems: list[str] = []
    seen_hashes: set[str] = set()
    for asset in assets:
        if not isinstance(asset, Mapping):
            problems.append("promotion_asset_malformed")
            continue
        raw_path = asset.get("path")
        digest = str(asset.get("sha256") or "").casefold()
        if (
            not isinstance(raw_path, str)
            or not raw_path
            or "\\" in raw_path
            or not HASH_RE.fullmatch(digest)
            or digest in seen_hashes
        ):
            problems.append("promotion_asset_malformed")
            continue
        seen_hashes.add(digest)
        relative = Path(raw_path)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or tuple(relative.parts[: len(expected_prefix.parts)])
            != tuple(expected_prefix.parts)
            or relative.suffix.casefold() != ".png"
        ):
            problems.append("promotion_asset_path_unsafe")
            continue
        path = (REPO_DIR / relative).resolve()
        root = (REPO_DIR / expected_prefix).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            problems.append("promotion_asset_missing")
            continue
        if _sha256_file(path) != digest:
            problems.append("promotion_asset_hash_mismatch")
        if digest not in figure_notes:
            problems.append("promotion_asset_release_lineage_missing")
    return sorted(set(problems))


def _reference_note_fields(note: Any) -> dict[str, str]:
    if not isinstance(note, str):
        return {}
    fields: dict[str, str] = {}
    for part in note.split(";"):
        name, separator, value = part.strip().partition("=")
        if separator and name and value:
            fields[name.strip()] = value.strip()
    return fields


def _promotion_evidence_problem_codes(item: Mapping[str, Any]) -> list[str]:
    """Validate evidence that is intentionally stricter than model fields.

    The staging report's auto-grade count is based on normalized release fields.
    Production authorization additionally binds those fields back to the exact
    content-verification and answer evidence references emitted by the assembler.
    These checks run only for otherwise auto-grade-ready rows.
    """

    content_sha256 = str(item.get("content_sha256") or "").casefold()
    problems: list[str] = []
    if not HASH_RE.fullmatch(content_sha256):
        problems.append("promotion_source_content_hash_missing")
    elif content_sha256 != release_policy._content_sha256(item):
        problems.append("promotion_source_content_hash_mismatch")

    references = [
        row
        for row in item.get("source_references") or []
        if isinstance(row, Mapping)
    ]
    content_rows = [
        row
        for row in references
        if row.get("kind") == "verified_content_ledger"
        and isinstance(row.get("sha256"), str)
        and HASH_RE.fullmatch(str(row["sha256"]).casefold())
    ]
    if len(content_rows) != 1:
        problems.append("promotion_content_ledger_lineage_missing")
    else:
        fields = _reference_note_fields(content_rows[0].get("note"))
        if fields.get("stem_status") != "verified":
            problems.append("promotion_stem_not_ledger_verified")
        expected_options_status = (
            "verified" if item.get("item_type") in {"mcq", "msq"} else "not_applicable"
        )
        if fields.get("options_status") != expected_options_status:
            problems.append("promotion_options_not_ledger_verified")
        figure_status = fields.get("figure_status")
        if item.get("assets"):
            if figure_status != "asset_ready":
                problems.append("promotion_asset_readiness_unbound")
        elif figure_status != "not_required":
            problems.append("promotion_asset_absence_unverified")

    answer_status = item.get("answer_status")
    if answer_status == "official":
        official_rows = [
            row
            for row in references
            if row.get("kind") == "verified_answer_key"
            and _reference_note_fields(row.get("note")).get("status") == "official"
        ]
        if len(official_rows) != 1:
            problems.append("promotion_official_answer_lineage_missing")
    elif answer_status == "community_verified":
        sources: set[str] = set()
        for row in references:
            if (
                row.get("kind") != "community_answer_claim"
                or not isinstance(row.get("sha256"), str)
                or not HASH_RE.fullmatch(str(row["sha256"]).casefold())
            ):
                continue
            source = _reference_note_fields(row.get("note")).get("source")
            if source:
                sources.add(source.casefold())
        if len(sources) < 2:
            problems.append("promotion_community_answer_lineage_incomplete")
    else:
        problems.append("promotion_answer_lineage_unverified")
    return sorted(set(problems))


def build_promotion(
    *,
    release_path: Path = DEFAULT_RELEASE,
    release_report_path: Path = DEFAULT_RELEASE_REPORT,
    expected_papers: int = EXPECTED_PAPERS,
    expected_records: int = EXPECTED_RECORDS,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    initial_release_file_sha256 = _sha256_file(release_path)
    initial_report_file_sha256 = _sha256_file(release_report_path)
    release = _read_json(release_path)
    release_report = _read_json(release_report_path)
    _validate_release_report(
        release,
        release_report,
        expected_papers=expected_papers,
        expected_records=expected_records,
    )
    try:
        document = PyqArchiveDocument.model_validate(release)
        _validate_document(document)
    except Exception as exc:
        raise PromotionBuildError(f"source release is invalid: {exc}") from exc
    if len(document.papers) != expected_papers or len(document.questions) != expected_records:
        raise PromotionBuildError("source release archive identity drifted")
    if any(item.practice_eligible for item in document.questions):
        raise PromotionBuildError("source release already contains promoted rows")

    paper_by_id = {
        paper.id: paper.model_dump(mode="json") for paper in document.papers
    }
    release_problem_counts: Counter[str] = Counter()
    auto_problem_counts: Counter[str] = Counter()
    selected: list[dict[str, Any]] = []
    selected_keys: set[tuple[str, int]] = set()
    for model in document.questions:
        item = model.model_dump(mode="json")
        paper = paper_by_id[item["source_paper_id"]]
        release_blockers = release_policy._release_blockers(item)
        release_problem_counts.update(release_blockers)
        auto_blockers = release_policy._auto_gradable_blockers(
            item, paper, release_blockers
        )
        auto_problem_counts.update(auto_blockers)
        if auto_blockers:
            continue
        promotion_blockers = sorted(
            set(
                _promotion_evidence_problem_codes(item)
                + _asset_problem_codes(item)
            )
        )
        if promotion_blockers:
            raise PromotionBuildError(
                "otherwise auto-grade-ready row failed production evidence: "
                f"{item['source_paper_id']}/{item['item_label']}: "
                + ", ".join(promotion_blockers)
            )
        key = item["source_paper_id"], item["ordinal"]
        if key in selected_keys:
            raise PromotionBuildError(f"promotion identity duplicated: {key}")
        selected_keys.add(key)
        selected.append(
            {
                "source_paper_id": item["source_paper_id"],
                "ordinal": item["ordinal"],
                "item_label": item["item_label"],
                "source_content_sha256": item["content_sha256"],
            }
        )
    if dict(sorted(release_problem_counts.items())) != release_report.get(
        "release_blockers"
    ):
        raise PromotionBuildError("release blocker ledger drifted")
    if dict(sorted(auto_problem_counts.items())) != release_report.get(
        "auto_gradable_blockers"
    ):
        raise PromotionBuildError("auto-grade blocker ledger drifted")
    expected_selected = release_report["counts"].get("auto_gradable_ready")
    if expected_selected != len(selected):
        raise PromotionBuildError(
            f"promotion selection count {len(selected)} != release report {expected_selected}"
        )
    selected.sort(key=lambda row: (row["source_paper_id"], row["ordinal"]))
    selection_sha256 = _canonical_sha256(selected)

    promoted = copy.deepcopy(release)
    source_release_sha256 = _canonical_sha256(release)
    promoted["artifact_version"] = (
        f"gate-cs-pyq-practice-{source_release_sha256[:12]}-"
        f"{selection_sha256[:12]}"
    )
    promoted_count = 0
    selected_key_set = {
        (row["source_paper_id"], row["ordinal"]) for row in selected
    }
    for item in promoted["questions"]:
        key = item["source_paper_id"], item["ordinal"]
        item["practice_eligible"] = key in selected_key_set
        if item["practice_eligible"]:
            promoted_count += 1
        item["content_sha256"] = release_policy._content_sha256(item)
    if promoted_count != len(selected):
        raise PromotionBuildError("promotion application count drifted")
    try:
        promoted_document = PyqArchiveDocument.model_validate(promoted)
        _validate_document(promoted_document)
    except Exception as exc:
        raise PromotionBuildError(f"promoted archive failed import schema: {exc}") from exc
    if len(promoted_document.questions) != expected_records:
        raise PromotionBuildError("promoted archive dropped archival rows")
    if sum(item.practice_eligible for item in promoted_document.questions) != len(selected):
        raise PromotionBuildError("promoted archive over- or under-promoted rows")

    source_bindings = {
        "staging_release": _binding(release_path),
        "staging_release_report": _binding(release_report_path),
    }
    if (
        source_bindings["staging_release"]["sha256"]
        != initial_release_file_sha256
        or source_bindings["staging_release_report"]["sha256"]
        != initial_report_file_sha256
    ):
        raise PromotionBuildError("source release or report changed during promotion")
    promoted_sha256 = _canonical_sha256(promoted)
    allowlist_core = {
        "schema_version": "1.0-pyq-practice-promotion-allowlist",
        "source_role": "exact_production_practice_materialization_authorization",
        "database_writes_performed": False,
        "production_import_authorized": True,
        "practice_materialization_authorized": True,
        "unlisted_promotion_authorized": False,
        "selection_policy_fail_closed": True,
        "input_bindings": source_bindings,
        "source_release_artifact_sha256": source_release_sha256,
        "source_release_report_sha256": release_report["report_sha256"],
        "promoted_archive_artifact_sha256": promoted_sha256,
        "selection_sha256": selection_sha256,
        "archive_record_count": expected_records,
        "practice_eligible_count": len(selected),
        "records": selected,
    }
    allowlist = {
        **allowlist_core,
        "artifact_sha256": _canonical_sha256(allowlist_core),
    }
    report_core = {
        "schema_version": "1.0-pyq-practice-promotion-report",
        "database_writes_performed": False,
        "production_import_authorized": True,
        "practice_materialization_authorized": True,
        "input_bindings": source_bindings,
        "source_release_artifact_sha256": source_release_sha256,
        "source_release_report_sha256": release_report["report_sha256"],
        "promoted_archive_artifact_sha256": promoted_sha256,
        "allowlist_artifact_sha256": allowlist["artifact_sha256"],
        "counts": {
            "papers": len(promoted_document.papers),
            "archive_records_preserved": len(promoted_document.questions),
            "practice_eligible": len(selected),
            "archive_only": len(promoted_document.questions) - len(selected),
        },
        "selection_sha256": selection_sha256,
        "invariants": {
            "all_archive_records_preserved": len(promoted_document.questions)
            == expected_records,
            "only_allowlisted_rows_promoted": {
                (item.source_paper_id, item.ordinal)
                for item in promoted_document.questions
                if item.practice_eligible
            }
            == selected_key_set,
            "database_writes_disabled": True,
        },
    }
    if not all(report_core["invariants"].values()):
        raise PromotionBuildError("promotion invariants failed")
    report = {**report_core, "report_sha256": _canonical_sha256(report_core)}
    return promoted, allowlist, report


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, default=DEFAULT_RELEASE)
    parser.add_argument("--release-report", type=Path, default=DEFAULT_RELEASE_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--allowlist", type=Path, default=DEFAULT_ALLOWLIST)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    promoted, allowlist, report = build_promotion(
        release_path=args.release.resolve(),
        release_report_path=args.release_report.resolve(),
    )
    _write_json(args.output.resolve(), promoted)
    _write_json(args.allowlist.resolve(), allowlist)
    _write_json(args.report.resolve(), report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
