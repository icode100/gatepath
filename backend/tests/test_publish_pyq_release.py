from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "publish_pyq_release.py"
SPEC = importlib.util.spec_from_file_location("publish_pyq_release", SCRIPT_PATH)
assert SPEC and SPEC.loader
publisher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publisher)


def _asset(digest: str = "a" * 64) -> dict[str, str]:
    return {
        "kind": "stem_diagram",
        "path": "tmp/pyq/build/figure-assets/paper-1/source.png",
        "alt": "Exact diagram",
        "sha256": digest,
    }


def _question(*, practice: bool = False, digest: str = "a" * 64) -> dict:
    item = {
        "source_paper_id": "paper-1",
        "item_label": "Q1",
        "ordinal": 1,
        "legacy_source_ordinals": [1],
        "parent_item_label": None,
        "source_page": 1,
        "marks": 1,
        "item_type": "nat",
        "question_md": "Compute 1+1.",
        "options": [],
        "accepted_answers": ["2"],
        "solution_md": "The answer is 2.",
        "subject_code": "EM",
        "topic_slug": "discrete-mathematics",
        "syllabus_status": "in_syllabus",
        "transcription_status": "verified",
        "answer_status": "official",
        "classification_status": "verified",
        "practice_eligible": practice,
        "review_flags": [],
        "assets": [_asset(digest)],
        "source_references": [],
        "extraction_method": "fixture",
        "extraction_confidence": 1.0,
    }
    item["content_sha256"] = publisher.release_policy._content_sha256(item)
    return item


def test_rebase_changes_only_asset_path_and_dependent_content_hash() -> None:
    source = {
        "schema_version": "1.0",
        "artifact_version": "fixture",
        "papers": [{"id": "paper-1"}],
        "questions": [_question()],
    }
    published = publisher._rebase_archive_assets(source)
    assert published["questions"][0]["assets"][0]["path"] == (
        "question-assets/pyq/paper-1/" + "a" * 64 + ".png"
    )
    assert published["questions"][0]["content_sha256"] != source["questions"][0][
        "content_sha256"
    ]
    publisher._assert_archive_equivalent(
        source, published, allow_version_change=False
    )

    substantive_drift = copy.deepcopy(published)
    substantive_drift["questions"][0]["question_md"] = "Changed question"
    with pytest.raises(publisher.PublicationError, match="corpus drifted"):
        publisher._assert_archive_equivalent(
            source, substantive_drift, allow_version_change=False
        )


def test_path_rebasing_is_portable_and_fail_closed() -> None:
    digest = "b" * 64
    assert publisher._published_lineage_binding(
        {"path": "tmp/pyq/build/final.json", "sha256": digest, "bytes": 10}
    ) == {
        "lineage_id": f"sha256:{digest}",
        "sha256": digest,
        "bytes": 10,
        "availability": publisher.LOGICAL_LINEAGE_AVAILABILITY,
    }
    assert publisher._published_lineage_binding(
        {"path": "backend/data/source.json", "sha256": digest, "bytes": 10}
    ) == {
        "lineage_id": f"sha256:{digest}",
        "sha256": digest,
        "bytes": 10,
        "availability": publisher.LOGICAL_LINEAGE_AVAILABILITY,
    }
    with pytest.raises(publisher.PublicationError, match="Unsafe"):
        publisher._published_lineage_binding(
            {"path": "C:/Users/person/source.json", "sha256": digest, "bytes": 10}
        )
    with pytest.raises(publisher.PublicationError, match="Unexpected"):
        publisher._published_lineage_binding(
            {"path": "other/source.json", "sha256": digest, "bytes": 10}
        )
    with pytest.raises(publisher.PublicationError, match="temporary path"):
        publisher._assert_portable_paths(({"path": "tmp/pyq/source.json"},))


