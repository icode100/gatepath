from __future__ import annotations

import copy
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pytest


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "build_pyq_practice_promotion.py"
)
SPEC = importlib.util.spec_from_file_location(
    "build_pyq_practice_promotion", SCRIPT
)
assert SPEC is not None and SPEC.loader is not None
builder = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = builder
SPEC.loader.exec_module(builder)


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _binding(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "sha256": builder._sha256_file(path),
        "bytes": path.stat().st_size,
    }


def _question(
    *,
    ordinal: int,
    solution: str | None,
    content_note: str | None = None,
) -> dict[str, Any]:
    note = content_note or (
        f"canonical_ordinal={ordinal}; stem_status=verified; "
        "stem_method=checksum_bound_original_text_block; "
        "options_status=verified; "
        "options_method=checksum_bound_original_text_block; "
        "figure_status=not_required"
    )
    item: dict[str, Any] = {
        "source_paper_id": "gate-cs-2025-set-1",
        "item_label": str(ordinal),
        "ordinal": ordinal,
        "legacy_source_ordinals": [],
        "parent_item_label": None,
        "source_page": ordinal,
        "marks": 1.0,
        "item_type": "mcq",
        "question_md": f"Which option is correct for fixture {ordinal}?",
        "options": ["A", "B", "C", "D"],
        "accepted_answers": "A",
        "solution_md": solution,
        "subject_code": "EM",
        "topic_slug": "discrete-mathematics",
        "syllabus_status": "in_syllabus",
        "transcription_status": "verified",
        "answer_status": "official",
        "classification_status": "verified",
        "practice_eligible": False,
        "review_flags": [],
        "assets": [],
        "source_references": [
            {
                "kind": "original_pdf_item",
                "url": "https://example.test/gate-cs-2025-set-1.pdf",
                "sha256": "a" * 64,
                "note": f"canonical_parent_ordinal={ordinal}; source_pages={ordinal}",
            },
            {
                "kind": "verified_content_ledger",
                "url": None,
                "sha256": "c" * 64,
                "note": note,
            },
            {
                "kind": "verified_answer_key",
                "url": None,
                "sha256": None,
                "note": "status=official; claim_ids=fixture-key",
            },
        ],
        "extraction_method": "content_ledger_fixture",
        "extraction_confidence": 1.0,
    }
    item["content_sha256"] = builder.release_policy._content_sha256(item)
    return item


