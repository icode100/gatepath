"""Build the reproducible, local GATE CSE question bank.

The generated questions are deterministic: each item is produced from a
topic-specific calculation or a curated set of syllabus facts.  Re-running
this file creates byte-for-byte identical JSON (including a fixed release
timestamp) unless the source code or the optional PYQ file changes.

Usage:
    python backend/scripts/generate_question_bank.py
    python backend/scripts/generate_question_bank.py --validate
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any


BACKEND_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BACKEND_DIR / "data"
OUTPUT_PATH = DATA_DIR / "question_bank.json"
PYQ_PATH = DATA_DIR / "pyq_consolidated.json"
REPORT_PATH = DATA_DIR / "question_bank_manifest.json"

SCHEMA_VERSION = "1.0"
BANK_VERSION = "gate-cs-2027-v1"
GENERATED_AT = "2026-07-30T00:00:00Z"
TECHNICAL_TARGET = 210
GA_TARGET = 120


@dataclass(frozen=True)
class SubjectSpec:
    code: str
    slug: str
    name: str
    target: int


@dataclass(frozen=True)
class TopicSpec:
    course: str
    name: str
    slug: str
    numeric_kind: str
    truths: tuple[str, ...]
    falsehoods: tuple[str, ...]


SUBJECTS: tuple[SubjectSpec, ...] = (
    SubjectSpec("EM", "engineering-mathematics", "Engineering Mathematics", TECHNICAL_TARGET),
    SubjectSpec("DL", "digital-logic", "Digital Logic", TECHNICAL_TARGET),
    SubjectSpec(
        "COA",
        "computer-organization-and-architecture",
        "Computer Organization and Architecture",
        TECHNICAL_TARGET,
    ),
    SubjectSpec(
        "PDS",
        "programming-and-data-structures",
        "Programming and Data Structures",
        TECHNICAL_TARGET,
    ),
    SubjectSpec("ALG", "algorithms", "Algorithms", TECHNICAL_TARGET),
    SubjectSpec("TOC", "theory-of-computation", "Theory of Computation", TECHNICAL_TARGET),
    SubjectSpec("CD", "compiler-design", "Compiler Design", TECHNICAL_TARGET),
    SubjectSpec("OS", "operating-systems", "Operating Systems", TECHNICAL_TARGET),
    SubjectSpec("DBMS", "databases", "Databases", TECHNICAL_TARGET),
    SubjectSpec("CN", "computer-networks", "Computer Networks", TECHNICAL_TARGET),
    SubjectSpec("GA", "general-aptitude", "General Aptitude", GA_TARGET),
)


def _facts(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split("|"))


def _topic(
    course: str,
    name: str,
    slug: str,
    numeric_kind: str,
    truths: str,
    falsehoods: str,
) -> TopicSpec:
    return TopicSpec(
        course=course,
        name=name,
        slug=slug,
        numeric_kind=numeric_kind,
        truths=_facts(truths),
        falsehoods=_facts(falsehoods),
    )


# Every topic is taken from the attached GATE 2027 CS syllabus.  The facts are
# deliberately explicit so MSQ answers are auditable rather than model-guessed.
TOPICS: tuple[TopicSpec, ...] = (
    _topic(
        "EM",
        "Discrete Mathematics",
        "discrete-mathematics",
        "complete_graph",
        "In every finite undirected graph, the sum of vertex degrees is twice the number of edges.|An equivalence relation is reflexive, symmetric, and transitive.|A tree with n vertices has n - 1 edges.",
        "Every partial order is a total order.|Every group is commutative.|A simple cycle on n vertices has n - 1 edges.",
    ),
    _topic(
        "EM",
        "Linear Algebra",
        "linear-algebra",
        "triangular_determinant",
        "The determinant equals the product of eigenvalues, counted with multiplicity.|A square system with a nonsingular coefficient matrix has a unique solution.|Every real symmetric matrix has real eigenvalues.",
        "Every square matrix is diagonalizable.|A zero determinant implies a unique solution for every right-hand side.|Row operations never change a determinant.",
    ),
    _topic(
        "EM",
        "Calculus",
        "calculus",
        "quadratic_derivative",
        "Differentiability at a point implies continuity there.|An interior differentiable local extremum must have zero derivative.|The fundamental theorem links definite integration and antiderivatives.",
        "Continuity at a point always implies differentiability there.|Every stationary point is a local maximum.|A differentiable function can have a jump discontinuity.",
    ),
    _topic(
        "EM",
        "Probability and Statistics",
        "probability-and-statistics",
        "binomial_expectation",
        "For a binomial random variable, the mean is np.|Independent events A and B satisfy P(A intersection B) = P(A)P(B).|Variance is unchanged when a constant is added to a random variable.",
        "Mutually exclusive nonempty events are independent.|For every random variable, variance equals its mean.|Conditional probabilities P(A given B) and P(B given A) are always equal.",
    ),
    _topic(
        "DL",
        "Boolean Algebra",
        "boolean-algebra",
        "boolean_minterms",
        "De Morgan's law gives complement(AB) = complement(A) + complement(B).|A canonical minterm contains every variable exactly once.|X XOR X is always zero.",
        "X + XY equals X + Y.|A maxterm evaluates to zero for every input assignment.|X AND complement(X) equals one.",
    ),
    _topic(
        "DL",
        "Combinational Circuits",
        "combinational-circuits",
        "mux_inputs",
        "A combinational circuit has no state memory.|A decoder with n inputs can have up to 2^n output lines.|A full adder accepts three one-bit inputs.",
        "A multiplexer with s select lines has only s data inputs.|A half adder has a carry-in input.|A combinational output depends on the previous clock cycle.",
    ),
    _topic(
        "DL",
        "Sequential Circuits",
        "sequential-circuits",
        "counter_bits",
        "A sequential circuit can depend on stored state.|A D flip-flop samples its input at its active clock event.|A modulo-m counter needs at least ceil(log2(m)) state bits.",
        "Every latch is edge triggered.|A sequential circuit has no feedback path.|A k-bit binary counter has only k distinct states.",
    ),
    _topic(
        "DL",
        "Number Representation and Arithmetic",
        "number-representation-and-arithmetic",
        "unsigned_values",
        "An n-bit unsigned word has 2^n distinct patterns.|The n-bit two's-complement range is -2^(n-1) through 2^(n-1)-1.|Two's-complement negation complements the bits and adds one.",
        "An n-bit unsigned word has maximum value 2^n.|Sign extension changes the represented two's-complement value.|Adding two positive two's-complement values can never overflow.",
    ),
    _topic(
        "COA",
        "Machine Instructions and Addressing Modes",
        "machine-instructions-and-addressing-modes",
        "effective_address",
        "Immediate addressing places the operand value in the instruction.|Base-plus-offset addressing adds a displacement to a base register.|Indirect addressing requires an additional memory reference for the effective address.",
        "Immediate addressing always fetches the operand from data memory.|Register addressing names a memory location only.|PC-relative addressing cannot support branches.",
    ),
    _topic(
        "COA",
        "ALU, Datapath and Control",
        "alu-datapath-and-control",
        "alu_result",
        "The ALU performs arithmetic and logical operations.|A datapath contains storage and functional units connected by buses.|A control unit selects datapath operations for each instruction.",
        "The program counter is part of secondary storage.|A hardwired control unit stores every control word in a writable cache.|An ALU alone determines the instruction sequence.",
    ),
    _topic(
        "COA",
        "Instruction Pipelining",
        "instruction-pipelining",
        "pipeline_cycles",
        "Ideal pipelining improves throughput, not the latency of one instruction.|A load-use dependency can require a stall even with forwarding.|A branch can create a control hazard.",
        "Forwarding removes every possible pipeline stall.|A structural hazard is caused only by branch instructions.|An ideal k-stage pipeline completes n instructions in kn cycles.",
    ),
    _topic(
        "COA",
        "Memory Hierarchy",
        "memory-hierarchy",
        "amat",
        "Temporal locality means recently used data is likely to be reused.|Average memory access time includes hit time plus miss rate times miss penalty.|A larger block can exploit spatial locality.",
        "A cache miss never accesses a lower memory level.|Direct-mapped caches have no conflict misses.|Write-through updates only the cache copy.",
    ),
    _topic(
        "COA",
        "I/O Interface",
        "i-o-interface",
        "polling_time",
        "Programmed I/O can make the CPU poll device status.|Interrupt-driven I/O lets a device notify the processor.|Memory-mapped I/O uses ordinary address-space operations.",
        "Interrupt-driven I/O requires continuous polling.|Programmed I/O always transfers blocks without CPU involvement.|Every I/O device executes CPU instructions directly.",
    ),
    _topic(
        "COA",
        "Interrupts and DMA",
        "interrupts-and-dma",
        "dma_time",
        "DMA can transfer a block with limited CPU intervention.|A vectored interrupt identifies an interrupt-service entry.|Cycle stealing lets DMA use individual memory-bus cycles.",
        "DMA requires one CPU instruction for every transferred byte.|Interrupt masking physically disconnects all devices.|A non-vectored interrupt always supplies the ISR address directly.",
    ),
    _topic(
        "PDS",
        "Programming in C",
        "programming-in-c",
        "pointer_address",
        "Pointer arithmetic is scaled by the pointed-to type size.|Array indexing a[i] is defined using pointer arithmetic.|C passes ordinary function arguments by value.",
        "Incrementing an int pointer always adds one byte.|A local automatic variable persists after its function returns.|C arrays perform bounds checks automatically.",
    ),
    _topic(
        "PDS",
        "Recursion",
        "recursion",
        "recursive_calls",
        "A terminating recursion needs progress toward a base case.|Each active recursive call has its own activation record.|A recursive algorithm can be described by a recurrence.",
        "Every recursive function uses constant stack space.|A base case makes the first call unnecessary.|Tail recursion always has exponential running time.",
    ),
    _topic(
        "PDS",
        "Arrays",
        "arrays",
        "array_address",
        "Array elements occupy contiguous storage.|C stores multidimensional arrays in row-major order.|Random access by index is constant time for an array.",
        "Inserting at the front of a dense array is always constant time.|An array index can never be computed arithmetically.|Column-major order is mandated by C.",
    ),
    _topic(
        "PDS",
        "Stacks and Queues",
        "stacks-and-queues",
        "queue_capacity",
        "A stack uses last-in, first-out order.|A queue uses first-in, first-out order.|A circular queue reuses positions released at the front.",
        "A queue removes the newest element first.|A stack requires sorted keys.|A circular queue cannot be implemented with an array.",
    ),
    _topic(
        "PDS",
        "Linked Lists",
        "linked-lists",
        "list_traversal",
        "A singly linked node stores a link to its successor.|Insertion after a known node can be constant time.|A doubly linked list supports traversal in both directions.",
        "A linked list provides constant-time access to its kth node without extra indexing.|Every linked-list node is contiguous with the next node.|Deleting a node never changes any link.",
    ),
    _topic(
        "PDS",
        "Trees and Binary Search Trees",
        "trees-and-binary-search-trees",
        "perfect_tree_nodes",
        "Inorder traversal of a BST visits distinct keys in sorted order.|A tree with n vertices has n - 1 edges.|A binary tree node has at most two children.",
        "Preorder traversal of every BST is sorted.|Every binary tree is height balanced.|A complete binary tree must have an odd number of nodes.",
    ),
    _topic(
        "PDS",
        "Heaps",
        "heaps",
        "heap_parent",
        "A binary heap is a complete binary tree.|The maximum key is at the root of a max-heap.|Insertion can require a path of swaps toward the root.",
        "A max-heap stores all keys in sorted array order.|Searching an arbitrary key in a binary heap is always logarithmic.|The root of a min-heap contains the maximum key.",
    ),
    _topic(
        "PDS",
        "Graphs",
        "graphs",
        "adjacency_entries",
        "An adjacency list uses O(V + E) space for a sparse graph.|An undirected edge appears twice in ordinary adjacency lists.|An adjacency matrix supports constant-time edge lookup.",
        "Every graph is connected.|An adjacency matrix uses O(V + E) space in all cases.|A directed edge must appear twice in an adjacency list.",
    ),
    _topic(
        "ALG",
        "Searching, Sorting and Hashing",
        "searching-sorting-and-hashing",
        "binary_search",
        "Binary search requires an ordered search interval.|Comparison sorting has an Omega(n log n) worst-case lower bound in the general model.|A hash collision occurs when distinct keys map to one slot.",
        "Binary search is correct on an arbitrary unsorted array.|Every hash table operation is worst-case O(1).|Merge sort is an in-place constant-space algorithm in its standard array implementation.",
    ),
    _topic(
        "ALG",
        "Complexity Analysis",
        "complexity-analysis",
        "nested_loop_ops",
        "Theta notation gives an asymptotically tight bound.|Constants are ignored in asymptotic growth classes.|A polynomial-time bound is closed under addition and multiplication.",
        "O(n) and Omega(n) are mutually exclusive.|Every exponential algorithm is faster than every polynomial algorithm for all inputs.|Worst-case time can be smaller than best-case time.",
    ),
    _topic(
        "ALG",
        "Divide and Conquer",
        "divide-and-conquer",
        "merge_levels",
        "Divide and conquer solves subproblems and combines their results.|Merge sort has logarithmically many merge levels.|Binary search discards about half the remaining interval.",
        "Every divide-and-conquer recurrence has quadratic complexity.|Merge sort performs no combine work.|Divide and conquer cannot be implemented recursively.",
    ),
    _topic(
        "ALG",
        "Greedy Algorithms",
        "greedy-algorithms",
        "mst_edges",
        "Kruskal's algorithm adds safe edges in nondecreasing weight order.|Prim's algorithm grows one tree.|A greedy proof commonly uses an exchange argument.",
        "A locally best choice is optimal for every optimization problem.|Kruskal's algorithm may retain a cycle in an MST.|Every shortest-path problem permits negative cycles.",
    ),
    _topic(
        "ALG",
        "Dynamic Programming",
        "dynamic-programming",
        "dp_cells",
        "Dynamic programming exploits overlapping subproblems.|Memoization is top-down caching.|Tabulation stores subproblem answers in an evaluation order.",
        "Dynamic programming never uses extra memory.|Optimal substructure is irrelevant to dynamic programming.|Memoization recomputes every subproblem each time.",
    ),
    _topic(
        "ALG",
        "Graph Algorithms",
        "graph-algorithms",
        "bfs_scans",
        "BFS finds shortest unweighted path lengths from a source.|DFS can identify connected components.|Dijkstra's standard correctness requires nonnegative edge weights.",
        "BFS always finds minimum-weight paths with arbitrary edge weights.|DFS uses a FIFO queue as its defining discipline.|Dijkstra's algorithm remains correct with a reachable negative cycle.",
    ),
    _topic(
        "TOC",
        "Regular Expressions and Finite Automata",
        "regular-expressions-and-finite-automata",
        "dfa_subsets",
        "Regular expressions and finite automata define the same language class.|Every DFA is also an NFA.|Subset construction can produce up to 2^n DFA states from n NFA states.",
        "A finite automaton recognizes every context-free language.|An NFA is more expressive than a DFA.|A DFA may have two transitions on one symbol from the same state.",
    ),
    _topic(
        "TOC",
        "Context-Free Grammars",
        "context-free-grammars",
        "parse_tree_nodes",
        "A context-free production has one nonterminal on its left side.|A parse tree records a grammatical derivation.|An ambiguous grammar has a string with two distinct parse trees.",
        "Every context-free grammar is unambiguous.|A regular language cannot have a context-free grammar.|A leftmost derivation expands the rightmost nonterminal first.",
    ),
    _topic(
        "TOC",
        "Pushdown Automata",
        "pushdown-automata",
        "pda_stack",
        "A pushdown automaton has an unbounded stack.|Nondeterministic PDAs recognize the context-free languages.|A stack can match nested delimiters.",
        "A PDA has only finite memory in total.|Every Turing-recognizable language is accepted by a PDA.|A PDA stack supports random access to every stored symbol.",
    ),
    _topic(
        "TOC",
        "Pumping Lemmas and Language Properties",
        "pumping-lemmas-and-language-properties",
        "pumping_length",
        "The regular languages are closed under complement.|A pumping lemma can be used to prove that a language is not regular.|Context-free languages are closed under union.",
        "The regular pumping lemma proves that a language is regular.|Context-free languages are closed under intersection.|Every subset of a regular language is regular.",
    ),
    _topic(
        "TOC",
        "Turing Machines and Undecidability",
        "turing-machines-and-undecidability",
        "tm_steps",
        "A Turing machine has a finite control and an unbounded tape model.|The halting problem is undecidable.|A mapping reduction can transfer undecidability to a target problem.",
        "Every recognizable language is decidable.|A Turing machine tape has a fixed finite bound independent of input.|An undecidable language has no recognizer.",
    ),
    _topic(
        "CD",
        "Lexical Analysis",
        "lexical-analysis",
        "token_count",
        "A lexer groups characters into tokens.|Regular expressions commonly specify token patterns.|Whitespace can often be discarded by lexical analysis.",
        "A lexer builds the complete parse tree.|Context-free parsing is required to recognize every identifier.|A lexeme is always a token category rather than source text.",
    ),
    _topic(
        "CD",
        "Parsing",
        "parsing",
        "parse_actions",
        "LL parsing is top down.|LR parsing is bottom up.|FIRST and FOLLOW sets help construct predictive parsing tables.",
        "Shift-reduce parsing is top down.|An LL(1) parser uses unlimited lookahead.|Every context-free grammar is LR(0).",
    ),
    _topic(
        "CD",
        "Syntax-Directed Translation",
        "syntax-directed-translation",
        "attribute_evaluations",
        "Synthesized attributes are computed from child information.|Inherited attributes can pass context from parent or siblings.|A syntax-directed definition associates attributes and rules with grammar symbols or productions.",
        "Every attribute must be inherited.|Attribute evaluation never depends on a parse tree.|A synthesized attribute can only be supplied by the lexer.",
    ),
    _topic(
        "CD",
        "Runtime Environments",
        "runtime-environments",
        "activation_memory",
        "An activation record can store a return address.|Recursive calls require distinct active records.|Static links can support access to lexically enclosing scopes.",
        "All recursive calls share one set of local variables.|A return address is stored only in source code.|Stack allocation can never support procedure calls.",
    ),
    _topic(
        "CD",
        "Intermediate Code Generation",
        "intermediate-code-generation",
        "tac_instructions",
        "Three-address code limits the number of explicit operands per instruction.|Temporaries can name intermediate expression results.|An abstract syntax tree omits some concrete grammar detail.",
        "Three-address code requires exactly three machine registers.|Intermediate code is always target-machine binary.|A temporary can never be reused.",
    ),
    _topic(
        "CD",
        "Code Optimization and Data-Flow Analysis",
        "code-optimization-and-data-flow-analysis",
        "common_subexpressions",
        "A live variable may be used along a future path before redefinition.|Common-subexpression elimination can avoid repeated computation.|Constant propagation substitutes known constant values.",
        "Dead-code elimination must preserve every unreachable assignment.|Liveness is a forward-only property by definition.|Optimization may change the observable program result.",
    ),
    _topic(
        "OS",
        "System Calls",
        "system-calls",
        "syscall_transitions",
        "A system call transfers control to a privileged kernel routine.|A read system call can block while waiting for I/O.|User programs request protected services through the system-call interface.",
        "A system call executes entirely without entering kernel mode.|Every library call is necessarily a system call.|User code may directly execute every privileged instruction.",
    ),
    _topic(
        "OS",
        "Processes and Threads",
        "processes-and-threads",
        "thread_stacks",
        "Threads in one process share an address space.|Each thread needs its own execution stack.|A context switch can save and restore processor state.",
        "All processes share one virtual address space by default.|Threads of a process share one stack.|A blocked process must be running simultaneously.",
    ),
    _topic(
        "OS",
        "Concurrency and Synchronization",
        "concurrency-and-synchronization",
        "semaphore_value",
        "Mutual exclusion prevents simultaneous execution of a protected critical section.|A semaphore wait can block a caller.|A race outcome can depend on instruction interleaving.",
        "A mutex allows every thread to enter the critical section together.|Synchronization is unnecessary for shared writable state.|A semaphore signal must always block.",
    ),
    _topic(
        "OS",
        "Deadlocks",
        "deadlocks",
        "deadlock_available",
        "Mutual exclusion is one Coffman condition.|Banker's algorithm is a deadlock-avoidance method.|A cycle is sufficient for deadlock when every resource type has one instance.",
        "Preempting every resource preserves the no-preemption condition.|Deadlock requires no waiting process.|A resource-allocation cycle is never relevant.",
    ),
    _topic(
        "OS",
        "CPU and I/O Scheduling",
        "cpu-and-i-o-scheduling",
        "round_robin_slices",
        "Round robin uses a time quantum.|Shortest-job-first minimizes average waiting time when burst lengths are known.|Preemptive scheduling can interrupt a running process.",
        "FCFS is always preemptive.|Round robin with a finite quantum runs one process to completion before another.|Disk scheduling never considers head movement.",
    ),
    _topic(
        "OS",
        "Memory and Virtual Memory",
        "memory-and-virtual-memory",
        "page_count",
        "Paging divides virtual memory into fixed-size pages.|A page fault occurs when a referenced page is absent from memory.|A TLB caches address translations.",
        "Paging requires every process to occupy contiguous physical memory.|A larger page size always removes internal fragmentation.|A TLB stores file contents.",
    ),
    _topic(
        "OS",
        "File Systems",
        "file-systems",
        "file_blocks",
        "Indexed allocation supports direct access through an index block.|A directory maps names to file metadata references.|Free-space management tracks unallocated blocks.",
        "Contiguous allocation can never fragment free space.|A file descriptor is the file's textual contents.|Every directory must be stored outside the file system.",
    ),
    _topic(
        "DBMS",
        "ER Model",
        "er-model",
        "er_relations",
        "An entity set contains similar entities.|A key distinguishes entities in an entity set.|A many-to-many relationship is normally mapped to its own relation.",
        "Every relationship is one-to-one.|A weak entity has a full key independent of its owner.|An attribute can never be composite.",
    ),
    _topic(
        "DBMS",
        "Relational Model",
        "relational-model",
        "cartesian_product",
        "Selection filters tuples.|Projection chooses attributes.|A Cartesian product pairs every tuple of one relation with every tuple of the other.",
        "Projection always increases the number of attributes.|Selection changes only the relation schema, never its tuples.|A relation permits duplicate tuples under the mathematical model.",
    ),
    _topic(
        "DBMS",
        "SQL",
        "sql",
        "sql_groups",
        "WHERE filters rows before grouping.|HAVING can filter aggregate groups.|COUNT(*) counts rows in a group.",
        "HAVING must execute before WHERE.|GROUP BY always produces one group per input row.|A subquery can never appear in a WHERE clause.",
    ),
    _topic(
        "DBMS",
        "Integrity Constraints",
        "integrity-constraints",
        "key_assignments",
        "A primary key value is unique and non-null.|A foreign key references a candidate key value or may be null when permitted.|A domain constraint restricts allowable attribute values.",
        "A relation can contain duplicate primary-key values.|Every foreign-key value must be different from every referenced value.|Entity integrity permits a null primary key.",
    ),
    _topic(
        "DBMS",
        "Normal Forms",
        "normal-forms",
        "closure_size",
        "BCNF requires every nontrivial determinant to be a superkey.|A lossless decomposition preserves all original tuples under join.|A functional dependency X -> Y holds when equal X values imply equal Y values.",
        "Every 3NF relation violates 2NF.|BCNF is weaker than 3NF.|A lossy decomposition is required for normalization.",
    ),
    _topic(
        "DBMS",
        "File Organization and Indexing",
        "file-organization-and-indexing",
        "bplus_capacity",
        "B+ tree leaves contain data entries and are linked for range scans.|Hash indexes are effective for equality lookup.|A dense index has an entry for every search-key value or record as defined by the organization.",
        "A B+ tree stores all data records only in internal nodes.|Hashing preserves key order for range scans.|The B+ tree root must always be at least half full.",
    ),
    _topic(
        "DBMS",
        "Transactions and Concurrency Control",
        "transactions-and-concurrency-control",
        "conflict_pairs",
        "An acyclic precedence graph characterizes conflict serializability.|Two-phase locking has a growing phase and a shrinking phase.|Atomicity requires all-or-nothing transaction effects.",
        "Every interleaved schedule is conflict serializable.|Shared locks conflict with all other shared locks.|A committed transaction may be silently half applied under atomicity.",
    ),
    _topic(
        "CN",
        "Layering and Switching",
        "layering-and-switching",
        "encapsulation_bytes",
        "Layering separates protocol responsibilities.|Packet switching statistically multiplexes links.|Encapsulation adds protocol control information around payload.",
        "Circuit switching never reserves resources.|Every layer directly interprets every higher-layer header.|Packet switching gives every flow a dedicated physical circuit.",
    ),
    _topic(
        "CN",
        "Data Link Layer",
        "data-link-layer",
        "crc_bits",
        "A degree-r CRC generator appends r check bits.|Ethernet uses frames.|A bridge forwards using link-layer addresses.",
        "CRC can correct every possible error pattern.|A bridge routes using application URLs.|Framing is unnecessary on a shared link.",
    ),
    _topic(
        "CN",
        "Routing Algorithms",
        "routing-algorithms",
        "path_cost",
        "Link-state routing distributes link information.|Distance-vector routing exchanges distance estimates with neighbors.|A shortest-path cost is the sum of its link costs for additive metrics.",
        "Flooding sends a packet on no outgoing links.|Distance-vector routing has a complete global topology map at every update.|A shortest path must contain the greatest number of hops.",
    ),
    _topic(
        "CN",
        "IPv4 Addressing and Forwarding",
        "ipv4-addressing-and-forwarding",
        "ipv4_hosts",
        "CIDR prefixes express network-prefix length.|Longest-prefix matching chooses the most specific route.|ARP resolves an IPv4 address to a link-layer address on a local network.",
        "A /24 prefix leaves 24 host bits.|Routers normally forward using the source address only.|NAT never changes an IP header checksum.",
    ),
    _topic(
        "CN",
        "Transport Layer",
        "transport-layer",
        "tcp_window",
        "TCP provides an ordered byte stream.|UDP does not establish a connection before sending.|Flow control protects a receiver from an overly fast sender.",
        "TCP preserves application message boundaries.|UDP guarantees retransmission of lost datagrams.|A TCP acknowledgement consumes one sequence number solely because it is an ACK.",
    ),
    _topic(
        "CN",
        "Application Layer",
        "application-layer",
        "http_requests",
        "DNS maps names to resource records.|HTTP is an application-layer protocol.|SMTP is used to transfer email.",
        "ARP resolves Internet domain names.|HTTP requires UDP in every version.|DNS has no caching.",
    ),
    _topic(
        "CN",
        "Network Performance",
        "network-performance",
        "transmission_delay",
        "Transmission delay equals packet bits divided by link bit rate.|Propagation delay depends on distance and signal speed.|Throughput cannot exceed the bottleneck-link rate.",
        "Transmission delay is independent of packet length.|Propagation delay equals packet size divided by bandwidth.|End-to-end throughput always exceeds every link rate.",
    ),
    _topic(
        "GA",
        "Verbal Aptitude",
        "verbal-aptitude",
        "word_count",
        "Subject and finite verb should agree in number.|A contrast connector should preserve the logical relation between clauses.|Context can determine the intended meaning of a word.",
        "Every sentence fragment is grammatically complete.|A singular subject always takes a plural finite verb.|Punctuation never affects meaning.",
    ),
    _topic(
        "GA",
        "Quantitative Aptitude",
        "quantitative-aptitude",
        "percentage_change",
        "A percentage change is measured relative to the original value.|The mean is the sum divided by the number of observations.|A ratio is unchanged when both terms are multiplied by the same nonzero factor.",
        "A 20 percent increase followed by a 20 percent decrease restores the original value.|The median is always equal to the mean.|Dividing one term of a ratio by two leaves the ratio unchanged.",
    ),
    _topic(
        "GA",
        "Analytical Aptitude",
        "analytical-aptitude",
        "arrangements",
        "A valid deduction must hold in every arrangement satisfying the premises.|Contradiction can eliminate a candidate arrangement.|A bijection pairs each object with exactly one counterpart.",
        "One supporting example proves a universal conclusion.|Ignoring a premise cannot change the solution set.|n distinct objects have n possible linear orders.",
    ),
    _topic(
        "GA",
        "Spatial Aptitude",
        "spatial-aptitude",
        "painted_cubes",
        "A rigid rotation preserves distances.|Opposite faces of a cube never share an edge.|Cutting each cube edge into n equal parts creates n^3 small cubes.",
        "A mirror reflection is always a rotation.|All six faces of a cube meet at one vertex.|Cutting each edge into n parts creates 6n cubes.",
    ),
)


SUBJECT_BY_CODE = {subject.code: subject for subject in SUBJECTS}
TOPICS_BY_COURSE: dict[str, list[TopicSpec]] = {
    subject.code: [topic for topic in TOPICS if topic.course == subject.code]
    for subject in SUBJECTS
}


def _number(value: float) -> int | float:
    rounded = round(value, 4)
    return int(rounded) if float(rounded).is_integer() else rounded


def numeric_problem(kind: str, serial: int) -> tuple[str, int | float, str]:
    """Return a topic-specific, derived numerical problem and explanation."""

    n = serial + 1
    if kind == "complete_graph":
        vertices = 5 + n
        answer = vertices * (vertices - 1) // 2
        return (
            f"A simple complete graph has {vertices} vertices. How many edges does it contain?",
            answer,
            f"Every unordered vertex pair is an edge, so C({vertices}, 2) = {vertices}*{vertices - 1}/2 = {answer}.",
        )
    if kind == "triangular_determinant":
        a, b, c = 2 + n, 3 + (n % 5), 4 + (n % 7)
        answer = a * b * c
        return (
            f"An upper triangular 3 x 3 matrix has diagonal entries {a}, {b}, and {c}. Find its determinant.",
            answer,
            f"The determinant of a triangular matrix is the diagonal product: {a}*{b}*{c} = {answer}.",
        )
    if kind == "quadratic_derivative":
        a, b, x = 1 + (n % 7), 2 + n, 1 + (n % 6)
        answer = 2 * a * x + b
        return (
            f"For f(x) = {a}x^2 + {b}x + 3, find f'({x}).",
            answer,
            f"f'(x) = {2 * a}x + {b}; substituting x={x} gives {answer}.",
        )
    if kind == "binomial_expectation":
        trials, numerator = 8 + n, 2 + (n % 5)
        denominator = 10
        answer = _number(trials * numerator / denominator)
        return (
            f"X is binomial with n={trials} and p={numerator}/10. Find E[X].",
            answer,
            f"For a binomial variable E[X]=np={trials}*{numerator}/10={answer}.",
        )
    if kind == "boolean_minterms":
        variables, ones = 4 + n, 1 + (n % 3)
        answer = math.comb(variables, ones)
        return (
            f"A Boolean function of {variables} variables is 1 exactly when {ones} inputs are 1. How many minterms make it 1?",
            answer,
            f"Choose the {ones} asserted variables: C({variables}, {ones}) = {answer}.",
        )
    if kind == "mux_inputs":
        selects = 2 + n
        answer = 2**selects
        return (
            f"How many data inputs does a multiplexer with {selects} select lines require?",
            answer,
            f"Each select word chooses one input, so the count is 2^{selects} = {answer}.",
        )
    if kind == "counter_bits":
        states = 5 + 3 * n
        answer = math.ceil(math.log2(states))
        return (
            f"What is the minimum number of flip-flops for a counter with {states} distinct states?",
            answer,
            f"Choose the least k with 2^k >= {states}; k = ceil(log2({states})) = {answer}.",
        )
    if kind == "unsigned_values":
        bits = 4 + n
        answer = 2**bits
        return (
            f"How many distinct values can a {bits}-bit unsigned word represent?",
            answer,
            f"There are two choices per bit, giving 2^{bits} = {answer} patterns.",
        )
    if kind == "effective_address":
        base, displacement = 1000 + 64 * n, 12 + 4 * n
        answer = base + displacement
        return (
            f"A base register contains address {base}; an instruction uses displacement {displacement}. Find the base-plus-offset effective address.",
            answer,
            f"Effective address = base + displacement = {base} + {displacement} = {answer}.",
        )
    if kind == "alu_result":
        left, right, shift = 17 + n, 3 + (n % 9), 1 + (n % 3)
        answer = (left + right) << shift
        return (
            f"An ALU first adds {left} and {right}, then logically shifts the result left by {shift} bit(s). Find the unsigned result.",
            answer,
            f"The sum is {left + right}; left shifting by {shift} multiplies by 2^{shift}, giving {answer}.",
        )
    if kind == "pipeline_cycles":
        stages, instructions, stalls = 4 + (n % 4), 8 + n, n % 3
        answer = stages + instructions - 1 + stalls
        return (
            f"A {stages}-stage pipeline executes {instructions} instructions and incurs {stalls} total stall cycle(s). How many cycles are required?",
            answer,
            f"Ideal cycles are {stages}+{instructions}-1; adding {stalls} stalls gives {answer}.",
        )
    if kind == "amat":
        hit, miss_rate, penalty = 1 + (n % 4), 5 * (1 + n % 5), 20 + 5 * n
        answer = _number(hit + (miss_rate / 100) * penalty)
        return (
            f"A cache hit takes {hit} ns, miss rate is {miss_rate}%, and additional miss penalty is {penalty} ns. Find AMAT in ns.",
            answer,
            f"AMAT = {hit} + ({miss_rate}/100)*{penalty} = {answer} ns.",
        )
    if kind == "polling_time":
        polls, cycles = 20 + 5 * n, 3 + (n % 5)
        answer = polls * cycles
        return (
            f"A programmed-I/O loop performs {polls} status polls, each costing {cycles} CPU cycles. Find total polling cycles.",
            answer,
            f"Total polling cost is {polls}*{cycles} = {answer} cycles.",
        )
    if kind == "dma_time":
        words, cycles = 32 + 8 * n, 2 + (n % 4)
        answer = words * cycles
        return (
            f"A DMA controller transfers {words} words and occupies the bus for {cycles} cycles per word. Find occupied bus cycles.",
            answer,
            f"The transfer occupies {words}*{cycles} = {answer} bus cycles.",
        )
    if kind == "pointer_address":
        base, index, size = 1000 + 128 * n, 2 + n, (1, 2, 4, 8)[n % 4]
        answer = base + index * size
        return (
            f"In C, an array starts at byte address {base}; each element is {size} byte(s). Find the address of element a[{index}].",
            answer,
            f"Row address arithmetic gives {base}+{index}*{size} = {answer}.",
        )
    if kind == "recursive_calls":
        depth = 4 + n
        answer = depth + 1
        return (
            f"A function F(k) makes exactly one call to F(k-1) for k>0 and stops at F(0). Including the base call, how many calls arise from F({depth})?",
            answer,
            f"The calls are F({depth}), F({depth - 1}), ..., F(0): {depth}+1 = {answer}.",
        )
    if kind == "array_address":
        rows, columns, row, col, size = 4 + n, 5 + n, n % (4 + n), (2 * n) % (5 + n), 4
        index = row * columns + col
        answer = 2000 + size * index
        return (
            f"A row-major int A[{rows}][{columns}] starts at address 2000 with 4-byte elements. Find address A[{row}][{col}].",
            answer,
            f"Linear index = {row}*{columns}+{col}={index}; address = 2000+4*{index}={answer}.",
        )
    if kind == "queue_capacity":
        slots = 8 + n
        answer = slots - 1
        return (
            f"An array circular queue has {slots} slots and uses one empty slot to distinguish full from empty. What is its usable capacity?",
            answer,
            f"One slot is reserved, so usable capacity is {slots}-1={answer}.",
        )
    if kind == "list_traversal":
        nodes, step_cost = 10 + 2 * n, 2 + (n % 4)
        answer = (nodes - 1) * step_cost
        return (
            f"Traversing a singly linked list of {nodes} nodes follows {nodes - 1} next links, each costing {step_cost} time units. Find total link-following cost.",
            answer,
            f"There are {nodes}-1 links, so cost = {nodes - 1}*{step_cost}={answer}.",
        )
    if kind == "perfect_tree_nodes":
        height = 2 + n
        answer = 2 ** (height + 1) - 1
        return (
            f"A perfect binary tree has root at height 0 and overall height {height}. How many nodes does it have?",
            answer,
            f"Nodes = 1+2+...+2^{height} = 2^{height + 1}-1 = {answer}.",
        )
    if kind == "heap_parent":
        index = 8 + 3 * n
        answer = index // 2
        return (
            f"In a 1-indexed binary heap, what is the parent index of the node at index {index}?",
            answer,
            f"For a 1-indexed heap, parent(i)=floor(i/2), so floor({index}/2)={answer}.",
        )
    if kind == "adjacency_entries":
        edges = 7 + 3 * n
        answer = 2 * edges
        return (
            f"An undirected simple graph has {edges} edges. How many neighbor entries occur across all ordinary adjacency lists?",
            answer,
            f"Each edge is listed at both endpoints, giving 2*{edges}={answer} entries.",
        )
    if kind == "binary_search":
        exponent = 4 + n
        items = 2**exponent
        answer = exponent
        return (
            f"A binary-search candidate interval has {items} items. How many exact halvings reduce it to one item?",
            answer,
            f"{items}=2^{exponent}; therefore {exponent} halvings leave one candidate.",
        )
    if kind == "nested_loop_ops":
        size = 5 + n
        answer = size * (size + 1) // 2
        return (
            f"A nested loop executes its inner statement i times for i=1 through {size}. How many total executions occur?",
            answer,
            f"The count is 1+...+{size}={size}*{size + 1}/2={answer}.",
        )
    if kind == "merge_levels":
        exponent = 3 + n
        items = 2**exponent
        answer = exponent
        return (
            f"Merge sort is run on {items} items. How many halving levels occur before singleton subarrays?",
            answer,
            f"Because {items}=2^{exponent}, log2({items})={answer} halving levels occur.",
        )
    if kind == "mst_edges":
        vertices = 5 + n
        answer = vertices - 1
        return (
            f"A connected graph has {vertices} vertices. How many edges are in any spanning tree?",
            answer,
            f"Every tree on {vertices} vertices contains {vertices}-1={answer} edges.",
        )
    if kind == "dp_cells":
        rows, cols = 3 + n, 5 + (n % 7)
        answer = (rows + 1) * (cols + 1)
        return (
            f"An LCS table includes row/column zero for strings of lengths {rows} and {cols}. How many DP cells are stored?",
            answer,
            f"The table dimensions are ({rows}+1) by ({cols}+1), giving {answer} cells.",
        )
    if kind == "bfs_scans":
        edges = 8 + 4 * n
        answer = 2 * edges
        return (
            f"BFS scans adjacency lists of an undirected graph with {edges} edges. How many edge entries are examined in total?",
            answer,
            f"Each undirected edge occurs in two adjacency lists, so {answer} entries are scanned.",
        )
    if kind == "dfa_subsets":
        nfa_states = 3 + n
        answer = 2**nfa_states
        return (
            f"Subset construction is applied to an NFA with {nfa_states} states. What is the maximum number of DFA subset states?",
            answer,
            f"There are 2^{nfa_states} subsets, hence at most {answer} DFA states.",
        )
    if kind == "parse_tree_nodes":
        leaves = 3 + n
        answer = 2 * leaves - 1
        return (
            f"A full binary parse tree has {leaves} terminal leaves. How many total nodes does it contain?",
            answer,
            f"A full binary tree with L leaves has L-1 internal nodes, so total = 2L-1 = {answer}.",
        )
    if kind == "pda_stack":
        symbols = 4 + n
        answer = symbols
        return (
            f"A PDA for a^k b^k pushes one marker per a. What is its maximum marker count on input a^{symbols}b^{symbols}?",
            answer,
            f"It pushes once for each of the {symbols} leading a symbols, reaching {answer} markers.",
        )
    if kind == "pumping_length":
        pumping = 5 + n
        answer = pumping
        return (
            f"A regular-language pumping lemma supplies pumping length p={pumping}. What is the minimum string length to which its decomposition guarantee applies?",
            answer,
            f"The guarantee applies to every string whose length is at least p, so the minimum is {answer}.",
        )
    if kind == "tm_steps":
        symbols = 5 + n
        answer = symbols
        return (
            f"A Turing-machine head initially scans the leftmost symbol of a "
            f"{symbols}-symbol unary input. It moves right once per step. "
            f"How many head moves are required before it first scans the "
            f"blank immediately to the right of the input?",
            answer,
            f"Starting on the first input symbol, move {symbols - 1} times to "
            f"reach the last symbol and once more to reach the blank: "
            f"{symbols - 1}+1={answer}.",
        )
    if kind == "token_count":
        identifiers, operators, literals = 2 + n, 1 + (n % 4), 2 + (n % 5)
        answer = identifiers + operators + literals
        return (
            f"A source fragment contains {identifiers} identifier lexemes, {operators} operator lexemes, and {literals} numeric literals, with whitespace ignored. How many tokens are emitted?",
            answer,
            f"Each listed lexeme yields one token: {identifiers}+{operators}+{literals}={answer}.",
        )
    if kind == "parse_actions":
        tokens = 5 + n
        answer = 2 * tokens - 1
        return (
            f"A simple shift-reduce trace shifts {tokens} tokens and performs {tokens - 1} reductions. How many shift/reduce actions occur?",
            answer,
            f"Actions = {tokens} shifts + {tokens - 1} reductions = {answer}.",
        )
    if kind == "attribute_evaluations":
        leaves = 3 + n
        internal = leaves - 1
        answer = leaves + internal
        return (
            f"An attributed full binary expression tree has {leaves} leaves and one synthesized-value evaluation at every node. How many evaluations occur?",
            answer,
            f"The tree has {leaves}+({leaves}-1)={answer} nodes, hence {answer} evaluations.",
        )
    if kind == "activation_memory":
        depth, record_size = 3 + n, 16 + 8 * (n % 5)
        answer = depth * record_size
        return (
            f"At maximum recursion depth {depth}, every activation record occupies {record_size} bytes. Find active-record storage in bytes.",
            answer,
            f"Storage = depth*record size = {depth}*{record_size}={answer} bytes.",
        )
    if kind == "tac_instructions":
        operators = 3 + n
        answer = operators
        return (
            f"An expression tree has {operators} binary operator nodes. With one three-address instruction per operator, how many instructions are emitted?",
            answer,
            f"Each operator produces one instruction, giving {answer} instructions.",
        )
    if kind == "common_subexpressions":
        repeats = 2 + n
        answer = repeats - 1
        return (
            f"The same available expression is computed {repeats} times without operand redefinition. How many computations can common-subexpression elimination remove?",
            answer,
            f"Keep the first computation and replace the remaining {repeats}-1={answer}.",
        )
    if kind == "syscall_transitions":
        calls = 3 + n
        answer = 2 * calls
        return (
            f"A process makes {calls} non-nested system calls. Counting one user-to-kernel and one kernel-to-user transition per call, how many mode transitions occur?",
            answer,
            f"Each call causes two transitions, so 2*{calls}={answer}.",
        )
    if kind == "thread_stacks":
        threads, stack_kib = 2 + n, 8 + 4 * (n % 6)
        answer = threads * stack_kib
        return (
            f"A process has {threads} threads, each with a private {stack_kib} KiB stack. Find total private-stack storage in KiB.",
            answer,
            f"Total stack storage = {threads}*{stack_kib}={answer} KiB.",
        )
    if kind == "semaphore_value":
        initial, waits, signals = 3 + (n % 5), 1 + (n % 3), 4 + n
        answer = initial - waits + signals
        return (
            f"A counting semaphore starts at {initial}. After {waits} successful wait operations and {signals} signal operations, with no blocking, find its value.",
            answer,
            f"A successful wait decrements and a signal increments, so the value is {initial}-{waits}+{signals}={answer}.",
        )
    if kind == "deadlock_available":
        total, allocated = 10 + 3 * n, 4 + 2 * n
        answer = total - allocated
        return (
            f"A resource type has {total} instances, of which {allocated} are allocated. How many instances are available?",
            answer,
            f"Available = total - allocated = {total}-{allocated}={answer}.",
        )
    if kind == "round_robin_slices":
        burst, quantum = 20 + 3 * n, 3 + (n % 5)
        answer = math.ceil(burst / quantum)
        return (
            f"A process has CPU burst {burst} ms under round robin with quantum {quantum} ms. How many CPU slices does it need if it never blocks?",
            answer,
            f"Slices = ceil({burst}/{quantum}) = {answer}.",
        )
    if kind == "page_count":
        size_kib, page_kib = 50 + 7 * n, 4 * (2 ** (n % 3))
        answer = math.ceil(size_kib / page_kib)
        return (
            f"A segment of {size_kib} KiB is paged with {page_kib} KiB pages. How many pages are required?",
            answer,
            f"Pages = ceil({size_kib}/{page_kib}) = {answer}.",
        )
    if kind == "file_blocks":
        bytes_count, block_size = 10000 + 137 * n, 1024
        answer = math.ceil(bytes_count / block_size)
        return (
            f"A file contains {bytes_count} bytes and data blocks hold {block_size} bytes. Ignoring metadata blocks, how many data blocks are required?",
            answer,
            f"Blocks = ceil({bytes_count}/{block_size}) = {answer}.",
        )
    if kind == "er_relations":
        entity_sets, many_many = 2 + n, 1 + (n % 4)
        answer = entity_sets + many_many
        return (
            f"An ER design has {entity_sets} strong entity sets and {many_many} many-to-many relationships, each mapped separately. How many base relations result under this simplified mapping?",
            answer,
            f"One relation per entity set and per many-to-many relationship gives {entity_sets}+{many_many}={answer}.",
        )
    if kind == "cartesian_product":
        left, right = 3 + n, 4 + 2 * n
        answer = left * right
        return (
            f"Relations R and S contain {left} and {right} tuples. If all pairs are distinct, how many tuples are in R cross S?",
            answer,
            f"Cartesian product cardinality is {left}*{right}={answer}.",
        )
    if kind == "sql_groups":
        rows, group_size = 24 + 6 * n, 2 + (n % 5)
        rows = rows - (rows % group_size)
        answer = rows // group_size
        return (
            f"A GROUP BY query processes {rows} rows equally divided into groups of {group_size} rows. How many groups are produced?",
            answer,
            f"Number of groups = {rows}/{group_size} = {answer}.",
        )
    if kind == "key_assignments":
        digits = 3 + (n % 6)
        reserved = n
        answer = 10**digits - reserved
        return (
            f"A candidate key is a fixed string of {digits} decimal digits with leading zeroes allowed. If {reserved} values are reserved, how many assignable key values remain?",
            answer,
            f"There are 10^{digits} raw strings; after removing {reserved} reserved values, {answer} remain.",
        )
    if kind == "closure_size":
        initial, additions = 1 + (n % 4), 2 + n
        answer = initial + additions
        return (
            f"An attribute-closure computation starts with {initial} attributes and functional dependencies add {additions} distinct new attributes. What is the final closure size?",
            answer,
            f"No attribute is added twice, so closure size = {initial}+{additions}={answer}.",
        )
    if kind == "bplus_capacity":
        leaves, entries = 3 + n, 20 + 5 * (n % 7)
        answer = leaves * entries
        return (
            f"A B+ tree has {leaves} leaf nodes, each currently holding {entries} data entries. How many data entries are stored in the leaves?",
            answer,
            f"Leaf entries = {leaves}*{entries}={answer}.",
        )
    if kind == "conflict_pairs":
        reads, writes = 2 + n, 1 + (n % 5)
        answer = reads * writes
        return (
            f"Transaction T1 performs {reads} reads of item X and T2 performs {writes} writes of X, with every read ordered against every write. How many cross-transaction read-write operation pairs conflict?",
            answer,
            f"Every T1 read conflicts with every T2 write: {reads}*{writes}={answer}.",
        )
    if kind == "encapsulation_bytes":
        payload, layers, header = 500 + 20 * n, 2 + (n % 4), 12 + (n % 5)
        answer = payload + layers * header
        return (
            f"A {payload}-byte payload crosses {layers} layers, each adding a {header}-byte header. No trailer is added. Find transmitted bytes.",
            answer,
            f"Total = payload + layers*header = {payload}+{layers}*{header}={answer}.",
        )
    if kind == "crc_bits":
        degree = 3 + n
        answer = degree
        return (
            f"A CRC generator polynomial has degree {degree}. How many CRC check bits are appended?",
            answer,
            f"A degree-r generator produces an r-bit remainder, so {answer} bits are appended.",
        )
    if kind == "path_cost":
        a, b, c = 2 + n, 3 + (n % 7), 4 + (n % 5)
        answer = a + b + c
        return (
            f"A route uses three links of costs {a}, {b}, and {c}. With an additive metric, what is the route cost?",
            answer,
            f"Additive path cost = {a}+{b}+{c}={answer}.",
        )
    if kind == "ipv4_hosts":
        prefix = 20 + (n % 9)
        subnets = n
        per_subnet = 2 ** (32 - prefix) - 2
        answer = subnets * per_subnet
        return (
            f"An allocation contains {subnets} separate conventional IPv4 /{prefix} subnet(s). Excluding each network and directed-broadcast address, how many usable host addresses exist in total?",
            answer,
            f"Each subnet has 2^{32 - prefix}-2={per_subnet} usable addresses; {subnets} subnet(s) provide {answer}.",
        )
    if kind == "tcp_window":
        segments, segment_bytes = 4 + n, 500 + 100 * (n % 8)
        answer = segments * segment_bytes
        return (
            f"A TCP sender may have {segments} full segments outstanding, each carrying {segment_bytes} payload bytes. Find the payload window in bytes.",
            answer,
            f"Window payload = {segments}*{segment_bytes}={answer} bytes.",
        )
    if kind == "http_requests":
        objects = 3 + n
        answer = objects + 1
        return (
            f"An uncached page consists of one base HTML document and {objects} embedded objects, with one HTTP GET per object. How many GET requests are sent?",
            answer,
            f"One request fetches the base document and {objects} fetch embedded objects: {answer}.",
        )
    if kind == "transmission_delay":
        kib, mbps = 1 + n, 1 + (n % 10)
        bits = kib * 1024 * 8
        answer = _number(bits / (mbps * 1_000_000) * 1000)
        return (
            f"A {kib} KiB packet is serialized on a {mbps} Mbps link. Find transmission delay in milliseconds.",
            answer,
            f"Delay = ({kib}*1024*8)/({mbps}*10^6) seconds = {answer} ms.",
        )
    if kind == "word_count":
        sentences, words = 2 + n, 5 + (n % 9)
        answer = sentences * words
        return (
            f"A passage has {sentences} sentences with exactly {words} words each. How many words does it contain?",
            answer,
            f"Total words = {sentences}*{words}={answer}.",
        )
    if kind == "percentage_change":
        original, percent = 50 + 10 * n, 5 * (1 + n % 8)
        answer = _number(original * (1 + percent / 100))
        return (
            f"A quantity is {original} and increases by {percent}%. Find the new value.",
            answer,
            f"New value = {original}*(1+{percent}/100)={answer}.",
        )
    if kind == "arrangements":
        objects = 4 + n
        answer = objects * (objects - 1)
        return (
            f"From {objects} distinct objects, how many ordered selections of two different objects are possible?",
            answer,
            f"There are {objects} choices first and {objects - 1} second, giving {answer} ordered selections.",
        )
    if kind == "painted_cubes":
        divisions = 2 + n
        answer = divisions**3
        return (
            f"Each edge of a cube is divided into {divisions} equal parts and all grid cuts are made. How many small cubes result?",
            answer,
            f"The three dimensions each contribute a factor {divisions}, so the count is {divisions}^3={answer}.",
        )
    raise KeyError(f"Unknown numeric kind: {kind}")


def _option_value(value: int | float) -> str:
    if isinstance(value, float) and not value.is_integer():
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return str(int(value))


def _numeric_options(
    answer: int | float, rotation: int
) -> tuple[list[dict[str, str]], str]:
    delta: int | float = 1 if isinstance(answer, int) or float(answer).is_integer() else 0.1
    candidates: list[int | float] = [
        _number(answer),
        _number(answer + delta),
        _number(answer - delta),
        _number(answer + 2 * delta),
    ]
    unique: list[int | float] = []
    for candidate in candidates:
        if candidate not in unique:
            unique.append(candidate)
    while len(unique) < 4:
        unique.append(_number(answer + (len(unique) + 2) * delta))
    rotated = unique[rotation:] + unique[:rotation]
    identifiers = ("A", "B", "C", "D")
    options = [
        {"id": identifier, "text": _option_value(value)}
        for identifier, value in zip(identifiers, rotated, strict=True)
    ]
    correct_index = rotated.index(_number(answer))
    return options, identifiers[correct_index]


def _original_question(
    subject: SubjectSpec,
    topic: TopicSpec,
    local_index: int,
    question_type: str,
) -> dict[str, Any]:
    serial_for_type = local_index // 3
    marks = 1 if (local_index + len(topic.slug)) % 2 == 0 else 2
    difficulty = ("easy", "medium", "hard")[(local_index // 3) % 3]
    base_id = (
        f"gate27-original-{subject.code.lower()}-{topic.slug}-"
        f"{question_type}-{serial_for_type + 1:03d}"
    )
    common: dict[str, Any] = {
        "external_id": base_id,
        "course": subject.code,
        "subject_slug": subject.slug,
        "topic": topic.name,
        "topic_slug": topic.slug,
        "question_type": question_type,
        "difficulty": difficulty,
        "marks": marks,
        "numerical_tolerance": 0.0001,
        "source_kind": "original",
        "tags": [
            "gate-2027",
            "syllabus-aligned",
            topic.slug,
            "deterministic-generated",
        ],
    }
    if question_type in {"mcq", "nat"}:
        # MCQ and NAT records use disjoint parameter serials. They therefore
        # exercise the same syllabus method without duplicating the same
        # numerical problem in two answer formats.
        problem_serial = serial_for_type * 2 + (1 if question_type == "nat" else 0)
        stem, answer, explanation = numeric_problem(
            topic.numeric_kind,
            problem_serial,
        )
        if question_type == "mcq":
            options, correct = _numeric_options(answer, problem_serial % 4)
            common.update(
                {
                    "question": f"{stem} Choose the correct value.",
                    "options": options,
                    "correct_answer": correct,
                    "explanation": explanation,
                }
            )
        else:
            common.update(
                {
                    "question": f"{stem} Enter the numerical answer.",
                    "options": [],
                    "correct_answer": answer,
                    "explanation": explanation,
                }
            )
        return common

    # Expand the six audited atomic facts into a larger deterministic claim
    # pool. A conjunction of two true statements is true; a conjunction with
    # one known false statement is false. This keeps every option auditable
    # while providing enough distinct semantic sets for all course variants.
    true_claims = topic.truths + tuple(
        f"Both statements hold: (i) {left} (ii) {right}"
        for left, right in combinations(topic.truths, 2)
    )
    false_claims = topic.falsehoods + tuple(
        f"Both statements hold: (i) {true_statement} (ii) {false_statement}"
        for true_statement in topic.truths
        for false_statement in topic.falsehoods
    )
    true_pairs = tuple(combinations(true_claims, 2))
    false_pairs = tuple(combinations(false_claims, 2))
    chosen = list(true_pairs[serial_for_type % len(true_pairs)]) + list(
        false_pairs[(serial_for_type // len(true_pairs)) % len(false_pairs)]
    )
    rotation = (serial_for_type * 3 + local_index) % 4
    chosen = chosen[rotation:] + chosen[:rotation]
    option_ids = ("A", "B", "C", "D")
    true_set = set(true_claims)
    correct = [
        identifier
        for identifier, statement in zip(option_ids, chosen, strict=True)
        if statement in true_set
    ]
    common.update(
        {
            "question": (
                f"Consider the following claims about {topic.name}. "
                "Select all statements that are correct."
            ),
            "options": [
                {"id": identifier, "text": statement}
                for identifier, statement in zip(option_ids, chosen, strict=True)
            ],
            "correct_answer": correct,
            "explanation": (
                "The correct choices state standard syllabus properties: "
                + "; ".join(statement for statement in chosen if statement in true_set)
                + "."
            ),
        }
    )
    return common


def generate_originals() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for subject in SUBJECTS:
        subject_topics = TOPICS_BY_COURSE[subject.code]
        base, extra = divmod(subject.target, len(subject_topics))
        for topic_index, topic in enumerate(subject_topics):
            count = base + (1 if topic_index < extra else 0)
            # Offset the type cycle per topic, while preserving all three types
            # in every topic because every count is comfortably above three.
            for local_index in range(count):
                qtype = ("mcq", "msq", "nat")[(local_index + topic_index) % 3]
                records.append(
                    _original_question(subject, topic, local_index, qtype)
                )
    return records


def load_pyqs() -> list[dict[str, Any]]:
    if not PYQ_PATH.exists():
        return []
    payload = json.loads(PYQ_PATH.read_text(encoding="utf-8"))
    records = payload["questions"] if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise ValueError(f"{PYQ_PATH} must contain a question list")
    # The consolidated file intentionally preserves review-required OCR/image
    # records for all supplied question numbers.  Only fully verified rows are
    # eligible for the live quiz bank.
    return [
        record
        for record in records
        if record.get("safe_for_quiz", True)
        and record.get("status", "verified") == "verified"
    ]


def canonical_digest(question: dict[str, Any]) -> str:
    value = {
        "question": " ".join(str(question["question"]).lower().split()),
        "options": question.get("options", []),
    }
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def original_semantic_digest(question: dict[str, Any]) -> str:
    """Digest generated semantics without letting answer format hide reuse."""

    stem = re.sub(
        r"\s*(?:Choose the correct value\.|Enter the numerical answer\.)\s*$",
        "",
        str(question.get("question", "")),
        flags=re.IGNORECASE,
    )
    normalized_stem = " ".join(stem.lower().split())
    normalized_options = (
        sorted(
            " ".join(str(option.get("text", "")).lower().split())
            for option in question.get("options", [])
            if isinstance(option, dict)
        )
        if question.get("question_type") == "msq"
        else []
    )
    encoded = json.dumps(
        {
            "course": question.get("course"),
            "topic": question.get("topic"),
            "stem": normalized_stem,
            "options": normalized_options,
        },
        sort_keys=True,
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_manifest(
    questions: list[dict[str, Any]],
    revision_notes: list[dict[str, Any]],
    duplicate_count: int,
) -> dict[str, Any]:
    by_course: dict[str, Any] = {}
    for subject in SUBJECTS:
        records = [q for q in questions if q["course"] == subject.code]
        original_records = [
            q for q in records if q["source_kind"] == "original"
        ]
        semantic_variants = len(
            {original_semantic_digest(q) for q in original_records}
        )
        by_type = {
            kind: sum(q["question_type"] == kind for q in records)
            for kind in ("mcq", "msq", "nat")
        }
        by_marks = {
            str(mark): sum(q["marks"] == mark for q in records)
            for mark in (1, 2)
        }
        topic_counts = {
            topic.name: sum(q["topic"] == topic.name for q in records)
            for topic in TOPICS_BY_COURSE[subject.code]
        }
        by_course[subject.code] = {
            "name": subject.name,
            "count": len(records),
            "by_type": by_type,
            "by_marks": by_marks,
            "by_topic": topic_counts,
            "generated_semantic_variants": semantic_variants,
        }
    previous_year = [q for q in questions if q["source_kind"] == "previous_year"]
    years = sorted({q["source_year"] for q in previous_year if q.get("source_year")})
    return {
        "schema_version": SCHEMA_VERSION,
        "bank_version": BANK_VERSION,
        "generated_at": GENERATED_AT,
        "question_count": len(questions),
        "original_count": sum(q["source_kind"] == "original" for q in questions),
        "previous_year_count": len(previous_year),
        "previous_year_years": years,
        "duplicate_records_removed": duplicate_count,
        "generated_semantic_variants": {
            course: details["generated_semantic_variants"]
            for course, details in by_course.items()
        },
        "courses": by_course,
        "quality_gates": {
            "technical_minimum_per_course": TECHNICAL_TARGET,
            "minimum_each_type_per_technical_course": 20,
            "minimum_generated_semantic_variants_per_technical_course": (
                TECHNICAL_TARGET
            ),
            "all_syllabus_topics_present": True,
            "revision_note_count": len(revision_notes),
            "revision_notes_cover_every_syllabus_topic": (
                len(revision_notes) == len(TOPICS)
            ),
            "revision_note_minimum_key_points": 3,
            "revision_note_minimum_common_traps": 3,
            "revision_note_minimum_worked_examples_after_import": 3,
            "stable_external_ids": True,
            "derived_answers": True,
        },
        "source_notes": [
            "Original questions are deterministic topic-specific calculations or curated concept checks.",
            "Previous-year questions are included only when transcription, classification, and official-key resolution are explicit.",
            "See pyq_extraction_manifest.json for supplied-paper coverage and unresolved extraction items.",
        ],
    }


def build_revision_notes() -> list[dict[str, Any]]:
    """Build syllabus-bounded note metadata from the audited topic facts.

    The database importer combines this metadata with the canonical syllabus
    description already stored on each topic, then attaches worked examples
    from the authoritative original question bank. Keeping the facts and
    falsehoods here makes concept checks and revision notes share one source of
    truth instead of maintaining another hand-written topic map.
    """

    subject_by_code = {subject.code: subject for subject in SUBJECTS}
    notes: list[dict[str, Any]] = []
    for topic in TOPICS:
        subject = subject_by_code[topic.course]
        pattern_question, _, pattern_solution = numeric_problem(
            topic.numeric_kind,
            0,
        )
        common_traps = [
            f"Do not assume that {falsehood[0].lower()}{falsehood[1:]}"
            for falsehood in topic.falsehoods
        ]
        notes.append(
            {
                "course": subject.code,
                "subject_slug": subject.slug,
                "topic": topic.name,
                "topic_slug": topic.slug,
                "title": f"{topic.name}: GATE revision notes",
                "summary": (
                    f"{topic.name} questions depend on its defining properties "
                    "and a careful application of the standard calculation "
                    "pattern."
                ),
                "key_points": list(topic.truths),
                "common_traps": common_traps,
                "reasoning_pattern": (
                    f"Model question: {pattern_question} "
                    f"Reasoning: {pattern_solution}"
                ),
            }
        )
    return notes


def build_bank() -> tuple[dict[str, Any], dict[str, Any]]:
    candidates = load_pyqs() + generate_originals()
    seen_ids: set[str] = set()
    seen_content: set[str] = set()
    questions: list[dict[str, Any]] = []
    duplicates = 0
    for question in candidates:
        external_id = question["external_id"]
        digest = canonical_digest(question)
        if external_id in seen_ids or digest in seen_content:
            duplicates += 1
            continue
        seen_ids.add(external_id)
        seen_content.add(digest)
        questions.append(question)
    questions.sort(key=lambda item: item["external_id"])
    revision_notes = build_revision_notes()
    bank = {
        "schema_version": SCHEMA_VERSION,
        "bank_version": BANK_VERSION,
        "generated_at": GENERATED_AT,
        "revision_notes": revision_notes,
        "questions": questions,
    }
    return bank, build_manifest(questions, revision_notes, duplicates)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Run the standalone validator after generation.",
    )
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    bank, manifest = build_bank()
    OUTPUT_PATH.write_text(
        json.dumps(bank, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    REPORT_PATH.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        f"Wrote {len(bank['questions'])} questions to {OUTPUT_PATH} "
        f"(bank {BANK_VERSION})."
    )
    if args.validate:
        from validate_question_bank import validate_bank

        errors, summary = validate_bank(OUTPUT_PATH)
        print(json.dumps(summary, indent=2))
        if errors:
            for error in errors:
                print(f"ERROR: {error}")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
