from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "assemble_pyq_release.py"
)
SPEC = importlib.util.spec_from_file_location("assemble_pyq_release", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
assembler = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = assembler
SPEC.loader.exec_module(assembler)


def _write(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _embedded(value: dict[str, Any], field: str = "artifact_sha256") -> dict[str, Any]:
    core = {key: child for key, child in value.items() if key != field}
    return {**core, field: assembler._canonical_sha256(core)}


def _input_binding(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "sha256": assembler._sha256_file(path),
        "bytes": path.stat().st_size,
    }


def _canonical_question(
    *,
    label: str,
    ordinal: int,
    item_type: str,
    question: str,
    options: list[str] | None = None,
    solution: str | None = None,
) -> dict[str, Any]:
    return {
        "source_paper_id": "gate-cs-2000",
        "item_label": label,
        "ordinal": ordinal,
        "legacy_source_ordinals": [],
        "parent_item_label": None,
        "source_page": ordinal,
        "marks": 1,
        "item_type": item_type,
        "question_md": question,
        "options": options or [],
        "accepted_answers": None,
        "solution_md": solution,
        "subject_code": "EM",
        "topic_slug": "discrete-mathematics",
        "syllabus_status": "review_required",
        "transcription_status": "verified",
        "answer_status": "unresolved",
        "classification_status": "review_required",
        "practice_eligible": False,
        "review_flags": [],
        "assets": [],
        "source_references": [],
        "extraction_method": "fixture",
        "extraction_confidence": 1.0,
    }


def _make_fixture(tmp_path: Path) -> dict[str, Path]:
    paths = {
        name: tmp_path / filename
        for name, filename in {
            "manifest": "manifest.json",
            "canonical": "canonical.json",
            "canonical_report": "canonical.report.json",
            "raw_candidates": "candidates.raw.json",
            "candidates": "candidates.structured.json",
            "candidate_report": "candidates.report.json",
            "provenance": "provenance.json",
            "overlay": "overlay.json",
            "answer_index": "answers.json",
            "legacy_audit": "legacy.json",
            "topic_policy": "topics.json",
            "slot_policy": "slots.json",
            "legacy_child_policy": "children.json",
            "topic_inventory": "inventory.json",
            "content_ledger": "content-ledger.json",
            "figure_assets": "figure-assets.json",
            "source_verification": "source-verification.json",
            "source_evidence": "source-evidence.json",
            "classification_base": "classification-base.json",
        }.items()
    }
    paths["source_pdf"] = tmp_path / "fixture.pdf"
    paths["source_pdf"].write_bytes(b"%PDF-1.4\nfixture bound question paper\n%%EOF\n")
    source_pdf_sha = assembler._sha256_file(paths["source_pdf"])
    _write(paths["source_evidence"], {"fixture": True})
    manifest = {
        "papers": [
            {
                "id": "gate-cs-2000",
                "year": 2000,
                "local_sha256": source_pdf_sha,
            }
        ]
    }
    _write(paths["manifest"], manifest)
    _write(paths["topic_policy"], {"policy": "fixture"})
    _write(paths["slot_policy"], {"policy": "fixture-slots"})
    _write(
        paths["topic_inventory"],
        {
            "courses": {
                "EM": {"by_topic": {"Discrete Mathematics": {"count": 1}}},
                "DL": {"by_topic": {"Boolean Algebra": {"count": 1}}},
            }
        },
    )

    questions = [
        _canonical_question(
            label="1",
            ordinal=1,
            item_type="mcq",
            question="Which option is correct?",
            options=["Alpha", "Beta", "Gamma", "Delta"],
            solution="The checksum-bound key selects A.",
        ),
        _canonical_question(
            label="2",
            ordinal=2,
            item_type="descriptive",
            question="Shared parent",
        ),
    ]
    canonical = {
        "schema_version": "1.0",
        "artifact_version": "fixture-canonical-v1",
        "papers": [
            {
                "id": "gate-cs-2000",
                "exam_code": "GATE",
                "paper_code": "CS",
                "year": 2000,
                "session_label": "single",
                "display_name": "GATE CS 2000",
                "expected_item_count": 2,
                "source_url": "https://example.test/gate-cs-2000.pdf",
                "answer_key_url": "https://example.test/gate-cs-2000-key.pdf",
                "source_pdf_sha256": source_pdf_sha,
                "answer_key_sha256": "b" * 64,
                "source_aliases": [],
                "source_status": "verified",
                "notes": "fixture",
            }
        ],
        "questions": questions,
    }
    _write(paths["canonical"], canonical)
    canonical_report = {
        "artifact_version": canonical["artifact_version"],
        "inputs": {
            "manifest": {
                "path": str(paths["manifest"]),
                "sha256": assembler._sha256_file(paths["manifest"]),
            }
        },
        "invariants": {"actual_paper_count": 1, "actual_item_count": 2},
    }
    _write(paths["canonical_report"], canonical_report)

    raw_candidates = {
        "database_writes_performed": False,
        "automatic_promotion_allowed": False,
        "paper_count": 1,
        "slot_count": 2,
        "questions": [],
    }
    _write(paths["raw_candidates"], raw_candidates)
    candidate_rows = []
    for question in questions:
        candidate_rows.append(
            {
                "source_paper_id": "gate-cs-2000",
                "item_label": question["item_label"],
                "ordinal": question["ordinal"],
                "candidate": {
                    "question_text": question["question_md"],
                    "options": question["options"],
                    "item_type": question["item_type"],
                    "marks": question["marks"],
                    "course": "EM",
                    "topic": "discrete-mathematics",
                    "classification_outcome": "mapped",
                },
                "secondary_snapshots": {"examside": None},
            }
        )
    structured = {
        "schema_version": "fixture",
        "database_writes_performed": False,
        "automatic_promotion_allowed": False,
        "paper_count": 1,
        "slot_count": 2,
        "questions": candidate_rows,
        "input_artifact_sha256": assembler._sha256_file(paths["raw_candidates"]),
    }
    _write(paths["candidates"], structured)
    candidate_report = {
        "paper_count": 1,
        "slot_count": 2,
        "reconciliation": {
            "classification": {
                "policy_sha256": assembler._sha256_file(paths["topic_policy"]),
                "slot_policy_sha256": assembler._sha256_file(paths["slot_policy"]),
                "after": {"unresolved_conflicts": 0},
            }
        },
    }
    _write(paths["candidate_report"], candidate_report)

    provenance_items = [
        {
            "source_paper_id": "gate-cs-2000",
            "canonical_ordinal": ordinal,
            "item_label": str(ordinal),
            "source_label": str(ordinal),
            "source_pages": [ordinal],
            "boundary": {
                "start_page": ordinal,
                "start_offset": 0,
                "end_page": ordinal,
                "end_offset": 10,
            },
            "text_block_sha256": ("c" if ordinal == 1 else "d") * 64,
            "source_pdf_sha256": source_pdf_sha,
            "evidence_status": "exact_text_block",
            "practice_eligible": False,
            "production_import_authorized": False,
        }
        for ordinal in (1, 2)
    ]
    provenance = _embedded(
        {
            "schema_version": "1.0",
            "production_import_authorized": False,
            "source_manifest_sha256": assembler._sha256_file(paths["manifest"]),
            "canonical_identity": {"paper_count": 1, "item_count": 2},
            "papers": [],
            "items": provenance_items,
        }
    )
    _write(paths["provenance"], provenance)

    overlay_core = {
        "schema_version": "fixture",
        "database_writes_performed": False,
        "production_import_authorized": False,
        "automatic_promotion_allowed": False,
        "input_bindings": {
            "canonical_archive": _input_binding(paths["canonical"]),
            "canonical_candidates": _input_binding(paths["candidates"]),
            "original_pdf_provenance": _input_binding(paths["provenance"]),
            "source_manifest": _input_binding(paths["manifest"]),
        },
        "items": [
            {
                "source_paper_id": "gate-cs-2000",
                "canonical_ordinal": 1,
                "item_label": "1",
                "status": "exact",
                "proposed_overlay": None,
            },
            {
                "source_paper_id": "gate-cs-2000",
                "canonical_ordinal": 2,
                "item_label": "2",
                "status": "exact",
                "proposed_overlay": None,
            },
        ],
    }
    overlay = _embedded(overlay_core)
    _write(paths["overlay"], overlay)

    answer_core = {
        "schema_version": "1.0",
        "production_import_authorized": False,
        "practice_promotion_authorized": False,
        "manifest_sha256": assembler._sha256_file(paths["manifest"]),
        "sources": [],
        "claims": [],
        "conflicts": [],
        "gaps": [],
        "summary": {},
        "resolutions": [
            {
                "source_paper_id": "gate-cs-2000",
                "canonical_ordinal": 1,
                "item_label": "1",
                "status": "official",
                "selected_answer": {"kind": "options", "options": ["A"]},
                "selected_question_type": "MCQ",
                "selected_marks": 1,
                "supporting_claim_ids": ["claim-1"],
                "claim_ids": ["claim-1"],
            }
        ],
    }
    answer_index = {
        **answer_core,
        "artifact_version": assembler._canonical_sha256(answer_core),
    }
    _write(paths["answer_index"], answer_index)

    ledger_items = []
    for question, provenance_item in zip(questions, provenance_items, strict=True):
        option_content = [
            {"id": chr(ord("A") + index), "text": str(option)}
            for index, option in enumerate(question["options"])
        ]
        evidence = {
            "source_pdf_sha256": source_pdf_sha,
            "source_pages": provenance_item["source_pages"],
            "text_block_sha256": provenance_item["text_block_sha256"],
            "page_text_sha256": [
                {
                    "page": provenance_item["source_pages"][0],
                    "sha256": ("e" if question["ordinal"] == 1 else "f") * 64,
                }
            ],
        }
        ledger_items.append(
            {
                "source_paper_id": "gate-cs-2000",
                "canonical_ordinal": question["ordinal"],
                "item_label": question["item_label"],
                "item_type": question["item_type"],
                "course": "EM",
                "topic": "discrete-mathematics",
                "stem": {
                    "status": "verified",
                    "content": question["question_md"],
                    "content_sha256": assembler._sha256_text(question["question_md"]),
                    "verification_method": "checksum_bound_original_text_block",
                    "evidence": evidence,
                    "blockers": [],
                },
                "options": (
                    {
                        "status": "verified",
                        "content": option_content,
                        "content_sha256": assembler._canonical_sha256(option_content),
                        "verification_method": "checksum_bound_original_text_block",
                        "evidence": evidence,
                        "blockers": [],
                    }
                    if question["item_type"] == "mcq"
                    else {
                        "status": "not_applicable",
                        "content": None,
                        "content_sha256": None,
                        "verification_method": None,
                        "evidence": None,
                        "blockers": [],
                    }
                ),
                "figure_evidence": {
                    "status": "not_required",
                    "assessment": "not_detected",
                    "source_pdf_sha256": source_pdf_sha,
                    "source_pages": provenance_item["source_pages"],
                    "asset_count": 0,
                    "asset_sha256": [],
                },
                "asset_blockers": [],
                "blockers": [],
            }
        )
    ledger_core = {
        "schema_version": "1.0-staging-pyq-content-verification",
        "source_role": "staging_content_verification_ledger_only",
        "database_writes_performed": False,
        "production_import_authorized": False,
        "automatic_promotion_allowed": False,
        "practice_eligible_count": 0,
        "canonical_identity": {"paper_count": 1, "parent_slot_count": 2},
        "input_bindings": {
            "structured_candidates": _input_binding(paths["candidates"]),
            "original_pdf_provenance": _input_binding(paths["provenance"]),
            "original_transcription_overlay": _input_binding(paths["overlay"]),
            "official_answer_index": _input_binding(paths["answer_index"]),
        },
        "verification_policy": {
            "exact_original_text_block_allowed": True,
            "cross_source_requires_mutual_unique_match": True,
            "cross_source_requires_original_text_block": True,
            "cross_source_requires_official_answer_type_marks": True,
            "cross_source_requires_gateoverflow_and_examside_agreement": True,
            "cross_source_minimum_original_similarity": 0.95,
            "cross_source_minimum_gateoverflow_similarity": 0.95,
            "cross_source_latex_code_html_visual_auto_acceptance": False,
            "matcher_cross_source_option_auto_acceptance": False,
            "canonical_page_options_require_exact_examside_agreement": True,
            "third_party_explanations_consumed": False,
        },
        "items": ledger_items,
    }
    _write(paths["content_ledger"], _embedded(ledger_core))

    child_records = []
    for order, (label, prompt) in enumerate(
        (("2(a)", "First leaf"), ("2(b)", "Second leaf")), start=1
    ):
        prompt_hash = assembler._sha256_text(prompt)
        child_records.append(
            {
                "child_item_label": label,
                "child_order": order,
                "question_type": "descriptive",
                "prompt_text": prompt,
                "prompt_text_sha256": prompt_hash,
                "prompt_source": "original_transcription_overlay_child",
                "prompt_evidence": {
                    "overlay_artifact_sha256": overlay["artifact_sha256"],
                    "source_child_text_sha256": prompt_hash,
                    "source_text_block_sha256": "d" * 64,
                    "parent_text_boundary": provenance_items[1]["boundary"],
                },
                "shared_context": {
                    "strategy": "preserve_pre_expansion_parent_question",
                    "source_paper_id": "gate-cs-2000",
                    "canonical_parent_ordinal": 2,
                    "parent_item_label": "2",
                    "canonical_parent_question_sha256": assembler._sha256_text(
                        "Shared parent"
                    ),
                    "additional_shared_text": "Additional setting",
                    "additional_shared_text_sha256": assembler._sha256_text(
                        "Additional setting"
                    ),
                },
                "source_pages": [2],
                "rendered_page_evidence": [
                    {"page": 2, "rendered_page_sha256": "e" * 64}
                ],
                "marks": 1,
                "marks_status": "exact_visible",
                "materialization_status": "exact",
                "review_flags": [],
            }
        )
    legacy_core = {
        "schema_version": "fixture",
        "database_writes_performed": False,
        "production_import_authorized": False,
        "automatic_promotion_allowed": False,
        "input_bindings": {
            "canonical_archive_sha256": assembler._sha256_file(paths["canonical"]),
            "original_pdf_provenance_sha256": assembler._sha256_file(
                paths["provenance"]
            ),
            "source_manifest_sha256": assembler._sha256_file(paths["manifest"]),
            "original_question_transcription_overlay_sha256": assembler._sha256_file(
                paths["overlay"]
            ),
        },
        "summary": {
            "paper_count": 1,
            "descriptive_parent_count": 1,
            "canonical_slot_count": 2,
            "final_split_database_record_count": 3,
            "corpus_delta": 1,
            "residual_review_row_count": 0,
        },
        "papers": [
            {
                "paper_id": "gate-cs-2000",
                "canonical_slot_count": 2,
                "final_split_database_record_count": 3,
                "residual_review_row_count": 0,
                "decisions": [
                    {
                        "parent_canonical_ordinal": 2,
                        "parent_item_label": "2",
                        "decision": "split",
                        "child_labels": ["2(a)", "2(b)"],
                        "child_records": child_records,
                        "record_count_after_decision": 2,
                        "review_required": False,
                    }
                ],
            }
        ],
    }
    _write(paths["legacy_audit"], _embedded(legacy_core))
    child_decisions = []
    for child in child_records:
        key = "gate-cs-2000", 2, child["child_item_label"]
        evidence_hash, excerpt = assembler._legacy_child_evidence(child, key=key)
        differs_from_parent = child["child_item_label"] == "2(a)"
        child_decisions.append(
            {
                "paper_id": key[0],
                "parent_canonical_ordinal": key[1],
                "child_item_label": key[2],
                "decision": "map",
                "canonical_course": "DL" if differs_from_parent else "EM",
                "canonical_topic": (
                    "boolean-algebra" if differs_from_parent else "discrete-mathematics"
                ),
                "reason_code": "fixture_child_evidence",
                "reason": "Fixture evidence supports the canonical topic.",
                "parent_comparison": (
                    "differs_from_parent" if differs_from_parent else "same_as_parent"
                ),
                "prompt_text_sha256": child["prompt_text_sha256"],
                "evidence_sha256": evidence_hash,
                "evidence_excerpt": excerpt,
            }
        )
    _write(
        paths["legacy_child_policy"],
        {
            "schema_version": "1.0",
            "policy_version": "fixture-children-v1",
            "scope": {
                "split_parent_count": 1,
                "materialized_child_count": 2,
                "legacy_subpart_audit_sha256": assembler._sha256_file(
                    paths["legacy_audit"]
                ),
                "canonical_inventory_sha256": assembler._sha256_file(
                    paths["topic_inventory"]
                ),
            },
            "database_writes_performed": False,
            "production_import_authorized": False,
            "summary": {"mapped": 2, "out_of_syllabus": 0, "review": 0},
            "child_decisions": child_decisions,
        },
    )
    figure_items = [
        {
            "source_paper_id": "gate-cs-2000",
            "canonical_ordinal": question["ordinal"],
            "child_item_label": None,
            "item_label": question["item_label"],
            "record_kind": "canonical_parent",
            "dependence_status": "not_required",
            "dependence_assessment": "not_detected",
            "source_pdf_sha256": source_pdf_sha,
            "source_pages": [question["ordinal"]],
            "prompt_text_sha256": [assembler._sha256_text(question["question_md"])],
            "detection_signals": [],
            "assets": [],
            "review_flags": [],
            "production_import_authorized": False,
        }
        for question in questions
    ]
    figure_items.extend(
        {
            "source_paper_id": "gate-cs-2000",
            "canonical_ordinal": 2,
            "child_item_label": child["child_item_label"],
            "item_label": child["child_item_label"],
            "record_kind": "expanded_legacy_child",
            "dependence_status": "not_required",
            "dependence_assessment": "not_detected",
            "source_pdf_sha256": source_pdf_sha,
            "source_pages": child["source_pages"],
            "prompt_text_sha256": assembler._figure_prompt_hashes(
                ("Additional setting", child["prompt_text"])
            ),
            "detection_signals": [],
            "assets": [],
            "review_flags": [],
            "production_import_authorized": False,
        }
        for child in child_records
    )
    figure_core = {
        "schema_version": "1.0-staging-original-pdf-figure-assets",
        "scope": "fixture",
        "database_writes_performed": False,
        "production_import_authorized": False,
        "automatic_promotion_allowed": False,
        "practice_eligible_count": 0,
        "identity": {
            "paper_count": 1,
            "canonical_parent_count": 2,
            "expanded_legacy_child_count": 2,
            "audited_record_count": 4,
        },
        "input_bindings": {
            "source_manifest": _input_binding(paths["manifest"]),
            "canonical_archive": _input_binding(paths["canonical"]),
            "original_pdf_provenance": _input_binding(paths["provenance"]),
            "original_transcription_overlay": _input_binding(paths["overlay"]),
            "legacy_subpart_audit": _input_binding(paths["legacy_audit"]),
        },
        "source_files": [
            {
                "paper_id": "gate-cs-2000",
                "manifest_local_file": "fixture.pdf",
                "source_pdf_sha256": source_pdf_sha,
                "source_page_count": 2,
            }
        ],
        "render_specification": {"renderer": "fixture", "dpi": 216},
        "status_vocabulary": {},
        "items": figure_items,
        "papers": [],
    }
    _write(paths["figure_assets"], _embedded(figure_core))
    ledger_core["input_bindings"]["original_pdf_figure_assets"] = _input_binding(
        paths["figure_assets"]
    )
    _write(paths["content_ledger"], _embedded(ledger_core))
    source_verification_core = {
        "schema_version": "1.0-staging-paper-source-verification",
        "scope": "fixture",
        "staging_guard": {
            "production_import_authorized": False,
            "database_write_authorized": False,
            "promotion_authorized": False,
            "practice_eligible": False,
        },
        "verification_policy": {
            "official": "Fixture official byte identity.",
            "secondary": "Fixture two-source byte identity.",
            "url_only_or_single_republisher_is_sufficient": False,
            "answer_key_can_verify_question_paper_identity": False,
        },
        "input_bindings": {
            "source_manifest": _input_binding(paths["manifest"]),
            "canonical_archive": _input_binding(paths["canonical"]),
            "original_pdf_provenance": _input_binding(paths["provenance"]),
            "source_evidence_catalog": _input_binding(paths["source_evidence"]),
        },
        "invariants": {
            "expected_paper_count": 1,
            "actual_paper_count": 1,
            "expected_parent_item_count": 2,
            "canonical_parent_item_count": 2,
            "provenance_parent_item_count": 2,
            "all_papers_have_false_staging_guards": True,
        },
        "decision_counts": {"verified": 1},
        "method_counts": {"primary_official_byte_identity": 1},
        "papers": [
            {
                "source_paper_id": "gate-cs-2000",
                "year": 2000,
                "session": "single",
                "decision": "verified",
                "method": "primary_official_byte_identity",
                "local_source": {
                    "manifest_declared_path": "fixture.pdf",
                    "absolute_path": str(paths["source_pdf"].resolve()),
                    "sha256": source_pdf_sha,
                    "bytes": paths["source_pdf"].stat().st_size,
                    "pages": 2,
                    "valid_pdf": True,
                    "identity_matches_manifest_and_provenance": True,
                },
                "counts": {
                    "expected_item_count": 2,
                    "manifest_observed_item_count": 2,
                    "canonical_item_count": 2,
                    "provenance_item_count": 2,
                    "counts_agree": True,
                },
                "provenance_binding": {
                    "source_pdf_sha256": source_pdf_sha,
                    "source_page_count": 2,
                    "item_count": 2,
                    "unresolved_count": 0,
                },
                "evidence": [
                    {
                        "evidence_id": "fixture-official",
                        "authority": "primary_official",
                        "source_url": "https://example.test/fixture.pdf",
                        "index_url": "https://example.test/index.html",
                        "source_domain": "example.test",
                        "independently_acquired": True,
                        "artifact": {
                            "declared_path": "fixture.pdf",
                            "absolute_path": str(paths["source_pdf"].resolve()),
                            "sha256": source_pdf_sha,
                            "bytes": paths["source_pdf"].stat().st_size,
                            "pages": 2,
                            "valid_pdf": True,
                        },
                        "observed_item_count": 2,
                        "byte_identical_to_bound_source": True,
                        "page_structure_agrees": True,
                        "item_structure_agrees": True,
                        "official_index_confirmed": True,
                        "official_source_confirmed": True,
                        "qualifies_primary_official_byte_identity": True,
                        "qualifies_cross_validated_republication_candidate": False,
                    }
                ],
                "blockers": [],
                "review_flags": [
                    "bound_local_source_integrity_verified",
                    "official_index_confirmed",
                ],
                "staging_guard": {
                    "production_import_authorized": False,
                    "database_write_authorized": False,
                    "promotion_authorized": False,
                    "practice_eligible": False,
                },
            }
        ],
    }
    _write(paths["source_verification"], _embedded(source_verification_core))
    return paths


def _assemble(paths: dict[str, Path]) -> tuple[dict[str, Any], dict[str, Any]]:
    return assembler.assemble_release(
        canonical_path=paths["canonical"],
        canonical_report_path=paths["canonical_report"],
        raw_candidates_path=paths["raw_candidates"],
        candidates_path=paths["candidates"],
        candidate_report_path=paths["candidate_report"],
        provenance_path=paths["provenance"],
        overlay_path=paths["overlay"],
        answer_index_path=paths["answer_index"],
        legacy_audit_path=paths["legacy_audit"],
        manifest_path=paths["manifest"],
        topic_policy_path=paths["topic_policy"],
        slot_policy_path=paths["slot_policy"],
        legacy_child_policy_path=paths["legacy_child_policy"],
        topic_inventory_path=paths["topic_inventory"],
        content_ledger_path=paths["content_ledger"],
        figure_assets_path=paths["figure_assets"],
        source_verification_path=paths["source_verification"],
        classification_review_path=None,
        expected_paper_count=1,
        expected_parent_count=2,
        expected_expanded_count=3,
        expected_legacy_paper_ids={"gate-cs-2000"},
        expected_classification_counts={
            "mapped": 3,
            "out_of_syllabus": 0,
            "review": 0,
        },
    )


def _rewrite_figure_and_refresh_ledger(
    paths: dict[str, Path], figure: dict[str, Any]
) -> None:
    _write(paths["figure_assets"], _embedded(figure))
    ledger = json.loads(paths["content_ledger"].read_text(encoding="utf-8"))
    ledger_core = {key: value for key, value in ledger.items() if key != "artifact_sha256"}
    ledger_core["input_bindings"]["original_pdf_figure_assets"] = _input_binding(
        paths["figure_assets"]
    )
    _write(paths["content_ledger"], _embedded(ledger_core))


def test_assembler_expands_children_deterministically_without_promotion(
    tmp_path: Path,
) -> None:
    paths = _make_fixture(tmp_path)

    artifact, report = _assemble(paths)
    repeated_artifact, repeated_report = _assemble(paths)

    assert artifact == repeated_artifact
    assert report == repeated_report
    assert artifact["papers"][0]["expected_item_count"] == 3
    assert artifact["papers"][0]["source_status"] == "verified"
    assert [row["ordinal"] for row in artifact["questions"]] == [1, 2, 3]
    assert [row["item_label"] for row in artifact["questions"]] == [
        "1",
        "2(a)",
        "2(b)",
    ]
    assert artifact["questions"][1]["parent_item_label"] == "2"
    assert artifact["questions"][0]["subject_code"] == "EM"
    assert artifact["questions"][1]["subject_code"] == "DL"
    assert artifact["questions"][1]["topic_slug"] == "boolean-algebra"
    assert artifact["questions"][1]["question_md"] == (
        "Shared parent\n\nAdditional setting\n\nFirst leaf"
    )
    assert all(row["practice_eligible"] is False for row in artifact["questions"])
    assert report["counts"] == {
        "papers": 1,
        "canonical_parent_slots": 2,
        "expanded_archive_records": 3,
        "legacy_expansion_delta": 1,
        "archival_complete": 3,
        "release_ready": 3,
        "archive_only": 0,
        "auto_gradable_ready": 1,
        "practice_eligible": 0,
    }
    assert report["database_writes_performed"] is False
    assert report["production_import_authorized"] is False
    assert report["automatic_promotion_allowed"] is False
    assert report["classification_counts"] == {
        "mapped": 3,
        "out_of_syllabus": 0,
        "review": 0,
    }
    assert report["answer_evidence_counts"] == {"not_applicable": 2, "official": 1}
    assert report["community_verified_answers_by_year"] == {}
    assert report["paper_source_verification_counts"] == {
        "decisions": {"verified": 1},
        "methods": {"primary_official_byte_identity": 1},
        "verified_paper_ids": ["gate-cs-2000"],
    }
    assert report["figure_asset_counts"] == {
        "audited_records": 4,
        "parents": {"not_required": 2},
        "expanded_children": {"not_required": 2},
        "attached_asset_references": 0,
        "attached_unique_asset_sha256": 0,
    }


def test_paper_source_review_decision_downgrades_canonical_verified_status(
    tmp_path: Path,
) -> None:
    paths = _make_fixture(tmp_path)
    source = json.loads(paths["source_verification"].read_text(encoding="utf-8"))
    core = {key: value for key, value in source.items() if key != "artifact_sha256"}
    core["papers"][0]["decision"] = "review"
    core["papers"][0]["blockers"] = ["official_identity_requires_review"]
    core["decision_counts"] = {"review": 1}
    _write(paths["source_verification"], _embedded(core))

    artifact, report = _assemble(paths)

    assert artifact["papers"][0]["source_status"] == "review_required"
    assert report["counts"]["auto_gradable_ready"] == 0
    assert report["auto_gradable_blockers"][
        "paper_source_not_explicitly_promoted"
    ] == 3


def test_verified_paper_requires_exact_official_byte_identity(tmp_path: Path) -> None:
    paths = _make_fixture(tmp_path)
    source = json.loads(paths["source_verification"].read_text(encoding="utf-8"))
    core = {key: value for key, value in source.items() if key != "artifact_sha256"}
    core["papers"][0]["evidence"][0][
        "qualifies_primary_official_byte_identity"
    ] = False
    _write(paths["source_verification"], _embedded(core))

    with pytest.raises(assembler.ReleaseAssemblyError, match="byte identity is unproven"):
        _assemble(paths)


def test_exact_child_figure_review_remains_a_release_blocker(tmp_path: Path) -> None:
    paths = _make_fixture(tmp_path)
    figure = json.loads(paths["figure_assets"].read_text(encoding="utf-8"))
    core = {key: value for key, value in figure.items() if key != "artifact_sha256"}
    child = next(
        row for row in core["items"] if row.get("child_item_label") == "2(a)"
    )
    child.update(
        {
            "dependence_status": "review_required",
            "dependence_assessment": "potential",
            "detection_signals": ["parent:original_rendered_page_review_required"],
            "review_flags": ["manual_original_page_figure_review_required"],
        }
    )
    _rewrite_figure_and_refresh_ledger(paths, core)

    artifact, report = _assemble(paths)

    expanded = next(row for row in artifact["questions"] if row["item_label"] == "2(a)")
    assert expanded["assets"] == []
    assert "figure_asset_review_required" in expanded["review_flags"]
    assert "manual_original_page_figure_review_required" in expanded["review_flags"]
    assert report["counts"]["release_ready"] == 2
    assert report["figure_asset_counts"]["expanded_children"] == {
        "not_required": 1,
        "review_required": 1,
    }


def test_figure_index_must_cover_every_expanded_child_key(tmp_path: Path) -> None:
    paths = _make_fixture(tmp_path)
    figure = json.loads(paths["figure_assets"].read_text(encoding="utf-8"))
    core = {key: value for key, value in figure.items() if key != "artifact_sha256"}
    core["items"] = [
        row for row in core["items"] if row.get("child_item_label") != "2(b)"
    ]
    _rewrite_figure_and_refresh_ledger(paths, core)

    with pytest.raises(assembler.ReleaseAssemblyError, match="item coverage drifted"):
        _assemble(paths)


def test_ready_parent_asset_is_hash_checked_and_attached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(assembler, "REPO_DIR", tmp_path)
    paths = _make_fixture(tmp_path)
    source_pdf_sha = json.loads(paths["manifest"].read_text(encoding="utf-8"))[
        "papers"
    ][0]["local_sha256"]
    relative_path = Path(
        "tmp/pyq/build/figure-assets/gate-cs-2000/"
        "pyq-figure-0123456789abcdefabcd--stem-diagram.png"
    )
    asset_path = tmp_path / relative_path
    asset_path.parent.mkdir(parents=True, exist_ok=True)
    asset_path.write_bytes(b"\x89PNG\r\n\x1a\nfixture-original-crop")
    asset_sha256 = assembler._sha256_file(asset_path)
    raw_asset = {
        "asset_id": "pyq-figure-0123456789abcdefabcd",
        "relative_path": relative_path.as_posix(),
        "media_type": "image/png",
        "sha256": asset_sha256,
        "bytes": asset_path.stat().st_size,
        "pixel_width": 120,
        "pixel_height": 80,
        "source_page": 1,
        "source_pdf_sha256": source_pdf_sha,
        "source_page_render_sha256": "9" * 64,
        "crop_box_pixels": [0, 0, 120, 80],
        "crop_box_pdf_points": [0.0, 0.0, 40.0, 26.667],
        "render_dpi": 216,
        "asset_role": "stem_diagram",
        "visual_kind": "fixture_diagram",
        "alt_text": "A checksum-bound fixture diagram.",
        "caption": "Original fixture question diagram.",
        "review_status": "visually_reviewed_exact_bounds",
        "origin": "checksum_bound_original_question_paper_pdf_crop",
    }
    figure = json.loads(paths["figure_assets"].read_text(encoding="utf-8"))
    figure_core = {
        key: value for key, value in figure.items() if key != "artifact_sha256"
    }
    parent = next(
        row
        for row in figure_core["items"]
        if row["canonical_ordinal"] == 1 and row["child_item_label"] is None
    )
    parent.update(
        {
            "dependence_status": "asset_ready",
            "dependence_assessment": "confirmed",
            "detection_signals": ["original_overlay_visual_review_flag"],
            "assets": [raw_asset],
        }
    )
    _write(paths["figure_assets"], _embedded(figure_core))
    ledger = json.loads(paths["content_ledger"].read_text(encoding="utf-8"))
    ledger_core = {
        key: value for key, value in ledger.items() if key != "artifact_sha256"
    }
    ledger_core["input_bindings"]["original_pdf_figure_assets"] = _input_binding(
        paths["figure_assets"]
    )
    ledger_core["items"][0]["figure_evidence"].update(
        {
            "status": "asset_ready",
            "assessment": "confirmed",
            "asset_count": 1,
            "asset_sha256": [asset_sha256],
        }
    )
    _write(paths["content_ledger"], _embedded(ledger_core))

    artifact, report = _assemble(paths)

    assert artifact["questions"][0]["assets"] == [
        {
            "kind": "stem_diagram",
            "path": relative_path.as_posix(),
            "alt": "A checksum-bound fixture diagram.",
            "sha256": asset_sha256,
        }
    ]
    assert report["figure_asset_counts"]["attached_asset_references"] == 1

    figure_core["items"][0]["assets"][0]["alt_text"] = ""
    _write(paths["figure_assets"], _embedded(figure_core))
    ledger_core["input_bindings"]["original_pdf_figure_assets"] = _input_binding(
        paths["figure_assets"]
    )
    _write(paths["content_ledger"], _embedded(ledger_core))
    with pytest.raises(assembler.ReleaseAssemblyError, match="accessible description"):
        _assemble(paths)


def test_stale_downstream_binding_fails_closed(tmp_path: Path) -> None:
    paths = _make_fixture(tmp_path)
    structured = json.loads(paths["candidates"].read_text(encoding="utf-8"))
    structured["drift"] = True
    _write(paths["candidates"], structured)

    with pytest.raises(assembler.ReleaseAssemblyError, match="stale input hash"):
        _assemble(paths)


def test_content_ledger_review_downgrades_prior_verified_transcription(
    tmp_path: Path,
) -> None:
    paths = _make_fixture(tmp_path)
    ledger = json.loads(paths["content_ledger"].read_text(encoding="utf-8"))
    core = {key: value for key, value in ledger.items() if key != "artifact_sha256"}
    stem = core["items"][0]["stem"]
    stem.update(
        {
            "status": "review",
            "content": None,
            "content_sha256": None,
            "verification_method": None,
            "evidence": None,
            "blockers": ["manual_source_review_required"],
        }
    )
    core["items"][0]["blockers"] = ["manual_source_review_required"]
    _write(paths["content_ledger"], _embedded(core))

    artifact, report = _assemble(paths)

    first = artifact["questions"][0]
    assert first["question_md"] == "Which option is correct?"
    assert first["transcription_status"] == "review_required"
    assert "manual_source_review_required" in first["review_flags"]
    assert report["counts"]["release_ready"] == 2
    assert report["counts"]["archive_only"] == 1


def test_content_ledger_verified_hash_drift_fails_closed(tmp_path: Path) -> None:
    paths = _make_fixture(tmp_path)
    ledger = json.loads(paths["content_ledger"].read_text(encoding="utf-8"))
    core = {key: value for key, value in ledger.items() if key != "artifact_sha256"}
    core["items"][0]["stem"]["content"] = "Tampered but not rehashed"
    _write(paths["content_ledger"], _embedded(core))

    with pytest.raises(assembler.ReleaseAssemblyError, match="content hash drifted"):
        _assemble(paths)


def test_content_ledger_must_cover_every_parent_slot(tmp_path: Path) -> None:
    paths = _make_fixture(tmp_path)
    ledger = json.loads(paths["content_ledger"].read_text(encoding="utf-8"))
    core = {key: value for key, value in ledger.items() if key != "artifact_sha256"}
    core["items"].pop()
    _write(paths["content_ledger"], _embedded(core))

    with pytest.raises(assembler.ReleaseAssemblyError, match="coverage drifted"):
        _assemble(paths)


def test_rendered_page_cross_source_evidence_uses_its_own_similarity_contract() -> None:
    field = {
        "verification_method": "mutually_unique_cross_source_original_page",
        "evidence": {
            "source_pdf_sha256": "a" * 64,
            "source_pages": [1],
            "rendered_page_evidence": [{"page": 1, "sha256": "b" * 64}],
            "examside_raw_response_sha256": "c" * 64,
            "gateoverflow_body_sha256": "d" * 64,
            "gateoverflow_page_text_sha256": "e" * 64,
            "gateoverflow_text_similarity": 0.96,
            "official_resolution_claim_ids": ["claim-1"],
        },
    }

    assembler._validate_content_evidence(
        field,
        key=("gate-cs-2019", 3),
        field_name="stem",
        provenance={
            "source_pdf_sha256": "a" * 64,
            "source_pages": [1],
            "text_block_sha256": None,
        },
    )


def test_official_type_can_refine_only_unverified_ledger_option_semantics() -> None:
    ledger_row = {
        "item_type": "nat",
        "stem": {"status": "review", "verification_method": None},
        "options": {"status": "not_applicable", "verification_method": None},
        "figure_evidence": {"status": "review_required"},
        "asset_blockers": ["manual_original_page_figure_review_required"],
        "blockers": ["manual_original_page_figure_review_required"],
    }
    _, options, status, flags, _, _ = assembler._content_ledger_transcription(
        key=("gate-cs-2015-session-1", 65),
        question="Review-only stem",
        options=[{"id": "A", "text": "unverified"}],
        prior_status="review_required",
        resolved_item_type="mcq",
        ledger_row=ledger_row,
        ledger_artifact_sha256="a" * 64,
    )
    assert options == []
    assert status == "review_required"
    assert "content_ledger_type_refined_by_official_answer" in flags

    conflicting = copy.deepcopy(ledger_row)
    conflicting["options"] = {
        "status": "verified",
        "content": [{"id": "A", "text": "verified"}],
        "verification_method": "checksum_bound_original_text_block",
    }
    with pytest.raises(assembler.ReleaseAssemblyError, match="item type"):
        assembler._content_ledger_transcription(
            key=("gate-cs-2015-session-1", 65),
            question="Review-only stem",
            options=[],
            prior_status="review_required",
            resolved_item_type="mcq",
            ledger_row=conflicting,
            ledger_artifact_sha256="a" * 64,
        )


def test_empty_classification_review_gate_binds_base_projection(tmp_path: Path) -> None:
    paths = _make_fixture(tmp_path)
    artifact, _ = _assemble(paths)
    projection = assembler._classification_projection(artifact["questions"])
    base_identity = {
        "expected_count": 0,
        "classification_projection_sha256": assembler._canonical_sha256(
            projection
        ),
        "review_key_sha256": assembler._canonical_sha256([]),
    }
    base_core = {
        "schema_version": "1.0-staging-pyq-classification-review-base",
        "source_role": "immutable_pre_override_classification_projection",
        "database_writes_performed": False,
        "production_import_authorized": False,
        "automatic_promotion_allowed": False,
        "input_bindings": {
            "canonical_archive": _input_binding(paths["canonical"]),
            "legacy_subpart_audit": _input_binding(paths["legacy_audit"]),
            "legacy_child_policy": _input_binding(paths["legacy_child_policy"]),
            "base_parent_policy": _input_binding(paths["slot_policy"]),
            "topic_inventory": _input_binding(paths["topic_inventory"]),
            "content_verification_ledger": _input_binding(paths["content_ledger"]),
            "original_pdf_provenance": _input_binding(paths["provenance"]),
        },
        "counts": {"expanded_records": 3, "review_rows": 0},
        "base_review_identity": base_identity,
        "classification_projection_sha256": base_identity[
            "classification_projection_sha256"
        ],
        "classification_projection": projection,
        "review_rows": [],
    }
    _write(paths["classification_base"], _embedded(base_core))
    validated_base = assembler._validate_classification_review_base(
        json.loads(paths["classification_base"].read_text(encoding="utf-8")),
        canonical_path=paths["canonical"],
        legacy_path=paths["legacy_audit"],
        child_policy_path=paths["legacy_child_policy"],
        parent_policy_path=paths["slot_policy"],
        inventory_path=paths["topic_inventory"],
        content_ledger_path=paths["content_ledger"],
        provenance_path=paths["provenance"],
        base_items=artifact["questions"],
    )

    tampered_base = copy.deepcopy(base_core)
    tampered_base["classification_projection"][0]["topic_slug"] = "tampered-topic"
    tampered_projection_hash = assembler._canonical_sha256(
        tampered_base["classification_projection"]
    )
    tampered_base["classification_projection_sha256"] = tampered_projection_hash
    tampered_base["base_review_identity"][
        "classification_projection_sha256"
    ] = tampered_projection_hash
    with pytest.raises(
        assembler.ReleaseAssemblyError,
        match="projection differs from pre-override release",
    ):
        assembler._validate_classification_review_base(
            _embedded(tampered_base),
            canonical_path=paths["canonical"],
            legacy_path=paths["legacy_audit"],
            child_policy_path=paths["legacy_child_policy"],
            parent_policy_path=paths["slot_policy"],
            inventory_path=paths["topic_inventory"],
            content_ledger_path=paths["content_ledger"],
            provenance_path=paths["provenance"],
            base_items=artifact["questions"],
        )
    core = {
        "schema_version": "1.0-staging-pyq-classification-review-overrides",
        "source_role": "fixture",
        "database_writes_performed": False,
        "production_import_authorized": False,
        "automatic_promotion_allowed": False,
        "practice_eligible_count": 0,
        "base_review_identity": base_identity,
        "input_bindings": {
            "classification_review_base": _input_binding(
                paths["classification_base"]
            ),
            "canonical_archive": _input_binding(paths["canonical"]),
            "legacy_subpart_audit": _input_binding(paths["legacy_audit"]),
            "legacy_child_policy": _input_binding(paths["legacy_child_policy"]),
            "base_parent_policy": _input_binding(paths["slot_policy"]),
            "topic_inventory": _input_binding(paths["topic_inventory"]),
            "content_verification_ledger": _input_binding(paths["content_ledger"]),
            "original_pdf_provenance": _input_binding(paths["provenance"]),
        },
        "policy": {
            "allowed_decisions": ["map", "out_of_syllabus", "review"],
            "map_requires_single_inventory_course_topic": True,
            "out_of_syllabus_requires_original_evidence": True,
            "compound_or_insufficient_evidence_remains_review": True,
            "third_party_content_is_not_evidence": True,
            "base_policy_is_comparison_only": True,
            "expanded_children_require_explicit_child_identity": True,
        },
        "counts": {"total": 0, "by_decision": {}, "by_evidence_kind": {}},
        "decisions": [],
    }
    gate = _embedded(core)
    assert assembler._validate_classification_review_overrides(
        gate,
        classification_base_path=paths["classification_base"],
        classification_base_identity=validated_base,
        canonical_path=paths["canonical"],
        legacy_path=paths["legacy_audit"],
        child_policy_path=paths["legacy_child_policy"],
        parent_policy_path=paths["slot_policy"],
        inventory_path=paths["topic_inventory"],
        content_ledger_path=paths["content_ledger"],
        provenance_path=paths["provenance"],
        base_items=artifact["questions"],
        paper_by_id={paper["id"]: paper for paper in artifact["papers"]},
        inventory_raw=json.loads(paths["topic_inventory"].read_text(encoding="utf-8")),
    ) == {}

    stale = copy.deepcopy(core)
    stale["base_review_identity"]["classification_projection_sha256"] = "0" * 64
    with pytest.raises(assembler.ReleaseAssemblyError, match="identity"):
        assembler._validate_classification_review_overrides(
            _embedded(stale),
            classification_base_path=paths["classification_base"],
            classification_base_identity=validated_base,
            canonical_path=paths["canonical"],
            legacy_path=paths["legacy_audit"],
            child_policy_path=paths["legacy_child_policy"],
            parent_policy_path=paths["slot_policy"],
            inventory_path=paths["topic_inventory"],
            content_ledger_path=paths["content_ledger"],
            provenance_path=paths["provenance"],
            base_items=artifact["questions"],
            paper_by_id={paper["id"]: paper for paper in artifact["papers"]},
            inventory_raw=json.loads(
                paths["topic_inventory"].read_text(encoding="utf-8")
            ),
        )

    stale_binding = copy.deepcopy(core)
    stale_binding["input_bindings"]["classification_review_base"]["sha256"] = (
        "0" * 64
    )
    with pytest.raises(assembler.ReleaseAssemblyError, match="binding"):
        assembler._validate_classification_review_overrides(
            _embedded(stale_binding),
            classification_base_path=paths["classification_base"],
            classification_base_identity=validated_base,
            canonical_path=paths["canonical"],
            legacy_path=paths["legacy_audit"],
            child_policy_path=paths["legacy_child_policy"],
            parent_policy_path=paths["slot_policy"],
            inventory_path=paths["topic_inventory"],
            content_ledger_path=paths["content_ledger"],
            provenance_path=paths["provenance"],
            base_items=artifact["questions"],
            paper_by_id={paper["id"]: paper for paper in artifact["papers"]},
            inventory_raw=json.loads(
                paths["topic_inventory"].read_text(encoding="utf-8")
            ),
        )


def test_classification_base_allows_only_nonclassification_flag_evolution(
    tmp_path: Path,
) -> None:
    paths = _make_fixture(tmp_path)
    artifact, _ = _assemble(paths)
    base_items = copy.deepcopy(artifact["questions"])
    item = base_items[0]
    item.update(
        {
            "subject_code": None,
            "topic_slug": None,
            "syllabus_status": "review_required",
            "classification_status": "review_required",
            "review_flags": [
                "classification_review_required",
                "newer_content_evidence_blocker",
            ],
        }
    )
    projection = assembler._classification_projection(base_items)
    frozen_review = assembler._classification_review_row(item)
    frozen_review["review_flags"] = [
        "classification_review_required",
        "historical_content_evidence_blocker",
    ]
    key = (
        f"{item['source_paper_id']}#"
        f"{assembler._release_canonical_parent_ordinal(item)}"
    )
    identity = {
        "expected_count": 1,
        "classification_projection_sha256": assembler._canonical_sha256(projection),
        "review_key_sha256": assembler._canonical_sha256([key]),
    }
    core = {
        "schema_version": "1.0-staging-pyq-classification-review-base",
        "source_role": "immutable_pre_override_classification_projection",
        "database_writes_performed": False,
        "production_import_authorized": False,
        "automatic_promotion_allowed": False,
        "input_bindings": {
            "canonical_archive": _input_binding(paths["canonical"]),
            "legacy_subpart_audit": _input_binding(paths["legacy_audit"]),
            "legacy_child_policy": _input_binding(paths["legacy_child_policy"]),
            "base_parent_policy": _input_binding(paths["slot_policy"]),
            "topic_inventory": _input_binding(paths["topic_inventory"]),
            "content_verification_ledger": _input_binding(paths["content_ledger"]),
            "original_pdf_provenance": _input_binding(paths["provenance"]),
        },
        "counts": {"expanded_records": 3, "review_rows": 1},
        "base_review_identity": identity,
        "classification_projection_sha256": identity[
            "classification_projection_sha256"
        ],
        "classification_projection": projection,
        "review_rows": [frozen_review],
    }
    validated = assembler._validate_classification_review_base(
        _embedded(core),
        canonical_path=paths["canonical"],
        legacy_path=paths["legacy_audit"],
        child_policy_path=paths["legacy_child_policy"],
        parent_policy_path=paths["slot_policy"],
        inventory_path=paths["topic_inventory"],
        content_ledger_path=paths["content_ledger"],
        provenance_path=paths["provenance"],
        base_items=base_items,
    )
    assert validated["expected_count"] == 1

    tampered = copy.deepcopy(core)
    tampered["review_rows"][0]["item_label"] = "tampered"
    with pytest.raises(assembler.ReleaseAssemblyError, match="rows differ"):
        assembler._validate_classification_review_base(
            _embedded(tampered),
            canonical_path=paths["canonical"],
            legacy_path=paths["legacy_audit"],
            child_policy_path=paths["legacy_child_policy"],
            parent_policy_path=paths["slot_policy"],
            inventory_path=paths["topic_inventory"],
            content_ledger_path=paths["content_ledger"],
            provenance_path=paths["provenance"],
            base_items=base_items,
        )


def test_classification_override_application_rehashes_record(tmp_path: Path) -> None:
    paths = _make_fixture(tmp_path)
    artifact, _ = _assemble(paths)
    item = copy.deepcopy(artifact["questions"][0])
    item.update(
        {
            "subject_code": None,
            "topic_slug": None,
            "syllabus_status": "review_required",
            "classification_status": "review_required",
            "review_flags": sorted(
                set(item["review_flags"] + ["classification_review_required"])
            ),
        }
    )
    item["content_sha256"] = assembler._content_sha256(item)
    old_hash = item["content_sha256"]
    key = ("gate-cs-2000", 1, "1", None)
    assembler._apply_classification_review_overrides(
        [item],
        {
            key: {
                "decision": "map",
                "course": "EM",
                "topic": "discrete-mathematics",
                "decision_evidence_sha256": "b" * 64,
            }
        },
        artifact_sha256="c" * 64,
    )
    assert item["classification_status"] == "verified"
    assert "classification_review_required" not in item["review_flags"]
    assert item["content_sha256"] != old_hash
    assert item["content_sha256"] == assembler._content_sha256(item)


def test_missing_or_ambiguous_legacy_child_content_fails_closed(
    tmp_path: Path,
) -> None:
    paths = _make_fixture(tmp_path)
    audit = json.loads(paths["legacy_audit"].read_text(encoding="utf-8"))
    core = {key: value for key, value in audit.items() if key != "artifact_sha256"}
    children = core["papers"][0]["decisions"][0]["child_records"]
    children[1]["prompt_text"] = children[0]["prompt_text"]
    children[1]["prompt_text_sha256"] = children[0]["prompt_text_sha256"]
    children[1]["prompt_evidence"]["source_child_text_sha256"] = children[0][
        "prompt_text_sha256"
    ]
    _write(paths["legacy_audit"], _embedded(core))

    with pytest.raises(assembler.ReleaseAssemblyError, match="ambiguous"):
        _assemble(paths)


def test_authoritative_answer_conflict_fails_closed(tmp_path: Path) -> None:
    paths = _make_fixture(tmp_path)
    answer = json.loads(paths["answer_index"].read_text(encoding="utf-8"))
    core = {key: value for key, value in answer.items() if key != "artifact_version"}
    core["conflicts"] = [
        {
            "source_paper_id": "gate-cs-2000",
            "canonical_ordinal": 1,
            "kind": "official_claim_conflict",
            "claim_ids": ["a", "b"],
        }
    ]
    _write(
        paths["answer_index"],
        {**core, "artifact_version": assembler._canonical_sha256(core)},
    )

    with pytest.raises(assembler.ReleaseAssemblyError, match="authoritative conflicts"):
        _assemble(paths)


def test_review_only_child_classification_fails_closed(tmp_path: Path) -> None:
    paths = _make_fixture(tmp_path)
    policy = json.loads(paths["legacy_child_policy"].read_text(encoding="utf-8"))
    policy["child_decisions"][0]["decision"] = "review"
    policy["child_decisions"][0]["canonical_course"] = None
    policy["child_decisions"][0]["canonical_topic"] = None
    policy["summary"] = {"mapped": 1, "out_of_syllabus": 0, "review": 1}
    _write(paths["legacy_child_policy"], policy)

    with pytest.raises(assembler.ReleaseAssemblyError, match="review-only"):
        _assemble(paths)


def test_official_type_is_resolved_before_strict_secondary_option_parse() -> None:
    canonical = _canonical_question(
        label="1",
        ordinal=1,
        item_type="unknown",
        question=None,
    )
    candidate_body = "Pick one:\nA. Alpha\nB. Beta\nC. Gamma\nD. Delta"
    candidate = {
        "candidate": {"item_type": "unknown", "marks": None},
        "secondary_snapshots": {
            "gateoverflow": {
                "question_body_text": candidate_body,
                "question_body_sha256": assembler._sha256_text(candidate_body),
            }
        },
    }
    resolution = {
        "status": "official",
        "selected_answer": {"kind": "options", "options": ["A"]},
        "selected_question_type": "MCQ",
        "selected_marks": 1,
        "supporting_claim_ids": ["official-1"],
    }

    item_type, marks, answer, answer_status, _, _ = assembler._answer(
        canonical=canonical,
        candidate_row=candidate,
        resolution=resolution,
    )
    question, options, status, flags = assembler._transcription(
        canonical=canonical,
        candidate_row=candidate,
        overlay={"status": "review", "proposed_overlay": None},
        matcher_row=None,
        resolved_item_type=item_type,
    )

    assert (item_type, marks, answer, answer_status) == ("mcq", 1, "A", "official")
    assert question == "Pick one:"
    assert [option["id"] for option in options] == list("ABCD")
    assert status == "review_required"
    assert "secondary_options_review_only" in flags


def _community_candidate_row() -> dict[str, Any]:
    body = "Question text from GateOverflow"
    return {
        "reconciliation_status": "exact",
        "withheld_reasons": [],
        "candidate_review_reasons": [],
        "candidate": {
            "item_type": "mcq",
            "marks": 1,
            "answer": "A",
            "answer_status": "community_corroborated_candidate",
            "answer_claims": [
                {
                    "source": "gateoverflow",
                    "value": "A",
                    "authority": "secondary_community_candidate",
                },
                {
                    "source": "examside",
                    "value": "A",
                    "authority": "secondary_community_candidate",
                },
            ],
        },
        "secondary_snapshots": {
            "gateoverflow": {
                "question_body_text": body,
                "question_body_sha256": assembler._sha256_text(body),
                "page_text_sha256": "a" * 64,
            },
            "examside": {
                "source_id": "fixture-answer",
                "source_url": "https://example.test/fixture-answer",
                "raw_response_sha256": "b" * 64,
                "question_type": "mcq",
                "marks": 1,
            },
        },
        "promotion_review": {
            "answer_evidence": {
                "requirements_met": True,
                "independent_community_sources": ["examside", "gateoverflow"],
            }
        },
    }


def test_exact_two_source_community_answer_is_preserved_with_claim_hashes() -> None:
    canonical = _canonical_question(
        label="1", ordinal=1, item_type="mcq", question="Question"
    )

    item_type, marks, answer, status, flags, references = assembler._answer(
        canonical=canonical,
        candidate_row=_community_candidate_row(),
        resolution=None,
    )

    assert (item_type, marks, answer, status) == ("mcq", 1, "A", "community_verified")
    assert flags == []
    assert [reference["sha256"] for reference in references] == ["b" * 64, "a" * 64]
    assert {reference["kind"] for reference in references} == {
        "community_answer_claim"
    }


def test_single_source_community_answer_never_becomes_verified() -> None:
    canonical = _canonical_question(
        label="1", ordinal=1, item_type="mcq", question="Question"
    )
    candidate = _community_candidate_row()
    candidate["candidate"]["answer_claims"] = candidate["candidate"][
        "answer_claims"
    ][:1]
    candidate["promotion_review"]["answer_evidence"][
        "independent_community_sources"
    ] = ["gateoverflow"]

    _, _, answer, status, flags, references = assembler._answer(
        canonical=canonical,
        candidate_row=candidate,
        resolution=None,
    )

    assert answer is None
    assert status == "unresolved"
    assert references == []
    assert "community_answer_independent_sources_missing" in flags
    assert "objective_answer_not_verified" in flags


def test_conflicting_community_claims_fail_closed() -> None:
    canonical = _canonical_question(
        label="1", ordinal=1, item_type="mcq", question="Question"
    )
    candidate = _community_candidate_row()
    candidate["candidate"]["answer_claims"][1]["value"] = "B"

    with pytest.raises(assembler.ReleaseAssemblyError, match="claims conflict"):
        assembler._answer(
            canonical=canonical,
            candidate_row=candidate,
            resolution=None,
        )


def test_invalid_multi_option_mcq_community_shape_remains_unverified() -> None:
    canonical = _canonical_question(
        label="1", ordinal=1, item_type="mcq", question="Question"
    )
    candidate = _community_candidate_row()
    candidate["candidate"]["answer"] = ["A", "B"]
    for claim in candidate["candidate"]["answer_claims"]:
        claim["value"] = ["A", "B"]

    _, _, answer, status, flags, _ = assembler._answer(
        canonical=canonical,
        candidate_row=candidate,
        resolution=None,
    )

    assert answer is None
    assert status == "unresolved"
    assert "community_answer_shape_invalid" in flags


def test_review_only_match_or_secondary_text_never_becomes_verified() -> None:
    canonical = _canonical_question(
        label="1",
        ordinal=1,
        item_type="mcq",
        question="placeholder",
    )
    canonical["question_md"] = None
    canonical["transcription_status"] = "missing"
    candidate = {
        "candidate": {
            "question_text": "Secondary text",
            "options": ["A", "B", "C", "D"],
        }
    }
    matcher = {
        "manual_review_required": True,
        "proposed_review_content": {
            "question_text": "Matcher text",
            "options": ["A", "B", "C", "D"],
        },
    }

    question, options, status, flags = assembler._transcription(
        canonical=canonical,
        candidate_row=candidate,
        overlay={"status": "review", "proposed_overlay": {"question_text": "OCR"}},
        matcher_row=matcher,
        resolved_item_type="mcq",
    )

    assert question == "Matcher text"
    assert options == ["A", "B", "C", "D"]
    assert status == "review_required"
    assert "matcher_transcription_review_only" in flags
    assert "matcher_options_review_only" in flags


def test_matcher_list_bindings_are_hash_checked_recursively(tmp_path: Path) -> None:
    primary = tmp_path / "candidate.json"
    ocr = tmp_path / "ocr.json"
    primary.write_text("candidate", encoding="utf-8")
    ocr.write_text("ocr", encoding="utf-8")
    matcher = _embedded(
        {
            "schema_version": "1.0-staging-high-confidence-transcription-matches",
            "database_writes_performed": False,
            "production_import_authorized": False,
            "automatic_promotion_allowed": False,
            "input_bindings": {
                "candidate": _input_binding(primary),
                "ocr_candidates": [_input_binding(ocr)],
            },
            "matches": [],
            "decisions": [],
        }
    )

    assert assembler._validate_matcher(matcher, matcher_path=tmp_path / "matcher.json") == {}

    ocr.write_text("drift", encoding="utf-8")
    with pytest.raises(assembler.ReleaseAssemblyError, match="is stale"):
        assembler._validate_matcher(matcher, matcher_path=tmp_path / "matcher.json")