def _fixture(
    tmp_path: Path,
    *,
    first_content_note: str | None = None,
) -> tuple[Path, Path, dict[str, Any], dict[str, Any], Path]:
    bound_input = tmp_path / "content-ledger.json"
    _write(bound_input, {"artifact": "checksum-bound-fixture"})
    release = {
        "schema_version": "1.0",
        "artifact_version": "fixture-staging-release-v1",
        "papers": [
            {
                "id": "gate-cs-2025-set-1",
                "exam_code": "GATE",
                "paper_code": "CS",
                "year": 2025,
                "session_label": "set-1",
                "display_name": "GATE CS 2025 Set 1",
                "expected_item_count": 2,
                "source_url": "https://example.test/gate-cs-2025-set-1.pdf",
                "answer_key_url": "https://example.test/gate-cs-2025-set-1-key.pdf",
                "source_pdf_sha256": "a" * 64,
                "answer_key_sha256": "b" * 64,
                "source_aliases": [],
                "source_status": "verified",
                "notes": "checksum-bound source fixture",
            }
        ],
        "questions": [
            _question(
                ordinal=1,
                solution="The official key and derivation select A.",
                content_note=first_content_note,
            ),
            _question(ordinal=2, solution=None),
        ],
    }
    release_path = tmp_path / "final_pyq_release.json"
    _write(release_path, release)

    paper = release["papers"][0]
    release_blockers: Counter[str] = Counter()
    auto_blockers: Counter[str] = Counter()
    auto_ready = 0
    release_ready = 0
    for item in release["questions"]:
        current = builder.release_policy._release_blockers(item)
        release_blockers.update(current)
        release_ready += int(not current)
        automatic = builder.release_policy._auto_gradable_blockers(
            item, paper, current
        )
        auto_blockers.update(automatic)
        auto_ready += int(not automatic)
    report_core = {
        "schema_version": builder.release_policy.REPORT_SCHEMA_VERSION,
        "artifact_version": release["artifact_version"],
        "artifact_sha256": builder._canonical_sha256(release),
        "source_role": "checksum_bound_staging_release_only",
        "database_writes_performed": False,
        "production_import_authorized": False,
        "automatic_promotion_allowed": False,
        "input_bindings": {"content_verification_ledger": _binding(bound_input)},
        "counts": {
            "papers": 1,
            "canonical_parent_slots": 2,
            "expanded_archive_records": 2,
            "legacy_expansion_delta": 0,
            "archival_complete": 2,
            "release_ready": release_ready,
            "archive_only": 2 - release_ready,
            "auto_gradable_ready": auto_ready,
            "practice_eligible": 0,
        },
        "release_blockers": dict(sorted(release_blockers.items())),
        "auto_gradable_blockers": dict(sorted(auto_blockers.items())),
        "papers": [],
        "invariants": {
            "all_records_archived": True,
            "practice_promotion_disabled": True,
        },
    }
    report = {
        **report_core,
        "report_sha256": builder._canonical_sha256(report_core),
    }
    report_path = tmp_path / "final_pyq_release.report.json"
    _write(report_path, report)
    return release_path, report_path, release, report, bound_input


def _rehash_report(report: dict[str, Any]) -> None:
    core = {key: value for key, value in report.items() if key != "report_sha256"}
    report["report_sha256"] = builder._canonical_sha256(core)


def test_build_promotion_preserves_archive_and_promotes_only_exact_ready_set(
    tmp_path: Path,
) -> None:
    release_path, report_path, release, _, _ = _fixture(tmp_path)

    promoted, allowlist, report = builder.build_promotion(
        release_path=release_path,
        release_report_path=report_path,
        expected_papers=1,
        expected_records=2,
    )
    second = builder.build_promotion(
        release_path=release_path,
        release_report_path=report_path,
        expected_papers=1,
        expected_records=2,
    )

    assert second == (promoted, allowlist, report)
    assert len(promoted["questions"]) == 2
    assert [row["practice_eligible"] for row in promoted["questions"]] == [
        True,
        False,
    ]
    assert release["questions"][0]["practice_eligible"] is False
    assert allowlist["production_import_authorized"] is True
    assert allowlist["practice_materialization_authorized"] is True
    assert allowlist["database_writes_performed"] is False
    assert allowlist["unlisted_promotion_authorized"] is False
    assert allowlist["practice_eligible_count"] == 1
    assert allowlist["archive_record_count"] == 2
    assert allowlist["records"] == [
        {
            "source_paper_id": "gate-cs-2025-set-1",
            "ordinal": 1,
            "item_label": "1",
            "source_content_sha256": release["questions"][0]["content_sha256"],
        }
    ]
    assert allowlist["artifact_sha256"] == builder._canonical_sha256(
        {key: value for key, value in allowlist.items() if key != "artifact_sha256"}
    )
    assert report["counts"] == {
        "papers": 1,
        "archive_records_preserved": 2,
        "practice_eligible": 1,
        "archive_only": 1,
    }
    assert report["invariants"] == {
        "all_archive_records_preserved": True,
        "only_allowlisted_rows_promoted": True,
        "database_writes_disabled": True,
    }
    assert report["report_sha256"] == builder._canonical_sha256(
        {key: value for key, value in report.items() if key != "report_sha256"}
    )
    assert promoted["questions"][0]["content_sha256"] != release["questions"][0][
        "content_sha256"
    ]
    assert promoted["questions"][1]["content_sha256"] == release["questions"][1][
        "content_sha256"
    ]


