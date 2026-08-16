import type { QuestionAsset } from "@/lib/question-assets";
import type {
  AcceptedAnswer,
  QuestionReviewStatus,
} from "@/lib/answer-review";

export type QuestionType = "MCQ" | "MSQ" | "NAT";

export type Subject = {
  id: string;
  code: string;
  title: string;
  shortTitle: string;
  description: string;
  progress: number;
  mastery: number;
  questionCount: number;
  estimatedHours: number;
  accent: string;
  phase: "Foundations" | "Core reasoning" | "Systems";
  topics: Array<{
    id: string;
    apiId?: number;
    title: string;
    progress: number;
    questions: number;
    duration: string;
  }>;
  note: {
    title: string;
    summary: string;
    intuition: string;
    formula: string;
    formulaHint: string;
    exampleTitle: string;
    exampleSteps: string[];
    checkpoint: string[];
    traps: string[];
  };
};

export type PracticeQuestion = {
  id: string;
  subjectId: string;
  topicId: string;
  type: QuestionType;
  marks: 1 | 2;
  prompt: string;
  options?: Array<{ id: string; label: string }>;
  correct: string[];
  acceptedAnswer?: AcceptedAnswer;
  reviewStatus?: QuestionReviewStatus;
  explanation: string;
  source?: string;
  year?: number;
  difficulty: "Easy" | "Medium" | "Hard";
  assets?: QuestionAsset[];
  archiveItemType?: string;
  archiveStatus?: string;
};

const topic = (
  id: string,
  title: string,
  progress: number,
  questions: number,
  duration: string,
) => ({ id, title, progress, questions, duration });

