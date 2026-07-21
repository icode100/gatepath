from __future__ import annotations

import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Difficulty,
    Question,
    QuestionSource,
    QuestionType,
    RevisionNote,
    Subject,
    Topic,
)


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


# This mirrors the GATE CSE syllabus hierarchy. The bank combines original
# practice material with the explicitly provenanced official PYQs below.
SYLLABUS: list[dict[str, Any]] = [
    {
        "slug": "engineering-mathematics",
        "code": "EM",
        "name": "Engineering Mathematics",
        "description": "Discrete mathematics, linear algebra, calculus, probability and statistics required for GATE CSE.",
        "topics": [
            ("Discrete Mathematics", "Propositional and first-order logic; sets, relations, functions, partial orders, lattices, monoids, groups, graphs, combinatorics, recurrences and generating functions.", "For a graph with 6 vertices of degree 2, use the handshaking lemma to obtain 6 edges."),
            ("Linear Algebra", "Matrices, determinants, systems of linear equations, eigenvalues and eigenvectors, and LU decomposition.", "For a triangular matrix, read eigenvalues directly from its diagonal entries."),
            ("Calculus", "Limits, continuity, differentiability, maxima and minima, mean value theorem, and integration.", "Differentiate a function, find stationary points, and compare endpoint values to locate an absolute maximum."),
            ("Probability and Statistics", "Random variables; uniform, normal, exponential, Poisson and binomial distributions; descriptive statistics; conditional probability and Bayes theorem.", "Apply Bayes theorem by multiplying each prior probability by its likelihood and then normalizing."),
        ],
    },
    {
        "slug": "digital-logic",
        "code": "DL",
        "name": "Digital Logic",
        "description": "Boolean algebra, logic circuits, number representation and computer arithmetic.",
        "topics": [
            ("Boolean Algebra", "Boolean identities, truth tables, canonical forms and logic-gate realization.", "Use De Morgan's law to rewrite the complement of a product as the sum of complements."),
            ("Combinational Circuits", "Minimization and design of adders, multiplexers, decoders and other combinational circuits.", "Implement a two-variable function by using the variables as select inputs of a 4-to-1 multiplexer."),
            ("Sequential Circuits", "Latches, flip-flops, registers, counters and finite-state sequential circuit behavior.", "Derive the next-state table before selecting flip-flop excitation inputs."),
            ("Number Representation and Arithmetic", "Signed and unsigned integers, fixed- and floating-point representation, and computer arithmetic.", "Negate a two's-complement word by complementing all bits and adding one."),
        ],
    },
    {
        "slug": "computer-organization-and-architecture",
        "code": "COA",
        "name": "Computer Organization and Architecture",
        "description": "Instructions, processor datapath, pipelining, memory hierarchy and I/O organization.",
        "topics": [
            ("Machine Instructions and Addressing Modes", "Machine instructions, operands, instruction formats and addressing modes.", "In base-plus-offset addressing, add the sign-extended displacement to the base register."),
            ("ALU, Datapath and Control", "ALU organization, processor datapath and hardwired or microprogrammed control.", "Trace register values across fetch, decode and execute datapath stages for a single instruction."),
            ("Instruction Pipelining", "Pipeline stages, throughput, speedup, structural, data and control hazards.", "Resolve a read-after-write dependency with forwarding when the producer result is available early enough."),
            ("Memory Hierarchy", "Cache, main memory, secondary storage, locality and effective memory access time.", "Compute average access time as hit time plus miss rate multiplied by miss penalty."),
            ("I/O Interface", "I/O interfaces, programmed I/O, interrupt-driven I/O and device communication.", "Interrupt-driven I/O lets the CPU execute other work until the device signals completion."),
            ("Interrupts and DMA", "Interrupt handling, priorities and direct memory access.", "DMA transfers a block between a device and memory with limited CPU intervention."),
        ],
    },
    {
        "slug": "programming-and-data-structures",
        "code": "PDS",
        "name": "Programming and Data Structures",
        "description": "Programming in C, recursion and fundamental linear, tree and graph data structures.",
        "topics": [
            ("Programming in C", "C syntax and semantics, functions, pointers, structures and program execution.", "When a pointer is incremented, it advances by the size of its pointed-to type."),
            ("Recursion", "Recursive definitions, call stacks, base cases and recurrence of recursive programs.", "Trace factorial by expanding calls until the base case and then multiplying during unwinding."),
            ("Arrays", "One- and multidimensional arrays, indexing and row-major layout.", "Compute a row-major address using base plus element size times the linearized index."),
            ("Stacks and Queues", "LIFO stacks, FIFO queues, circular queues and their applications.", "Evaluate a postfix expression by pushing operands and applying each operator to the top values."),
            ("Linked Lists", "Singly, doubly and circular linked lists and pointer-based operations.", "Delete a known successor node by relinking the predecessor before releasing the removed node."),
            ("Trees and Binary Search Trees", "Tree traversals, binary trees and binary search tree operations.", "An inorder traversal of a binary search tree visits stored keys in sorted order."),
            ("Heaps", "Binary heaps, heap operations and array representation.", "Restore a max-heap after deleting the root by moving the last key to the root and sifting down."),
            ("Graphs", "Graph representations and elementary graph data-structure operations.", "An adjacency list uses space proportional to vertices plus edges for a sparse graph."),
        ],
    },
    {
        "slug": "algorithms",
        "code": "ALG",
        "name": "Algorithms",
        "description": "Algorithm analysis and standard design techniques for searching, sorting and graph problems.",
        "topics": [
            ("Searching, Sorting and Hashing", "Linear and binary search, comparison sorting, hashing and collision handling.", "Binary search halves the remaining sorted interval after every comparison."),
            ("Complexity Analysis", "Asymptotic worst-case time and space complexity.", "Drop constants and lower-order terms when expressing a polynomial running time in theta notation."),
            ("Divide and Conquer", "Divide-and-conquer design and recurrence analysis.", "Merge sort divides into two halves and combines two sorted lists in linear time."),
            ("Greedy Algorithms", "Greedy-choice construction and correctness reasoning.", "Kruskal repeatedly adds the lightest edge that does not create a cycle."),
            ("Dynamic Programming", "Optimal substructure, overlapping subproblems, tabulation and memoization.", "Store each subproblem value once when computing the longest common subsequence."),
            ("Graph Algorithms", "Breadth-first and depth-first search, connected components, spanning trees and shortest paths.", "Breadth-first search gives shortest path lengths in an unweighted graph."),
        ],
    },
    {
        "slug": "theory-of-computation",
        "code": "TOC",
        "name": "Theory of Computation",
        "description": "Automata, grammars, Turing machines and decidability.",
        "topics": [
            ("Regular Expressions and Finite Automata", "Regular expressions, deterministic and nondeterministic finite automata and their equivalence.", "Use subset construction to convert an NFA state set into one DFA state."),
            ("Context-Free Grammars", "Context-free grammars, derivations, parse trees and ambiguity.", "A leftmost derivation always expands the leftmost remaining nonterminal."),
            ("Pushdown Automata", "Pushdown automata and their relationship with context-free languages.", "Use the stack to match a block of opening symbols with a later block of closing symbols."),
            ("Pumping Lemmas and Language Properties", "Pumping lemmas and closure or decision properties of regular and context-free languages.", "To disprove regularity, choose a long structured string and show every legal pumping split fails."),
            ("Turing Machines and Undecidability", "Turing machines, computability, reductions and undecidable problems.", "A mapping reduction transfers undecidability from a known problem to the target problem."),
        ],
    },
    {
        "slug": "compiler-design",
        "code": "CD",
        "name": "Compiler Design",
        "description": "Compiler front end, intermediate representation, runtime organization and analysis.",
        "topics": [
            ("Lexical Analysis", "Tokens, patterns, lexemes and finite-automata based lexical analysis.", "A lexer groups a sequence of digit characters into one numeric token."),
            ("Parsing", "Top-down and bottom-up parsing, FIRST and FOLLOW sets and parse conflicts.", "An LL(1) parser selects a production using the nonterminal and one lookahead token."),
            ("Syntax-Directed Translation", "Syntax-directed definitions, attributes and translation schemes.", "A synthesized expression value is computed from the values of its child nodes."),
            ("Runtime Environments", "Activation records, storage allocation, parameter passing and control links.", "A recursive call receives a distinct activation record containing its local variables and return address."),
            ("Intermediate Code Generation", "Intermediate representations and three-address code.", "Break a nested arithmetic expression into temporaries with at most one operator per instruction."),
            ("Code Optimization and Data-Flow Analysis", "Local optimization; constant propagation; liveness; common subexpression elimination.", "A variable is live before a statement if its current value may be used along some later path."),
        ],
    },
    {
        "slug": "operating-systems",
        "code": "OS",
        "name": "Operating Systems",
        "description": "Processes, concurrency, scheduling, memory management and file systems.",
        "topics": [
            ("System Calls", "System-call interface and transitions between user and kernel execution.", "A read request enters the kernel through a system call and returns a result to user mode."),
            ("Processes and Threads", "Process and thread states, context switching and inter-process communication.", "Threads in one process share the address space but retain separate execution stacks."),
            ("Concurrency and Synchronization", "Race conditions, critical sections, mutexes, semaphores and monitors.", "Protect a shared counter update with mutual exclusion to prevent lost updates."),
            ("Deadlocks", "Deadlock conditions, prevention, avoidance and detection.", "A resource-allocation cycle implies deadlock when every resource type has a single instance."),
            ("CPU and I/O Scheduling", "CPU scheduling and disk or I/O scheduling policies.", "Round-robin bounds a ready process's waiting between turns by the time quantum and queue length."),
            ("Memory and Virtual Memory", "Contiguous allocation, paging, segmentation, virtual memory and page replacement.", "Split a virtual address into a page number and an offset determined by page size."),
            ("File Systems", "Files, directories, allocation methods and free-space management.", "Indexed allocation keeps block addresses in an index block to support direct access."),
        ],
    },
    {
        "slug": "databases",
        "code": "DBMS",
        "name": "Databases",
        "description": "Data modeling, relational queries, normalization, indexing and transactions.",
        "topics": [
            ("ER Model", "Entity-relationship modeling, keys, attributes, relationships and mapping constraints.", "Represent a many-to-many relationship with its own relation containing both entity keys."),
            ("Relational Model", "Relations, keys, relational algebra and tuple relational calculus.", "A selection filters tuples while a projection chooses attributes."),
            ("SQL", "SQL data definition, queries, aggregation, subqueries and views.", "Use GROUP BY before HAVING when filtering aggregate groups."),
            ("Integrity Constraints", "Domain, key, entity-integrity and referential-integrity constraints.", "A foreign key either matches a referenced candidate key or is null when null is permitted."),
            ("Normal Forms", "Functional dependencies and normalization through standard normal forms.", "Decompose on a violating dependency while checking lossless join and dependency preservation."),
            ("File Organization and Indexing", "File organization, ordered files, hashing and B/B+ tree indexes.", "A B+ tree keeps data entries at leaves and links leaves for efficient range scans."),
            ("Transactions and Concurrency Control", "ACID properties, schedules, serializability, locking and recovery concepts.", "Build a precedence graph; an acyclic graph means the schedule is conflict serializable."),
        ],
    },
    {
        "slug": "computer-networks",
        "code": "CN",
        "name": "Computer Networks",
        "description": "Network models, links, routing, Internet protocols, transport and applications.",
        "topics": [
            ("Layering and Switching", "OSI and TCP/IP layering; packet, circuit and virtual-circuit switching.", "Encapsulation adds each layer's control information as data moves down a protocol stack."),
            ("Data Link Layer", "Framing, error detection, medium access, bridges and Ethernet.", "A CRC sender appends a remainder so the transmitted polynomial is divisible by the generator."),
            ("Routing Algorithms", "Shortest-path, flooding, distance-vector and link-state routing.", "Link-state routing runs a shortest-path algorithm after distributing link costs."),
            ("IPv4 Addressing and Forwarding", "IPv4, CIDR, fragmentation, forwarding, ARP, DHCP, ICMP and NAT.", "A /24 IPv4 prefix leaves 8 host bits and therefore 256 total addresses."),
            ("Transport Layer", "UDP, TCP, sockets, flow control and congestion control.", "TCP uses acknowledgements and a sliding window for reliable ordered byte delivery."),
            ("Application Layer", "DNS, SMTP, HTTP, FTP and email protocols.", "DNS resolves a domain name through cached or iterative queries to name servers."),
            ("Network Performance", "Delay, bandwidth, throughput, utilization and basic performance calculations.", "Transmission delay equals packet length in bits divided by link rate in bits per second."),
        ],
    },
    {
        "slug": "general-aptitude",
        "code": "GA",
        "name": "General Aptitude",
        "description": "Verbal, quantitative, analytical and spatial aptitude common to GATE papers.",
        "topics": [
            ("Verbal Aptitude", "Basic English grammar, vocabulary, reading comprehension and narrative sequencing.", "Choose the connector that preserves the logical contrast between two clauses."),
            ("Quantitative Aptitude", "Data interpretation; ratios; percentages; powers; logarithms; permutations; series; mensuration; geometry; elementary statistics and probability.", "A 20 percent increase multiplies a value by 1.20."),
            ("Analytical Aptitude", "Logic, deduction, analogy and numerical relationships.", "List the constraints explicitly and eliminate any arrangement that violates one."),
            ("Spatial Aptitude", "Shape transformations, paper folding, cutting and patterns in two and three dimensions.", "Track the orientation of a marked face through each stated rotation."),
        ],
    },
]


