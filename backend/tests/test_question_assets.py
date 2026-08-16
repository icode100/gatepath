from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.question_assets as question_asset_policy
from app.api import _question_public
from app.models import Difficulty, QuestionSource, QuestionType
from app.pyq_archive import (
    ArchiveQuestion,
    AssetReference,
    PyqArchiveDocument,
    _content_sha256,
)
from app.question_assets import (
    QuestionAssetValidationError,
    public_question_asset,
    validate_public_asset_payload,
)


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "materialize_pyq_question_assets.py"
)
SPEC = importlib.util.spec_from_file_location("materialize_pyq_question_assets", SCRIPT_PATH)
assert SPEC and SPEC.loader
MATERIALIZER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MATERIALIZER
SPEC.loader.exec_module(MATERIALIZER)


def _asset(*, path: str, kind: str = "stem_diagram", sha256: str = "a" * 64):
    return AssetReference(
        kind=kind,
        path=path,
        alt="A verified diagram with labelled nodes.",
        sha256=sha256,
    )


def test_public_asset_projection_is_same_origin_and_fail_closed() -> None:
    projected = public_question_asset(
        _asset(
            path=(
                "tmp/pyq/build/figure-assets/gate-cs-2025-set-1/"
                "verified.png"
            )
        ),
        paper_id="gate-cs-2025-set-1",
    )
    assert projected == {
        "role": "stem_diagram",
        "url": f"/question-assets/pyq/gate-cs-2025-set-1/{'a' * 64}.png",
        "alt_text": "A verified diagram with labelled nodes.",
        "sha256": "a" * 64,
    }

    with pytest.raises(QuestionAssetValidationError, match="exact immutable"):
        public_question_asset(
            _asset(path="tmp/pyq/build/figure-assets/other-paper/verified.png"),
            paper_id="gate-cs-2025-set-1",
        )
    with pytest.raises(QuestionAssetValidationError, match="unapproved"):
        public_question_asset(
            _asset(
                path=(
                    "tmp/pyq/build/figure-assets/gate-cs-2025-set-1/"
                    "verified.png"
                ),
                kind="remote_html",
            ),
            paper_id="gate-cs-2025-set-1",
        )


def _dimensioned_png(*, width: int = 2, height: int = 3) -> bytes:
    return (
        question_asset_policy.PNG_SIGNATURE
        + (13).to_bytes(4, "big")
        + b"IHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
    )


