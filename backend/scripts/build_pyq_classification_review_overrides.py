"""Build a fail-closed, staging-only second-pass classification contract.

The final release assembler deliberately leaves ambiguous course/topic labels
as ``review_required``.  This module revisits exactly that bounded set using
only checksum-bound original text blocks or OCR made from checksum-bound
original PDF pages.  It never changes the base classification policies and it
never authorizes production import or practice eligibility.

Third-party indexes are not evidence here.  They may have helped a human find
the original page, but every emitted decision is bound to an original-PDF
text/page hash.  Compound questions and insufficient/misaligned locators stay
``review``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Mapping


REPO_DIR = Path(__file__).resolve().parents[2]
BUILD_DIR = REPO_DIR / "tmp" / "pyq" / "build"
DATA_DIR = REPO_DIR / "backend" / "data"

DEFAULT_BASE = DATA_DIR / "pyq_classification_review_base.json"
DEFAULT_CANONICAL = BUILD_DIR / "canonical_pyq_archive.json"
DEFAULT_LEGACY_AUDIT = DATA_DIR / "legacy_pyq_subparts_1996_2002.json"
DEFAULT_LEGACY_CHILD_POLICY = DATA_DIR / "pyq_legacy_child_classifications.json"
DEFAULT_PARENT_POLICY = DATA_DIR / "pyq_slot_classification_overrides.json"
DEFAULT_TOPIC_INVENTORY = DATA_DIR / "question_bank_manifest.json"
DEFAULT_CONTENT_LEDGER = BUILD_DIR / "verified_pyq_content.json"
DEFAULT_PROVENANCE = BUILD_DIR / "original_pdf_provenance.json"
DEFAULT_REVIEW_EVIDENCE = BUILD_DIR / "classification_review_evidence.json"
DEFAULT_LOCATOR_OCR = BUILD_DIR / "original_pdf_locator_ocr_candidates.json"
DEFAULT_2015_OCR = BUILD_DIR / "classification_review_2015_page_ocr.json"
DEFAULT_OUTPUT = DATA_DIR / "pyq_classification_review_overrides.json"

OCR_CACHE_PATHS = {
    "gate-cs-2017-session-1": REPO_DIR / "tmp" / "pyq" / "ocr-text" / "CS1-2017.json",
    "gate-cs-2017-session-2": REPO_DIR / "tmp" / "pyq" / "ocr-text" / "CS2-2017.json",
    "gate-cs-2019": REPO_DIR / "tmp" / "pyq" / "ocr-text" / "CS-2019.json",
    "gate-cs-2020": REPO_DIR / "tmp" / "pyq" / "ocr-text" / "CS-2020.json",
}
OCR_IMAGE_DIRS = {
    "gate-cs-2017-session-1": REPO_DIR / "tmp" / "pyq" / "ocr-CS1-2017",
    "gate-cs-2017-session-2": REPO_DIR / "tmp" / "pyq" / "ocr-CS2-2017",
    "gate-cs-2019": REPO_DIR / "tmp" / "pyq" / "ocr-2019",
    "gate-cs-2020": REPO_DIR / "tmp" / "pyq" / "ocr-2020",
}

SCHEMA_VERSION = "1.0-staging-pyq-classification-review-overrides"
EXPECTED_REVIEW_COUNT = 82
EXPECTED_EXPANDED_COUNT = 2873
BASE_SCHEMA_VERSION = "1.0-staging-pyq-classification-review-base"


class ClassificationReviewError(RuntimeError):
    """Raised when a classification decision or evidence binding is unsafe."""


def _map(course: str, topic: str, code: str, reason: str) -> tuple[str, str, str, str, str]:
    return ("map", course, topic, code, reason)


def _oos(code: str, reason: str) -> tuple[str, None, None, str, str]:
    return ("out_of_syllabus", None, None, code, reason)


def _review(code: str, reason: str) -> tuple[str, None, None, str, str]:
    return ("review", None, None, code, reason)


# Every row is a fresh evidence decision.  Existing policy values appear only
# in the emitted prior-classification comparison and are never inherited.
DECISIONS: dict[str, tuple[str, str | None, str | None, str, str]] = {
    "gate-cs-1996#22": _map("COA", "machine-instructions-and-addressing-modes", "explicit_machine_instruction_timing", "The original question explicitly asks about execution cycles of the 8085 RET machine instruction."),
    "gate-cs-1996#30": _oos("numerical_root_finding_not_in_current_syllabus", "Newton-Raphson root-finding is numerical analysis and is not listed in the GATE CSE 2027 syllabus."),
    "gate-cs-1997#5": _review("compound_algorithm_paradigms", "The exact question spans greedy, depth-first search, dynamic programming, and divide-and-conquer; no single canonical topic is faithful."),
    "gate-cs-1997#52": _map("PDS", "linked-lists", "explicit_linked_list_pointer_program", "The original Pascal record and pointer procedure operates on a linked list."),
    "gate-cs-1998#45": _map("COA", "machine-instructions-and-addressing-modes", "explicit_processor_address_space", "The original question asks for the address space of the 8086 processor."),
    "gate-cs-1999#9": _review("compound_os_abstractions", "The question deliberately matches threads, virtual address spaces, file systems, and signals to different hardware resources."),
    "gate-cs-1999#23": _oos("numerical_root_finding_not_in_current_syllabus", "Newton-Raphson convergence conditions are numerical analysis outside the current syllabus."),
    "gate-cs-1999#38": _map("CD", "runtime-environments", "explicit_dynamic_scoping", "The program outcome depends explicitly on dynamic scoping in the run-time environment."),
    "gate-cs-1999#39": _map("CD", "lexical-analysis", "explicit_token_count", "The question asks for the number of lexical tokens in a Fortran statement."),
    "gate-cs-2000#27": _oos("polynomial_interpolation_not_in_current_syllabus", "Minimum-degree polynomial interpolation is not listed in the current Engineering Mathematics syllabus."),
    "gate-cs-2000#36": _oos("graphics_frame_buffer_not_in_current_syllabus", "Graphics display modes and frame-buffer colour capacity are outside the current GATE CSE syllabus."),
    "gate-cs-2005#3": _review("original_locator_conflict", "The canonical locator lands inside another question's code/options and does not isolate question 3 safely."),
    "gate-cs-2005#4": _review("original_locator_conflict", "The canonical locator page starts at question 5 and does not contain an unambiguous question-4 block."),
    "gate-cs-2005#58": _map("ALG", "complexity-analysis", "explicit_p_np_completeness", "The original question compares P/NP-completeness of two independent-set decision problems."),
    "gate-cs-2007#4": _map("EM", "discrete-mathematics", "explicit_planar_graph", "The original question asks about a minimum-edge non-planar graph."),
    "gate-cs-2007#19": _map("CN", "data-link-layer", "explicit_ethernet_encoding", "The original question asks about Manchester encoding in Ethernet."),
    "gate-cs-2007#28": _oos("numerical_root_finding_not_in_current_syllabus", "The original question is a Newton-Raphson numerical-method iteration."),
    "gate-cs-2007#66": _map("CN", "data-link-layer", "explicit_token_ring", "The original question asks about bit delay in a token-ring LAN."),
    "gate-cs-2007#70": _map("CN", "layering-and-switching", "explicit_protocol_layer_matching", "The question explicitly matches SMTP, BGP, TCP, and PPP to protocol layers."),
    "gate-cs-2008#21": _oos("numerical_quadrature_not_in_current_syllabus", "Trapezoidal-rule error sizing is numerical analysis outside the current syllabus."),
    "gate-cs-2008#22": _oos("numerical_root_finding_not_in_current_syllabus", "The Newton-Raphson iteration is numerical analysis outside the current syllabus."),
    "gate-cs-2008#24": _review("formula_ocr_and_syllabus_boundary", "The summation limits/formula are not preserved clearly enough in page OCR, and generic summation has no unique current topic."),
    "gate-cs-2008#44": _map("ALG", "complexity-analysis", "explicit_subset_sum_complexity", "The original question asks about pseudo-polynomial subset-sum complexity and NP hardness."),
    "gate-cs-2009#14": _map("ALG", "complexity-analysis", "explicit_np_classification", "The original question explicitly reasons about membership in NP and NP-completeness."),
    "gate-cs-2009#17": _review("compound_compiler_phases", "The question spans lexical analysis, syntax analysis, code generation, and code optimization."),
    "gate-cs-2009#19": _oos("software_engineering_not_in_current_syllabus", "Software-module coupling categories are outside the current syllabus."),
    "gate-cs-2009#20": _oos("web_markup_not_in_current_syllabus", "HTML table layout is outside the current syllabus."),
    "gate-cs-2009#46": _oos("cryptography_not_in_current_syllabus", "RSA cryptosystem equations are outside the current syllabus."),
    "gate-cs-2009#49": _oos("software_engineering_not_in_current_syllabus", "Data-flow-diagram rules are outside the current syllabus."),
    "gate-cs-2009#50": _oos("software_testing_not_in_current_syllabus", "Cyclomatic-complexity testing criteria are outside the current syllabus."),
    "gate-cs-2010#2": _oos("numerical_root_finding_not_in_current_syllabus", "The original question is a Newton-Raphson numerical-method iteration."),
    "gate-cs-2010#15": _map("CN", "ipv4-addressing-and-forwarding", "explicit_ipv4_ttl", "The question explicitly asks why the IPv4 Time-to-Live header field is needed."),
    "gate-cs-2010#16": _map("CN", "application-layer", "explicit_client_server_application", "The question asks which named Internet service is not a client-server application."),
    "gate-cs-2010#21": _oos("software_testing_not_in_current_syllabus", "Cyclomatic complexity of integrated software modules is outside the current syllabus."),
    "gate-cs-2010#22": _oos("software_engineering_not_in_current_syllabus", "Software-life-cycle activity matching is outside the current syllabus."),
    "gate-cs-2010#44": _oos("software_testing_not_in_current_syllabus", "Statement-coverage test-suite selection is outside the current syllabus."),
    "gate-cs-2011#2": _map("CN", "layering-and-switching", "explicit_layer_visibility", "The question is explicitly about which headers and traffic properties are visible through protocol layer 4."),
    "gate-cs-2011#5": _oos("software_engineering_not_in_current_syllabus", "Software development and five-year maintenance cost estimation are outside the current syllabus."),
    "gate-cs-2011#7": _oos("software_engineering_not_in_current_syllabus", "Basic COCOMO effort estimation is outside the current syllabus."),
    "gate-cs-2011#9": _oos("web_markup_not_in_current_syllabus", "HTML page actions are outside the current syllabus."),
    "gate-cs-2011#10": _oos("software_engineering_not_in_current_syllabus", "SRS document contents are outside the current syllabus."),
    "gate-cs-2011#47": _oos("software_testing_not_in_current_syllabus", "Black-box test-case design for a software routine is outside the current syllabus."),
    "gate-cs-2014-session-1#47": _map("DL", "number-representation-and-arithmetic", "binary_weight_encoding", "The 1,2,4,8,16 coin counts encode the excess weight as a binary number."),
    "gate-cs-2015-session-1#11": _map("EM", "discrete-mathematics", "explicit_function_composition", "The original question compares compositions of two explicitly defined functions."),
    "gate-cs-2015-session-1#16": _oos("software_testing_not_in_current_syllabus", "Software testing methods and test levels are outside the current syllabus."),
    "gate-cs-2015-session-1#21": _map("DL", "sequential-circuits", "explicit_johnson_counter", "The question asks for the state sequence of a four-bit Johnson counter."),
    "gate-cs-2015-session-1#22": _map("COA", "machine-instructions-and-addressing-modes", "explicit_three_address_instruction", "The question asks what each address field in a three-address instruction can specify."),
    "gate-cs-2015-session-1#23": _map("CN", "transport-layer", "explicit_tcp_connection", "All statements concern sequence numbers, retransmission timeout, and advertised window in TCP."),
    "gate-cs-2015-session-1#24": _oos("cryptography_not_in_current_syllabus", "Symmetric-key confidentiality key counts are outside the current syllabus."),
    "gate-cs-2015-session-1#25": _oos("web_markup_not_in_current_syllabus", "XML and HTML specification details are outside the current syllabus."),
    "gate-cs-2015-session-1#26": _map("CN", "ipv4-addressing-and-forwarding", "explicit_ip_header", "The question asks which IPv4 header field a router does not modify."),
    "gate-cs-2015-session-1#27": _map("CN", "application-layer", "explicit_application_protocol_connections", "The question compares TCP connection use by HTTP, FTP, TELNET, and SMTP."),
    "gate-cs-2015-session-1#28": _map("TOC", "pumping-lemmas-and-language-properties", "explicit_language_closure_properties", "The question asks closure/decidability properties of context-free and recursively enumerable languages."),
    "gate-cs-2015-session-1#29": _map("OS", "memory-and-virtual-memory", "explicit_page_table_size", "The question computes page-table size from logical address and page-size parameters."),
    "gate-cs-2015-session-1#31": _map("DBMS", "sql", "explicit_sql_select_semantics", "The question explicitly compares SQL SELECT with relational algebra operations."),
    "gate-cs-2015-session-1#36": _map("CN", "data-link-layer", "explicit_stop_and_wait", "The question computes the minimum frame size for stop-and-wait link utilization."),
    "gate-cs-2015-session-1#52": _map("OS", "cpu-and-i-o-scheduling", "explicit_periodic_priority_scheduling", "The question schedules periodic tasks by inverse-period priority on a uniprocessor."),
    "gate-cs-2015-session-2#12": _map("EM", "discrete-mathematics", "explicit_power_set", "The question asks for the cardinality of a finite set's power set."),
    "gate-cs-2015-session-2#14": _map("EM", "discrete-mathematics", "finite_divisor_count", "Counting the divisors of 2100 is a finite combinatorial counting problem."),
    "gate-cs-2015-session-2#22": _map("PDS", "heaps", "explicit_heap_construction_bound", "The question asks for a lower bound to convert a complete binary tree with heap subtrees into a heap."),
    "gate-cs-2015-session-2#23": _map("PDS", "trees-and-binary-search-trees", "explicit_binary_tree_degree_identity", "The question relates the leaf count to nodes having two children in a binary tree."),
    "gate-cs-2015-session-2#29": _oos("software_engineering_not_in_current_syllabus", "The original question asks for the basic COCOMO equations."),
    "gate-cs-2015-session-2#46": _map("TOC", "pumping-lemmas-and-language-properties", "explicit_regular_language_classification", "The question asks which of several formally defined languages are regular."),
    "gate-cs-2015-session-2#49": _map("ALG", "divide-and-conquer", "explicit_partition_selection_recursion", "The question completes recursive kth-smallest selection using a partition operation."),
    "gate-cs-2015-session-2#53": _map("COA", "instruction-pipelining", "explicit_pipeline_hazards_and_forwarding", "The question computes cycles for dependent instructions in a four-stage pipeline with operand forwarding."),
    "gate-cs-2015-session-3#18": _oos("web_markup_not_in_current_syllabus", "HTML base URLs and relative links are outside the current syllabus."),
    "gate-cs-2015-session-3#21": _map("PDS", "trees-and-binary-search-trees", "explicit_binary_tree_degree_identity", "The question relates leaf nodes to nodes having exactly two children in a binary tree."),
    "gate-cs-2015-session-3#31": _map("OS", "concurrency-and-synchronization", "explicit_critical_section_protocol", "The question evaluates mutual exclusion and deadlock properties of a two-process critical-section protocol."),
    "gate-cs-2015-session-3#60": _map("EM", "discrete-mathematics", "explicit_relation_properties", "The question asks whether a relation on ordered pairs is reflexive and symmetric."),
    "gate-cs-2015-session-3#65": _map("CD", "parsing", "explicit_ll_lr_parsing", "The question asks whether LL(1) and LR(1) parsers can parse strings from a given grammar."),
    "gate-cs-2016-session-2#29": _review("compound_compiler_phases", "The exact question spans lexical analysis, parsing, semantic analysis, and runtime environments."),
    "gate-cs-2017-session-1#15": _review("compound_algorithm_paradigms", "The original question jointly maps Kruskal, Quicksort, and Floyd-Warshall across three design paradigms."),
    "gate-cs-2017-session-1#25": _oos("cryptography_not_in_current_syllabus", "Digital signatures and birthday attacks are outside the current syllabus."),
    "gate-cs-2017-session-1#54": _oos("cryptography_not_in_current_syllabus", "RSA public/private key computation is outside the current syllabus."),
    "gate-cs-2017-session-2#15": _review("compound_compiler_phases", "The question matches syntax trees, character streams, intermediate representations, and token streams to different compiler phases."),
    "gate-cs-2018#18": _review("compound_compiler_phases", "The exact question spans lexical/syntax rules, type checking, intermediate representations, and runtime stacks."),
    "gate-cs-2019#64": _oos("cryptography_not_in_current_syllabus", "RSA modulus factorization is outside the current syllabus."),
    "gate-cs-2020#19": _review("compound_compiler_phases", "The question jointly tests symbol-table access, recursive runtime storage, and declaration-error detection phases."),
    "gate-cs-2023#11": _review("broad_frontend_backend_boundary", "Front-end/back-end compiler partitioning spans several canonical compiler topics and has no unique topic."),
    "gate-cs-2024-set-2#21": _review("compound_compiler_phases", "The exact question matches lexical analysis, syntax analysis, intermediate-code generation, and optimization to outputs."),
    "gate-cs-2025-set-1#12": _review("symbol_table_spans_topics", "The symbol-table question spans scope, data-structure implementation, parsing, and lexical-analysis lifecycle."),
    "gate-cs-2025-set-2#38": _review("compound_data_structures", "The exact meld question simultaneously compares linked lists, array heaps, and binary search trees."),
}


CONTINUATION_PAGES = {
    "gate-cs-2015-session-1#52": 20,
    "gate-cs-2015-session-2#46": 42,
    "gate-cs-2015-session-2#49": 44,
    "gate-cs-2015-session-2#53": 47,
    "gate-cs-2015-session-3#31": 64,
    "gate-cs-2015-session-3#65": 79,
}

ALLOW_FULL_PAGE_REVIEW = {"gate-cs-2005#3", "gate-cs-2005#4"}


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ClassificationReviewError(f"Cannot read JSON {path}: {exc}") from exc


def _validate_embedded(payload: Any, *, context: str) -> str | None:
    if not isinstance(payload, Mapping) or "artifact_sha256" not in payload:
        return None
    expected = payload.get("artifact_sha256")
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ClassificationReviewError(f"{context}: malformed artifact_sha256")
    core = {key: value for key, value in payload.items() if key != "artifact_sha256"}
    if _canonical_sha256(core) != expected:
        raise ClassificationReviewError(f"{context}: embedded artifact_sha256 mismatch")
    return expected


def _binding(path: Path, *, validate_embedded: bool = False) -> dict[str, Any]:
    resolved = path.resolve()
    payload = _read_json(resolved) if validate_embedded else None
    embedded = (
        _validate_embedded(payload, context=str(resolved))
        if validate_embedded
        else None
    )
    result: dict[str, Any] = {
        "path": resolved.relative_to(REPO_DIR).as_posix(),
        "sha256": _sha256_file(resolved),
        "bytes": resolved.stat().st_size,
    }
    if embedded is not None:
        result["embedded_artifact_sha256"] = embedded
    return result


def _normalise_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _canonical_inventory(raw: Mapping[str, Any]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for course, data in (raw.get("courses") or {}).items():
        topics = (data or {}).get("by_topic") or {}
        slugs = {
            re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")
            for name in topics
        }
        result[str(course)] = slugs
    return result


def _classification_projection(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "source_paper_id": row["source_paper_id"],
            "canonical_parent_ordinal": _canonical_parent_ordinal(row),
            "final_release_ordinal": row["ordinal"],
            "item_label": row["item_label"],
            "parent_item_label": row.get("parent_item_label"),
            "subject_code": row.get("subject_code"),
            "topic_slug": row.get("topic_slug"),
            "syllabus_status": row.get("syllabus_status"),
            "classification_status": row.get("classification_status"),
        }
        for row in questions
    ]


def _canonical_parent_ordinal(row: Mapping[str, Any]) -> int:
    explicit = row.get("canonical_parent_ordinal")
    if isinstance(explicit, int) and explicit > 0:
        return explicit
    values: set[int] = set()
    for reference in row.get("source_references") or []:
        if not isinstance(reference, Mapping) or reference.get("kind") != "canonical_parent_slot":
            continue
        match = re.search(
            r"canonical_parent_ordinal=(\d+)", str(reference.get("note") or "")
        )
        if match:
            values.add(int(match.group(1)))
    if len(values) > 1:
        raise ClassificationReviewError(
            f"{row.get('source_paper_id')}#{row.get('ordinal')}: conflicting canonical parent ordinals"
        )
    return next(iter(values), int(row["ordinal"]))


def _key(row: Mapping[str, Any]) -> str:
    return f"{row['source_paper_id']}#{_canonical_parent_ordinal(row)}"


def _validated_base_snapshot(payload: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    _validate_embedded(payload, context="classification review base")
    if payload.get("schema_version") != BASE_SCHEMA_VERSION:
        raise ClassificationReviewError("Unexpected classification review base schema")
    for field in (
        "database_writes_performed",
        "production_import_authorized",
        "automatic_promotion_allowed",
    ):
        if payload.get(field) is not False:
            raise ClassificationReviewError(f"Unsafe base guard: {field}")
    projection = payload.get("classification_projection")
    if not isinstance(projection, list) or len(projection) != EXPECTED_EXPANDED_COUNT:
        raise ClassificationReviewError("Classification base projection must contain 2,873 rows")
    projection_sha = _canonical_sha256(projection)
    if payload.get("classification_projection_sha256") != projection_sha:
        raise ClassificationReviewError("Classification base projection hash mismatch")
    review_rows = payload.get("review_rows")
    if not isinstance(review_rows, list) or len(review_rows) != EXPECTED_REVIEW_COUNT:
        raise ClassificationReviewError("Classification base must contain 82 review rows")
    keys = [_key(row) for row in review_rows]
    if len(set(keys)) != EXPECTED_REVIEW_COUNT or set(keys) != set(DECISIONS):
        raise ClassificationReviewError("Classification base review identity drifted")
    if any(
        row.get("classification_status") != "review_required"
        or row.get("syllabus_status") != "review_required"
        or "classification_review_required" not in (row.get("review_flags") or [])
        for row in review_rows
    ):
        raise ClassificationReviewError("Classification base contains a finalized review row")
    review_key_sha = _canonical_sha256(sorted(keys))
    identity = payload.get("base_review_identity")
    expected_identity = {
        "expected_count": EXPECTED_REVIEW_COUNT,
        "classification_projection_sha256": projection_sha,
        "review_key_sha256": review_key_sha,
    }
    if identity != expected_identity:
        raise ClassificationReviewError("Classification base identity hash drifted")
    projection_review = {
        (
            row["source_paper_id"],
            int(row["canonical_parent_ordinal"]),
            row["item_label"],
        ): row
        for row in projection
        if row.get("classification_status") == "review_required"
    }
    for row in review_rows:
        key = (
            row["source_paper_id"],
            int(row["canonical_parent_ordinal"]),
            row["item_label"],
        )
        projected = projection_review.get(key)
        if projected is None or any(
            projected.get(field) != row.get(source_field)
            for field, source_field in (
                ("final_release_ordinal", "ordinal"),
                ("parent_item_label", "parent_item_label"),
                ("subject_code", "subject_code"),
                ("topic_slug", "topic_slug"),
                ("syllabus_status", "syllabus_status"),
                ("classification_status", "classification_status"),
            )
        ):
            raise ClassificationReviewError(
                f"Classification base review row is absent from projection: {_key(row)}"
            )
    return [dict(row) for row in review_rows], dict(expected_identity)


def _marker_number(row: Mapping[str, Any]) -> int | None:
    paper = str(row["source_paper_id"])
    label = str(row["item_label"])
    if paper.startswith(("gate-cs-2014", "gate-cs-2017", "gate-cs-2019", "gate-cs-2020")):
        match = re.search(r"(\d+)$", label)
        return int(match.group(1)) if match else None
    if paper.startswith("gate-cs-2015"):
        return int(row["ordinal"])
    return None


def _extract_marker_excerpt(
    text: str,
    *,
    row: Mapping[str, Any],
    continuation: bool,
) -> tuple[str, str]:
    normal = _normalise_space(text)
    if not normal:
        return "", ""
    if continuation:
        marker = _marker_number(row)
        next_pattern = (
            re.compile(
                rf"(?:Question\s*Number|Q\.?\s*(?:No\.?)?)\s*:?\s*{marker + 1}(?!\d)",
                re.IGNORECASE,
            )
            if marker is not None
            else None
        )
        end_match = next_pattern.search(normal) if next_pattern else None
        return normal[: end_match.start() if end_match else min(len(normal), 1800)], "continuation_page_prefix"

    marker_number = _marker_number(row)
    patterns: list[re.Pattern[str]] = []
    if marker_number is not None:
        patterns.append(
            re.compile(
                rf"(?:Question\s*Number|Q\.?\s*(?:No\.?)?)\s*:?\s*{marker_number}(?!\d)",
                re.IGNORECASE,
            )
        )
        patterns.append(re.compile(rf"\b{marker_number}\b"))
    else:
        label = re.escape(str(row["item_label"]))
        label = label.replace(r"\.", r"\s*\.\s*")
        patterns.append(re.compile(rf"\b{label}\s*\.?", re.IGNORECASE))
        patterns.append(re.compile(rf"\b{int(row['ordinal'])}\b"))

    found = next((match for pattern in patterns if (match := pattern.search(normal))), None)
    if found is None:
        return "", ""
    start = found.start()
    tail = normal[found.end() :]
    next_question = re.search(
        r"(?:Question\s*Number|Q\.?\s*(?:No\.?)?)\s*:?\s*\d+(?!\d)",
        tail,
        re.IGNORECASE,
    )
    end = found.end() + next_question.start() if next_question else min(len(normal), start + 1800)
    return normal[start:end].strip(), found.group(0)


def _exact_original_evidence(
    *, row: Mapping[str, Any], evidence_row: Mapping[str, Any]
) -> dict[str, Any] | None:
    original = evidence_row.get("original_source") or {}
    text = original.get("text")
    status = original.get("evidence_status")
    if not isinstance(text, str) or not text.strip():
        return None
    if status not in {"exact_text_block", "rendered_page_review_required"}:
        return None
    if status != "exact_text_block" and len(_normalise_space(text)) < 80:
        return None
    declared = original.get("text_block_sha256")
    if declared != _sha256_text(text):
        raise ClassificationReviewError(f"{_key(row)}: original text-block hash mismatch")
    pages = original.get("source_pages") or []
    return {
        "kind": (
            "checksum_bound_original_text_block"
            if status == "exact_text_block"
            else "checksum_bound_original_page_text_review"
        ),
        "source_pdf_sha256": original.get("source_pdf_sha256"),
        "source_pages": pages,
        "text_block_sha256": declared,
        "excerpt": text,
        "excerpt_sha256": _sha256_text(text),
        "rendered_page_evidence": list(original.get("rendered_page_evidence") or []),
        "question_boundary_status": status,
    }


def _locator_ocr_maps(payload: Mapping[str, Any]) -> tuple[dict[str, Mapping[str, Any]], dict[tuple[str, int], Mapping[str, Any]]]:
    papers: dict[str, Mapping[str, Any]] = {}
    pages: dict[tuple[str, int], Mapping[str, Any]] = {}
    for paper in payload.get("papers") or []:
        paper_id = str(paper["paper_id"])
        papers[paper_id] = paper
        for page in paper.get("pages") or []:
            pages[(paper_id, int(page["page"]))] = page
    return papers, pages


def _ocr_evidence(
    *,
    row: Mapping[str, Any],
    provenance_papers: Mapping[str, Mapping[str, Any]],
    locator_papers: Mapping[str, Mapping[str, Any]],
    locator_pages: Mapping[tuple[str, int], Mapping[str, Any]],
    ocr_2015: Mapping[str, Any],
    cache_payloads: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    key = _key(row)
    paper_id = str(row["source_paper_id"])
    page_number = CONTINUATION_PAGES.get(key, int(row["source_page"]))
    continuation = key in CONTINUATION_PAGES
    source_pdf_sha = (provenance_papers.get(paper_id) or {}).get("source_pdf_sha256")

    text: str
    page_text_sha: str
    image_sha: str | None
    confidence: float | None
    source_kind: str
    source_artifact_sha: str | None = None

    if paper_id.startswith("gate-cs-2015"):
        page = next(
            (item for item in ocr_2015.get("pages") or [] if int(item["page"]) == page_number),
            None,
        )
        if page is None:
            raise ClassificationReviewError(f"{key}: 2015 OCR page {page_number} missing")
        if ocr_2015.get("source_pdf_sha256") != source_pdf_sha:
            raise ClassificationReviewError(f"{key}: 2015 OCR source PDF hash mismatch")
        text = str(page.get("normalized_text") or "")
        page_text_sha = _sha256_text(text)
        image_sha = str(page.get("image_sha256") or "")
        image_path = REPO_DIR / str(page["image_path"])
        if _sha256_file(image_path) != image_sha:
            raise ClassificationReviewError(f"{key}: 2015 rendered image hash mismatch")
        confidence_values = [float(line["confidence"]) for line in page.get("lines") or []]
        confidence = sum(confidence_values) / len(confidence_values) if confidence_values else None
        source_kind = "checksum_bound_original_pdf_page_rapidocr"
        source_artifact_sha = str(ocr_2015.get("artifact_sha256"))
    elif paper_id in cache_payloads:
        page = (cache_payloads[paper_id] or {}).get(str(page_number))
        if not isinstance(page, Mapping):
            raise ClassificationReviewError(f"{key}: OCR cache page {page_number} missing")
        text = str(page.get("text") or "")
        page_text_sha = _sha256_text(text)
        image_path = OCR_IMAGE_DIRS[paper_id] / f"page-{page_number:02d}.png"
        if not image_path.exists():
            raise ClassificationReviewError(f"{key}: rendered OCR image missing: {image_path}")
        image_sha = _sha256_file(image_path)
        confidence = float(page["confidence"]) if page.get("confidence") is not None else None
        source_kind = "checksum_bound_original_pdf_page_rapidocr_cache"
    else:
        page = locator_pages.get((paper_id, page_number))
        paper = locator_papers.get(paper_id)
        if page is None or paper is None:
            raise ClassificationReviewError(f"{key}: no checksum-bound OCR page evidence")
        if paper.get("source_pdf_sha256") != source_pdf_sha:
            raise ClassificationReviewError(f"{key}: locator OCR source PDF hash mismatch")
        text = str(page.get("normalized_ocr_text") or "")
        page_text_sha = str(page.get("normalized_ocr_sha256") or "")
        if page_text_sha != _sha256_text(text):
            raise ClassificationReviewError(f"{key}: locator OCR text hash mismatch")
        image_sha = str(page.get("ocr_rendered_png_sha256") or page.get("source_rendered_pgm_sha256") or "") or None
        confidence = float(page["mean_confidence"]) if page.get("mean_confidence") is not None else None
        source_kind = "checksum_bound_original_pdf_page_ocr_index"
        source_artifact_sha = None

    excerpt, marker = _extract_marker_excerpt(text, row=row, continuation=continuation)
    if not excerpt:
        if key not in ALLOW_FULL_PAGE_REVIEW:
            raise ClassificationReviewError(f"{key}: OCR excerpt marker not found")
        excerpt = _normalise_space(text)[:1800]
        marker = "full_page_locator_conflict_review_only"
    return {
        "kind": source_kind,
        "source_pdf_sha256": source_pdf_sha,
        "source_pages": [page_number],
        "page_ocr_text_sha256": page_text_sha,
        "rendered_page_sha256": image_sha,
        "ocr_confidence": confidence,
        "ocr_artifact_sha256": source_artifact_sha,
        "locator": marker,
        "excerpt": excerpt,
        "excerpt_sha256": _sha256_text(excerpt),
        "question_boundary_status": (
            "continuation_page_item_bounded"
            if continuation
            else "marker_bounded_page_ocr"
            if key not in ALLOW_FULL_PAGE_REVIEW
            else "page_level_locator_conflict"
        ),
    }


def build_overrides(
    *,
    base_path: Path = DEFAULT_BASE,
    canonical_path: Path = DEFAULT_CANONICAL,
    legacy_audit_path: Path = DEFAULT_LEGACY_AUDIT,
    legacy_child_policy_path: Path = DEFAULT_LEGACY_CHILD_POLICY,
    parent_policy_path: Path = DEFAULT_PARENT_POLICY,
    topic_inventory_path: Path = DEFAULT_TOPIC_INVENTORY,
    content_ledger_path: Path = DEFAULT_CONTENT_LEDGER,
    provenance_path: Path = DEFAULT_PROVENANCE,
    review_evidence_path: Path = DEFAULT_REVIEW_EVIDENCE,
    locator_ocr_path: Path = DEFAULT_LOCATOR_OCR,
    ocr_2015_path: Path = DEFAULT_2015_OCR,
) -> dict[str, Any]:
    base = _read_json(base_path)
    canonical = _read_json(canonical_path)
    legacy_audit = _read_json(legacy_audit_path)
    child_policy = _read_json(legacy_child_policy_path)
    parent_policy = _read_json(parent_policy_path)
    inventory_raw = _read_json(topic_inventory_path)
    ledger = _read_json(content_ledger_path)
    provenance = _read_json(provenance_path)
    review_evidence_raw = _read_json(review_evidence_path)
    locator_ocr = _read_json(locator_ocr_path)
    ocr_2015 = _read_json(ocr_2015_path)
    cache_payloads = {paper: _read_json(path) for paper, path in OCR_CACHE_PATHS.items()}

    for context, payload in (
        ("legacy audit", legacy_audit),
        ("content ledger", ledger),
        ("original provenance", provenance),
        ("locator OCR", locator_ocr),
        ("2015 OCR", ocr_2015),
    ):
        _validate_embedded(payload, context=context)

    review_rows, base_review_identity = _validated_base_snapshot(base)
    keys = [_key(row) for row in review_rows]
    if len(set(keys)) != len(keys):
        raise ClassificationReviewError("Base review identities are not unique")
    if set(keys) != set(DECISIONS):
        missing = sorted(set(keys) - set(DECISIONS))
        extra = sorted(set(DECISIONS) - set(keys))
        raise ClassificationReviewError(f"Decision coverage mismatch; missing={missing}; extra={extra}")

    canonical_keys = {
        (row["source_paper_id"], int(row["ordinal"]), row["item_label"])
        for row in canonical.get("questions") or []
    }
    inventory = _canonical_inventory(inventory_raw)
    review_evidence = {str(row["key"]): row for row in review_evidence_raw}
    provenance_papers = {str(row["paper_id"]): row for row in provenance.get("papers") or []}
    locator_papers, locator_pages = _locator_ocr_maps(locator_ocr)

    decisions: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    evidence_counts: Counter[str] = Counter()
    for row in review_rows:
        key = _key(row)
        decision, course, topic, reason_code, reason = DECISIONS[key]
        if row.get("parent_item_label") is not None:
            raise ClassificationReviewError(
                f"{key}: unexpected expanded child in this parent-only 82-row pass"
            )
        canonical_parent_ordinal = _canonical_parent_ordinal(row)
        canonical_key = (
            row["source_paper_id"],
            canonical_parent_ordinal,
            row["item_label"],
        )
        if canonical_key not in canonical_keys:
            raise ClassificationReviewError(f"{key}: canonical parent identity missing")
        if decision == "map":
            if course not in inventory or topic not in inventory[course]:
                raise ClassificationReviewError(f"{key}: non-canonical map {course}/{topic}")
        elif course is not None or topic is not None:
            raise ClassificationReviewError(f"{key}: non-map decision must not carry course/topic")

        evidence_row = review_evidence.get(key) or {}
        evidence = _exact_original_evidence(row=row, evidence_row=evidence_row)
        if evidence is None:
            evidence = _ocr_evidence(
                row=row,
                provenance_papers=provenance_papers,
                locator_papers=locator_papers,
                locator_pages=locator_pages,
                ocr_2015=ocr_2015,
                cache_payloads=cache_payloads,
            )
        if decision != "review" and evidence["question_boundary_status"] == "page_level_locator_conflict":
            raise ClassificationReviewError(f"{key}: unresolved page evidence cannot map/OOS")

        prior = {
            "final_release_ordinal": int(row["ordinal"]),
            "classification_status": row.get("classification_status"),
            "syllabus_status": row.get("syllabus_status"),
            "course": row.get("subject_code"),
            "topic": row.get("topic_slug"),
            "review_flags": list(row.get("review_flags") or []),
        }
        record = {
            "source_paper_id": row["source_paper_id"],
            "canonical_parent_ordinal": canonical_parent_ordinal,
            "item_label": row["item_label"],
            "parent_item_label": row.get("parent_item_label"),
            "child_item_label": None,
            "decision": decision,
            "course": course,
            "topic": topic,
            "reason_code": reason_code,
            "reason": reason,
            "evidence": evidence,
            "prior_classification": prior,
        }
        record["decision_evidence_sha256"] = _canonical_sha256(
            {
                "identity": {
                    "source_paper_id": record["source_paper_id"],
                    "canonical_parent_ordinal": record["canonical_parent_ordinal"],
                    "item_label": record["item_label"],
                    "child_item_label": record["child_item_label"],
                },
                "decision": decision,
                "course": course,
                "topic": topic,
                "reason_code": reason_code,
                "reason": reason,
                "evidence_sha256": evidence["excerpt_sha256"],
            }
        )
        decisions.append(record)
        counts[decision] += 1
        evidence_counts[evidence["kind"]] += 1

    paths = {
        "classification_review_base": base_path,
        "canonical_archive": canonical_path,
        "legacy_subpart_audit": legacy_audit_path,
        "legacy_child_policy": legacy_child_policy_path,
        "base_parent_policy": parent_policy_path,
        "topic_inventory": topic_inventory_path,
        "content_verification_ledger": content_ledger_path,
        "original_pdf_provenance": provenance_path,
        "classification_review_evidence": review_evidence_path,
        "original_locator_ocr": locator_ocr_path,
        "classification_review_2015_ocr": ocr_2015_path,
        **{f"ocr_cache_{paper}": path for paper, path in OCR_CACHE_PATHS.items()},
    }
    embedded_names = {
        "classification_review_base",
        "legacy_subpart_audit",
        "content_verification_ledger",
        "original_pdf_provenance",
        "original_locator_ocr",
        "classification_review_2015_ocr",
    }
    bindings = {
        name: _binding(path, validate_embedded=name in embedded_names)
        for name, path in sorted(paths.items())
    }

    core = {
        "schema_version": SCHEMA_VERSION,
        "source_role": "staging_only_authoritative_classification_review_evidence",
        "database_writes_performed": False,
        "production_import_authorized": False,
        "automatic_promotion_allowed": False,
        "practice_eligible_count": 0,
        "base_review_identity": {
            **base_review_identity,
        },
        "input_bindings": bindings,
        "policy": {
            "allowed_decisions": ["map", "out_of_syllabus", "review"],
            "map_requires_single_inventory_course_topic": True,
            "out_of_syllabus_requires_original_evidence": True,
            "compound_or_insufficient_evidence_remains_review": True,
            "third_party_content_is_not_evidence": True,
            "base_policy_is_comparison_only": True,
            "expanded_children_require_explicit_child_identity": True,
        },
        "counts": {
            "total": len(decisions),
            "by_decision": dict(sorted(counts.items())),
            "by_evidence_kind": dict(sorted(evidence_counts.items())),
        },
        "decisions": decisions,
    }
    return {**core, "artifact_sha256": _canonical_sha256(core)}


def validate_artifact(artifact: Mapping[str, Any]) -> None:
    _validate_embedded(artifact, context="classification review overrides")
    if artifact.get("schema_version") != SCHEMA_VERSION:
        raise ClassificationReviewError("Unexpected classification override schema")
    for field in (
        "database_writes_performed",
        "production_import_authorized",
        "automatic_promotion_allowed",
    ):
        if artifact.get(field) is not False:
            raise ClassificationReviewError(f"Unsafe guard: {field}")
    if artifact.get("practice_eligible_count") != 0:
        raise ClassificationReviewError("Classification override artifact cannot enable practice")
    rows = artifact.get("decisions") or []
    if len(rows) != EXPECTED_REVIEW_COUNT:
        raise ClassificationReviewError("Override artifact does not cover 82 decisions")
    identities = {
        (
            row["source_paper_id"],
            row["canonical_parent_ordinal"],
            row["item_label"],
            row.get("child_item_label"),
        )
        for row in rows
    }
    if len(identities) != EXPECTED_REVIEW_COUNT:
        raise ClassificationReviewError("Override identities are not unique")
    for row in rows:
        evidence = row.get("evidence") or {}
        excerpt = evidence.get("excerpt")
        if not isinstance(excerpt, str) or not excerpt:
            raise ClassificationReviewError("Every decision requires a non-empty evidence excerpt")
        if evidence.get("excerpt_sha256") != _sha256_text(excerpt):
            raise ClassificationReviewError("Evidence excerpt hash mismatch")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true", help="Fail if output differs")
    args = parser.parse_args()
    artifact = build_overrides()
    validate_artifact(artifact)
    rendered = json.dumps(artifact, indent=2, ensure_ascii=False) + "\n"
    if args.check:
        if not args.output.exists() or args.output.read_text(encoding="utf-8") != rendered:
            raise ClassificationReviewError(f"Stale classification override artifact: {args.output}")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(json.dumps({"output": str(args.output), "counts": artifact["counts"], "artifact_sha256": artifact["artifact_sha256"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