def option(identifier: str, text: str) -> dict[str, str]:
    return {"id": identifier, "text": text}


CURATED: list[dict[str, Any]] = [
    {"subject": "engineering-mathematics", "topic": "Linear Algebra", "type": QuestionType.MCQ, "text": "The eigenvalues of the matrix [[2, 1], [0, 3]] are", "options": [option("A", "1 and 6"), option("B", "2 and 3"), option("C", "2 and 2"), option("D", "3 and 3")], "answer": "B", "explanation": "A triangular matrix has its eigenvalues on the diagonal, so they are 2 and 3."},
    {"subject": "engineering-mathematics", "topic": "Probability and Statistics", "type": QuestionType.NAT, "text": "A fair coin is tossed twice. What is the probability of getting exactly one head?", "options": [], "answer": 0.5, "explanation": "The equally likely outcomes are HH, HT, TH and TT; two of four have exactly one head."},
    {"subject": "digital-logic", "topic": "Boolean Algebra", "type": QuestionType.MCQ, "text": "Which expression is equivalent to the complement of A AND B?", "options": [option("A", "NOT A AND NOT B"), option("B", "NOT A OR NOT B"), option("C", "A OR B"), option("D", "A AND B")], "answer": "B", "explanation": "By De Morgan's law, (AB)' = A' + B'."},
    {"subject": "digital-logic", "topic": "Number Representation and Arithmetic", "type": QuestionType.NAT, "text": "How many distinct values can an 8-bit unsigned binary number represent?", "options": [], "answer": 256, "explanation": "Eight bits give 2^8 = 256 distinct bit patterns."},
    {"subject": "computer-organization-and-architecture", "topic": "Memory Hierarchy", "type": QuestionType.NAT, "text": "A cache hit takes 1 ns. The miss rate is 0.1 and the additional miss penalty is 20 ns. Find the average access time in ns.", "options": [], "answer": 3, "explanation": "Average access time = 1 + 0.1 × 20 = 3 ns."},
    {"subject": "computer-organization-and-architecture", "topic": "Instruction Pipelining", "type": QuestionType.MSQ, "text": "Which of the following are pipeline hazards?", "options": [option("A", "Structural hazard"), option("B", "Data hazard"), option("C", "Control hazard"), option("D", "Locality hazard")], "answer": ["A", "B", "C"], "explanation": "Structural, data and control hazards are the standard pipeline hazard classes."},
    {"subject": "programming-and-data-structures", "topic": "Stacks and Queues", "type": QuestionType.MCQ, "text": "Which data structure directly supports last-in, first-out access?", "options": [option("A", "Queue"), option("B", "Stack"), option("C", "Heap"), option("D", "Graph")], "answer": "B", "explanation": "A stack removes the most recently pushed item first."},
    {"subject": "programming-and-data-structures", "topic": "Trees and Binary Search Trees", "type": QuestionType.MCQ, "text": "Which traversal of a binary search tree lists distinct keys in increasing order?", "options": [option("A", "Preorder"), option("B", "Postorder"), option("C", "Inorder"), option("D", "Level order")], "answer": "C", "explanation": "Inorder visits left subtree, node, then right subtree, producing sorted BST keys."},
    {"subject": "algorithms", "topic": "Graph Algorithms", "type": QuestionType.MCQ, "text": "Which algorithm finds shortest path lengths from a source in an unweighted graph?", "options": [option("A", "Depth-first search"), option("B", "Breadth-first search"), option("C", "Kruskal's algorithm"), option("D", "Heap sort")], "answer": "B", "explanation": "BFS explores vertices in nondecreasing number of edges from the source."},
    {"subject": "algorithms", "topic": "Searching, Sorting and Hashing", "type": QuestionType.NAT, "text": "Starting with 1024 candidates, how many halvings are needed to reduce the candidate set to one?", "options": [], "answer": 10, "explanation": "1024 = 2^10, so ten halvings leave one candidate."},
    {"subject": "theory-of-computation", "topic": "Regular Expressions and Finite Automata", "type": QuestionType.MCQ, "text": "Which machine model recognizes exactly the regular languages?", "options": [option("A", "Finite automaton"), option("B", "Pushdown automaton"), option("C", "Linear bounded automaton"), option("D", "Unrestricted grammar")], "answer": "A", "explanation": "Finite automata and regular expressions define exactly the regular languages."},
    {"subject": "theory-of-computation", "topic": "Pumping Lemmas and Language Properties", "type": QuestionType.MSQ, "text": "Regular languages are closed under which operations?", "options": [option("A", "Union"), option("B", "Intersection"), option("C", "Complement"), option("D", "Set difference")], "answer": ["A", "B", "C", "D"], "explanation": "Regular languages are closed under all four listed Boolean operations."},
    {"subject": "compiler-design", "topic": "Lexical Analysis", "type": QuestionType.MCQ, "text": "Which compiler phase normally recognizes identifiers and numeric literals?", "options": [option("A", "Lexical analysis"), option("B", "Register allocation"), option("C", "Instruction scheduling"), option("D", "Linking")], "answer": "A", "explanation": "The lexical analyzer groups character sequences into tokens such as identifiers and numbers."},
    {"subject": "compiler-design", "topic": "Code Optimization and Data-Flow Analysis", "type": QuestionType.MSQ, "text": "Which are standard data-flow facts used in compiler optimization?", "options": [option("A", "Liveness"), option("B", "Reaching definitions"), option("C", "Available expressions"), option("D", "Token length")], "answer": ["A", "B", "C"], "explanation": "The first three are data-flow analyses; token length is not one."},
    {"subject": "operating-systems", "topic": "Deadlocks", "type": QuestionType.MSQ, "text": "Which conditions are necessary for a deadlock?", "options": [option("A", "Mutual exclusion"), option("B", "Hold and wait"), option("C", "No preemption"), option("D", "Circular wait")], "answer": ["A", "B", "C", "D"], "explanation": "All four Coffman conditions are necessary for deadlock."},
    {"subject": "operating-systems", "topic": "Memory and Virtual Memory", "type": QuestionType.NAT, "text": "How many offset bits are required for a page size of 4096 bytes in a byte-addressed system?", "options": [], "answer": 12, "explanation": "4096 = 2^12, so the low 12 address bits form the page offset."},
    {"subject": "databases", "topic": "Relational Model", "type": QuestionType.NAT, "text": "Relations R and S contain 4 and 5 tuples respectively. If every pair is distinct, how many tuples are in R cross S?", "options": [], "answer": 20, "explanation": "A Cartesian product pairs every R tuple with every S tuple: 4 × 5 = 20."},
    {"subject": "databases", "topic": "Transactions and Concurrency Control", "type": QuestionType.MCQ, "text": "A schedule is conflict serializable exactly when its precedence graph is", "options": [option("A", "complete"), option("B", "acyclic"), option("C", "weighted"), option("D", "undirected")], "answer": "B", "explanation": "A schedule is conflict serializable if and only if its precedence graph has no cycle."},
    {"subject": "computer-networks", "topic": "IPv4 Addressing and Forwarding", "type": QuestionType.NAT, "text": "Ignoring reserved subnet and directed-broadcast addresses, how many usable host addresses are in an IPv4 /24 subnet?", "options": [], "answer": 254, "explanation": "A /24 has 256 addresses; excluding network and broadcast addresses leaves 254."},
    {"subject": "computer-networks", "topic": "Transport Layer", "type": QuestionType.MSQ, "text": "Which services are provided by TCP?", "options": [option("A", "Reliable byte stream"), option("B", "In-order delivery"), option("C", "Flow control"), option("D", "Preservation of application message boundaries")], "answer": ["A", "B", "C"], "explanation": "TCP is a reliable ordered byte stream with flow control; it does not preserve message boundaries."},
    {"subject": "general-aptitude", "topic": "Quantitative Aptitude", "type": QuestionType.NAT, "text": "A quantity increases from 80 to 100. What is the percentage increase?", "options": [], "answer": 25, "explanation": "The increase is 20 on a base of 80, so 20/80 × 100 = 25 percent."},
    {"subject": "general-aptitude", "topic": "Verbal Aptitude", "type": QuestionType.MCQ, "text": "Choose the grammatically correct sentence.", "options": [option("A", "Each of the students have a card."), option("B", "Each of the students has a card."), option("C", "Each of the student have cards."), option("D", "Each students has a card.")], "answer": "B", "explanation": "The subject 'each' is singular and takes 'has'."},
]