export const subjects: Subject[] = [
  {
    id: "engineering-mathematics",
    code: "EM",
    title: "Engineering Mathematics",
    shortTitle: "Mathematics",
    description: "Discrete structures, linear algebra, calculus, probability and statistics.",
    progress: 68,
    mastery: 72,
    questionCount: 312,
    estimatedHours: 18,
    accent: "#596fe8",
    phase: "Foundations",
    topics: [
      topic("discrete-math", "Discrete Mathematics", 82, 96, "4h 20m"),
      topic("linear-algebra", "Linear Algebra", 72, 61, "3h 10m"),
      topic("calculus", "Calculus", 58, 74, "3h 45m"),
      topic("probability", "Probability & Statistics", 54, 81, "4h 05m"),
    ],
    note: {
      title: "Counting before calculating",
      summary: "Most discrete-mathematics errors come from counting the same outcome twice. Define the sample space, decide whether order matters, then choose the rule.",
      intuition: "The sum rule handles mutually exclusive choices; the product rule handles a sequence of independent choices. Inclusion–exclusion repairs overlaps when choices are not disjoint.",
      formula: "|A ∪ B| = |A| + |B| − |A ∩ B|",
      formulaHint: "For three sets, add singles, subtract pairwise intersections, then add the triple intersection.",
      exampleTitle: "Strings with at least one repeated symbol",
      exampleSteps: [
        "Count all length-4 strings over 6 symbols: 6⁴.",
        "Count the complement with all symbols distinct: 6 × 5 × 4 × 3.",
        "Subtract: 6⁴ − 360 = 936 strings.",
      ],
      checkpoint: ["Can you state the complement event?", "Does order change the outcome?", "Are any cases counted twice?"],
      traps: ["Treating overlapping cases as disjoint", "Using permutations when order is irrelevant"],
    },
  },
  {
    id: "digital-logic",
    code: "DL",
    title: "Digital Logic",
    shortTitle: "Digital Logic",
    description: "Boolean algebra, combinational and sequential circuits, number representations.",
    progress: 56,
    mastery: 61,
    questionCount: 196,
    estimatedHours: 11,
    accent: "#d97757",
    phase: "Foundations",
    topics: [
      topic("boolean-algebra", "Boolean Algebra", 76, 48, "2h 30m"),
      topic("combinational", "Combinational Circuits", 64, 54, "2h 40m"),
      topic("sequential", "Sequential Circuits", 38, 62, "3h 15m"),
      topic("number-systems", "Number Representation", 49, 32, "1h 40m"),
    ],
    note: {
      title: "Simplify by structure",
      summary: "Boolean identities and Karnaugh maps are two views of the same task: forming the largest valid implicants without changing the function.",
      intuition: "Adjacent K-map cells differ in exactly one literal. Grouping powers of two removes the literals that change inside the group.",
      formula: "X + X̄Y = X + Y",
      formulaHint: "Absorption often removes a term faster than expanding the full expression.",
      exampleTitle: "Minimize F(A,B,C) = Σm(1,3,5,7)",
      exampleSteps: ["All listed minterms have C = 1.", "They form one group of four in a 3-variable K-map.", "A and B vary, so F reduces to C."],
      checkpoint: ["Are groups powers of two?", "Did you include every 1?", "Can a larger group replace two smaller ones?"],
      traps: ["Grouping diagonal cells", "Forgetting wrap-around adjacency"],
    },
  },
  {
    id: "computer-organization",
    code: "COA",
    title: "Computer Organization & Architecture",
    shortTitle: "COA",
    description: "Machine instructions, datapaths, pipelines, memory hierarchy and I/O.",
    progress: 42,
    mastery: 48,
    questionCount: 286,
    estimatedHours: 19,
    accent: "#4f67d8",
    phase: "Foundations",
    topics: [
      topic("instruction-set-addressing", "Instruction Set & Addressing Modes", 71, 54, "2h 20m"),
      topic("alu-design", "Arithmetic & Logic Unit", 48, 39, "2h 15m"),
      topic("control-unit", "Hardwired & Microprogrammed Control", 34, 41, "2h 40m"),
      topic("memory-hierarchy", "Memory Interfacing & Cache Hierarchy", 28, 94, "5h 00m"),
      topic("io-interface", "I/O, Interrupts & DMA", 44, 37, "2h 05m"),
      topic("pipelining", "Instruction Pipelining & Hazards", 35, 71, "4h 10m"),
    ],
    note: {
      title: "Locality makes a cache useful",
      summary: "A cache works because recently used blocks and nearby addresses are likely to be used again. Every address is split into tag, index and block offset.",
      intuition: "The offset selects a byte inside a block; the index selects a set; the tag confirms that the requested memory block currently occupies that set.",
      formula: "AMAT = Hit time + Miss rate × Miss penalty",
      formulaHint: "Keep all time units consistent. For multi-level caches, the L1 miss penalty includes the L2 access path.",
      exampleTitle: "Address split for a direct-mapped cache",
      exampleSteps: ["A 32 KiB cache with 64-byte blocks has 512 lines.", "Offset bits = log₂64 = 6; index bits = log₂512 = 9.", "For 32-bit addresses, tag bits = 32 − 9 − 6 = 17."],
      checkpoint: ["How many sets are present?", "Is addressing byte- or word-addressable?", "Does associativity change the number of index bits?"],
      traps: ["Using cache size instead of set count", "Adding miss rate and hit rate as percentages without conversion"],
    },
  },
  {
    id: "programming-data-structures",
    code: "PDS",
    title: "Programming & Data Structures",
    shortTitle: "Programming",
    description: "C programming, recursion, arrays, lists, stacks, queues, trees and heaps.",
    progress: 78,
    mastery: 81,
    questionCount: 344,
    estimatedHours: 16,
    accent: "#3f79c9",
    phase: "Core reasoning",
    topics: [
      topic("c-programming", "C Programming", 88, 92, "3h 20m"),
      topic("recursion", "Functions & Recursion", 78, 61, "2h 45m"),
      topic("linear-structures", "Arrays, Lists, Stacks & Queues", 74, 103, "4h 15m"),
      topic("trees-heaps", "Trees, BSTs & Heaps", 69, 88, "4h 00m"),
    ],
    note: {
      title: "Make the invariant explicit",
      summary: "A data structure is easiest to reason about when you state what remains true after every operation—heap order, stack discipline or BST ordering.",
      intuition: "In a binary heap, shape and order are separate invariants: it is complete as a tree, and each parent obeys the heap relation with its children.",
      formula: "parent(i)=⌊(i−1)/2⌋, left(i)=2i+1, right(i)=2i+2",
      formulaHint: "These indices assume a zero-based array representation.",
      exampleTitle: "Insert 18 into a max-heap",
      exampleSteps: ["Place 18 at the next available leaf to preserve completeness.", "Compare with its parent and swap while 18 is larger.", "Stop at the root or when the parent is at least 18."],
      checkpoint: ["Which invariant can the operation break?", "What is the worst-case tree height?", "Is the array zero- or one-indexed?"],
      traps: ["Confusing a heap with a sorted array", "Assuming a BST must be balanced"],
    },
  },
  {
    id: "algorithms",
    code: "ALG",
    title: "Algorithms",
    shortTitle: "Algorithms",
    description: "Searching, sorting, hashing, asymptotics, paradigms and graph algorithms.",
    progress: 63,
    mastery: 67,
    questionCount: 318,
    estimatedHours: 20,
    accent: "#8359c7",
    phase: "Core reasoning",
    topics: [
      topic("complexity", "Asymptotic Analysis", 82, 58, "2h 35m"),
      topic("sorting-searching", "Searching, Sorting & Hashing", 74, 70, "3h 30m"),
      topic("paradigms", "Algorithm Design Techniques", 49, 93, "5h 20m"),
      topic("graph-algorithms", "Graph Algorithms", 46, 97, "5h 10m"),
    ],
    note: {
      title: "A recurrence describes the work",
      summary: "For divide-and-conquer algorithms, separate the number of subproblems, their reduced size and the non-recursive combine work.",
      intuition: "A recursion tree makes the Master theorem visual: compare work at each level and see whether the root, every level or leaves dominate.",
      formula: "T(n) = aT(n/b) + f(n)",
      formulaHint: "Compare f(n) with n^(log_b a), including the polynomial gap conditions.",
      exampleTitle: "Solve T(n) = 2T(n/2) + n",
      exampleSteps: ["Here a=2, b=2, so n^(log₂2)=n.", "f(n)=Θ(n), matching the critical term.", "Master theorem case 2 gives T(n)=Θ(n log n)."],
      checkpoint: ["How many recursive children are created?", "What work happens outside recursion?", "Do Master theorem regularity conditions hold?"],
      traps: ["Dropping logarithmic factors", "Applying Master theorem to unequal subproblem sizes"],
    },
  },
  {
    id: "theory-computation",
    code: "TOC",
    title: "Theory of Computation",
    shortTitle: "Theory of Computation",
    description: "Regular languages, grammars, push-down automata, Turing machines and decidability.",
    progress: 38,
    mastery: 44,
    questionCount: 272,
    estimatedHours: 18,
    accent: "#c65d7b",
    phase: "Core reasoning",
    topics: [
      topic("regular-languages", "Regular Languages & Automata", 62, 84, "4h 10m"),
      topic("cfg-pda", "CFGs & Push-down Automata", 34, 76, "4h 00m"),
      topic("turing-machines", "Turing Machines", 24, 49, "2h 55m"),
      topic("decidability", "Undecidability", 18, 63, "3h 30m"),
    ],
    note: {
      title: "Track distinguishable futures",
      summary: "A DFA state represents all prefixes that have the same possible accepting continuations. Minimization merges only states with identical future behavior.",
      intuition: "Myhill–Nerode reasoning turns state counting into a proof: find prefixes that some suffix can distinguish.",
      formula: "p ≡L q iff ∀z: pz ∈ L ⇔ qz ∈ L",
      formulaHint: "The number of equivalence classes equals the state count of the minimal DFA.",
      exampleTitle: "Binary strings whose value is divisible by 3",
      exampleSteps: ["Use one state for each remainder 0, 1 and 2.", "Reading bit b changes remainder r to (2r+b) mod 3.", "Remainder 0 is the accepting state."],
      checkpoint: ["What information about the prefix affects the future?", "Can a suffix distinguish two candidate states?", "Is the language closed under the operation used?"],
      traps: ["Mistaking an NFA path for universal choice", "Using the pumping lemma to prove regularity"],
    },
  },
  {
    id: "compiler-design",
    code: "CD",
    title: "Compiler Design",
    shortTitle: "Compilers",
    description: "Lexical analysis, parsing, syntax-directed translation and runtime environments.",
    progress: 27,
    mastery: 35,
    questionCount: 184,
    estimatedHours: 13,
    accent: "#b9822b",
    phase: "Core reasoning",
    topics: [
      topic("lexical-analysis", "Lexical Analysis", 54, 38, "1h 55m"),
      topic("parsing", "Parsing", 24, 81, "4h 25m"),
      topic("syntax-directed", "Syntax-directed Translation", 18, 36, "2h 05m"),
      topic("runtime", "Runtime Environments", 20, 29, "1h 40m"),
    ],
    note: {
      title: "FIRST predicts, FOLLOW recovers",
      summary: "An LL(1) parser chooses one production using a single lookahead symbol. FIRST locates possible starts; FOLLOW matters when a production can derive ε.",
      intuition: "Each parsing-table cell must contain at most one production. A collision is direct evidence that the grammar is not LL(1) as written.",
      formula: "If ε ∈ FIRST(α), place A→α under every symbol in FOLLOW(A)",
      formulaHint: "Remove left recursion and left-factor before building an LL(1) table.",
      exampleTitle: "FIRST of E′ → +TE′ | ε",
      exampleSteps: ["The first alternative begins with terminal +.", "The second alternative derives ε.", "Therefore FIRST(E′) = { +, ε }."],
      checkpoint: ["Can the right side derive ε?", "Is the grammar left recursive?", "Do SELECT sets overlap?"],
      traps: ["Putting ε itself in the input columns", "Confusing left factoring with left recursion removal"],
    },
  },
  {
    id: "operating-systems",
    code: "OS",
    title: "Operating Systems",
    shortTitle: "Operating Systems",
    description: "Processes, concurrency, deadlocks, scheduling, memory and file systems.",
    progress: 59,
    mastery: 63,
    questionCount: 326,
    estimatedHours: 19,
    accent: "#4773b8",
    phase: "Systems",
    topics: [
      topic("processes-threads", "Processes, Threads & IPC", 78, 65, "3h 00m"),
      topic("concurrency", "Concurrency & Synchronization", 54, 86, "4h 20m"),
      topic("deadlocks", "Deadlocks", 61, 54, "2h 40m"),
      topic("memory", "Memory Management", 48, 79, "4h 05m"),
      topic("filesystems", "File Systems", 39, 42, "2h 10m"),
    ],
    note: {
      title: "Safety is not the same as deadlock",
      summary: "A safe state has at least one order in which every process can finish. An unsafe state is a warning: it may lead to deadlock, but it is not necessarily deadlocked yet.",
      intuition: "Banker’s algorithm repeatedly finds a process whose remaining need fits the current work vector, then releases its allocation.",
      formula: "Need = Max − Allocation",
      formulaHint: "A safe sequence exists only if the finish loop can include every process.",
      exampleTitle: "One-resource safety check",
      exampleSteps: ["Available is 2; P1 needs 1 and can finish first.", "Release P1’s allocation of 3, so work becomes 5.", "Any process needing at most 5 may now finish; continue until all are included."],
      checkpoint: ["Did you compute Need component-wise?", "Can at least one unfinished process proceed?", "Did released allocations return to Work?"],
      traps: ["Calling every unsafe state deadlocked", "Adding Max rather than Allocation after completion"],
    },
  },
  {
    id: "databases",
    code: "DBMS",
    title: "Databases",
    shortTitle: "Databases",
    description: "ER models, relational algebra, SQL, normalization, indexing and transactions.",
    progress: 65,
    mastery: 69,
    questionCount: 304,
    estimatedHours: 17,
    accent: "#6070b8",
    phase: "Systems",
    topics: [
      topic("relational-model", "ER & Relational Models", 82, 57, "2h 30m"),
      topic("sql-algebra", "SQL & Relational Algebra", 72, 79, "3h 40m"),
      topic("normalization", "Dependencies & Normalization", 51, 73, "3h 50m"),
      topic("indexing", "File Organization & Indexing", 55, 46, "2h 30m"),
      topic("transactions", "Transactions & Concurrency", 48, 49, "2h 45m"),
    ],
    note: {
      title: "A dependency is a statement about all valid rows",
      summary: "X → Y means that any two tuples agreeing on X must also agree on Y. Attribute closure turns this definition into a practical key and normalization tool.",
      intuition: "Start with X itself, repeatedly add attributes implied by dependencies, and stop when no new attribute can be added.",
      formula: "X is a superkey iff X⁺ contains every attribute of R",
      formulaHint: "A candidate key is a minimal superkey—remove each attribute and test again.",
      exampleTitle: "Find (A)⁺ for F = {A→B, B→C, CD→E}",
      exampleSteps: ["Begin with {A}.", "A→B adds B; then B→C adds C.", "D is absent, so CD→E cannot fire. Thus A⁺={A,B,C}."],
      checkpoint: ["Did you begin with every attribute in X?", "Can a newly added attribute trigger another FD?", "Is the superkey minimal?"],
      traps: ["Checking dependencies on one sample table only", "Confusing lossless join with dependency preservation"],
    },
  },
  {
    id: "computer-networks",
    code: "CN",
    title: "Computer Networks",
    shortTitle: "Networks",
    description: "Layering, switching, routing, transport protocols and application services.",
    progress: 47,
    mastery: 53,
    questionCount: 296,
    estimatedHours: 18,
    accent: "#397ba8",
    phase: "Systems",
    topics: [
      topic("link-layer", "Data Link Layer", 64, 61, "3h 00m"),
      topic("network-layer", "IP & Routing", 49, 89, "4h 30m"),
      topic("transport", "TCP & UDP", 37, 78, "4h 00m"),
      topic("application", "Application Layer", 42, 44, "2h 10m"),
    ],
    note: {
      title: "Longest prefix wins",
      summary: "IP forwarding compares a destination against routing prefixes and chooses the matching entry with the greatest prefix length, not the numerically closest network.",
      intuition: "A /24 route is more specific than a /16 route because it fixes more leading bits. A default /0 route matches everything but loses to any specific match.",
      formula: "Usable hosts in a /p IPv4 subnet = 2^(32−p) − 2",
      formulaHint: "The usual subtraction excludes network and broadcast addresses; treat special point-to-point cases separately only when stated.",
      exampleTitle: "Choose a route for 10.4.7.19",
      exampleSteps: ["Both 10.0.0.0/8 and 10.4.0.0/16 match.", "10.4.7.0/24 also matches and has the longest prefix.", "Forward through the next hop stored with the /24 entry."],
      checkpoint: ["Which prefixes actually match bit-for-bit?", "Which matching prefix is longest?", "Is the question asking host count or address count?"],
      traps: ["Choosing the route with the smallest metric before prefix length", "Confusing propagation delay with transmission delay"],
    },
  },
];

