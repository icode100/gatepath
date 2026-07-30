"""Extract, key, classify, and consolidate supplied GATE CS PYQs.

This script is intentionally conservative.  It imports a question only when:

* the question boundary is found in order,
* an official key row is resolved,
* all required options are recoverable for MCQ/MSQ,
* no unsupported alternative answer is present, and
* the syllabus course/topic classifier has positive evidence.

Anything else is listed in ``backend/data/pyq_extraction_manifest.json`` rather
than silently guessed.  Text extraction uses pypdf first.  If a rendered page
exists in ``tmp/pyq/ocr-<year-or-label>/``, RapidOCR is used as a fallback for
image-only pages and its mean confidence is recorded.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pypdf import PdfReader


REPO_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_DIR / "backend" / "data"
TMP_DIR = REPO_DIR / "tmp" / "pyq"
OUTPUT_PATH = DATA_DIR / "pyq_consolidated.json"
MANIFEST_PATH = DATA_DIR / "pyq_extraction_manifest.json"
OCR_CACHE_DIR = TMP_DIR / "ocr-text"
GENERATED_AT = "2026-07-30T00:00:00Z"


@dataclass(frozen=True)
class PaperSpec:
    label: str
    year: int
    paper_path: str
    key_path: str
    numbering: str
    session: int | None
    ga_pages: int
    source_url: str
    answer_key_url: str
    expected_questions: int = 65
    ocr_dir: str | None = None
    source_note: str | None = None


ARCHIVE_URL = "https://gate2027.iitm.ac.in/download"
IITK_2017_URL = "https://gate.iitk.ac.in/GATE2023/doc/papers/2017/cs_2017.pdf"
PAPERS: tuple[PaperSpec, ...] = (
    PaperSpec(
        "CS1-2017",
        2017,
        "replacement-CS1-2017.pdf",
        "replacement-CS1-2017.pdf",
        "cs_then_ga_global",
        None,
        0,
        IITK_2017_URL,
        IITK_2017_URL,
        ocr_dir="ocr-CS1-2017",
        source_note="Mirror replacement of the corrupt supplied CS1 entry; official IIT Kanpur index URL retained.",
    ),
    PaperSpec(
        "CS2-2017",
        2017,
        "replacement-CS2-2017.pdf",
        "source/CS/CS2-2017.pdf",
        "cs_then_ga_global",
        None,
        0,
        IITK_2017_URL,
        IITK_2017_URL,
        ocr_dir="ocr-CS2-2017",
        source_note="Mirror replacement used for paper text; official key is embedded in the supplied CS2 file.",
    ),
    PaperSpec(
        "CS-2018",
        2018,
        "source/CS/CS2018.pdf",
        "source/CS/CS2018.pdf",
        "local_ga_cs",
        None,
        3,
        "https://gate.iitk.ac.in/GATE2023/doc/papers/2018/cs_2018.pdf",
        "https://gate.iitk.ac.in/GATE2023/doc/papers/2018/cs_2018.pdf",
    ),
    PaperSpec(
        "CS-2019",
        2019,
        "official-CS-2019.pdf",
        "source/CS/CS2019.pdf",
        "local_ga_cs",
        None,
        3,
        "https://gate.iitk.ac.in/GATE2023/doc/papers/2019/cs_2019.pdf",
        "https://gate.iitk.ac.in/GATE2023/doc/papers/2019/cs_2019.pdf",
        ocr_dir="ocr-2019",
    ),
    PaperSpec(
        "CS-2020",
        2020,
        "official-CS-2020.pdf",
        "source/CS/CS2020.pdf",
        "local_ga_cs",
        6,
        3,
        "https://gate.iitk.ac.in/GATE2023/doc/papers/2020/cs_2020.pdf",
        "https://gate.iitk.ac.in/GATE2023/doc/papers/2020/cs_2020.pdf",
        ocr_dir="ocr-2020",
    ),
    PaperSpec(
        "CS1-2021",
        2021,
        "official-CS1-2021.pdf",
        "official-CS1-2021-key.pdf",
        "local_ga_cs",
        5,
        10,
        "https://gate.iitb.ac.in/G21/2021_papers/CS1.pdf",
        "https://gate2027.iitm.ac.in/static/doc/download/Answer_keys2021/cs_merged_2021.pdf",
        ocr_dir="ocr-CS1-2021",
    ),
    PaperSpec(
        "CS2-2021",
        2021,
        "official-CS2-2021.pdf",
        "official-CS2-2021-key.pdf",
        "local_ga_cs",
        6,
        10,
        "https://gate.iitb.ac.in/G21/2021_papers/CS2.pdf",
        "https://gate2027.iitm.ac.in/static/doc/download/Answer_keys2021/cs_merged_2021.pdf",
        ocr_dir="ocr-CS2-2021",
    ),
    PaperSpec(
        "CS-2022",
        2022,
        "source/CS/CS2022.pdf",
        "official-keys/CS-2022-key.pdf",
        "ga_then_cs_global",
        1,
        10,
        "https://gate.iitk.ac.in/GATE2023/doc/papers/2022/cs_2022.pdf",
        "https://gate2027.iitm.ac.in/static/doc/download/Answer_keys2022/cs_2022.pdf",
    ),
    PaperSpec(
        "CS-2023",
        2023,
        "source/CS/CS2023.pdf",
        "official-keys/CS-2023-key.pdf",
        "ga_then_cs_global",
        1,
        0,
        "https://gate.iitk.ac.in/GATE2023/doc/papers/2023/cs_2023.pdf",
        "https://gate2027.iitm.ac.in/static/doc/download/Answer_keys2023/CS_ANS_GATE2023.pdf",
    ),
    PaperSpec(
        "CS1-2024",
        2024,
        "source/CS/CS12024.pdf",
        "official-keys/CS1-2024-key.pdf",
        "ga_then_cs_global",
        5,
        0,
        "https://gate2027.iitm.ac.in/static/doc/download/2024/CS124S5.pdf",
        "https://gate2027.iitm.ac.in/static/doc/download/2024/CS1FinalAnswerKey.pdf",
    ),
    PaperSpec(
        "CS2-2024",
        2024,
        "source/CS/CS22024.pdf",
        "official-keys/CS2-2024-key.pdf",
        "ga_then_cs_global",
        6,
        0,
        "https://gate2027.iitm.ac.in/static/doc/download/2024/CS224S6.pdf",
        "https://gate2027.iitm.ac.in/static/doc/download/2024/CS2FinalAnswerKey.pdf",
    ),
    PaperSpec(
        "CS1-2025",
        2025,
        "source/CS/CS12025.pdf",
        "official-keys/CS1-2025-key.pdf",
        "ga_then_cs_global",
        1,
        0,
        ARCHIVE_URL,
        "https://gate2027.iitm.ac.in/static/doc/download/2025_Key/CS1_Keys.pdf",
    ),
    PaperSpec(
        "CS2-2025",
        2025,
        "source/CS/CS22025.pdf",
        "official-keys/CS2-2025-key.pdf",
        "ga_then_cs_global",
        2,
        0,
        ARCHIVE_URL,
        "https://gate2027.iitm.ac.in/static/doc/download/2025_Key/CS2_Keys.pdf",
    ),
)


# Stable backend slugs.  Weighted phrases are ordered from specific to broad.
CLASSIFIER: dict[tuple[str, str, str], tuple[str, ...]] = {
    ("EM", "Discrete Mathematics", "discrete-mathematics"): (
        "propositional", "partial order", "lattice", "group", "monoid", "combinator",
        "recurrence", "generating function", "graph", "edge", "vertex", "relation",
    ),
    ("EM", "Linear Algebra", "linear-algebra"): (
        "eigenvalue", "eigenvector", "matrix", "matrices", "determinant", "linear equations", "lu decomposition",
    ),
    ("EM", "Calculus", "calculus"): (
        "derivative", "differentiab", "continuity", "continuous", "integral", "maximum", "minimum", "limit",
    ),
    ("EM", "Probability and Statistics", "probability-and-statistics"): (
        "probability", "random variable", "distribution", "poisson", "binomial", "bayes", "variance", "mean",
    ),
    ("DL", "Boolean Algebra", "boolean-algebra"): (
        "boolean", "minterm", "maxterm", "karnaugh", "logic function", "truth table",
    ),
    ("DL", "Combinational Circuits", "combinational-circuits"): (
        "multiplexer", "decoder", "encoder", "full adder", "half adder", "combinational",
    ),
    ("DL", "Sequential Circuits", "sequential-circuits"): (
        "flip-flop", "flip flop", "counter", "latch", "state table", "sequential circuit", "register",
    ),
    ("DL", "Number Representation and Arithmetic", "number-representation-and-arithmetic"): (
        "two's complement", "2's complement", "floating point", "signed integer", "binary number", "overflow",
    ),
    ("COA", "Machine Instructions and Addressing Modes", "machine-instructions-and-addressing-modes"): (
        "addressing mode", "instruction format", "machine instruction", "operand", "effective address",
    ),
    ("COA", "ALU, Datapath and Control", "alu-datapath-and-control"): (
        "datapath", "control unit", "microprogram", "alu", "register transfer",
    ),
    ("COA", "Instruction Pipelining", "instruction-pipelining"): (
        "pipeline", "forwarding", "hazard", "stall", "speedup",
    ),
    ("COA", "Memory Hierarchy", "memory-hierarchy"): (
        "cache", "memory hierarchy", "miss rate", "hit rate", "page table", "tlb", "locality",
    ),
    ("COA", "I/O Interface", "i-o-interface"): (
        "programmed i/o", "i/o interface", "input output", "peripheral",
    ),
    ("COA", "Interrupts and DMA", "interrupts-and-dma"): (
        "interrupt", "dma", "cycle stealing", "direct memory access",
    ),
    ("PDS", "Programming in C", "programming-in-c"): (
        "c program", "#include", "printf", "scanf", "pointer", "struct ", "sizeof", "char *", "int ",
    ),
    ("PDS", "Recursion", "recursion"): ("recursive", "recursion", "function calls itself"),
    ("PDS", "Arrays", "arrays"): ("array", "row-major", "row major", "a[", "matrix storage"),
    ("PDS", "Stacks and Queues", "stacks-and-queues"): (
        "stack", "queue", "push", "pop", "enqueue", "dequeue", "postfix",
    ),
    ("PDS", "Linked Lists", "linked-lists"): ("linked list", "next pointer", "doubly linked"),
    ("PDS", "Trees and Binary Search Trees", "trees-and-binary-search-trees"): (
        "binary search tree", "binary tree", "inorder", "preorder", "postorder", "tree traversal",
    ),
    ("PDS", "Heaps", "heaps"): ("heap", "heapify", "priority queue"),
    ("PDS", "Graphs", "graphs"): ("adjacency list", "adjacency matrix", "graph representation"),
    ("ALG", "Searching, Sorting and Hashing", "searching-sorting-and-hashing"): (
        "binary search", "sorting", "sort ", "hash", "collision", "searching",
    ),
    ("ALG", "Complexity Analysis", "complexity-analysis"): (
        "time complexity", "space complexity", "asymptotic", "big-o", "theta", "omega", "running time",
    ),
    ("ALG", "Divide and Conquer", "divide-and-conquer"): (
        "divide and conquer", "merge sort", "recurrence t(", "master theorem",
    ),
    ("ALG", "Greedy Algorithms", "greedy-algorithms"): (
        "greedy", "kruskal", "prim", "minimum spanning tree", "huffman",
    ),
    ("ALG", "Dynamic Programming", "dynamic-programming"): (
        "dynamic programming", "memoization", "longest common subsequence", "optimal substructure",
    ),
    ("ALG", "Graph Algorithms", "graph-algorithms"): (
        "breadth first", "depth first", "bfs", "dfs", "shortest path", "dijkstra", "connected component",
    ),
    ("TOC", "Regular Expressions and Finite Automata", "regular-expressions-and-finite-automata"): (
        "finite autom", "regular expression", "regular language", "dfa", "nfa",
    ),
    ("TOC", "Context-Free Grammars", "context-free-grammars"): (
        "context-free grammar", "context free grammar", "parse tree", "ambiguous grammar", "derivation",
    ),
    ("TOC", "Pushdown Automata", "pushdown-automata"): ("pushdown", "pda", "stack autom"),
    ("TOC", "Pumping Lemmas and Language Properties", "pumping-lemmas-and-language-properties"): (
        "pumping lemma", "closure property", "closed under", "non-regular", "non regular",
    ),
    ("TOC", "Turing Machines and Undecidability", "turing-machines-and-undecidability"): (
        "turing machine", "undecidable", "decidable", "halting problem", "recursive language", "recognizable",
    ),
    ("CD", "Lexical Analysis", "lexical-analysis"): ("lexical", "lexer", "token", "lexeme"),
    ("CD", "Parsing", "parsing"): (
        "parser", "parsing", "ll(1)", "lr(1)", "lalr", "shift-reduce", "first set", "follow set",
    ),
    ("CD", "Syntax-Directed Translation", "syntax-directed-translation"): (
        "syntax-directed", "syntax directed", "synthesized attribute", "inherited attribute",
    ),
    ("CD", "Runtime Environments", "runtime-environments"): (
        "activation record", "runtime environment", "parameter passing", "static link", "control link",
    ),
    ("CD", "Intermediate Code Generation", "intermediate-code-generation"): (
        "three-address", "three address", "intermediate code", "quadruple", "syntax tree",
    ),
    ("CD", "Code Optimization and Data-Flow Analysis", "code-optimization-and-data-flow-analysis"): (
        "data-flow", "data flow", "live variable", "reaching definition", "available expression", "code optimization",
    ),
    ("OS", "System Calls", "system-calls"): ("system call", "kernel mode", "user mode", "fork()", "exec()"),
    ("OS", "Processes and Threads", "processes-and-threads"): (
        "process", "thread", "context switch", "ipc", "inter-process",
    ),
    ("OS", "Concurrency and Synchronization", "concurrency-and-synchronization"): (
        "semaphore", "mutex", "critical section", "race condition", "monitor", "synchronization",
    ),
    ("OS", "Deadlocks", "deadlocks"): ("deadlock", "banker's", "resource allocation graph", "safe state"),
    ("OS", "CPU and I/O Scheduling", "cpu-and-i-o-scheduling"): (
        "scheduling", "round robin", "fcfs", "shortest job", "disk scheduling", "time quantum",
    ),
    ("OS", "Memory and Virtual Memory", "memory-and-virtual-memory"): (
        "virtual memory", "page replacement", "page fault", "paging", "segmentation", "physical memory",
    ),
    ("OS", "File Systems", "file-systems"): (
        "file system", "file allocation", "inode", "directory", "disk block", "free-space",
    ),
    ("DBMS", "ER Model", "er-model"): (
        "entity relationship", "er diagram", "entity set", "weak entity", "cardinality constraint",
    ),
    ("DBMS", "Relational Model", "relational-model"): (
        "relational algebra", "tuple relational", "relation r", "cartesian product", "projection", "selection",
    ),
    ("DBMS", "SQL", "sql"): (" sql ", "select ", "group by", "having ", "subquery", "create table"),
    ("DBMS", "Integrity Constraints", "integrity-constraints"): (
        "foreign key", "primary key", "referential integrity", "integrity constraint", "domain constraint",
    ),
    ("DBMS", "Normal Forms", "normal-forms"): (
        "normal form", "bcnf", "functional dependency", "candidate key", "dependency preservation",
    ),
    ("DBMS", "File Organization and Indexing", "file-organization-and-indexing"): (
        "b+ tree", "b-tree", "index", "file organization", "hash index",
    ),
    ("DBMS", "Transactions and Concurrency Control", "transactions-and-concurrency-control"): (
        "transaction", "serializ", "two-phase locking", "schedule", "recoverab", "conflict",
    ),
    ("CN", "Layering and Switching", "layering-and-switching"): (
        "osi", "tcp/ip", "layer", "packet switching", "circuit switching", "virtual circuit",
    ),
    ("CN", "Data Link Layer", "data-link-layer"): (
        "ethernet", "mac address", "data link", "crc", "csma", "bridge", "framing",
    ),
    ("CN", "Routing Algorithms", "routing-algorithms"): (
        "routing", "distance vector", "link state", "flooding", "route cost",
    ),
    ("CN", "IPv4 Addressing and Forwarding", "ipv4-addressing-and-forwarding"): (
        "ipv4", "ip address", "subnet", "cidr", "arp", "dhcp", "icmp", "nat", "fragment",
    ),
    ("CN", "Transport Layer", "transport-layer"): (
        "tcp", "udp", "transport layer", "congestion", "flow control", "socket", "sequence number",
    ),
    ("CN", "Application Layer", "application-layer"): ("dns", "http", "smtp", "ftp", "email"),
    ("CN", "Network Performance", "network-performance"): (
        "transmission delay", "propagation delay", "bandwidth", "throughput", "utilization", "link rate",
    ),
}


GA_TOPICS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "verbal": (
        "Verbal Aptitude",
        "verbal-aptitude",
        ("word", "sentence", "grammar", "passage", "meaning", "blank", "article", "vocabulary"),
    ),
    "quantitative": (
        "Quantitative Aptitude",
        "quantitative-aptitude",
        ("percent", "ratio", "probability", "average", "number", "area", "volume", "equation", "series"),
    ),
    "analytical": (
        "Analytical Aptitude",
        "analytical-aptitude",
        ("statement", "conclusion", "logical", "arrangement", "inference", "analogy"),
    ),
    "spatial": (
        "Spatial Aptitude",
        "spatial-aptitude",
        ("fold", "cube", "shape", "rotation", "mirror", "figure", "paper", "spatial"),
    ),
}


def _clean(value: str) -> str:
    value = value.replace("\u00a0", " ").replace("\u2013", "-").replace("\u2014", "-")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _ocr_engine() -> Any | None:
    package_dir = REPO_DIR / "tmp" / "ocr-packages"
    if not package_dir.exists():
        return None
    sys.path.insert(0, str(package_dir))
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        return None
    return RapidOCR()


def _ocr_image_for_page(directory: Path, page_number: int) -> Path | None:
    candidates = (
        directory / f"page-{page_number:02d}.png",
        directory / f"page-{page_number:03d}.png",
        directory / f"page-{page_number}.png",
    )
    return next((path for path in candidates if path.exists()), None)


def extract_pages(
    spec: PaperSpec, *, enable_ocr: bool
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    path = TMP_DIR / spec.paper_path
    reader = PdfReader(path)
    ocr_directory = TMP_DIR / spec.ocr_dir if spec.ocr_dir else None
    OCR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = OCR_CACHE_DIR / f"{spec.label}.json"
    cached: dict[str, Any] = {}
    if cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
    engine: Any | None = None
    pages: list[dict[str, Any]] = []
    method_counts: dict[str, int] = {"pypdf": 0, "ocr": 0, "low_text": 0}

    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        method = "pypdf"
        confidence = 0.98
        image = (
            _ocr_image_for_page(ocr_directory, page_number)
            if ocr_directory is not None
            else None
        )
        needs_ocr = len(_clean(text)) < 250 and image is not None and enable_ocr
        cache_key = str(page_number)
        if needs_ocr and cache_key in cached:
            cached_page = cached[cache_key]
            text = cached_page["text"]
            confidence = float(cached_page["confidence"])
            method = "ocr"
        elif needs_ocr:
            if engine is None:
                engine = _ocr_engine()
            if engine is not None:
                result, _ = engine(str(image))
                result = result or []
                text = "\n".join(str(item[1]) for item in result)
                scores = [float(item[2]) for item in result]
                confidence = sum(scores) / len(scores) if scores else 0.0
                method = "ocr"
                cached[cache_key] = {"text": text, "confidence": round(confidence, 4)}
        if len(_clean(text)) < 250 and method == "pypdf":
            method = "low_text"
            confidence = 0.35
        method_counts[method] += 1
        pages.append(
            {
                "page": page_number,
                "text": text,
                "method": method,
                "confidence": round(confidence, 4),
            }
        )

    if cached:
        cache_path.write_text(
            json.dumps(cached, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return pages, {
        "path": str(path.relative_to(REPO_DIR)).replace("\\", "/"),
        "pages": len(reader.pages),
        "characters": sum(len(page["text"]) for page in pages),
        "extraction_methods": method_counts,
    }


def _question_number(global_number: int, numbering: str) -> tuple[str, int]:
    if numbering == "ga_then_cs_global":
        return ("GA", global_number) if global_number <= 10 else ("CS", global_number)
    if numbering == "cs_then_ga_global":
        return ("CS", global_number) if global_number <= 55 else ("GA", global_number)
    raise ValueError(numbering)


QUESTION_RE = re.compile(
    r"(?mi)^\s*(?:Q\.?\s*(?:No\.?\s*)?|Question\s+Number\s*:\s*)(\d{1,2})"
    r"(?!\s*[\u2013\u2014-]\s*Q)(?:\s+|$)"
)


def _strip_page_noise(value: str) -> str:
    lines: list[str] = []
    for line in value.splitlines():
        compact = _clean(line)
        lower = compact.lower()
        if not compact:
            continue
        if re.fullmatch(r"page \d+ of \d+", lower):
            continue
        if re.fullmatch(r"(?:cs|ga)\s+page\s+\d+\s+of\s+\d+", lower):
            continue
        if "organizing institute:" in lower or "organising institute:" in lower:
            continue
        if lower.startswith("gate 20") and "computer science and information technology" in lower:
            continue
        if "copyright" in lower and "gate" in lower:
            continue
        if lower.startswith("computer science and information technology") and len(compact) < 100:
            continue
        if re.match(r"^q\.\s*\d+\s*-\s*q\.", lower):
            continue
        if lower.startswith("end of the question paper"):
            continue
        lines.append(compact)
    return _clean(" ".join(lines))


def extract_question_blocks(
    spec: PaperSpec, pages: list[dict[str, Any]]
) -> tuple[dict[int, dict[str, Any]], list[dict[str, Any]]]:
    candidates: list[dict[str, Any]] = []
    for page in pages:
        for match in QUESTION_RE.finditer(page["text"]):
            local_number = int(match.group(1))
            if not 1 <= local_number <= 65:
                continue
            candidates.append(
                {
                    "local_number": local_number,
                    "page": page["page"],
                    "start": match.start(),
                    "after": match.end(),
                    "method": page["method"],
                    "confidence": page["confidence"],
                }
            )

    # Select only the expected monotonically increasing sequence.  This drops
    # repeated footer/header artifacts such as a lone "Q.1" on later pages.
    accepted: list[dict[str, Any]] = []
    expected_global = 1
    expected_local = {"GA": 1, "CS": 1}
    for candidate in candidates:
        local = candidate["local_number"]
        if spec.numbering == "local_ga_cs":
            section = "GA" if candidate["page"] <= spec.ga_pages else "CS"
            if local != expected_local[section]:
                continue
            expected_local[section] += 1
            global_number = local if section == "GA" else local + 10
        else:
            if local != expected_global:
                continue
            section, global_number = _question_number(local, spec.numbering)
            expected_global += 1
        accepted.append({**candidate, "section": section, "global_number": global_number})

    page_by_number = {page["page"]: page for page in pages}
    blocks: dict[int, dict[str, Any]] = {}
    unresolved: list[dict[str, Any]] = []
    for index, current in enumerate(accepted):
        pieces: list[str] = []
        page_number = current["page"]
        end_page = (
            accepted[index + 1]["page"]
            if index + 1 < len(accepted)
            else page_number
        )
        for number in range(page_number, end_page + 1):
            page_text = page_by_number[number]["text"]
            start = current["after"] if number == page_number else 0
            if index + 1 < len(accepted) and number == end_page:
                end = accepted[index + 1]["start"]
            else:
                end = len(page_text)
            pieces.append(page_text[start:end])
        raw = _strip_page_noise("\n".join(pieces))
        if len(raw) < 12:
            unresolved.append(
                {
                    "question_number": current["global_number"],
                    "reason": "question_text_missing_or_image_only",
                    "source_page": page_number,
                }
            )
            continue
        blocks[current["global_number"]] = {
            "raw": raw,
            "section": current["section"],
            "source_page": page_number,
            "extraction_method": current["method"],
            "extraction_confidence": current["confidence"],
        }
    if spec.label == "CS-2023":
        # The 2023 technical PDF stores each Q-number at the page footer after
        # the question content.  Rebuild Q11-Q65 from the content preceding
        # that footer rather than treating the footer as the next block start.
        pending: list[str] = []
        pending_start: int | None = None
        for page in pages[7:]:
            if pending_start is None:
                pending_start = page["page"]
            matches = [
                match
                for match in QUESTION_RE.finditer(page["text"])
                if int(match.group(1)) >= 11
            ]
            if not matches:
                pending.append(page["text"])
                continue
            footer = matches[-1]
            number = int(footer.group(1))
            pending.append(page["text"][: footer.start()])
            raw = _strip_page_noise("\n".join(pending))
            if raw:
                blocks[number] = {
                    "raw": raw,
                    "section": "CS",
                    "source_page": pending_start,
                    "extraction_method": page["method"],
                    "extraction_confidence": page["confidence"],
                    "boundary_method": "question_number_after_content",
                }
            remainder = page["text"][footer.end() :]
            pending = [remainder] if _clean(remainder) else []
            pending_start = page["page"] if pending else None
    return blocks, unresolved


START_WITH_SESSION = re.compile(
    r"(?<!\d)(\d{1,2})\s*{session}\s+(MCQ|MSQ|NAT)\s+(GA|CS(?:-\d)?)\s+",
    re.IGNORECASE,
)
START_NO_SESSION = re.compile(
    r"(?<!\d)(\d{1,2})\s+(MCQ|MSQ|NAT)\s+(GA|CS(?:-\d)?)\s+",
    re.IGNORECASE,
)


def _parse_answer_tail(qtype: str, tail: str) -> tuple[Any, int] | None:
    tail = _clean(tail)
    if qtype in {"MCQ", "MSQ"}:
        match = re.match(
            r"(MTA|[A-D](?:\s*(?:[,;]|OR)\s*[A-D])*)\s+([12])(?=0(?:\s|$)|\s|$)",
            tail,
            re.IGNORECASE,
        )
        if not match:
            return None
        answer_text, marks_text = match.groups()
        if answer_text.upper() == "MTA":
            return {"marks_to_all": True}, int(marks_text)
        answer_groups = re.split(r"\s*OR\s*", answer_text.upper())
        if len(answer_groups) > 1:
            alternatives = [re.findall(r"[A-D]", group) for group in answer_groups]
            if qtype == "MCQ":
                return {"any_of": [group[0] for group in alternatives]}, int(marks_text)
            return {"any_of": alternatives}, int(marks_text)
        choices = re.findall(r"[A-D]", answer_text.upper())
        if qtype == "MCQ":
            if len(choices) != 1:
                return {"any_of": choices}, int(marks_text)
            return choices[0], int(marks_text)
        return choices, int(marks_text)

    number = r"-?\d+(?:\.\d+)?"
    match = re.match(
        rf"({number})\s+to\s+({number})"
        rf"((?:\s+OR\s+{number}\s+to\s+{number})*)\s+([12])(?=0(?:\s|$)|\s|$)",
        tail,
        re.IGNORECASE,
    )
    if not match:
        # Some legacy extracted key rows concatenate an integer range endpoint
        # and its mark, for example "3 to 31" means 3 to 3, one mark.
        legacy = re.match(
            rf"({number})\s+to\s+(-?\d+(?:\.\d+)?)([12])(?:\s|$)",
            tail,
            re.IGNORECASE,
        )
        if not legacy:
            return None
        minimum_text, maximum_text, marks_text = legacy.groups()
        alternatives = ""
    else:
        minimum_text, maximum_text, alternatives, marks_text = match.groups()
    def as_range(minimum_value: str, maximum_value: str) -> Any:
        minimum_number, maximum_number = float(minimum_value), float(maximum_value)
        minimum_normalized: int | float = (
            int(minimum_number) if minimum_number.is_integer() else minimum_number
        )
        maximum_normalized: int | float = (
            int(maximum_number) if maximum_number.is_integer() else maximum_number
        )
        return (
            minimum_normalized
            if minimum_normalized == maximum_normalized
            else {"min": minimum_normalized, "max": maximum_normalized}
        )

    answer: Any = as_range(minimum_text, maximum_text)
    if alternatives.strip():
        alternative_ranges = re.findall(
            rf"({number})\s+to\s+({number})", alternatives, re.IGNORECASE
        )
        answer = {
            "any_of": [answer]
            + [as_range(low, high) for low, high in alternative_ranges]
        }
    return answer, int(marks_text)


def _manual_2017_cs1_key() -> dict[int, dict[str, Any]]:
    letters_1_18 = "D B C B C B D B C B D B D D B A C D".split()
    nat_19_25: list[int | float] = [0, 18, 1, 4, 2.6, 3, 0.05]
    letters_26_36 = "A D C D A B C B D A C".split()
    letters_37_42 = "B A A B D A".split()
    nat_43_55: list[int | float | dict[str, float]] = [
        1024,
        11,
        {"min": 86.5, "max": 89.5},
        4,
        271,
        5,
        -16,
        {"min": 1.49, "max": 1.52},
        76,
        2,
        3,
        14,
        23,
    ]
    ga_56_65 = "C D C D C B A B D C".split()
    records: dict[int, dict[str, Any]] = {}
    for number, answer in enumerate(letters_1_18, start=1):
        records[number] = {"type": "mcq", "answer": answer, "marks": 1, "section": "CS"}
    for number, answer in enumerate(nat_19_25, start=19):
        records[number] = {"type": "nat", "answer": answer, "marks": 1, "section": "CS"}
    for number, answer in enumerate(letters_26_36, start=26):
        records[number] = {"type": "mcq", "answer": answer, "marks": 2, "section": "CS"}
    for number, answer in enumerate(letters_37_42, start=37):
        records[number] = {"type": "mcq", "answer": answer, "marks": 2, "section": "CS"}
    for number, answer in enumerate(nat_43_55, start=43):
        records[number] = {"type": "nat", "answer": answer, "marks": 2, "section": "CS"}
    for number, answer in enumerate(ga_56_65, start=56):
        records[number] = {
            "type": "mcq",
            "answer": answer,
            "marks": 1 if number <= 60 else 2,
            "section": "GA",
        }
    return records


def parse_key(spec: PaperSpec) -> tuple[dict[int, dict[str, Any]], list[dict[str, Any]]]:
    if spec.label == "CS1-2017":
        return _manual_2017_cs1_key(), []
    reader = PdfReader(TMP_DIR / spec.key_path)
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    text = text.replace("\u00a0", " ")
    if not _clean(text) and spec.ocr_dir:
        cache_path = OCR_CACHE_DIR / f"{spec.label}.json"
        if cache_path.exists():
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            text = "\n".join(
                cached[str(page)]["text"]
                for page in sorted(map(int, cached))
                if str(page) in cached
            )
    if spec.label == "CS-2019":
        text = _clean(text)
        corrections = {
            "8 MCQ GA B 2 6 MCQ GA C 2 10 MCQ": "8 MCQ GA B 2 9 MCQ GA C 2 10 MCQ",
            "5 MCQ CS C 1 9 MCQ CS B 1 7 MCQ": "5 MCQ CS C 1 6 MCQ CS B 1 7 MCQ",
            "7 MCQ CS B 1 ¥8 MCQ CS C 1": "7 MCQ CS B 1 8 MCQ CS C 1",
            "24 NAT CS 9049 1": "24 NAT CS 9049 to 9049 1",
            "55 NAT CS 1to 1 2": "55 NAT CS 1 to 1 2",
        }
        for before, after in corrections.items():
            text = text.replace(before, after)
    if spec.session is not None:
        pattern = re.compile(
            START_WITH_SESSION.pattern.replace("{session}", str(spec.session)),
            re.IGNORECASE,
        )
    else:
        pattern = START_NO_SESSION
    starts = list(pattern.finditer(text))
    records: dict[int, dict[str, Any]] = {}
    unresolved: list[dict[str, Any]] = []
    for index, match in enumerate(starts):
        local_number = int(match.group(1))
        qtype = match.group(2).upper()
        section = "GA" if match.group(3).upper() == "GA" else "CS"
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        parsed = _parse_answer_tail(qtype, text[match.end() : end])
        if spec.numbering == "local_ga_cs":
            global_number = local_number if section == "GA" else local_number + 10
        else:
            global_number = local_number
        if parsed is None:
            unresolved.append(
                {"question_number": global_number, "reason": "answer_key_row_unparsed"}
            )
            continue
        answer, marks = parsed
        records[global_number] = {
            "type": qtype.lower(),
            "answer": answer,
            "marks": marks,
            "section": section,
        }
        if isinstance(answer, dict) and (
            "any_of" in answer or "marks_to_all" in answer
        ):
            unresolved.append(
                {
                    "question_number": global_number,
                    "reason": "official_key_has_alternative_or_marks_to_all_answer",
                    "answer": answer,
                }
            )
    return records, unresolved


OPTION_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:\(\s*([A-D])\s*\)?\.?|([A-D])[\.\)])\s*",
    re.IGNORECASE,
)


def _option_id(match: re.Match[str]) -> str:
    return (match.group(1) or match.group(2)).upper()


BOILERPLATE_RE = re.compile(
    r"(?:q\.?\s*\d+\s*[-\u2013\u2014]\s*q\.?\s*\d+.*?carry\s+"
    r"(?:one|two)|answer\s+key|key\s*/\s*range|question\s+type|"
    r"page\s+\d+\s+of\s+\d+)",
    re.IGNORECASE,
)
COMPACT_MARKS_BOILERPLATE_RE = re.compile(
    r"q\.?\s*(?:\d+\s*[-\u2013\u2014]\s*q\.?\s*)?\d+\s*"
    r"carry\s*(?:one|two)\s*marks?\s*each",
    re.IGNORECASE,
)
HARD_DEBRIS_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("answer_metadata", re.compile(r"\b(?:Correct|Wrong)\s*:", re.IGNORECASE)),
    (
        "embedded_question_number",
        re.compile(r"\bQuestion\s+Number\s*:", re.IGNORECASE),
    ),
    ("watermark", re.compile(r"\bIQP\s*BANK\b|IQPBANK|www\.", re.IGNORECASE)),
    (
        "website_navigation",
        re.compile(
            r"HomeHome|Information\s*Brochure|Pre\s*Examination|"
            r"Important\s*Dates|FAQsFAQs|Contact\s*Us",
            re.IGNORECASE,
        ),
    ),
    (
        "paper_header",
        re.compile(
            r"\bGATE\s*20(?:17|18|19|20|21|22|23|24|25)\s*"
            r"(?:Computer\s*Sc|General\s+Aptitude|Graduate\s+Aptitude\s+Test)",
            re.IGNORECASE,
        ),
    ),
    (
        "section_page_footer",
        re.compile(
            r"\b(?:GA|CS(?:-\d+)?)\s+\d{1,2}\s*/\s*\d{1,2}\b",
            re.IGNORECASE,
        ),
    ),
    ("copyright_footer", re.compile(r"\bCopyright\s*:?\s*GATE\b", re.IGNORECASE)),
    (
        "embedded_q_label",
        re.compile(r"\bQ\.?\s*(?:No\.?\s*)?\d{1,2}\b", re.IGNORECASE),
    ),
    (
        "joined_word_ocr",
        re.compile(
            r"\b(?:Considerthe|Considera|Whichoneof|Whichof|Thetotal|Whena|"
            r"thefollowing|followingstatements?|assignpriorities|deviceraises|"
            r"avectored|toidentify|bethenumber|denotethe|maximumdegreeof|"
            r"setofall|isthestarting|arenon|semanticrules|operationExtract|"
            r"bargraph|namedStudent|grammarG|arenonterminals|lexicaltokens)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "joined_formula_ocr",
        re.compile(
            r"\b(?:If|then)[A-Z]\s*(?:=|[+\-*/])",
        ),
    ),
)
VISUAL_DEPENDENCY_RE = re.compile(
    r"\b(?:figure|diagram|(?:bar\s+|line\s+)?graph\s+(?:shown|given)|"
    r"shown\s+(?:above|below|in\s+the)|given\s+(?:above|below)\s+is|"
    r"following\s+(?:(?:two|three)\s+)?"
    r"(?:image|figure|diagram|circuit|graph|parse\s+tree|DFA|NFA|"
    r"state\s+diagram)|"
    r"(?:circuit|binary\s+tree|parse\s+tree|DFA|NFA|state\s+diagram)\s+"
    r"(?:given|shown|above|below))\b",
    re.IGNORECASE,
)
NESTED_OPTION_LABEL_RE = re.compile(r"\(\s*[A-D]\s*\)", re.IGNORECASE)
QUALITY_GATE_REGRESSION_CASES: tuple[
    tuple[str, str, set[str]], ...
] = (
    (
        "gate_2018_ga_footer",
        "0 GATE 2018 General Aptitude (GA) Set-3 GA 2/3",
        {"paper_header", "section_page_footer"},
    ),
    (
        "cs_page_counter",
        "Six green faces and one red face. CS 1/20",
        {"section_page_footer"},
    ),
    (
        "joined_formula",
        "IfP=2 and R=3, thenQ+S=7.",
        {"joined_formula_ocr"},
    ),
)


def transcription_quality_flags(value: str) -> list[str]:
    normalized = _clean(value)
    flags = [
        name for name, pattern in HARD_DEBRIS_PATTERNS if pattern.search(normalized)
    ]
    if BOILERPLATE_RE.search(normalized) or COMPACT_MARKS_BOILERPLATE_RE.search(
        normalized
    ):
        flags.append("marks_or_key_boilerplate")
    if VISUAL_DEPENDENCY_RE.search(normalized):
        flags.append("visual_dependency")
    if any(0xE000 <= ord(character) <= 0xF8FF for character in normalized):
        flags.append("private_use_math_glyph")
    if re.search(
        r"(?<![A-Za-z])(?:[a-z]\s+){3,}[a-z](?![A-Za-z])",
        normalized,
    ):
        flags.append("spaced_character_ocr")
    if len(normalized) >= 120:
        whitespace_ratio = sum(character.isspace() for character in normalized) / len(
            normalized
        )
        long_words = re.findall(r"[A-Za-z]{20,}", normalized)
        very_long_words = re.findall(r"[A-Za-z]{36,}", normalized)
        camel_joins = re.findall(r"[a-z]{2,}[A-Z][A-Za-z]{2,}", normalized)
        looks_like_code = any(
            marker in normalized
            for marker in ("#include", "printf(", "scanf(", "int main", "->")
        )
        if (
            (whitespace_ratio <= 0.12 and not looks_like_code)
            or bool(very_long_words)
            or (len(long_words) >= 3 and not looks_like_code)
            or (len(camel_joins) >= 4 and not looks_like_code)
        ):
            flags.append("dense_missing_space_ocr")
    return sorted(set(flags))


def quality_gate_regression_errors() -> list[str]:
    errors: list[str] = []
    for label, fixture, expected_flags in QUALITY_GATE_REGRESSION_CASES:
        observed = set(transcription_quality_flags(fixture))
        missing = expected_flags - observed
        if missing:
            errors.append(
                f"{label} did not detect expected flags {sorted(missing)}"
            )
    return errors


def prompt_quality_flags(value: str) -> list[str]:
    """Detect prompt-only damage that option text could otherwise conceal."""

    normalized = _clean(value)
    flags: list[str] = []
    if normalized.rstrip().endswith(("(", "[", "{")):
        flags.append("truncated_prompt")
    if re.search(r"(?:\breturn|\bif|[,={])\s*$", normalized, re.IGNORECASE):
        flags.append("suspicious_prompt_ending")
    return flags


def record_quality_flags(
    question: str,
    options: list[dict[str, str]],
    *,
    extraction_method: str | None = None,
) -> list[str]:
    """Apply the shared live-bank gate with a narrow manual-review exemption."""

    serialized = " ".join(
        [question] + [option.get("text", "") for option in options]
    )
    flags = sorted(
        set(
            transcription_quality_flags(serialized)
            + prompt_quality_flags(question)
        )
    )
    if any(
        NESTED_OPTION_LABEL_RE.search(option.get("text", ""))
        for option in options
    ):
        flags.append("nested_option_label")
    code_markers = (
        "#include",
        "printf(",
        "scanf(",
        "int main",
        "return ",
        "char *",
        "void ",
        "for (",
        "while (",
    )
    looks_like_code = any(marker in serialized for marker in code_markers)
    if looks_like_code and any(
        serialized.count(opening) != serialized.count(closing)
        for opening, closing in (("{", "}"), ("(", ")"), ("[", "]"))
    ):
        flags.append("unbalanced_code_delimiters")
    if extraction_method == "rapidocr_onnxruntime+visual_review":
        # The density heuristic is intentionally conservative for unreviewed
        # OCR, but it produces false positives on independently checked code,
        # bit strings, and compact formulae.  Hard debris, visual dependency,
        # private-use glyph, joined-word, and truncation checks still apply.
        flags = [flag for flag in flags if flag != "dense_missing_space_ocr"]
    return sorted(set(flags))


def record_quality_gate_regression_errors() -> list[str]:
    cases = (
        (
            "nested_option_label",
            "Choose the correct result.",
            [{"id": "A", "text": "Outer text (B) swallowed inner option"}],
            "nested_option_label",
        ),
        (
            "truncated_if",
            "Consider the following C fragment if",
            [],
            "suspicious_prompt_ending",
        ),
        (
            "unbalanced_code",
            "int main() { if (x > 0) return 1;",
            [],
            "unbalanced_code_delimiters",
        ),
        (
            "missing_parse_tree",
            "Consider the following parse tree for the expression.",
            [],
            "visual_dependency",
        ),
    )
    errors: list[str] = []
    for label, question, options, expected in cases:
        observed = record_quality_flags(question, options)
        if expected not in observed:
            errors.append(f"{label} did not detect expected flag {expected}")
    return errors


def _clean_question_text(value: str) -> str:
    value = _clean(value)
    value = re.sub(
        r"^Q\.?\s*(?:\d+\s*[-\u2013\u2014]\s*Q\.?\s*)?\d+\s*"
        r"carry\s*(?:one|two)\s*marks?\s*each\.?\s*",
        "",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"^(?:Q\.?\s*(?:No\.?\s*)?|Question\s+Number\s*:\s*)\d{1,2}\s*",
        "",
        value,
        flags=re.IGNORECASE,
    )
    return value.strip(" -")


def split_question(raw: str, qtype: str) -> tuple[str, list[dict[str, str]]] | None:
    matches = list(OPTION_RE.finditer(raw))
    selected: list[re.Match[str]] = []
    expected = ("A", "B", "C", "D")
    for match in matches:
        if len(selected) < 4 and _option_id(match) == expected[len(selected)]:
            selected.append(match)
    if qtype in {"mcq", "msq"}:
        if len(selected) != 4:
            return None
        question = _clean_question_text(raw[: selected[0].start()])
        options: list[dict[str, str]] = []
        for index, match in enumerate(selected):
            end = selected[index + 1].start() if index < 3 else len(raw)
            option_text = _clean(raw[match.end() : end])
            options.append({"id": _option_id(match), "text": option_text})
        if len(question) < 20 or any(len(option["text"]) < 1 for option in options):
            return None
        return question, options
    question = _clean_question_text(raw[: selected[0].start()] if selected else raw)
    if len(question) < 20:
        return None
    return question, []


def split_question_loose(
    raw: str, qtype: str | None
) -> tuple[str, list[dict[str, str]]]:
    """Keep exact recovered text/options even when a quiz-safe split is impossible."""

    strict = split_question(raw, qtype or "nat")
    if strict is not None:
        return strict
    matches = list(OPTION_RE.finditer(raw))
    selected: list[re.Match[str]] = []
    expected = ("A", "B", "C", "D")
    for match in matches:
        if len(selected) < 4 and _option_id(match) == expected[len(selected)]:
            selected.append(match)
    if not selected:
        return _clean_question_text(raw), []
    question = _clean_question_text(raw[: selected[0].start()])
    options: list[dict[str, str]] = []
    for index, match in enumerate(selected):
        end = selected[index + 1].start() if index + 1 < len(selected) else len(raw)
        options.append(
            {"id": _option_id(match), "text": _clean(raw[match.end() : end])}
        )
    return question, options


def recover_option_group_blocks(
    spec: PaperSpec,
    pages: list[dict[str, Any]],
    key: dict[int, dict[str, Any]],
    blocks: dict[int, dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    """Recover OCR MCQ/MSQ boundaries from complete A-B-C-D sequences.

    The official key provides the ordered list of option-based questions.
    Recognized question labels re-anchor that order; missing OCR labels are
    filled only between those anchors.  NAT questions are never inferred from
    option groups.
    """

    option_numbers = sorted(
        number
        for number, record in key.items()
        if record["type"] in {"mcq", "msq"}
    )
    option_position = 0
    recovered = dict(blocks)
    used: set[int] = set()
    for page in pages:
        if page["method"] != "ocr":
            continue
        text = page["text"]
        matches = list(OPTION_RE.finditer(text))
        groups: list[list[re.Match[str]]] = []
        current: list[re.Match[str]] = []
        for match in matches:
            identifier = _option_id(match)
            expected = ("A", "B", "C", "D")[len(current)] if len(current) < 4 else "A"
            if identifier == expected:
                current.append(match)
                if len(current) == 4:
                    groups.append(current)
                    current = []
            elif identifier == "A":
                current = [match]
            else:
                current = []

        cursor = 0
        for group in groups:
            line_end = text.find("\n", group[-1].end())
            if line_end < 0:
                line_end = len(text)
            block_start = cursor
            raw = _strip_page_noise(text[block_start:line_end])
            cursor = line_end
            prefix = text[block_start : group[0].start()]
            detected_matches = list(QUESTION_RE.finditer(prefix))
            detected_number: int | None = None
            if detected_matches:
                local = int(detected_matches[-1].group(1))
                if spec.numbering == "local_ga_cs":
                    section = "GA" if page["page"] <= spec.ga_pages else "CS"
                    detected_number = local if section == "GA" else local + 10
                else:
                    detected_number = local
            if (
                detected_number in option_numbers
                and detected_number not in used
                and option_numbers.index(detected_number) >= option_position
            ):
                number = detected_number
                option_position = option_numbers.index(number)
            else:
                while (
                    option_position < len(option_numbers)
                    and option_numbers[option_position] in used
                ):
                    option_position += 1
                if option_position >= len(option_numbers):
                    break
                number = option_numbers[option_position]
            option_position += 1
            used.add(number)
            strict = split_question(raw, key[number]["type"])
            if strict is None or transcription_quality_flags(
                " ".join([strict[0]] + [item["text"] for item in strict[1]])
            ):
                continue
            recovered[number] = {
                "raw": raw,
                "section": key[number]["section"],
                "source_page": page["page"],
                "extraction_method": "ocr_option_sequence",
                "extraction_confidence": page["confidence"],
                "boundary_method": "official_key_order_plus_abcd_sequence",
            }
    return recovered


def classify(section: str, question: str) -> tuple[str, str, str, float] | None:
    lower = f" {question.lower()} "
    if section == "GA":
        scored: list[tuple[int, str, str]] = []
        for _, (topic, slug, keywords) in GA_TOPICS.items():
            score = sum(2 if " " in term else 1 for term in keywords if term in lower)
            scored.append((score, topic, slug))
        score, topic, slug = max(scored)
        if score == 0:
            topic, slug = "Analytical Aptitude", "analytical-aptitude"
            score = 1
        return "GA", topic, slug, min(0.99, 0.65 + 0.08 * score)

    scored_topics: list[tuple[int, str, str, str]] = []
    for (course, topic, slug), keywords in CLASSIFIER.items():
        score = sum(3 if " " in term else 1 for term in keywords if term in lower)
        scored_topics.append((score, course, topic, slug))
    scored_topics.sort(reverse=True)
    score, course, topic, slug = scored_topics[0]
    second_score = scored_topics[1][0]
    if score == 0 or (score == second_score and score < 3):
        return None
    confidence = 0.62 + min(0.28, 0.04 * score) + (0.05 if score > second_score else 0.0)
    return course, topic, slug, min(0.98, confidence)


def _subject_slug(course: str) -> str:
    return {
        "EM": "engineering-mathematics",
        "DL": "digital-logic",
        "COA": "computer-organization-and-architecture",
        "PDS": "programming-and-data-structures",
        "ALG": "algorithms",
        "TOC": "theory-of-computation",
        "CD": "compiler-design",
        "OS": "operating-systems",
        "DBMS": "databases",
        "CN": "computer-networks",
        "GA": "general-aptitude",
    }[course]


MANUAL_2019_TOPICS: dict[int, tuple[str, str, str]] = {
    11: ("COA", "Memory Hierarchy", "memory-hierarchy"),
    12: ("COA", "Memory Hierarchy", "memory-hierarchy"),
    13: ("CD", "Parsing", "parsing"),
    14: ("DL", "Number Representation and Arithmetic", "number-representation-and-arithmetic"),
    15: ("EM", "Discrete Mathematics", "discrete-mathematics"),
    16: ("DL", "Boolean Algebra", "boolean-algebra"),
    17: ("TOC", "Regular Expressions and Finite Automata", "regular-expressions-and-finite-automata"),
    18: ("DL", "Number Representation and Arithmetic", "number-representation-and-arithmetic"),
    19: ("EM", "Linear Algebra", "linear-algebra"),
    20: ("EM", "Discrete Mathematics", "discrete-mathematics"),
    21: ("DBMS", "Transactions and Concurrency Control", "transactions-and-concurrency-control"),
    22: ("EM", "Discrete Mathematics", "discrete-mathematics"),
    23: ("EM", "Calculus", "calculus"),
    24: ("DBMS", "File Organization and Indexing", "file-organization-and-indexing"),
    25: ("TOC", "Pumping Lemmas and Language Properties", "pumping-lemmas-and-language-properties"),
    26: ("CN", "Application Layer", "application-layer"),
    27: ("OS", "Processes and Threads", "processes-and-threads"),
    28: ("PDS", "Programming in C", "programming-in-c"),
    29: ("CD", "Parsing", "parsing"),
    30: ("ALG", "Searching, Sorting and Hashing", "searching-sorting-and-hashing"),
    31: ("EM", "Discrete Mathematics", "discrete-mathematics"),
    32: ("EM", "Probability and Statistics", "probability-and-statistics"),
    33: ("OS", "Concurrency and Synchronization", "concurrency-and-synchronization"),
    34: ("PDS", "Programming in C", "programming-in-c"),
    35: ("ALG", "Dynamic Programming", "dynamic-programming"),
    36: ("PDS", "Recursion", "recursion"),
    37: ("PDS", "Programming in C", "programming-in-c"),
    38: ("CN", "IPv4 Addressing and Forwarding", "ipv4-addressing-and-forwarding"),
    39: ("CN", "IPv4 Addressing and Forwarding", "ipv4-addressing-and-forwarding"),
    40: ("DL", "Boolean Algebra", "boolean-algebra"),
    41: ("TOC", "Pumping Lemmas and Language Properties", "pumping-lemmas-and-language-properties"),
    42: ("DBMS", "Normal Forms", "normal-forms"),
    43: ("OS", "Memory and Virtual Memory", "memory-and-virtual-memory"),
    44: ("TOC", "Turing Machines and Undecidability", "turing-machines-and-undecidability"),
    45: ("EM", "Discrete Mathematics", "discrete-mathematics"),
    46: ("CD", "Syntax-Directed Translation", "syntax-directed-translation"),
    47: ("ALG", "Complexity Analysis", "complexity-analysis"),
    48: ("ALG", "Greedy Algorithms", "greedy-algorithms"),
    49: ("OS", "Deadlocks", "deadlocks"),
    50: ("PDS", "Heaps", "heaps"),
    51: ("OS", "CPU and I/O Scheduling", "cpu-and-i-o-scheduling"),
    52: ("OS", "File Systems", "file-systems"),
    53: ("CD", "Parsing", "parsing"),
    54: ("EM", "Linear Algebra", "linear-algebra"),
    55: ("COA", "Memory Hierarchy", "memory-hierarchy"),
    56: ("PDS", "Trees and Binary Search Trees", "trees-and-binary-search-trees"),
    57: ("EM", "Probability and Statistics", "probability-and-statistics"),
    58: ("EM", "Discrete Mathematics", "discrete-mathematics"),
    59: ("CN", "Data Link Layer", "data-link-layer"),
    60: ("DL", "Combinational Circuits", "combinational-circuits"),
    61: ("DBMS", "SQL", "sql"),
    62: ("PDS", "Programming in C", "programming-in-c"),
    63: ("PDS", "Programming in C", "programming-in-c"),
    # GATE 2019 Q64 is RSA/totient content absent from the attached 2027 CS
    # syllabus, so it remains preserved but review-only.
    65: ("DBMS", "Relational Model", "relational-model"),
}

MANUAL_2021_CS2_TOPICS: dict[int, tuple[str, str, str]] = {
    1: ("GA", "Verbal Aptitude", "verbal-aptitude"),
    2: ("GA", "Spatial Aptitude", "spatial-aptitude"),
    3: ("GA", "Quantitative Aptitude", "quantitative-aptitude"),
    4: ("GA", "Quantitative Aptitude", "quantitative-aptitude"),
    5: ("GA", "Verbal Aptitude", "verbal-aptitude"),
    6: ("GA", "Verbal Aptitude", "verbal-aptitude"),
    7: ("GA", "Spatial Aptitude", "spatial-aptitude"),
    8: ("GA", "Quantitative Aptitude", "quantitative-aptitude"),
    9: ("GA", "Quantitative Aptitude", "quantitative-aptitude"),
    10: ("GA", "Analytical Aptitude", "analytical-aptitude"),
    11: ("ALG", "Greedy Algorithms", "greedy-algorithms"),
    12: ("PDS", "Heaps", "heaps"),
    13: ("CD", "Syntax-Directed Translation", "syntax-directed-translation"),
    14: (
        "DL",
        "Number Representation and Arithmetic",
        "number-representation-and-arithmetic",
    ),
    15: ("DL", "Combinational Circuits", "combinational-circuits"),
    16: ("DBMS", "Integrity Constraints", "integrity-constraints"),
    17: ("CN", "Transport Layer", "transport-layer"),
    18: (
        "ALG",
        "Searching, Sorting and Hashing",
        "searching-sorting-and-hashing",
    ),
    19: (
        "TOC",
        "Regular Expressions and Finite Automata",
        "regular-expressions-and-finite-automata",
    ),
    20: ("PDS", "Arrays", "arrays"),
    21: ("EM", "Discrete Mathematics", "discrete-mathematics"),
    22: (
        "TOC",
        "Pumping Lemmas and Language Properties",
        "pumping-lemmas-and-language-properties",
    ),
    23: (
        "CD",
        "Intermediate Code Generation",
        "intermediate-code-generation",
    ),
    24: ("OS", "CPU and I/O Scheduling", "cpu-and-i-o-scheduling"),
    25: ("EM", "Discrete Mathematics", "discrete-mathematics"),
    26: (
        "PDS",
        "Trees and Binary Search Trees",
        "trees-and-binary-search-trees",
    ),
    27: (
        "TOC",
        "Regular Expressions and Finite Automata",
        "regular-expressions-and-finite-automata",
    ),
    28: (
        "DL",
        "Number Representation and Arithmetic",
        "number-representation-and-arithmetic",
    ),
    29: ("COA", "Memory Hierarchy", "memory-hierarchy"),
    30: ("COA", "Interrupts and DMA", "interrupts-and-dma"),
    31: (
        "DBMS",
        "File Organization and Indexing",
        "file-organization-and-indexing",
    ),
    32: (
        "EM",
        "Probability and Statistics",
        "probability-and-statistics",
    ),
    33: ("PDS", "Recursion", "recursion"),
    34: ("EM", "Linear Algebra", "linear-algebra"),
    35: ("EM", "Calculus", "calculus"),
    36: ("ALG", "Greedy Algorithms", "greedy-algorithms"),
    37: ("COA", "Memory Hierarchy", "memory-hierarchy"),
    38: ("DL", "Sequential Circuits", "sequential-circuits"),
    39: (
        "EM",
        "Probability and Statistics",
        "probability-and-statistics",
    ),
    40: (
        "CD",
        "Code Optimization and Data-Flow Analysis",
        "code-optimization-and-data-flow-analysis",
    ),
    41: ("DBMS", "SQL", "sql"),
    42: (
        "DBMS",
        "Transactions and Concurrency Control",
        "transactions-and-concurrency-control",
    ),
    43: (
        "EM",
        "Probability and Statistics",
        "probability-and-statistics",
    ),
    44: ("CN", "Data Link Layer", "data-link-layer"),
    45: ("PDS", "Linked Lists", "linked-lists"),
    46: (
        "TOC",
        "Pumping Lemmas and Language Properties",
        "pumping-lemmas-and-language-properties",
    ),
    47: ("EM", "Linear Algebra", "linear-algebra"),
    48: (
        "CD",
        "Code Optimization and Data-Flow Analysis",
        "code-optimization-and-data-flow-analysis",
    ),
    49: ("ALG", "Complexity Analysis", "complexity-analysis"),
    50: ("DBMS", "Normal Forms", "normal-forms"),
    51: ("TOC", "Context-Free Grammars", "context-free-grammars"),
    52: (
        "OS",
        "Concurrency and Synchronization",
        "concurrency-and-synchronization",
    ),
    53: ("OS", "Deadlocks", "deadlocks"),
    54: (
        "DL",
        "Number Representation and Arithmetic",
        "number-representation-and-arithmetic",
    ),
    55: ("CN", "Routing Algorithms", "routing-algorithms"),
    56: ("ALG", "Graph Algorithms", "graph-algorithms"),
    57: (
        "TOC",
        "Regular Expressions and Finite Automata",
        "regular-expressions-and-finite-automata",
    ),
    58: ("OS", "Memory and Virtual Memory", "memory-and-virtual-memory"),
    59: ("PDS", "Recursion", "recursion"),
    60: ("EM", "Discrete Mathematics", "discrete-mathematics"),
    61: ("CD", "Parsing", "parsing"),
    62: ("DL", "Boolean Algebra", "boolean-algebra"),
    63: ("COA", "Instruction Pipelining", "instruction-pipelining"),
    64: ("CN", "Data Link Layer", "data-link-layer"),
    65: ("ALG", "Graph Algorithms", "graph-algorithms"),
}

REVIEWED_TOPIC_OVERRIDES: dict[
    tuple[str, int], tuple[str, str, str]
] = {
    ("CS-2018", 17): (
        "TOC",
        "Turing Machines and Undecidability",
        "turing-machines-and-undecidability",
    ),
    ("CS-2018", 19): ("COA", "Interrupts and DMA", "interrupts-and-dma"),
    ("CS-2018", 26): ("EM", "Calculus", "calculus"),
    ("CS-2018", 54): (
        "EM",
        "Probability and Statistics",
        "probability-and-statistics",
    ),
    ("CS-2022", 14): ("DBMS", "Relational Model", "relational-model"),
    ("CS-2022", 17): ("COA", "Interrupts and DMA", "interrupts-and-dma"),
    ("CS-2022", 61): (
        "COA",
        "Instruction Pipelining",
        "instruction-pipelining",
    ),
    ("CS-2023", 16): ("DBMS", "Relational Model", "relational-model"),
    ("CS-2023", 17): ("CN", "Data Link Layer", "data-link-layer"),
    ("CS-2023", 25): ("CN", "Routing Algorithms", "routing-algorithms"),
    ("CS-2023", 28): ("EM", "Calculus", "calculus"),
    ("CS-2023", 29): ("ALG", "Complexity Analysis", "complexity-analysis"),
    ("CS-2023", 33): (
        "COA",
        "Instruction Pipelining",
        "instruction-pipelining",
    ),
    ("CS1-2024", 44): ("DBMS", "Normal Forms", "normal-forms"),
    ("CS2-2024", 54): ("CN", "Transport Layer", "transport-layer"),
    ("CS2-2024", 55): ("CN", "Data Link Layer", "data-link-layer"),
    ("CS2-2024", 64): (
        "OS",
        "Memory and Virtual Memory",
        "memory-and-virtual-memory",
    ),
    ("CS1-2025", 14): (
        "OS",
        "Memory and Virtual Memory",
        "memory-and-virtual-memory",
    ),
    ("CS1-2025", 45): (
        "TOC",
        "Context-Free Grammars",
        "context-free-grammars",
    ),
    ("CS1-2025", 47): ("DBMS", "Normal Forms", "normal-forms"),
    ("CS2-2025", 24): (
        "TOC",
        "Pushdown Automata",
        "pushdown-automata",
    ),
    ("CS2-2025", 28): (
        "COA",
        "Machine Instructions and Addressing Modes",
        "machine-instructions-and-addressing-modes",
    ),
}

REVIEWED_FORCE_REVIEW: dict[tuple[str, int], str] = {
    ("CS-2018", 31): "reviewed_truncated_c_nat",
    ("CS-2018", 40): "reviewed_split_prompt_or_nested_option",
    ("CS-2018", 48): "reviewed_missing_parse_tree",
    ("CS-2022", 44): "reviewed_code_split_into_option",
    ("CS-2023", 19): "reviewed_missing_nfa_diagrams",
    ("CS-2023", 49): "reviewed_split_prompt",
    ("CS-2023", 56): "reviewed_truncated_nat",
    ("CS1-2021", 10): "reviewed_aom_misread_as_option",
    ("CS1-2024", 8): "reviewed_parenthetical_split_as_option",
    ("CS1-2024", 18): "reviewed_truncated_printf",
    ("CS1-2025", 16): "reviewed_list_match_option_swallow",
    ("CS1-2025", 33): "reviewed_truncated_if",
    ("CS1-2025", 34): "reviewed_truncated_printf",
    ("CS2-2024", 22): "reviewed_missing_dfa",
    ("CS2-2024", 33): "reviewed_c_split_at_char_pointer",
    ("CS2-2025", 17): "reviewed_list_match_option_swallow",
    ("CS2-2025", 19): "reviewed_truncated_printf",
    ("CS-2020", 7): "reviewed_joined_formula_ocr",
}


def classify_with_reviewed_override(
    paper: str,
    number: int,
    section: str,
    question: str,
) -> tuple[str, str, str, float] | None:
    override = REVIEWED_TOPIC_OVERRIDES.get((paper, number))
    if override is not None:
        return (*override, 0.99)
    return classify(section, question)


def _manual_2019_records(
    spec: PaperSpec, paper_stats: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any]] | None:
    """Ingest the independently page-verified 2019 OCR handoff."""

    structured_path = TMP_DIR / "ocr_2019" / "gate_2019_cse_structured.json"
    report_path = TMP_DIR / "ocr_2019" / "validation_report.json"
    if spec.label != "CS-2019" or not structured_path.exists():
        return None
    payload = json.loads(structured_path.read_text(encoding="utf-8"))
    validation = json.loads(report_path.read_text(encoding="utf-8"))
    visual_ids = set(validation["visual_dependency_ids"])
    source_records = payload["general_aptitude"] + payload["technical"]
    questions: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []

    for source in source_records:
        number = int(source["global_question_number"])
        section = source["section"]
        question_text = _clean(source["prompt"])
        classification = (
            (*MANUAL_2019_TOPICS[number], 0.99)
            if number in MANUAL_2019_TOPICS
            else classify(section, question_text)
            if section == "GA"
            else None
        )
        if classification:
            course, topic, topic_slug, classification_confidence = classification
            subject_slug: str | None = _subject_slug(course)
        else:
            course, topic, topic_slug = "UNRESOLVED", "Unresolved", "unresolved"
            subject_slug = None
            classification_confidence = 0.0

        options_source = source.get("options") or {}
        options = [
            {"id": identifier, "text": _clean(options_source[identifier])}
            for identifier in ("A", "B", "C", "D")
            if identifier in options_source
        ]
        answer_source = source["correct_answer"]
        if answer_source["kind"] == "option":
            accepted = answer_source["accepted_options"]
            answer: Any = (
                accepted[0] if len(accepted) == 1 else {"any_of": accepted}
            )
            has_alternatives = len(accepted) != 1
        else:
            ranges = answer_source["accepted_ranges"]
            normalized_ranges: list[Any] = []
            for answer_range in ranges:
                minimum, maximum = answer_range["min"], answer_range["max"]
                normalized_ranges.append(
                    minimum
                    if minimum == maximum
                    else {"min": minimum, "max": maximum}
                )
            answer = (
                normalized_ranges[0]
                if len(normalized_ranges) == 1
                else {"any_of": normalized_ranges}
            )
            has_alternatives = len(normalized_ranges) != 1

        original_flags = list(source["ocr"].get("flags") or [])
        review_flags = list(original_flags)
        if source["id"] in visual_ids:
            review_flags.append("visual_dependency")
        if has_alternatives:
            review_flags.append("alternative_answer_scoring")
        if classification is None:
            review_flags.append("course_topic_classification_low_confidence")
        manual_quality_flags = record_quality_flags(
            question_text,
            options,
            extraction_method="rapidocr_onnxruntime+visual_review",
        )
        review_flags.extend(
            f"transcription_debris:{flag}" for flag in manual_quality_flags
        )
        safe = (
            bool(source["ocr"].get("visually_verified"))
            and source["id"] not in visual_ids
            and not has_alternatives
            and classification is not None
            and not manual_quality_flags
        )
        if not safe:
            unresolved.append(
                {
                    "question_number": number,
                    "reason": ",".join(sorted(set(review_flags)))
                    or "not_verified_for_quiz",
                    "source_page": source["page"],
                }
            )
        image_name = Path(source["ocr"]["source_page_image"]).name
        answer_display = answer_source["official_key_display"]
        questions.append(
            {
                "external_id": f"gate-{spec.label.lower()}-q{number:02d}",
                "question": question_text,
                "options": options,
                "course": course,
                "subject_slug": subject_slug,
                "topic": topic,
                "topic_slug": topic_slug,
                "correct_answer": answer,
                "question_type": source["type"].lower(),
                "difficulty": "medium" if source["marks"] == 1 else "hard",
                "marks": source["marks"],
                "explanation": (
                    f"The official final answer key gives {answer_display}. "
                    "The supplied archive contains an answer key, not a worked solution."
                ),
                "numerical_tolerance": 0.0,
                "source_kind": "previous_year",
                "source_year": spec.year,
                "source_paper": spec.label,
                "source_question_number": number,
                "source_url": spec.source_url,
                "answer_key_url": spec.answer_key_url,
                "source_page": source["page"],
                "source_image": f"tmp/pyq/ocr-2019/{image_name}",
                "extraction_method": "rapidocr_onnxruntime+visual_review",
                "extraction_confidence": round(
                    min(
                        float(source["ocr"]["confidence"]),
                        classification_confidence,
                    ),
                    4,
                ),
                "tags": [
                    "gate-2019",
                    spec.label.lower(),
                    "official-pyq",
                    topic_slug,
                ],
                "status": "verified" if safe else "review_required",
                "safe_for_quiz": safe,
                "review_flags": sorted(set(review_flags)),
            }
        )

    questions.sort(key=lambda item: item["source_question_number"])
    safe_count = sum(question["safe_for_quiz"] for question in questions)
    stats = {
        "label": spec.label,
        "year": spec.year,
        "paper": paper_stats,
        "key_path": spec.key_path,
        "expected_questions": spec.expected_questions,
        "question_blocks_recovered": 65,
        "official_key_rows_recovered": 65,
        "consolidated_records": 65,
        "safe_records_emitted": safe_count,
        "review_required_records": 65 - safe_count,
        "unresolved_count": len(unresolved),
        "unresolved": unresolved,
        "source_url": spec.source_url,
        "answer_key_url": spec.answer_key_url,
        "source_note": (
            "RapidOCR transcription independently validated page-by-page; "
            "see tmp/pyq/ocr_2019/validation_report.json."
        ),
    }
    return questions, stats


def _manual_2021_cs2_records(
    spec: PaperSpec, paper_stats: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any]] | None:
    """Ingest the independently page-verified CS2-2021 OCR handoff."""

    structured_path = (
        TMP_DIR / "ocr_cs2_2021" / "gate_2021_cs2_structured.json"
    )
    report_path = TMP_DIR / "ocr_cs2_2021" / "validation_report.json"
    if spec.label != "CS2-2021" or not structured_path.exists():
        return None

    payload = json.loads(structured_path.read_text(encoding="utf-8"))
    validation = json.loads(report_path.read_text(encoding="utf-8"))
    source_records = payload.get("questions")
    if (
        validation.get("status") != "PASS"
        or validation.get("record_count") != 65
        or validation.get("errors")
        or not isinstance(source_records, list)
        or len(source_records) != 65
        or {
            int(source.get("global_question_number", -1))
            for source in source_records
        }
        != set(range(1, 66))
        or set(MANUAL_2021_CS2_TOPICS) != set(range(1, 66))
    ):
        raise ValueError("CS2-2021 structured handoff failed importer invariants")

    visual_ids = set(validation["visual_review_required_ids"])
    questions: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for source in source_records:
        number = int(source["global_question_number"])
        course, topic, topic_slug = MANUAL_2021_CS2_TOPICS[number]
        subject_slug = _subject_slug(course)
        question_text = _clean(source["prompt"])
        options_source = source.get("options") or {}
        options = [
            {"id": identifier, "text": _clean(options_source[identifier])}
            for identifier in ("A", "B", "C", "D")
            if identifier in options_source
        ]
        question_type = str(source["type"]).lower()
        answer_source = source["correct_answer"]
        has_alternatives = False
        if answer_source["kind"] == "option":
            accepted = list(answer_source["accepted_options"])
            if question_type == "msq":
                answer: Any = accepted
            else:
                answer = accepted[0] if len(accepted) == 1 else {"any_of": accepted}
                has_alternatives = len(accepted) != 1
        else:
            ranges = answer_source["accepted_ranges"]
            normalized_ranges: list[Any] = []
            for answer_range in ranges:
                minimum, maximum = answer_range["min"], answer_range["max"]
                normalized_ranges.append(
                    minimum
                    if minimum == maximum
                    else {"min": minimum, "max": maximum}
                )
            answer = (
                normalized_ranges[0]
                if len(normalized_ranges) == 1
                else {"any_of": normalized_ranges}
            )
            has_alternatives = len(normalized_ranges) != 1

        original_flags = list(source["ocr"].get("flags") or [])
        review_flags = list(original_flags)
        if source["id"] in visual_ids or source["ocr"].get(
            "requires_visual_review"
        ):
            review_flags.append("visual_dependency")
        if has_alternatives:
            review_flags.append("alternative_answer_scoring")
        quality_flags = record_quality_flags(
            question_text,
            options,
            extraction_method="rapidocr_onnxruntime+visual_review",
        )
        review_flags.extend(
            f"transcription_debris:{flag}" for flag in quality_flags
        )
        safe = (
            bool(source["ocr"].get("visually_verified"))
            and source["id"] not in visual_ids
            and not source["ocr"].get("requires_visual_review")
            and not has_alternatives
            and not quality_flags
            and (
                (question_type in {"mcq", "msq"} and len(options) == 4)
                or (question_type == "nat" and options == [])
            )
        )
        if not safe:
            unresolved.append(
                {
                    "question_number": number,
                    "reason": ",".join(sorted(set(review_flags)))
                    or "not_verified_for_quiz",
                    "source_page": source["source_page"],
                }
            )

        image_name = Path(source["ocr"]["source_page_image"]).name
        answer_display = answer_source["official_key_display"]
        questions.append(
            {
                "external_id": f"gate-{spec.label.lower()}-q{number:02d}",
                "question": question_text,
                "options": options,
                "course": course,
                "subject_slug": subject_slug,
                "topic": topic,
                "topic_slug": topic_slug,
                "correct_answer": answer,
                "question_type": question_type,
                "difficulty": "medium" if source["marks"] == 1 else "hard",
                "marks": source["marks"],
                "explanation": (
                    f"The official final answer key gives {answer_display}. "
                    "The supplied archive contains an answer key, not a worked solution."
                ),
                "numerical_tolerance": 0.0,
                "source_kind": "previous_year",
                "source_year": spec.year,
                "source_paper": spec.label,
                "source_question_number": number,
                "source_url": spec.source_url,
                "answer_key_url": spec.answer_key_url,
                "source_page": source["source_page"],
                "source_image": f"tmp/pyq/ocr-CS2-2021/{image_name}",
                "extraction_method": "rapidocr_onnxruntime+visual_review",
                "extraction_confidence": round(
                    min(float(source["ocr"]["confidence"]), 0.99),
                    4,
                ),
                "tags": [
                    "gate-2021",
                    spec.label.lower(),
                    "official-pyq",
                    topic_slug,
                ],
                "status": "verified" if safe else "review_required",
                "safe_for_quiz": safe,
                "review_flags": sorted(set(review_flags)),
            }
        )

    questions.sort(key=lambda item: item["source_question_number"])
    safe_count = sum(question["safe_for_quiz"] for question in questions)
    stats = {
        "label": spec.label,
        "year": spec.year,
        "paper": paper_stats,
        "key_path": spec.key_path,
        "expected_questions": spec.expected_questions,
        "question_blocks_recovered": 65,
        "official_key_rows_recovered": 65,
        "consolidated_records": 65,
        "safe_records_emitted": safe_count,
        "review_required_records": 65 - safe_count,
        "unresolved_count": len(unresolved),
        "unresolved": unresolved,
        "source_url": spec.source_url,
        "answer_key_url": spec.answer_key_url,
        "source_note": (
            "RapidOCR transcription independently validated page-by-page; "
            "see tmp/pyq/ocr_cs2_2021/validation_report.json."
        ),
    }
    return questions, stats


def consolidate_spec(
    spec: PaperSpec, *, enable_ocr: bool
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    pages, paper_stats = extract_pages(spec, enable_ocr=enable_ocr)
    manual_2021_cs2 = _manual_2021_cs2_records(spec, paper_stats)
    if manual_2021_cs2 is not None:
        return manual_2021_cs2
    manual_2019 = _manual_2019_records(spec, paper_stats)
    if manual_2019 is not None:
        return manual_2019
    key, key_unresolved = parse_key(spec)
    blocks, unresolved = extract_question_blocks(spec, pages)
    blocks = recover_option_group_blocks(spec, pages, key, blocks)
    unresolved.extend(key_unresolved)
    questions: list[dict[str, Any]] = []
    safe_numbers: set[int] = set()
    for number in range(1, spec.expected_questions + 1):
        block = blocks.get(number)
        key_record = key.get(number)
        if block is None:
            unresolved.append(
                {"question_number": number, "reason": "question_block_not_recovered"}
            )
            continue
        if key_record is None:
            unresolved.append(
                {"question_number": number, "reason": "official_key_not_recovered"}
            )
            continue
        answer = key_record["answer"]
        if isinstance(answer, dict) and (
            "any_of" in answer or "marks_to_all" in answer
        ):
            unresolved.append(
                {
                    "question_number": number,
                    "reason": "official_key_requires_alternative_answer_scoring",
                    "source_page": block["source_page"],
                }
            )
            continue
        split = split_question(block["raw"], key_record["type"])
        if split is None:
            unresolved.append(
                {
                    "question_number": number,
                    "reason": "options_or_question_text_incomplete",
                    "source_page": block["source_page"],
                }
            )
            continue
        question_text, options = split
        forced_review_reason = REVIEWED_FORCE_REVIEW.get((spec.label, number))
        if forced_review_reason:
            unresolved.append(
                {
                    "question_number": number,
                    "reason": forced_review_reason,
                    "source_page": block["source_page"],
                }
            )
            continue
        serialized_text = " ".join(
            [question_text] + [option["text"] for option in options]
        )
        quality_flags = record_quality_flags(question_text, options)
        if quality_flags:
            unresolved.append(
                {
                    "question_number": number,
                    "reason": "transcription_debris:" + ",".join(quality_flags),
                    "source_page": block["source_page"],
                }
            )
            continue
        if re.search(
            r"\b(figure|diagram|shown below|given below is an image|following image)\b",
            question_text,
            re.IGNORECASE,
        ):
            unresolved.append(
                {
                    "question_number": number,
                    "reason": "visual_dependency_not_safely_serializable",
                    "source_page": block["source_page"],
                }
            )
            continue
        classification = classify_with_reviewed_override(
            spec.label,
            number,
            key_record["section"],
            question_text,
        )
        if classification is None:
            unresolved.append(
                {
                    "question_number": number,
                    "reason": "course_topic_classification_low_confidence",
                    "source_page": block["source_page"],
                }
            )
            continue
        course, topic, topic_slug, classification_confidence = classification
        if key_record["type"] in {"mcq", "msq"}:
            option_ids = {option["id"] for option in options}
            answers = (
                [key_record["answer"]]
                if key_record["type"] == "mcq"
                else key_record["answer"]
            )
            if any(answer_id not in option_ids for answer_id in answers):
                unresolved.append(
                    {
                        "question_number": number,
                        "reason": "official_answer_not_present_in_extracted_options",
                        "source_page": block["source_page"],
                    }
                )
                continue
        answer_display = json.dumps(answer, ensure_ascii=False)
        questions.append(
            {
                "external_id": f"gate-{spec.label.lower()}-q{number:02d}",
                "question": question_text,
                "options": options,
                "course": course,
                "subject_slug": _subject_slug(course),
                "topic": topic,
                "topic_slug": topic_slug,
                "correct_answer": answer,
                "question_type": key_record["type"],
                "difficulty": "medium" if key_record["marks"] == 1 else "hard",
                "marks": key_record["marks"],
                "explanation": (
                    f"The official final answer key gives {answer_display}. "
                    "The supplied archive contains an answer key, not a worked solution."
                ),
                "numerical_tolerance": 0.0,
                "source_kind": "previous_year",
                "source_year": spec.year,
                "source_paper": spec.label,
                "source_question_number": number,
                "source_url": spec.source_url,
                "answer_key_url": spec.answer_key_url,
                "source_page": block["source_page"],
                "extraction_method": block["extraction_method"],
                "extraction_confidence": round(
                    min(
                        float(block["extraction_confidence"]),
                        classification_confidence,
                    ),
                    4,
                ),
                "tags": [
                    f"gate-{spec.year}",
                    spec.label.lower(),
                    "official-pyq",
                    topic_slug,
                ],
                "status": "verified",
                "safe_for_quiz": True,
                "review_flags": [],
            }
        )
        safe_numbers.add(number)

    unique_unresolved: list[dict[str, Any]] = []
    seen_unresolved: set[tuple[Any, Any]] = set()
    for item in unresolved:
        key_value = (item.get("question_number"), item.get("reason"))
        if key_value not in seen_unresolved:
            unique_unresolved.append(item)
            seen_unresolved.add(key_value)
    unresolved_by_number: dict[int, list[str]] = {}
    for item in unique_unresolved:
        number = item.get("question_number")
        if isinstance(number, int):
            unresolved_by_number.setdefault(number, []).append(item["reason"])

    safe_count = len(questions)
    for number in range(1, spec.expected_questions + 1):
        if number in safe_numbers:
            continue
        block = blocks.get(number)
        key_record = key.get(number)
        raw = block["raw"] if block else ""
        question_type = key_record["type"] if key_record else None
        question_text, options = split_question_loose(raw, question_type)
        section = (
            key_record["section"]
            if key_record
            else block["section"]
            if block
            else (
                "CS"
                if spec.numbering == "cs_then_ga_global" and number <= 55
                else "GA"
                if spec.numbering == "cs_then_ga_global"
                else "GA"
                if number <= 10
                else "CS"
            )
        )
        classification = (
            classify_with_reviewed_override(
                spec.label,
                number,
                section,
                question_text,
            )
            if question_text
            else None
        )
        if classification:
            course, topic, topic_slug, classification_confidence = classification
            subject_slug: str | None = _subject_slug(course)
        else:
            course, topic, topic_slug = "UNRESOLVED", "Unresolved", "unresolved"
            subject_slug = None
            classification_confidence = 0.0
        answer = key_record["answer"] if key_record else None
        marks = key_record["marks"] if key_record else None
        source_page = block["source_page"] if block else None
        source_image: str | None = None
        if spec.ocr_dir and source_page:
            image_path = _ocr_image_for_page(TMP_DIR / spec.ocr_dir, source_page)
            if image_path:
                source_image = str(image_path.relative_to(REPO_DIR)).replace("\\", "/")
        flags = unresolved_by_number.get(number, [])
        if not flags:
            flags = ["not_verified_for_quiz"]
        answer_display = json.dumps(answer, ensure_ascii=False)
        questions.append(
            {
                "external_id": f"gate-{spec.label.lower()}-q{number:02d}",
                "question": question_text or None,
                "options": options,
                "course": course,
                "subject_slug": subject_slug,
                "topic": topic,
                "topic_slug": topic_slug,
                "correct_answer": answer,
                "question_type": question_type,
                "difficulty": (
                    "medium" if marks == 1 else "hard" if marks == 2 else None
                ),
                "marks": marks,
                "explanation": (
                    f"The official final answer key gives {answer_display}. "
                    "This record requires source-page review before quiz use."
                    if key_record
                    else "The official key row was not safely recovered; source review is required."
                ),
                "numerical_tolerance": 0.0,
                "source_kind": "previous_year",
                "source_year": spec.year,
                "source_paper": spec.label,
                "source_question_number": number,
                "source_url": spec.source_url,
                "answer_key_url": spec.answer_key_url,
                "source_page": source_page,
                "source_image": source_image,
                "extraction_method": (
                    block["extraction_method"] if block else "unrecovered"
                ),
                "extraction_confidence": round(
                    min(
                        float(block["extraction_confidence"]) if block else 0.0,
                        classification_confidence,
                    ),
                    4,
                ),
                "tags": [
                    f"gate-{spec.year}",
                    spec.label.lower(),
                    "official-pyq",
                    "review-required",
                    topic_slug,
                ],
                "status": "review_required",
                "safe_for_quiz": False,
                "review_flags": sorted(set(flags)),
            }
        )

    questions.sort(key=lambda item: item["source_question_number"])
    stats = {
        "label": spec.label,
        "year": spec.year,
        "paper": paper_stats,
        "key_path": spec.key_path,
        "expected_questions": spec.expected_questions,
        "question_blocks_recovered": len(blocks),
        "official_key_rows_recovered": len(key),
        "consolidated_records": len(questions),
        "safe_records_emitted": safe_count,
        "review_required_records": len(questions) - safe_count,
        "unresolved_count": len(unique_unresolved),
        "unresolved": sorted(
            unique_unresolved,
            key=lambda item: (item.get("question_number", math.inf), item["reason"]),
        ),
        "source_url": spec.source_url,
        "answer_key_url": spec.answer_key_url,
        "source_note": spec.source_note,
    }
    return questions, stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-ocr",
        action="store_true",
        help="Use only embedded text, even when rendered OCR pages exist.",
    )
    parser.add_argument(
        "--only",
        action="append",
        help="Process only a paper label (repeatable), useful for diagnostics.",
    )
    parser.add_argument(
        "--cache-only",
        action="store_true",
        help="Populate OCR page caches for selected papers without writing data artifacts.",
    )
    args = parser.parse_args()
    selected = [
        spec for spec in PAPERS if not args.only or spec.label in set(args.only)
    ]
    if not selected:
        raise SystemExit("No matching paper labels")
    if args.cache_only:
        for spec in selected:
            _, stats = extract_pages(spec, enable_ocr=not args.no_ocr)
            print(
                f"{spec.label}: cached {stats['pages']} pages; "
                f"methods={stats['extraction_methods']}"
            )
        return 0

    all_questions: list[dict[str, Any]] = []
    paper_reports: list[dict[str, Any]] = []
    for spec in selected:
        questions, report = consolidate_spec(spec, enable_ocr=not args.no_ocr)
        all_questions.extend(questions)
        paper_reports.append(report)
        print(
            f"{spec.label}: {report['safe_records_emitted']} safe / "
            f"{report['expected_questions']} expected; "
            f"{report['official_key_rows_recovered']} key rows"
        )

    all_questions.sort(key=lambda item: item["external_id"])
    safe_questions = [
        question for question in all_questions if question["safe_for_quiz"]
    ]
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0",
        "bank_version": "gate-cs-pyq-2017-2025-v1",
        "generated_at": GENERATED_AT,
        "questions": all_questions,
    }
    OUTPUT_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    by_year: dict[str, int] = {}
    safe_by_year: dict[str, int] = {}
    for question in all_questions:
        year = str(question["source_year"])
        by_year[year] = by_year.get(year, 0) + 1
        if question["safe_for_quiz"]:
            safe_by_year[year] = safe_by_year.get(year, 0) + 1
    manifest = {
        "schema_version": "1.0",
        "generated_at": GENERATED_AT,
        "scope": "GATE CS papers supplied for 2017 through 2025",
        "source_archive": (
            "CS.zip (user-supplied; extracted under ignored tmp/pyq/source)"
        ),
        "syllabus_source": "CS_GATE2027_Syllabus.pdf (user-supplied)",
        "consolidated_record_count": len(all_questions),
        "records_by_year": dict(sorted(by_year.items())),
        "safe_question_count": len(safe_questions),
        "safe_questions_by_year": dict(sorted(safe_by_year.items())),
        "review_required_count": len(all_questions) - len(safe_questions),
        "papers": paper_reports,
        "quality_policy": {
            "ocr_is_fallback_only": True,
            "visual_dependency_preserved_but_not_quiz_safe": True,
            "alternative_keys_preserved_but_not_quiz_safe": True,
            "low_confidence_classification_preserved_but_not_quiz_safe": True,
            "nat_ranges_preserved_as_min_max_objects": True,
            "worked_solutions_available": False,
        },
        "notes": [
            "The supplied PDFs generally contain final answer keys rather than worked solutions.",
            "All 845 source question numbers are preserved; unsafe or incomplete transcriptions are marked review_required and never enter the live bank.",
            "Question numbers are normalized to 1-65 per paper; older papers that number CS before GA retain their original global numbering.",
        ],
    }
    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        f"Wrote {len(all_questions)} consolidated PYQ records to {OUTPUT_PATH}; "
        f"{len(safe_questions)} are verified for quiz use."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