OFFICIAL_2024_PAPER_URL = (
    "https://gate2027.iitm.ac.in/static/doc/download/2024/CS124S5.pdf"
)
OFFICIAL_2024_KEY_URL = (
    "https://gate2027.iitm.ac.in/static/doc/download/2024/CS1FinalAnswerKey.pdf"
)

# Verified against the official IISc Bengaluru paper and final answer key. These
# are deliberately kept separate from original practice content so clients can
# filter by source_kind and render provenance.
OFFICIAL_2024: list[dict[str, Any]] = [
    {
        "question_number": 12,
        "subject": "engineering-mathematics",
        "topic": "Linear Algebra",
        "type": QuestionType.MCQ,
        "text": "The product of all eigenvalues of the matrix [[1, 2, 3], [4, 5, 6], [7, 8, 9]] is",
        "options": [option("A", "-1"), option("B", "0"), option("C", "1"), option("D", "2")],
        "answer": "B",
        "explanation": "The rows are linearly dependent, so the determinant is zero. The determinant equals the product of all eigenvalues.",
    },
    {
        "question_number": 13,
        "subject": "digital-logic",
        "topic": "Number Representation and Arithmetic",
        "type": QuestionType.MCQ,
        "text": "A system uses 5-bit two's-complement signed integers. A = 01010 and B = 11010. Which operation causes arithmetic overflow or underflow?",
        "options": [option("A", "A + B"), option("B", "A - B"), option("C", "B - A"), option("D", "2 × B")],
        "answer": "B",
        "explanation": "A is 10 and B is -6. A - B is 16, outside the representable range -16 through 15.",
    },
    {
        "question_number": 14,
        "subject": "engineering-mathematics",
        "topic": "Probability and Statistics",
        "type": QuestionType.MCQ,
        "text": "A permutation is sampled uniformly from all permutations of {1, 2, ..., n}, n >= 4. X is the event that 1 occurs before 2, and Y that 3 occurs before 4. Which statement is true?",
        "options": [option("A", "X and Y are mutually exclusive"), option("B", "X and Y are independent"), option("C", "Either X or Y must occur"), option("D", "X is more likely than Y")],
        "answer": "B",
        "explanation": "Each relative order has probability one half, and fixing the order of one disjoint pair does not affect the other pair.",
    },
    {
        "question_number": 15,
        "subject": "computer-organization-and-architecture",
        "topic": "I/O Interface",
        "type": QuestionType.MCQ,
        "text": "Which statement about I/O and interrupts is false?",
        "options": [option("A", "Cycle-stealing DMA transfers one word during a stolen cycle"), option("B", "Burst-mode DMA has higher bulk-transfer throughput than cycle stealing"), option("C", "Programmed I/O gives better CPU utilization than interrupt-driven I/O"), option("D", "Vectored interrupts can start an ISR faster than non-vectored interrupts")],
        "answer": "C",
        "explanation": "Programmed I/O makes the CPU poll or wait for the device, whereas interrupt-driven I/O lets it perform useful work meanwhile.",
    },
    {
        "question_number": 16,
        "subject": "computer-networks",
        "topic": "Application Layer",
        "type": QuestionType.MCQ,
        "text": "With empty caches and one TCP connection for an entire webpage, order these outgoing packets: (i) index-page HTTP GET, (ii) DNS request, (iii) image HTTP GET, (iv) TCP SYN.",
        "options": [option("A", "iv, ii, iii, i"), option("B", "ii, iv, iii, i"), option("C", "ii, iv, i, iii"), option("D", "iv, ii, i, iii")],
        "answer": "C",
        "explanation": "Name resolution precedes connection establishment; the index is fetched after TCP opens, and only then can its embedded image be requested.",
    },
    {
        "question_number": 17,
        "subject": "algorithms",
        "topic": "Complexity Analysis",
        "type": QuestionType.MCQ,
        "text": "An algorithm checks whether an N-element array is sorted in either direction using one pass and only adjacent comparisons. Its worst-case time is",
        "options": [option("A", "both O(N) and Ω(N)"), option("B", "O(N) but not Ω(N)"), option("C", "Ω(N) but not O(N)"), option("D", "neither O(N) nor Ω(N)")],
        "answer": "A",
        "explanation": "The single pass performs a linear number of adjacent comparisons in the worst case, so the bound is Θ(N).",
    },
    {
        "question_number": 18,
        "subject": "programming-and-data-structures",
        "topic": "Programming in C",
        "type": QuestionType.MCQ,
        "text": "In C, a starts at 6 and b at 0. While (a < 10), the loop executes a = a / 12 + 1; a += b. What happens?",
        "options": [option("A", "It prints 9"), option("B", "It prints 10"), option("C", "It enters an infinite loop"), option("D", "It prints 6")],
        "answer": "C",
        "explanation": "Integer division changes a to 1 on the first iteration; every later iteration leaves it at 1, so the loop condition remains true.",
    },
    {
        "question_number": 19,
        "subject": "programming-and-data-structures",
        "topic": "Recursion",
        "type": QuestionType.MCQ,
        "text": "A recursive C function reads one character, recurses unless it read a newline, and prints the character while unwinding. For input 1234 followed by newline, what occurs?",
        "options": [option("A", "It does not terminate"), option("B", "It terminates with no output"), option("C", "It prints 4321"), option("D", "It prints 1234")],
        "answer": "C",
        "explanation": "Characters are printed after the recursive call returns, so the call stack reverses their order.",
    },
    {
        "question_number": 21,
        "subject": "databases",
        "topic": "File Organization and Indexing",
        "type": QuestionType.MCQ,
        "text": "In a B+ tree, the requirement of at least 50% node occupancy is relaxed for which case?",
        "options": [option("A", "Only the root node"), option("B", "All leaf nodes"), option("C", "All internal nodes"), option("D", "Only the leftmost leaf node")],
        "answer": "A",
        "explanation": "The root is allowed fewer children or entries; non-root internal and leaf nodes must satisfy the minimum occupancy rule.",
    },
    {
        "question_number": 22,
        "subject": "databases",
        "topic": "Normal Forms",
        "type": QuestionType.MSQ,
        "text": "Which statements about a relation R in first normal form (1NF) are true?",
        "options": [option("A", "R can have a multi-attribute key"), option("B", "R cannot have a foreign key"), option("C", "R cannot have a composite attribute"), option("D", "R cannot have more than one candidate key")],
        "answer": ["A", "C"],
        "explanation": "1NF requires atomic attribute values, but it permits composite keys, foreign keys, and multiple candidate keys.",
    },
    {
        "question_number": 23,
        "subject": "theory-of-computation",
        "topic": "Pumping Lemmas and Language Properties",
        "type": QuestionType.MSQ,
        "text": "Let L1 and L2 be regular and L3 be non-regular. Which statements are always true?",
        "options": [option("A", "L1 = L2 iff L1 intersect complement(L2) is empty"), option("B", "L1 union L3 is non-regular"), option("C", "complement(L3) is non-regular"), option("D", "complement(L1) union complement(L2) is regular")],
        "answer": ["C", "D"],
        "explanation": "If complement(L3) were regular then L3 would be regular. Regular languages are closed under complement and union.",
    },
    {
        "question_number": 24,
        "subject": "operating-systems",
        "topic": "Processes and Threads",
        "type": QuestionType.MSQ,
        "text": "Which statements about threads are true?",
        "options": [option("A", "Threads can only be implemented in kernel space"), option("B", "Each thread has its own open-file descriptor table"), option("C", "All threads of a process share one common stack"), option("D", "Threads of a process are by default not protected from each other")],
        "answer": ["D"],
        "explanation": "Threads share their process resources and address space but have separate stacks; they may be implemented in user or kernel space.",
    },
    {
        "question_number": 25,
        "subject": "operating-systems",
        "topic": "Processes and Threads",
        "type": QuestionType.MSQ,
        "text": "Which process-state transitions are not possible directly?",
        "options": [option("A", "Running to Ready"), option("B", "Waiting to Running"), option("C", "Ready to Waiting"), option("D", "Running to Terminated")],
        "answer": ["B", "C"],
        "explanation": "A waiting process first becomes ready before dispatch. A ready process cannot block without first running.",
    },
    {
        "question_number": 26,
        "subject": "compiler-design",
        "topic": "Parsing",
        "type": QuestionType.MSQ,
        "text": "Which of the following are bottom-up parsers?",
        "options": [option("A", "Shift-reduce parser"), option("B", "Predictive parser"), option("C", "LL(1) parser"), option("D", "LR parser")],
        "answer": ["A", "D"],
        "explanation": "Shift-reduce and LR parsers construct a rightmost derivation in reverse; predictive and LL(1) parsing are top-down.",
    },
    {
        "question_number": 27,
        "subject": "engineering-mathematics",
        "topic": "Probability and Statistics",
        "type": QuestionType.MSQ,
        "text": "For events A and B, P(A)=0.3, P(B)=0.5 and P(A intersect B)=0.1. Which statements are true?",
        "options": [option("A", "A and B are independent"), option("B", "P(A union B) = 0.7"), option("C", "P(A intersect complement(B)) = 0.2"), option("D", "P(complement(A) intersect complement(B)) = 0.4")],
        "answer": ["B", "C"],
        "explanation": "The union is 0.3 + 0.5 - 0.1 = 0.7, and A outside B is 0.3 - 0.1 = 0.2.",
    },
    {
        "question_number": 29,
        "subject": "computer-networks",
        "topic": "Transport Layer",
        "type": QuestionType.MSQ,
        "text": "TCP client P sends a SYN with sequence number NP. Server Q responds with SYN-ACK acknowledgement number NQ. Which statements are correct?",
        "options": [option("A", "NP is chosen randomly by P"), option("B", "NP is always 0 for a new connection"), option("C", "NQ equals NP"), option("D", "NQ equals NP + 1")],
        "answer": ["A", "D"],
        "explanation": "TCP selects an initial sequence number and the SYN consumes one sequence number, so the peer acknowledges NP + 1.",
    },
    {
        "question_number": 30,
        "subject": "computer-organization-and-architecture",
        "topic": "Instruction Pipelining",
        "type": QuestionType.MSQ,
        "text": "For a five-stage IF, ID, EX, MEM, WB processor, which statements about forwarding are correct?",
        "options": [option("A", "A result from an earlier instruction is passed to a later instruction's needed stage"), option("B", "MEM-stage output can be forwarded to the next instruction's EX input"), option("C", "Forwarding cannot prevent every pipeline stall"), option("D", "Forwarding needs no extra retrieval hardware")],
        "answer": ["A", "B", "C"],
        "explanation": "Forwarding bypasses values with extra paths and control, but some hazards such as load-use dependencies can still stall.",
    },
    {
        "question_number": 31,
        "subject": "computer-networks",
        "topic": "IPv4 Addressing and Forwarding",
        "type": QuestionType.MSQ,
        "text": "Which IP-header fields are modified when a packet leaves an internal network through a NAT device?",
        "options": [option("A", "Source IP"), option("B", "Destination IP"), option("C", "Header checksum"), option("D", "Total length")],
        "answer": ["A", "C"],
        "explanation": "Outbound NAT rewrites the source address; changing an IP-header field requires recomputing the header checksum.",
    },
]