const options = (...labels: string[]) =>
  labels.map((label, index) => ({ id: String.fromCharCode(65 + index), label }));

export const practiceQuestions: PracticeQuestion[] = [
  {
    id: "coa-addressing-1",
    subjectId: "computer-organization",
    topicId: "instruction-set-addressing",
    type: "NAT",
    marks: 1,
    prompt: "An instruction uses base-plus-index addressing. The base register contains 1200, the index register contains 36, and the displacement is −12. What effective address is generated?",
    correct: ["1224"],
    explanation: "Effective address = base + index + displacement = 1200 + 36 − 12 = 1224.",
    source: "GATE 2027 syllabus check",
    difficulty: "Easy",
  },
  {
    id: "coa-alu-1",
    subjectId: "computer-organization",
    topicId: "alu-design",
    type: "MCQ",
    marks: 1,
    prompt: "Which hardware block lets one ALU perform ADD, AND, OR, and XOR under the control of function-select inputs?",
    options: options("A multiplexer that selects among operation results", "A program counter", "A cache tag comparator", "A memory address register"),
    correct: ["A"],
    explanation: "An ALU can compute candidate arithmetic and logic results in parallel and use function-select lines to choose the required result through a multiplexer.",
    source: "GATE 2027 syllabus check",
    difficulty: "Easy",
  },
  {
    id: "coa-control-1",
    subjectId: "computer-organization",
    topicId: "control-unit",
    type: "MSQ",
    marks: 2,
    prompt: "Which statements about hardwired and microprogrammed control units are correct?",
    options: options("Hardwired control is usually faster", "Microprogrammed control is generally easier to modify", "A control memory stores microinstructions", "Hardwired control always requires a writable control store"),
    correct: ["A", "B", "C"],
    explanation: "Hardwired logic usually has lower control latency, while microprogrammed control is easier to change and obtains control signals from microinstructions stored in control memory. A writable control store is not a requirement of hardwired control.",
    source: "GATE 2027 syllabus check",
    difficulty: "Medium",
  },
  {
    id: "coa-cache-1",
    subjectId: "computer-organization",
    topicId: "memory-hierarchy",
    type: "MCQ",
    marks: 1,
    prompt: "A 32 KiB direct-mapped cache uses 64-byte blocks and 32-bit byte addresses. How many tag bits does each cache line store?",
    options: options("15", "17", "19", "21"),
    correct: ["B"],
    explanation: "There are 32 KiB / 64 B = 512 lines, so the index uses 9 bits. The block offset uses 6 bits. Tag bits = 32 − 9 − 6 = 17.",
    source: "Local concept check",
    difficulty: "Medium",
  },
  {
    id: "coa-io-1",
    subjectId: "computer-organization",
    topicId: "io-interface",
    type: "MCQ",
    marks: 1,
    prompt: "Which I/O technique transfers a block between a device and main memory with the least per-word CPU involvement?",
    options: options("Programmed I/O", "Interrupt-driven I/O", "Direct memory access", "Busy waiting"),
    correct: ["C"],
    explanation: "With DMA, the CPU initializes the transfer and the DMA controller moves the block, interrupting the CPU when the operation completes.",
    source: "GATE 2027 syllabus check",
    difficulty: "Easy",
  },
  {
    id: "coa-pipe-1",
    subjectId: "computer-organization",
    topicId: "pipelining",
    type: "NAT",
    marks: 2,
    prompt: "An ideal 5-stage pipeline executes 100 instructions with one cycle per stage after filling. Enter the total number of cycles.",
    correct: ["104"],
    explanation: "For k stages and n instructions, ideal cycles are k + n − 1. Therefore 5 + 100 − 1 = 104.",
    source: "Local concept check",
    difficulty: "Easy",
  },
  {
    id: "coa-addressing-2",
    subjectId: "computer-organization",
    topicId: "instruction-set-addressing",
    type: "MSQ",
    marks: 2,
    prompt: "Which statements about common addressing modes are correct?",
    options: options("Immediate addressing keeps the operand in the instruction", "Register-indirect addressing keeps the operand address in a register", "Direct addressing requires the operand itself to be a register", "Indexed addressing can support array access"),
    correct: ["A", "B", "D"],
    explanation: "Immediate mode embeds the value, register-indirect mode uses a register as a pointer, and indexed addressing naturally supports arrays. Direct mode supplies a memory address, not a register operand requirement.",
    source: "GATE 2027 syllabus check",
    difficulty: "Medium",
  },
  {
    id: "coa-alu-2",
    subjectId: "computer-organization",
    topicId: "alu-design",
    type: "MSQ",
    marks: 2,
    prompt: "For an n-bit ALU, which statements are correct?",
    options: options("A ripple-carry adder propagates carry through successive bit positions", "Carry lookahead reduces carry-propagation delay", "Logical right shift always copies the sign bit", "An overflow flag can be derived from the carries into and out of the sign bit"),
    correct: ["A", "B", "D"],
    explanation: "Ripple carry is serial across bit positions; carry lookahead computes carry information in parallel; and signed overflow can be detected from the carry into and out of the most significant bit. Logical right shift inserts zero rather than copying the sign bit.",
    source: "GATE 2027 syllabus check",
    difficulty: "Medium",
  },
  {
    id: "coa-control-2",
    subjectId: "computer-organization",
    topicId: "control-unit",
    type: "NAT",
    marks: 1,
    prompt: "A microprogrammed control store contains 512 microinstructions. What is the minimum number of bits needed in the microaddress register to address every microinstruction?",
    correct: ["9"],
    explanation: "Because 512 = 2⁹, a 9-bit microaddress can select every control-store word.",
    source: "GATE 2027 syllabus check",
    difficulty: "Easy",
  },
  {
    id: "coa-cache-2",
    subjectId: "computer-organization",
    topicId: "memory-hierarchy",
    type: "NAT",
    marks: 2,
    prompt: "A cache has a hit time of 1 ns, a miss rate of 5%, and a miss penalty of 40 ns. Using AMAT = hit time + miss rate × miss penalty, what is the average memory access time in ns?",
    correct: ["3"],
    explanation: "AMAT = 1 + 0.05 × 40 = 1 + 2 = 3 ns.",
    source: "GATE 2027 syllabus check",
    difficulty: "Easy",
  },
  {
    id: "coa-io-2",
    subjectId: "computer-organization",
    topicId: "io-interface",
    type: "MSQ",
    marks: 2,
    prompt: "Which statements about interrupts and DMA are correct?",
    options: options("An interrupt can notify the CPU that an I/O operation has completed", "DMA may temporarily take control of the memory bus", "Programmed I/O eliminates CPU polling by definition", "A DMA completion can be reported with an interrupt"),
    correct: ["A", "B", "D"],
    explanation: "Interrupts notify the CPU asynchronously, and a DMA controller may become bus master while moving data. Programmed I/O commonly uses CPU polling, while DMA completion is often signalled by an interrupt.",
    source: "GATE 2027 syllabus check",
    difficulty: "Medium",
  },
  {
    id: "coa-pipe-2",
    subjectId: "computer-organization",
    topicId: "pipelining",
    type: "MSQ",
    marks: 2,
    prompt: "Which statements about a classic instruction pipeline are correct?",
    options: options("Two instructions needing the same single-ported memory in one cycle can cause a structural hazard", "A branch can cause a control hazard", "A read-after-write dependency is a data hazard", "Forwarding removes every possible pipeline stall"),
    correct: ["A", "B", "C"],
    explanation: "Resource conflicts are structural hazards, branches create control hazards, and read-after-write dependencies are data hazards. Forwarding helps many dependencies but cannot remove every stall, such as some load-use cases.",
    source: "GATE 2027 syllabus check",
    difficulty: "Medium",
  },
  {
    id: "coa-addressing-3",
    subjectId: "computer-organization",
    topicId: "instruction-set-addressing",
    type: "NAT",
    marks: 2,
    prompt: "A fixed-length instruction is 32 bits wide and reserves 5 bits for each of three register fields. If all remaining bits form the opcode, how many distinct opcodes can be encoded?",
    correct: ["131072"],
    explanation: "The register fields use 15 bits, leaving 17 opcode bits. Therefore the format can encode 2¹⁷ = 131072 opcodes.",
    source: "GATE 2027 syllabus check",
    difficulty: "Medium",
  },
  {
    id: "coa-alu-3",
    subjectId: "computer-organization",
    topicId: "alu-design",
    type: "NAT",
    marks: 1,
    prompt: "A 4-bit ripple-carry adder has a worst-case carry propagation delay of 2 ns per bit position. Ignoring all other delays, what is its worst-case carry delay in ns?",
    correct: ["8"],
    explanation: "The carry may ripple through all four bit positions, so the worst-case delay is 4 × 2 = 8 ns.",
    source: "GATE 2027 syllabus check",
    difficulty: "Easy",
  },
  {
    id: "coa-control-3",
    subjectId: "computer-organization",
    topicId: "control-unit",
    type: "MCQ",
    marks: 1,
    prompt: "Compared with a highly encoded vertical microinstruction, a horizontal microinstruction typically has:",
    options: options("A wider control word and more directly specified control signals", "A narrower word and more decoding", "No control memory", "No next-address information"),
    correct: ["A"],
    explanation: "Horizontal microcode uses a wider word with control bits that map more directly to datapath signals, trading storage width for parallelism and less decoding.",
    source: "GATE 2027 syllabus check",
    difficulty: "Medium",
  },
  {
    id: "coa-cache-3",
    subjectId: "computer-organization",
    topicId: "memory-hierarchy",
    type: "NAT",
    marks: 2,
    prompt: "How many 16 Ki × 8-bit memory chips are required to build a 64 Ki × 16-bit memory module?",
    correct: ["8"],
    explanation: "Four banks are needed to increase the depth from 16 Ki to 64 Ki, and two chips operate in parallel to increase the word width from 8 to 16 bits. Therefore 4 × 2 = 8 chips are required.",
    source: "GATE 2027 syllabus check",
    difficulty: "Medium",
  },
  {
    id: "coa-io-3",
    subjectId: "computer-organization",
    topicId: "io-interface",
    type: "NAT",
    marks: 1,
    prompt: "A DMA controller transfers 4096 bytes over a 32-bit data bus, moving one full bus word per transfer cycle. How many transfer cycles are required?",
    correct: ["1024"],
    explanation: "A 32-bit word is 4 bytes. Therefore 4096/4 = 1024 transfer cycles are needed.",
    source: "GATE 2027 syllabus check",
    difficulty: "Easy",
  },
  {
    id: "coa-pipe-3",
    subjectId: "computer-organization",
    topicId: "pipelining",
    type: "NAT",
    marks: 2,
    prompt: "A 5-stage pipeline executes 20 instructions and incurs 4 stall cycles. Assuming one cycle per stage, how many total cycles are required?",
    correct: ["28"],
    explanation: "Ideal cycles are k + n − 1 = 5 + 20 − 1 = 24. Adding 4 stall cycles gives 28 total cycles.",
    source: "GATE 2027 syllabus check",
    difficulty: "Medium",
  },
  {
    id: "algo-1",
    subjectId: "algorithms",
    topicId: "complexity",
    type: "MCQ",
    marks: 1,
    prompt: "Which asymptotic bound solves T(n) = 2T(n/2) + n for n greater than 1?",
    options: options("Θ(log n)", "Θ(n)", "Θ(n log n)", "Θ(n²)"),
    correct: ["C"],
    explanation: "The recursive and combine terms contribute Θ(n) per level across log n levels, giving Θ(n log n).",
    source: "Local concept check",
    difficulty: "Easy",
  },
  {
    id: "algo-2",
    subjectId: "algorithms",
    topicId: "graph-algorithms",
    type: "MSQ",
    marks: 2,
    prompt: "Select every statement that is true for a connected, weighted, undirected graph with distinct edge weights.",
    options: options("The minimum spanning tree is unique", "Every lightest edge across a cut belongs to the MST", "Dijkstra works with negative edges", "Kruskal may use a disjoint-set structure"),
    correct: ["A", "B", "D"],
    explanation: "Distinct weights imply a unique MST; the cut property includes the unique lightest crossing edge; and Kruskal commonly uses disjoint sets. Dijkstra requires non-negative edge weights.",
    source: "Local concept check",
    difficulty: "Medium",
  },
  {
    id: "os-1",
    subjectId: "operating-systems",
    topicId: "deadlocks",
    type: "MSQ",
    marks: 2,
    prompt: "Which are necessary Coffman conditions for deadlock?",
    options: options("Mutual exclusion", "Hold and wait", "Preemption is mandatory", "Circular wait"),
    correct: ["A", "B", "D"],
    explanation: "The four necessary conditions are mutual exclusion, hold and wait, no preemption, and circular wait.",
    source: "Local concept check",
    difficulty: "Easy",
  },
  {
    id: "db-1",
    subjectId: "databases",
    topicId: "normalization",
    type: "MCQ",
    marks: 1,
    prompt: "For R(A,B,C) with F = {A→B, B→C}, which is a candidate key?",
    options: options("A", "B", "C", "BC"),
    correct: ["A"],
    explanation: "A⁺ = {A,B,C}, so A is a superkey. It is already minimal, hence a candidate key.",
    source: "Local concept check",
    difficulty: "Easy",
  },
  {
    id: "cn-1",
    subjectId: "computer-networks",
    topicId: "network-layer",
    type: "NAT",
    marks: 1,
    prompt: "How many usable host addresses are available in a conventional IPv4 /27 subnet?",
    correct: ["30"],
    explanation: "A /27 leaves 5 host bits, giving 2⁵ = 32 addresses. Excluding the network and broadcast addresses leaves 30.",
    source: "Local concept check",
    difficulty: "Easy",
  },
  {
    id: "toc-1",
    subjectId: "theory-computation",
    topicId: "regular-languages",
    type: "MSQ",
    marks: 2,
    prompt: "Which operations preserve regularity when applied to regular languages?",
    options: options("Union", "Intersection", "Complement", "Set difference"),
    correct: ["A", "B", "C", "D"],
    explanation: "Regular languages are closed under all four operations. Difference follows from intersection with the complement.",
    source: "Local concept check",
    difficulty: "Medium",
  },
  {
    id: "dl-1",
    subjectId: "digital-logic",
    topicId: "boolean-algebra",
    type: "MCQ",
    marks: 1,
    prompt: "The Boolean expression X + X̄Y simplifies to:",
    options: options("X", "Y", "X + Y", "XY"),
    correct: ["C"],
    explanation: "X + X̄Y = (X + X̄)(X + Y) = 1·(X + Y) = X + Y.",
    source: "Local concept check",
    difficulty: "Easy",
  },
  {
    id: "math-1",
    subjectId: "engineering-mathematics",
    topicId: "discrete-math",
    type: "NAT",
    marks: 2,
    prompt: "How many edges are present in the complete graph K₈?",
    correct: ["28"],
    explanation: "A complete graph on n vertices has n(n−1)/2 edges. For n=8, this is 8×7/2 = 28.",
    source: "Local concept check",
    difficulty: "Easy",
  },
  {
    id: "compiler-1",
    subjectId: "compiler-design",
    topicId: "parsing",
    type: "MCQ",
    marks: 1,
    prompt: "Which transformation is normally required before constructing an LL(1) table for E → E + T | T?",
    options: options("Remove left recursion", "Remove all terminals", "Convert to Chomsky normal form", "Introduce ambiguity"),
    correct: ["A"],
    explanation: "The grammar is immediately left recursive. LL(1) predictive parsing requires that left recursion be removed.",
    source: "Local concept check",
    difficulty: "Easy",
  },
  {
    id: "pds-1",
    subjectId: "programming-data-structures",
    topicId: "trees-heaps",
    type: "NAT",
    marks: 1,
    prompt: "What is the maximum number of nodes at level 5 of a binary tree when the root is at level 0?",
    correct: ["32"],
    explanation: "A binary tree has at most 2ˡ nodes at level l. At level 5, that is 2⁵ = 32.",
    source: "Local concept check",
    difficulty: "Easy",
  },
];