def test_release_tamper_is_rejected_before_promotion(tmp_path: Path) -> None:
    release_path, report_path, release, _, _ = _fixture(tmp_path)
    release["questions"][0]["question_md"] = "Tampered after report creation"
    release["questions"][0]["content_sha256"] = builder.release_policy._content_sha256(
        release["questions"][0]
    )
    _write(release_path, release)

    with pytest.raises(builder.PromotionBuildError, match="artifact hash drifted"):
        builder.build_promotion(
            release_path=release_path,
            release_report_path=report_path,
            expected_papers=1,
            expected_records=2,
        )


def test_stale_bound_input_is_rejected(tmp_path: Path) -> None:
    release_path, report_path, _, _, bound_input = _fixture(tmp_path)
    _write(bound_input, {"artifact": "changed after release assembly"})

    with pytest.raises(builder.PromotionBuildError, match="is stale"):
        builder.build_promotion(
            release_path=release_path,
            release_report_path=report_path,
            expected_papers=1,
            expected_records=2,
        )


def test_review_only_options_cannot_be_overpromoted(tmp_path: Path) -> None:
    content_note = (
        "canonical_ordinal=1; stem_status=verified; "
        "stem_method=checksum_bound_original_text_block; "
        "options_status=review; options_method=None; figure_status=not_required"
    )
    release_path, report_path, _, _, _ = _fixture(
        tmp_path, first_content_note=content_note
    )

    with pytest.raises(
        builder.PromotionBuildError,
        match="promotion_options_not_ledger_verified",
    ):
        builder.build_promotion(
            release_path=release_path,
            release_report_path=report_path,
            expected_papers=1,
            expected_records=2,
        )


def test_report_cannot_authorize_more_rows_than_the_exact_gate(tmp_path: Path) -> None:
    release_path, report_path, _, report, _ = _fixture(tmp_path)
    report["counts"]["auto_gradable_ready"] = 2
    _rehash_report(report)
    _write(report_path, report)

    with pytest.raises(builder.PromotionBuildError, match="selection count 1"):
        builder.build_promotion(
            release_path=release_path,
            release_report_path=report_path,
            expected_papers=1,
            expected_records=2,
        )


def test_source_content_checksum_tamper_fails_even_with_rehashed_report(
    tmp_path: Path,
) -> None:
    release_path, report_path, release, report, _ = _fixture(tmp_path)
    release["questions"][0]["content_sha256"] = "f" * 64
    _write(release_path, release)
    report["artifact_sha256"] = builder._canonical_sha256(release)
    _rehash_report(report)
    _write(report_path, report)

    with pytest.raises(builder.PromotionBuildError, match="Content checksum mismatch"):
        builder.build_promotion(
            release_path=release_path,
            release_report_path=report_path,
            expected_papers=1,
            expected_records=2,
        )


def test_unsafe_asset_cannot_be_promoted(tmp_path: Path) -> None:
    release_path, report_path, release, report, _ = _fixture(tmp_path)
    item = release["questions"][0]
    item["assets"] = [
        {
            "kind": "stem_diagram",
            "path": "tmp/pyq/build/figure-assets/gate-cs-2025-set-1/missing.png",
            "alt": "A reviewed diagram",
            "sha256": "d" * 64,
        }
    ]
    for reference in item["source_references"]:
        if reference["kind"] == "verified_content_ledger":
            reference["note"] = reference["note"].replace(
                "figure_status=not_required", "figure_status=asset_ready"
            )
    item["content_sha256"] = builder.release_policy._content_sha256(item)
    _write(release_path, release)
    report["artifact_sha256"] = builder._canonical_sha256(release)
    _rehash_report(report)
    _write(report_path, report)

    with pytest.raises(builder.PromotionBuildError, match="promotion_asset_missing"):
        builder.build_promotion(
            release_path=release_path,
            release_report_path=report_path,
            expected_papers=1,
            expected_records=2,
        )