def _note_for(topic: Topic, example: str) -> RevisionNote:
    key_points = [
        topic.description,
        "Write the relevant definition or invariant before applying a formula.",
        "Check boundary cases, units and assumptions before finalizing an answer.",
    ]
    content = (
        f"# {topic.name}\n\n"
        f"## Scope\n\n{topic.description}\n\n"
        "## Exam-focused method\n\n"
        "1. Identify the exact object, property or quantity the question asks for.\n"
        "2. State the applicable definition, invariant or formula.\n"
        "3. Substitute carefully, keeping track of boundary cases and units.\n"
        "4. Verify the result against the definition before selecting an option.\n\n"
        f"## Worked example\n\n{example}\n\n"
        "## Revision checkpoint\n\n"
        "Be able to explain the central definition, execute the standard method, and identify one common edge case."
    )
    return RevisionNote(
        topic=topic,
        title=f"{topic.name}: GATE revision notes",
        summary=topic.description,
        content_md=content,
        key_points=key_points,
        worked_examples=[
            {
                "question": f"Demonstrate the standard GATE method for a basic {topic.name} problem.",
                "solution": example,
            }
        ],
    )


def _concept_question(
    subject: Subject,
    topic: Topic,
    all_topics: list[Topic],
    index: int,
) -> Question:
    distractors = [candidate for candidate in all_topics if candidate.id != topic.id][:3]
    choices = [(topic.description, True)] + [(item.description, False) for item in distractors]
    rotation = index % 4
    choices = choices[rotation:] + choices[:rotation]
    identifiers = ["A", "B", "C", "D"]
    correct = identifiers[next(i for i, (_, is_correct) in enumerate(choices) if is_correct)]
    return Question(
        subject=subject,
        topic=topic,
        source=QuestionSource.ORIGINAL,
        source_kind=QuestionSource.ORIGINAL,
        question_type=QuestionType.MCQ,
        difficulty=Difficulty.MEDIUM,
        text=f"Which description most accurately matches the syllabus topic '{topic.name}'?",
        options=[option(identifier, text) for identifier, (text, _) in zip(identifiers, choices)],
        correct_answer=correct,
        numerical_tolerance=0.01,
        marks=2,
        explanation=f"{topic.name} covers {topic.description}",
        tags=[topic.slug, "concept-check"],
    )