def test_frozen_file_hash_guard_rejects_tamper(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    source.write_bytes(b"frozen")
    expected = publisher._sha256_file(source)
    publisher._verify_frozen_file(source, expected, name="fixture")
    source.write_bytes(b"tampered")
    with pytest.raises(publisher.PublicationError, match="hash drifted"):
        publisher._verify_frozen_file(source, expected, name="fixture")


def test_runtime_asset_gate_never_exposes_missing_practice_asset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    digest = publisher._sha256_bytes(b"png")
    item = _question(practice=True, digest=digest)
    item["assets"][0]["path"] = publisher._stable_asset_path("paper-1", digest)
    archive = {"questions": [item]}
    key = "paper-1", "Q1", "stem_diagram", digest
    deployed = {key: item["assets"][0]["path"]}
    monkeypatch.setattr(publisher, "EXPECTED_DEPLOYED_ASSET_REFS", 1)

    with pytest.raises(publisher.PublicationError, match="missing asset"):
        publisher._validate_runtime_asset_visibility(
            archive, deployed, public_root=tmp_path
        )

    target = tmp_path / item["assets"][0]["path"]
    target.parent.mkdir(parents=True)
    target.write_bytes(b"png")
    publisher._validate_runtime_asset_visibility(
        archive, deployed, public_root=tmp_path
    )

    item["practice_eligible"] = False
    target.unlink()
    monkeypatch.setattr(publisher, "EXPECTED_DEPLOYED_ASSET_REFS", 0)
    publisher._validate_runtime_asset_visibility(
        archive, deployed, public_root=tmp_path
    )


def test_tracked_publication_hashes_and_runtime_assets_are_self_consistent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = (
        publisher.DEFAULT_PUBLISHED_STAGING,
        publisher.DEFAULT_PUBLISHED_STAGING_REPORT,
        publisher.DEFAULT_PUBLISHED_PROMOTION,
        publisher.DEFAULT_PUBLISHED_ALLOWLIST,
        publisher.DEFAULT_PUBLISHED_PROMOTION_REPORT,
        publisher.DEFAULT_PUBLISHED_PROOF,
    )
    payloads = tuple(json.loads(path.read_text(encoding="utf-8")) for path in paths)
    staging, staging_report, promotion, allowlist, promotion_report, proof = payloads
    publisher._assert_portable_paths(payloads)
    assert staging_report["artifact_sha256"] == publisher._canonical_sha256(staging)
    assert staging_report["report_sha256"] == publisher._canonical_sha256(
        {key: value for key, value in staging_report.items() if key != "report_sha256"}
    )
    assert allowlist["promoted_archive_artifact_sha256"] == publisher._canonical_sha256(
        promotion
    )
    assert allowlist["artifact_sha256"] == publisher._canonical_sha256(
        {key: value for key, value in allowlist.items() if key != "artifact_sha256"}
    )
    assert promotion_report["report_sha256"] == publisher._canonical_sha256(
        {
            key: value
            for key, value in promotion_report.items()
            if key != "report_sha256"
        }
    )
    for name, binding in allowlist["input_bindings"].items():
        path = publisher.REPO_DIR / binding["path"]
        assert path.is_file(), name
        assert publisher._sha256_file(path) == binding["sha256"]
        assert path.stat().st_size == binding["bytes"]
    eligible_assets = [
        (item, asset)
        for item in promotion["questions"]
        if item["practice_eligible"]
        for asset in item["assets"]
    ]
    assert len(eligible_assets) == publisher.EXPECTED_DEPLOYED_ASSET_REFS
    for item, asset in eligible_assets:
        assert asset["path"].startswith(
            f"question-assets/pyq/{item['source_paper_id']}/"
        )
        target = publisher.PUBLIC_DIR / asset["path"]
        assert target.is_file()
        assert publisher._sha256_file(target) == asset["sha256"]
    assert all(
        item["practice_eligible"] is False
        for item in promotion["questions"]
        if item["assets"]
        and any(not (publisher.PUBLIC_DIR / asset["path"]).is_file() for asset in item["assets"])
    )
    assert proof["artifact_sha256"] == publisher._canonical_sha256(
        {key: value for key, value in proof.items() if key != "artifact_sha256"}
    )
    assert {row["mode"] for row in proof["lineage_rebindings"]} == {
        "checksum_only"
    }
    assert all(
        "path" not in binding
        for binding in staging_report["input_bindings"].values()
    )

    # A clean-checkout validation may touch only the six package JSON files and
    # promoted public PNGs--never any upstream extraction or policy artifact.
    allowed_files = {path.resolve() for path in paths}
    public_root = publisher.PUBLIC_DIR.resolve()
    original_sha256_file = publisher._sha256_file

    def guarded_sha256_file(path: Path) -> str:
        resolved = path.resolve()
        if resolved not in allowed_files and not resolved.is_relative_to(public_root):
            raise AssertionError(f"clean validator read external lineage: {resolved}")
        return original_sha256_file(path)

    monkeypatch.setattr(publisher, "_sha256_file", guarded_sha256_file)
    assert publisher.validate_published_package()["practice_eligible"] == 177


def test_published_report_never_falls_through_to_missing_lineage_files() -> None:
    with pytest.raises(
        publisher.promotion_policy.PromotionBuildError,
        match="checksum-only logical source lineage",
    ):
        publisher.promotion_policy.build_promotion(
            release_path=publisher.DEFAULT_PUBLISHED_STAGING,
            release_report_path=publisher.DEFAULT_PUBLISHED_STAGING_REPORT,
        )


def test_cli_rejects_every_output_escape_before_write(tmp_path: Path) -> None:
    outside = tmp_path / "escaped-practice.json"
    with pytest.raises(publisher.PublicationError, match="escapes the repository"):
        publisher.main(["--output-promotion", str(outside)])
    assert not outside.exists()


def test_default_publication_check_when_frozen_inputs_are_available() -> None:
    frozen = (
        publisher.DEFAULT_STAGING,
        publisher.DEFAULT_STAGING_REPORT,
        publisher.DEFAULT_PROMOTION,
        publisher.DEFAULT_ALLOWLIST,
        publisher.DEFAULT_PROMOTION_REPORT,
    )
    if not all(path.is_file() for path in frozen):
        pytest.skip("ignored frozen build inputs are not present in this checkout")
    assert publisher.main(["--check"]) == 0