const mockTemplates = [
  ...practiceQuestions,
  {
    id: "ga-logic",
    subjectId: "general-aptitude",
    topicId: "analytical-aptitude",
    type: "MCQ" as const,
    marks: 1 as const,
    prompt: "If every compiler is a translator and some translators are interpreters, which conclusion must be true?",
    options: options("Every interpreter is a compiler", "Every compiler is a translator", "No compiler is an interpreter", "Some compilers are interpreters"),
    correct: ["B"],
    explanation: "The first statement directly establishes that every compiler belongs to the set of translators; the other conclusions do not necessarily follow.",
    source: "Local mock sample",
    difficulty: "Easy" as const,
  },
  {
    id: "ga-quant",
    subjectId: "general-aptitude",
    topicId: "quantitative-aptitude",
    type: "NAT" as const,
    marks: 2 as const,
    prompt: "A value rises from 80 to 100. Enter the percentage increase.",
    correct: ["25"],
    explanation: "The increase is 20 on a base of 80, so the percentage increase is 20/80 × 100 = 25.",
    source: "Local mock sample",
    difficulty: "Easy" as const,
  },
];

export function buildMockQuestions(): PracticeQuestion[] {
  const list: PracticeQuestion[] = [];
  const mathematicsTemplate = practiceQuestions.find(
    (question) => question.subjectId === "engineering-mathematics",
  ) ?? practiceQuestions[0];
  const coreTemplates = practiceQuestions.filter(
    (question) => question.subjectId !== "engineering-mathematics",
  );
  for (let i = 0; i < 65; i += 1) {
    const isGA = i < 10;
    const isMathematics =
      (i >= 10 && i < 15) || (i >= 35 && i < 39);
    const base = isGA
      ? mockTemplates[mockTemplates.length - 2 + (i % 2)]
      : isMathematics
        ? mathematicsTemplate
        : coreTemplates[i % coreTemplates.length];
    // Official 100-mark distribution: GA has 5×1 + 5×2 and the
    // 55 subject questions have 25×1 + 30×2.
    const marks: 1 | 2 = i < 5 || (i >= 10 && i < 35) ? 1 : 2;
    list.push({
      ...base,
      id: `mock-${String(i + 1).padStart(2, "0")}`,
      marks,
      subjectId: isGA
        ? "general-aptitude"
        : isMathematics
          ? "engineering-mathematics"
          : base.subjectId,
      source: "Local mock sample",
    });
  }
  return list;
}

export const weeklyActivity = [
  { day: "M", minutes: 82 },
  { day: "T", minutes: 48 },
  { day: "W", minutes: 104 },
  { day: "T", minutes: 66 },
  { day: "F", minutes: 91 },
  { day: "S", minutes: 122 },
  { day: "S", minutes: 36 },
];