async def seed_database(session: AsyncSession) -> None:
    existing = await session.scalar(select(func.count(Subject.id)))
    if existing:
        return

    subjects: dict[str, Subject] = {}
    topic_by_key: dict[tuple[str, str], Topic] = {}
    examples: dict[int, str] = {}

    for subject_index, subject_data in enumerate(SYLLABUS, start=1):
        subject = Subject(
            slug=subject_data["slug"],
            code=subject_data["code"],
            name=subject_data["name"],
            description=subject_data["description"],
            order_index=subject_index,
        )
        session.add(subject)
        subjects[subject.slug] = subject
        for topic_index, (name, description, example) in enumerate(
            subject_data["topics"], start=1
        ):
            topic = Topic(
                subject=subject,
                slug=slugify(name),
                name=name,
                description=description,
                order_index=topic_index,
            )
            session.add(topic)
            topic_by_key[(subject.slug, name)] = topic
            examples[id(topic)] = example

    await session.flush()

    for topic in topic_by_key.values():
        session.add(_note_for(topic, examples[id(topic)]))

    for subject_slug, subject in subjects.items():
        subject_topics = [
            topic
            for (slug, _), topic in topic_by_key.items()
            if slug == subject_slug
        ]
        question_batch: list[Question] = []

        for data in [item for item in CURATED if item["subject"] == subject_slug]:
            topic = topic_by_key[(subject_slug, data["topic"])]
            question_batch.append(
                Question(
                    subject=subject,
                    topic=topic,
                    source=QuestionSource.ORIGINAL,
                    source_kind=QuestionSource.ORIGINAL,
                    question_type=data["type"],
                    difficulty=Difficulty.MEDIUM,
                    text=data["text"],
                    options=data["options"],
                    correct_answer=data["answer"],
                    numerical_tolerance=0.01,
                    marks=2,
                    explanation=data["explanation"],
                    tags=[topic.slug, "gate-style", "original"],
                )
            )

        fill_index = 0
        target_count = 10 if subject_slug == "general-aptitude" else 6
        while len(question_batch) < target_count:
            topic = subject_topics[fill_index % len(subject_topics)]
            question_batch.append(
                _concept_question(subject, topic, subject_topics, fill_index)
            )
            fill_index += 1

        # General Aptitude follows the official 5 one-mark + 5 two-mark split.
        # Each technical subject also contributes original material before the
        # verified previous-year questions are added below.
        one_mark_count = 5 if subject_slug == "general-aptitude" else 1
        for index, question in enumerate(question_batch):
            question.marks = 1 if index < one_mark_count else 2
            question.difficulty = (
                Difficulty.EASY
                if index < 2
                else Difficulty.MEDIUM
                if index < 5
                else Difficulty.HARD
            )
            session.add(question)

    for data in OFFICIAL_2024:
        subject = subjects[data["subject"]]
        topic = topic_by_key[(data["subject"], data["topic"])]
        session.add(
            Question(
                subject=subject,
                topic=topic,
                source=QuestionSource.PREVIOUS_YEAR,
                year=2024,
                exam_session="CS1, Session 5",
                source_kind=QuestionSource.PREVIOUS_YEAR,
                source_year=2024,
                source_paper="GATE 2024 CS1 (Session 5)",
                source_question_number=data["question_number"],
                source_url=OFFICIAL_2024_PAPER_URL,
                answer_key_url=OFFICIAL_2024_KEY_URL,
                question_type=data["type"],
                difficulty=Difficulty.MEDIUM,
                text=data["text"],
                options=data["options"],
                correct_answer=data["answer"],
                numerical_tolerance=0.01,
                marks=1,
                explanation=data["explanation"],
                tags=[topic.slug, "gate-2024", "cs1", "official-pyq"],
            )
        )

    await session.commit()