def test_stable_published_asset_requires_exact_local_sha_png(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    public_root = tmp_path / "public"
    public_root.mkdir()
    monkeypatch.setattr(question_asset_policy, "PUBLIC_ROOT", public_root)
    paper_id = "gate-cs-2025-set-1"
    png = _dimensioned_png()
    digest = hashlib.sha256(png).hexdigest()
    relative = f"question-assets/pyq/{paper_id}/{digest}.png"
    target = public_root / relative
    target.parent.mkdir(parents=True)
    target.write_bytes(png)
    asset = _asset(path=relative, sha256=digest)

    assert public_question_asset(asset, paper_id=paper_id) == {
        "role": "stem_diagram",
        "url": f"/{relative}",
        "alt_text": "A verified diagram with labelled nodes.",
        "sha256": digest,
    }
    assert question_asset_policy.source_asset_parts(
        asset, paper_id=paper_id
    ) == ("public", *Path(relative).parts)

    target.write_bytes(_dimensioned_png(width=0))
    with pytest.raises(QuestionAssetValidationError, match="dimensions"):
        public_question_asset(asset, paper_id=paper_id)
    target.write_bytes(png + b"tampered")
    with pytest.raises(QuestionAssetValidationError, match="checksum"):
        public_question_asset(asset, paper_id=paper_id)
    target.unlink()
    with pytest.raises(QuestionAssetValidationError, match="missing"):
        public_question_asset(asset, paper_id=paper_id)

    with pytest.raises(QuestionAssetValidationError, match="exact immutable"):
        public_question_asset(
            _asset(
                path=f"question-assets/pyq/other-paper/{digest}.png",
                sha256=digest,
            ),
            paper_id=paper_id,
        )
    with pytest.raises(QuestionAssetValidationError, match="traversal"):
        public_question_asset(
            _asset(path=f"question-assets/pyq/{paper_id}/../{digest}.png", sha256=digest),
            paper_id=paper_id,
        )


def test_stable_published_asset_rejects_symlinks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    public_root = tmp_path / "public"
    public_root.mkdir()
    monkeypatch.setattr(question_asset_policy, "PUBLIC_ROOT", public_root)
    paper_id = "gate-cs-2025-set-1"
    png = _dimensioned_png()
    digest = hashlib.sha256(png).hexdigest()
    relative = f"question-assets/pyq/{paper_id}/{digest}.png"
    link = public_root / relative
    link.parent.mkdir(parents=True)
    link.write_bytes(png)
    path_type = type(link)
    original_is_symlink = path_type.is_symlink
    monkeypatch.setattr(
        path_type,
        "is_symlink",
        lambda current: current == link or original_is_symlink(current),
    )
    with pytest.raises(QuestionAssetValidationError, match="symlink"):
        public_question_asset(
            _asset(path=relative, sha256=digest), paper_id=paper_id
        )


def test_question_public_serializes_valid_assets_and_rejects_remote_urls() -> None:
    payload = {
        "role": "stem_table",
        "url": f"/question-assets/pyq/gate-cs-2014-session-1/{'b' * 64}.png",
        "alt_text": "Allocation and maximum-resource table.",
        "sha256": "b" * 64,
    }
    question = SimpleNamespace(
        id=7,
        subject_id=1,
        subject=SimpleNamespace(slug="operating-systems", name="Operating Systems"),
        topic_id=2,
        topic=SimpleNamespace(slug="deadlocks", name="Deadlocks"),
        source=QuestionSource.PREVIOUS_YEAR,
        year=2014,
        exam_session="session-1",
        source_kind=QuestionSource.PREVIOUS_YEAR,
        source_year=2014,
        source_paper="gate-cs-2014-session-1",
        source_question_number=41,
        source_paper_id="gate-cs-2014-session-1",
        source_item_label="41",
        source_page=18,
        source_url=None,
        answer_key_url=None,
        extraction_method="original-pdf-visual-review",
        extraction_confidence=1.0,
        question_type=QuestionType.MCQ,
        difficulty=Difficulty.MEDIUM,
        text="Use the table to answer the question.",
        options=[{"id": "A", "text": "Safe"}, {"id": "B", "text": "Unsafe"}],
        numerical_tolerance=0.01,
        marks=2,
        tags=["pyq"],
        assets=[payload],
    )
    public = _question_public(question)
    assert public.assets[0].model_dump() == payload

    unsafe = dict(payload, url="https://example.test/tracker.png")
    with pytest.raises(QuestionAssetValidationError, match="local PNG"):
        validate_public_asset_payload([unsafe])


def _release_payload(*, paper_id: str, sha256: str) -> dict[str, object]:
    common = {
        "source_paper_id": paper_id,
        "source_page": 2,
        "marks": 1,
        "item_type": "mcq",
        "question_md": "Which option is correct?",
        "options": ["First", "Second"],
        "accepted_answers": "A",
        "solution_md": "The first option follows from the diagram.",
        "subject_code": "EM",
        "topic_slug": "discrete-mathematics",
        "syllabus_status": "in_syllabus",
        "transcription_status": "verified",
        "answer_status": "official",
        "classification_status": "verified",
    }
    payload = {
        "schema_version": "1.0",
        "artifact_version": "asset-materializer-test-v1",
        "papers": [
            {
                "id": paper_id,
                "year": 2025,
                "session_label": "set-1",
                "display_name": "GATE CS 2025 Set 1",
                "expected_item_count": 2,
                "source_pdf_sha256": "d" * 64,
                "source_status": "verified",
            }
        ],
        "questions": [
            {
                **common,
                "item_label": "1",
                "ordinal": 1,
                "practice_eligible": True,
                "assets": [
                    {
                        "kind": "stem_diagram",
                        "path": (
                            f"tmp/pyq/build/figure-assets/{paper_id}/approved.png"
                        ),
                        "alt": "A promotion-approved source diagram.",
                        "sha256": sha256,
                    }
                ],
            },
            {
                **common,
                "item_label": "2",
                "ordinal": 2,
                "practice_eligible": False,
                "classification_status": "review_required",
                "review_flags": ["manual_review_required"],
                "assets": [
                    {
                        "kind": "stem_diagram",
                        "path": (
                            f"tmp/pyq/build/figure-assets/{paper_id}/review-only.png"
                        ),
                        "alt": "A review-only diagram that must not be deployed.",
                        "sha256": "e" * 64,
                    }
                ],
            },
        ],
    }
    for item in payload["questions"]:
        item["content_sha256"] = _content_sha256(ArchiveQuestion.model_validate(item))
    return payload


def _file_binding(path: Path, *, repository: Path) -> dict[str, object]:
    raw = path.read_bytes()
    return {
        "path": path.relative_to(repository).as_posix(),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
    }


def test_materializer_copies_only_assets_on_promoted_questions(tmp_path: Path) -> None:
    paper_id = "gate-cs-2025-set-1"
    repository = tmp_path / "repo"
    source_dir = repository / "tmp" / "pyq" / "build" / "figure-assets" / paper_id
    source_dir.mkdir(parents=True)
    approved_bytes = b"\x89PNG\r\n\x1a\nverified-png-content"
    approved_sha = hashlib.sha256(approved_bytes).hexdigest()
    (source_dir / "approved.png").write_bytes(approved_bytes)
    # Deliberately not a real PNG. The materializer must never read this file
    # because its owning question is not promotion eligible.
    (source_dir / "review-only.png").write_bytes(b"not-a-png")

    release_path = repository / "tmp" / "pyq" / "build" / "release.json"
    release_path.parent.mkdir(parents=True, exist_ok=True)
    release_payload = _release_payload(paper_id=paper_id, sha256=approved_sha)
    release_path.write_text(
        json.dumps(release_payload),
        encoding="utf-8",
    )
    source_payload = copy.deepcopy(release_payload)
    source_payload["artifact_version"] = "asset-materializer-source-test-v1"
    for item in source_payload["questions"]:
        item["practice_eligible"] = False
        item["content_sha256"] = _content_sha256(
            ArchiveQuestion.model_validate(
                {key: value for key, value in item.items() if key != "content_sha256"}
            )
        )
    source_path = release_path.with_name("source-release.json")
    source_path.write_text(json.dumps(source_payload), encoding="utf-8")
    source_sha256 = MATERIALIZER._canonical_sha256(source_payload)
    source_report_core = {
        "schema_version": "1.0-staging-final-pyq-release",
        "artifact_version": source_payload["artifact_version"],
        "artifact_sha256": source_sha256,
        "database_writes_performed": False,
        "production_import_authorized": False,
        "automatic_promotion_allowed": False,
        "counts": {
            "expanded_archive_records": 2,
            "archival_complete": 2,
            "practice_eligible": 0,
        },
    }
    source_report = {
        **source_report_core,
        "report_sha256": MATERIALIZER._canonical_sha256(source_report_core),
    }
    source_report_path = release_path.with_name("source-release.report.json")
    source_report_path.write_text(json.dumps(source_report), encoding="utf-8")
    source_question = source_payload["questions"][0]
    allowlist_core = {
        "schema_version": "1.0-pyq-practice-promotion-allowlist",
        "source_role": "exact_production_practice_materialization_authorization",
        "database_writes_performed": False,
        "production_import_authorized": True,
        "practice_materialization_authorized": True,
        "unlisted_promotion_authorized": False,
        "selection_policy_fail_closed": True,
        "input_bindings": {
            "staging_release": _file_binding(source_path, repository=repository),
            "staging_release_report": _file_binding(
                source_report_path, repository=repository
            ),
        },
        "source_release_artifact_sha256": source_sha256,
        "source_release_report_sha256": source_report["report_sha256"],
        "promoted_archive_artifact_sha256": MATERIALIZER._canonical_sha256(
            release_payload
        ),
        "archive_record_count": 2,
        "practice_eligible_count": 1,
        "records": [
            {
                "source_paper_id": paper_id,
                "ordinal": 1,
                "item_label": "1",
                "source_content_sha256": source_question["content_sha256"],
            }
        ],
    }
    allowlist_core["selection_sha256"] = MATERIALIZER._canonical_sha256(
        allowlist_core["records"]
    )
    allowlist_path = release_path.with_name("release.allowlist.json")
    allowlist_path.write_text(
        json.dumps(
            {
                **allowlist_core,
                "artifact_sha256": MATERIALIZER._canonical_sha256(allowlist_core),
            }
        ),
        encoding="utf-8",
    )
    public_root = repository / "public" / "question-assets" / "pyq"
    manifest_path = repository / "backend" / "data" / "assets.json"
    manifest = MATERIALIZER.materialize(
        release_path=release_path,
        allowlist_path=allowlist_path,
        public_root=public_root,
        manifest_path=manifest_path,
        repository_root=repository,
        check=False,
    )

    deployed = public_root / paper_id / f"{approved_sha}.png"
    assert deployed.read_bytes() == approved_bytes
    assert len(list(public_root.rglob("*.png"))) == 1
    assert manifest["counts"] == {
        "question_asset_references": 1,
        "unique_png_files": 1,
        "source_questions": 1,
    }
    assert manifest["guards"]["archive_or_review_assets_included"] is False
    checked = MATERIALIZER.materialize(
        release_path=release_path,
        allowlist_path=allowlist_path,
        public_root=public_root,
        manifest_path=manifest_path,
        repository_root=repository,
        check=True,
    )
    assert checked["artifact_sha256"] == manifest["artifact_sha256"]

    source_bytes = source_path.read_bytes()
    source_path.write_bytes(source_bytes + b" ")
    with pytest.raises(
        MATERIALIZER.QuestionAssetMaterializationError,
        match="staging release input binding is stale",
    ):
        MATERIALIZER.materialize(
            release_path=release_path,
            allowlist_path=allowlist_path,
            public_root=public_root,
            manifest_path=manifest_path,
            repository_root=repository,
            check=True,
        )
    source_path.write_bytes(source_bytes)

    promoted_bytes = release_path.read_bytes()
    tampered_release = json.loads(promoted_bytes)
    tampered_release["questions"][0]["question_md"] = "Tampered after promotion"
    release_path.write_text(json.dumps(tampered_release), encoding="utf-8")
    with pytest.raises(
        MATERIALIZER.QuestionAssetMaterializationError,
        match="release artifact is invalid:.*Content checksum mismatch",
    ):
        MATERIALIZER.materialize(
            release_path=release_path,
            allowlist_path=allowlist_path,
            public_root=public_root,
            manifest_path=manifest_path,
            repository_root=repository,
            check=True,
        )
    release_path.write_bytes(promoted_bytes)

    extra = public_root / "unapproved.png"
    extra.write_bytes(approved_bytes)
    with pytest.raises(
        MATERIALIZER.QuestionAssetMaterializationError,
        match="unapproved PNGs",
    ):
        MATERIALIZER.materialize(
            release_path=release_path,
            allowlist_path=allowlist_path,
            public_root=public_root,
            manifest_path=manifest_path,
            repository_root=repository,
            check=True,
        )


def test_tracked_practice_package_assets_pass_materializer_check() -> None:
    repository = Path(__file__).resolve().parents[2]
    manifest = MATERIALIZER.materialize(
        release_path=(
            repository
            / "backend"
            / "data"
            / "gate_cs_pyq_practice_1996_2025.json"
        ),
        allowlist_path=(
            repository
            / "backend"
            / "data"
            / "gate_cs_pyq_practice_1996_2025.allowlist.json"
        ),
        public_root=repository / "public" / "question-assets" / "pyq",
        manifest_path=repository / "backend" / "data" / "pyq_question_assets.json",
        repository_root=repository,
        check=True,
        promotion_report_path=(
            repository
            / "backend"
            / "data"
            / "gate_cs_pyq_practice_1996_2025.report.json"
        ),
        publication_proof_path=(
            repository
            / "backend"
            / "data"
            / "gate_cs_pyq_publication_1996_2025.proof.json"
        ),
    )
    assert manifest["counts"] == {
        "question_asset_references": 9,
        "unique_png_files": 9,
        "source_questions": 9,
    }


def test_materializer_cli_default_check_is_the_tracked_proof_package() -> None:
    sources = MATERIALIZER._resolve_cli_sources(MATERIALIZER.parse_args([]))
    assert sources == MATERIALIZER.MaterializationSources(
        release_path=MATERIALIZER.DEFAULT_RELEASE.resolve(),
        allowlist_path=MATERIALIZER.DEFAULT_ALLOWLIST.resolve(),
        promotion_report_path=MATERIALIZER.DEFAULT_PROMOTION_REPORT.resolve(),
        publication_proof_path=MATERIALIZER.DEFAULT_PUBLICATION_PROOF.resolve(),
        staging=False,
    )
    assert MATERIALIZER.main(["--check"]) == 0


def test_tmp_materialization_requires_explicit_complete_staging_mode() -> None:
    staging = MATERIALIZER._resolve_cli_sources(
        MATERIALIZER.parse_args(["--staging"])
    )
    assert staging == MATERIALIZER.MaterializationSources(
        release_path=MATERIALIZER.STAGING_RELEASE.resolve(),
        allowlist_path=MATERIALIZER.STAGING_ALLOWLIST.resolve(),
        promotion_report_path=MATERIALIZER.STAGING_PROMOTION_REPORT.resolve(),
        publication_proof_path=None,
        staging=True,
    )
    with pytest.raises(
        MATERIALIZER.QuestionAssetMaterializationError,
        match="cannot be combined",
    ):
        MATERIALIZER._resolve_cli_sources(
            MATERIALIZER.parse_args(
                ["--staging", "--release", str(MATERIALIZER.STAGING_RELEASE)]
            )
        )
    with pytest.raises(
        MATERIALIZER.QuestionAssetMaterializationError,
        match="explicit mode requires",
    ):
        MATERIALIZER._resolve_cli_sources(
            MATERIALIZER.parse_args(
                ["--release", str(MATERIALIZER.STAGING_RELEASE)]
            )
        )
