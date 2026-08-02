import type { LearningTopic } from "../types";

const summaryExtension = (topic: LearningTopic): string => {
  switch (topic.subjectCode) {
    case "TOC":
      return `Study ${topic.title} by moving between a formal definition and a concrete language witness: build one valid recognizer or derivation, test a near-miss, and state the exact closure, acceptance, or decidability claim before drawing a conclusion.`;
    case "CD":
      return `For ${topic.title}, follow a small source fragment through the relevant compiler representation, record the invariant expected at the phase boundary, and connect each table, tree, graph, environment, or instruction back to the program meaning it must preserve.`;
    case "OS":
      return `Learn ${topic.title} through explicit machine-state snapshots: identify the active process or thread, owned and requested resources, triggering event, and measurable cost, then compare the state before and after the operating-system action.`;
    case "DBMS":
      return `Approach ${topic.title} with a tiny legal database instance or schedule, apply the rule step by step, and then alter one tuple, dependency, key value, or operation order to expose exactly when the claimed property stops holding.`;
    case "CN":
      return `For ${topic.title}, place each action at its correct layer, annotate a packet or timing line with headers, addresses, units, and state, and verify both the path through the network and the endpoint behavior at boundary conditions.`;
    case "GA":
      return `Practise ${topic.title} by externalizing the evidence in a sentence map, constraint table, labelled diagram, or unit-aware calculation, eliminating choices against that representation, and finishing with an independent grammar, magnitude, logic, or symmetry check.`;
    default:
      return `Develop ${topic.title} from its governing model, work a representative case, and test the result against the assumptions and boundary conditions stated in the official syllabus.`;
  }
};

const conceptFocus = (subjectCode: string, title: string): string => {
  if (subjectCode === "TOC") {
    if (/DFA|NFA|Regular expressions|state/i.test(title)) return "a transition table, a complete string trace, and a distinguishing suffix";
    if (/Production|Parse|Grammar|derivation/i.test(title)) return "a full derivation alongside the corresponding parse structure";
    if (/PDA|stack|CFG-PDA/i.test(title)) return "an instantaneous configuration containing state, unread input, and stack contents";
    if (/Pumping/i.test(title)) return "the pumping quantifiers, an adversarial decomposition, and a witness that defeats every legal split";
    if (/Closure|decision/i.test(title)) return "the direction of the closure construction and a counterexample to any unsupported converse";
    return "a machine configuration, halting outcome, language witness, and correctly directed reduction";
  }

  if (subjectCode === "CD") {
    if (/Token|Automata|lexeme|Disambiguation/i.test(title)) return "the source characters, maximal token boundary, recognizer state, and emitted token stream";
    if (/FIRST|FOLLOW|parsing|Grammar|LR/i.test(title)) return "the grammar item or parser stack, lookahead symbol, table entry, and resulting parser action";
    if (/Attribute|semantic|Dependency|attributed/i.test(title)) return "the parse-tree dependencies and the order in which semantic values become available";
    if (/Activation|links|Storage|parameters/i.test(title)) return "the call sequence, activation-record fields, binding path, and lifetime of each stored value";
    if (/Three-address|Trees|DAG|Control-flow translation/i.test(title)) return "the source expression, generated intermediate form, evaluation order, and any safely reused value";
    return "the control-flow graph, predecessor facts, transfer result, and meet value at every affected program point";
  }

  if (subjectCode === "OS") {
    if (/kernel|Process-control|I\/O calls/i.test(title)) return "the user/kernel boundary, call arguments, process state, and return or blocking event";
    if (/Process states|Thread|IPC|threading/i.test(title)) return "a state-transition timeline plus the resources that are private, shared, or transferred";
    if (/Race|Semaphore|mutex|Monitor|classical/i.test(title)) return "one interleaving, the protected invariant, and the happens-before relation created by synchronization";
    if (/Necessary conditions|Safe states|Handling/i.test(title)) return "the allocation and request state, wait-for relation, and a concrete completion or deadlock sequence";
    if (/scheduling|CPU policies|Disk/i.test(title)) return "an arrival-and-service timeline with every waiting, turnaround, response, or seek quantity labelled";
    if (/Allocation|Page tables|paging|replacement/i.test(title)) return "the virtual address fields, translation path, resident-set change, and memory-access cost";
    return "the directory or inode lookup path, logical-to-physical block mapping, and metadata or free-space update";
  }

  if (subjectCode === "DBMS") {
    if (/Entities|Relationships|Weak/i.test(title)) return "a small ER instance with keys, participation, cardinality, and the exact relational mapping";
    if (/Relations and algebra|Joins|calculus/i.test(title)) return "a tiny relation instance, tuple lineage through each operator, and one tuple that tests the predicate boundary";
    if (/Query|Grouping|Subqueries|NULL/i.test(title)) return "the logical SQL processing stages, intermediate rows or groups, and three-valued truth where NULL appears";
    if (/Domains|Referential|Constraint/i.test(title)) return "the database state before and after one insert, delete, or update that challenges the constraint";
    if (/Functional|Normal-form|Decomposition/i.test(title)) return "attribute closure, a candidate-key check, and a legal relation instance or join that exposes anomalies";
    if (/File|tree|Index/i.test(title)) return "the search path, page occupancy, fan-out, and number of disk-page reads or writes";
    return "the read/write schedule, precedence edges, lock or log actions, and the database state after failure or recovery";
  }

  if (subjectCode === "CN") {
    if (/Services|encapsulation|switching|Virtual circuits/i.test(title)) return "an end-to-end packet journey showing encapsulation, forwarding state, and the service exposed at each layer";
    if (/Framing|Medium|Ethernet/i.test(title)) return "the transmitted bit or frame sequence, error or contention event, and switch or access-control state";
    if (/Shortest|Distance-vector|Link-state/i.test(title)) return "a weighted topology, one algorithm iteration, and the resulting next-hop entry";
    if (/CIDR|Fragmentation|NAT|PAT/i.test(title)) return "the packet's address and header fields before and after forwarding, fragmentation, or boundary translation";
    if (/Ports|TCP|Connection|congestion/i.test(title)) return "a segment timeline with ports, sequence ranges, acknowledgements, windows, timers, and sender state";
    if (/DNS|HTTP|Email|file transfer/i.test(title)) return "the ordered application exchange, names or status fields, transport connection use, and cache or server state";
    return "a timing diagram whose propagation, transmission, queueing, processing, bandwidth, and byte/bit units remain explicit";
  }

  if (/Grammar|Vocabulary|Comprehension/i.test(title)) return "the exact words supplying agreement, reference, contrast, sequence, or passage evidence";
  if (/Ratio|Counting|Data|statistics|mensuration|probability/i.test(title)) return "a quantity table with its base, denominator, sample space, scale, and physical units";
  if (/Deduction|Ordering|Analogy|constraint|induction/i.test(title)) return "a symbolic implication, constraint grid, countermodel, or term-by-term pattern test";
  return "a labelled sketch that preserves adjacency, handedness, fold order, orientation, and any coincident images";
};

const reasoningExtension = (subjectCode: string, title: string, variant: number): string => {
  const focus = conceptFocus(subjectCode, title);
  const label = title.toLowerCase();

  if (variant % 3 === 0) {
    return `Reason about ${label} using ${focus}. Name the governing invariant before computing, preserve every stated convention, and test the smallest nontrivial or boundary case. A final answer is credible only when the constructed trace or evidence still supports it without importing an unstated assumption.`;
  }
  if (variant % 3 === 1) {
    return `A reliable analysis of ${label} starts with ${focus}. Carry the representation through one complete example, then change a single input condition to see which conclusion changes. This contrast separates a definition from its converse and exposes distractors that are correct only for a convenient special case.`;
  }
  return `For ${label}, write down ${focus} before evaluating options. Keep the representation consistent from the initial condition to the claimed outcome, and challenge it with one near-miss or counterexample. Also verify the relevant endpoint, empty case, unit, or tie convention instead of letting an implicit default decide the result.`;
};

const lesson = (topic: LearningTopic): LearningTopic => ({
  ...topic,
  summary: `${topic.summary} ${summaryExtension(topic)}`,
  concepts: topic.concepts.map((entry, index) => ({
    ...entry,
    explanation: `${entry.explanation} ${reasoningExtension(topic.subjectCode, entry.title, index)}`,
  })),
});

const concept = (
  title: string,
  explanation: string,
  keyIdeas: string[],
  examFocus: string,
  prompt: string,
  walkthrough: string,
): LearningTopic["concepts"][number] => ({
  title,
  explanation,
  keyIdeas,
  examFocus,
  example: { prompt, walkthrough },
});

const tocTopics: LearningTopic[] = [
  lesson({
    subjectCode: "TOC",
    subjectId: "theory-of-computation",
    topicId: "regular-expressions-and-finite-automata",
    title: "Regular Expressions and Finite Automata",
    summary: "Regular expressions, DFAs, and NFAs describe exactly the regular languages, while closure, subset construction, state equivalence, and minimization provide the main tools for constructing and comparing recognizers.",
    estimatedMinutes: 65,
    prerequisites: ["Sets and functions", "Basic propositional logic"],
    objectives: [
      "Translate between a regular expression and a finite automaton",
      "Execute subset construction and epsilon-closure correctly",
      "Minimize a DFA using distinguishable states",
      "Apply closure properties to regular-language questions",
    ],
    concepts: [
      concept(
        "DFA state meaning",
        "A deterministic finite automaton stores only the finite information about the prefix that can affect future acceptance. Every state therefore represents an equivalence class of prefixes, the transition function updates that class after one symbol, and acceptance depends only on the final class rather than the complete input history.",
        ["One transition per state-symbol pair", "A state summarizes relevant prefix history", "Acceptance is tested after the whole string"],
        "Trace strings carefully and distinguish a missing transition from an implicit dead state.",
        "Build a DFA over {0,1} that accepts strings with an even number of 1s.",
        "Use E for even parity and O for odd parity. Symbol 0 leaves parity unchanged, while 1 toggles E and O. Start in E and make only E accepting; for 1011 the trace E→O→O→E→O rejects.",
      ),
      concept(
        "NFA equivalence and subset construction",
        "An NFA may offer several next states and epsilon moves, yet it accepts when at least one complete path ends in an accepting state. Subset construction records the entire reachable NFA-state set as one DFA state. Epsilon-closure must be applied initially and after every symbol-induced move, otherwise reachable accepting paths are lost.",
        ["Nondeterministic choice is existential", "A DFA state is a set of NFA states", "Epsilon-closure consumes no input"],
        "Compute reachable subsets only; inaccessible powerset members do not become DFA states.",
        "An NFA starts at q0, has q0 --ε→ q1, and q1 --a→ q2 where q2 is final. What is the DFA move on a?",
        "The initial DFA state is ε-closure({q0})={q0,q1}. On a, q0 contributes nothing and q1 reaches q2. The closure of {q2} is {q2}, an accepting DFA state because it contains the NFA final state.",
      ),
      concept(
        "Regular expressions and minimization",
        "A regular expression denotes a language through union, concatenation, and Kleene star. Thompson-style fragments can turn it into an epsilon-NFA, while state elimination can move back toward an expression. DFA minimization instead partitions states by future behavior: accepting and nonaccepting states begin separated, then transitions repeatedly refine the partition until it is stable.",
        ["Union means alternative", "Concatenation preserves order", "Equivalent DFA states have identical accepting futures"],
        "Use a distinguishing suffix to prove that two states cannot be merged.",
        "Can states p and q be equivalent if reading 01 from p accepts but reading 01 from q rejects?",
        "No. The suffix 01 distinguishes the states: appending the same suffix produces different acceptance outcomes. They belong to different Myhill-Nerode classes and must remain in separate blocks during partition refinement.",
      ),
    ],
    formulae: [
      { label: "DFA transition extension", expression: "δ*(q, xa) = δ(δ*(q, x), a)", useWhen: "Tracing a complete string through a DFA" },
      { label: "Subset move", expression: "D(S, a) = ε-closure(⋃q∈S δN(q,a))", useWhen: "Converting an epsilon-NFA to a DFA" },
    ],
    checkpoints: [
      { question: "Can an NFA recognize a language that no DFA recognizes?", answer: "No. NFAs and DFAs have equal expressive power; subset construction produces an equivalent DFA, although it may have exponentially more states." },
      { question: "Why is a dead state sometimes necessary in a DFA?", answer: "A DFA transition function is total, so every state-symbol pair needs a destination. The dead state absorbs combinations from which acceptance is impossible." },
      { question: "What proves two DFA states distinguishable?", answer: "A suffix that is accepted from exactly one of the two states proves their future behaviors differ, so minimization cannot merge them." },
      { question: "Does epsilon in a regular expression mean the empty language?", answer: "No. ε denotes the language containing the empty string, whereas ∅ denotes a language containing no strings at all." },
      { question: "When is a DFA state accepting after subset construction?", answer: "The subset is accepting whenever it contains at least one accepting NFA state, matching the NFA's existential acceptance rule." },
    ],
  }),
  lesson({
    subjectCode: "TOC",
    subjectId: "theory-of-computation",
    topicId: "context-free-grammars",
    title: "Context-Free Grammars",
    summary: "Context-free grammars describe recursive syntactic structure through productions, derivations, parse trees, normal forms, and ambiguity, providing a precise way to reason about nested languages beyond finite-state memory.",
    estimatedMinutes: 60,
    prerequisites: ["Regular languages", "Trees and recursion"],
    objectives: ["Generate strings using leftmost and rightmost derivations", "Construct and interpret parse trees", "Identify ambiguity in a grammar", "Simplify grammars and reason about normal forms"],
    concepts: [
      concept(
        "Productions and derivations",
        "A context-free production replaces one nonterminal by a string of terminals and nonterminals, regardless of the surrounding symbols. A derivation is a sequence of such replacements beginning at the start symbol. Leftmost and rightmost derivations constrain which pending nonterminal is expanded, but both can describe the same parse tree and terminal string.",
        ["One nonterminal appears on a production's left side", "Sentential forms may mix terminals and nonterminals", "A terminal string ends a successful derivation"],
        "Do not confuse the order of derivation steps with the left-to-right order of terminals in the resulting string.",
        "For S→aSb | ε, derive aabb using a leftmost derivation.",
        "Start S⇒aSb. Expand the only nonterminal again: aaSbb. Finally apply S→ε to obtain aabb. The construction pairs each leading a with one trailing b, so every generated string has equal block lengths.",
      ),
      concept(
        "Parse trees and ambiguity",
        "A parse tree records hierarchical production choices: the root is the start symbol, internal nodes are nonterminals, and leaves read left to right form the derived string. A grammar is ambiguous when some string has two distinct parse trees, equivalently two different leftmost derivations. Ambiguity belongs to a grammar; inherent ambiguity is a stronger property of a language.",
        ["Leaves yield the input string", "Distinct parse trees establish grammar ambiguity", "Operator precedence can remove common expression ambiguity"],
        "To prove ambiguity, exhibit one concrete string and two complete structures rather than merely claiming productions overlap.",
        "Why is E→E+E | E*E | id ambiguous for id+id*id?",
        "One tree groups the expression as id+(id*id), placing multiplication lower in the tree. Another groups it as (id+id)*id. Both yield the same terminal string but encode different operation orders, so the grammar is ambiguous.",
      ),
      concept(
        "Grammar simplification and normal forms",
        "Grammar cleanup removes useless symbols, epsilon productions, and unit productions while preserving the intended language, with careful treatment of the empty string. Chomsky normal form restricts productions to A→BC or A→a, plus a controlled start-to-epsilon rule. The transformation can add helper variables but does not claim that every context-free language becomes regular.",
        ["Generating and reachable are separate usefulness tests", "Unit productions have one nonterminal on the right", "CNF parse trees are binary"],
        "Track whether ε belongs to the original language before eliminating nullable productions.",
        "A grammar has S→AB, A→a, B→b. Is it already in CNF?",
        "Yes. S→AB has exactly two nonterminals, and A→a and B→b each produce one terminal. If S is not used on any right side, no additional start symbol is required for this grammar.",
      ),
    ],
    formulae: [
      { label: "CFG form", expression: "G = (V, Σ, P, S), with productions A→α", useWhen: "Checking whether a production system is context free" },
      { label: "CNF production rule", expression: "A→BC or A→a (and optionally S₀→ε)", useWhen: "Recognizing or constructing Chomsky normal form" },
    ],
    checkpoints: [
      { question: "Can two different derivation orders represent the same parse tree?", answer: "Yes. A leftmost and a rightmost derivation may expand nodes in different orders while recording the same production choices and parse tree." },
      { question: "What is required to prove that a grammar is ambiguous?", answer: "Provide one generated string with two distinct parse trees, or equivalently two distinct leftmost or two distinct rightmost derivations." },
      { question: "Is every regular language context free?", answer: "Yes. A regular grammar is a restricted context-free grammar, and every finite automaton can be represented by an equivalent CFG." },
      { question: "Why test both generating and reachable symbols?", answer: "A symbol may derive terminals but never be reached from the start, or be reachable but never finish as terminals; either condition makes it useless." },
      { question: "Does converting a grammar to CNF remove language ambiguity?", answer: "No. CNF standardizes production shapes but does not generally eliminate ambiguity in the grammar or inherent ambiguity in the language." },
    ],
  }),
  lesson({
    subjectCode: "TOC",
    subjectId: "theory-of-computation",
    topicId: "pushdown-automata",
    title: "Pushdown Automata",
    summary: "Pushdown automata combine finite control with an unbounded stack, enabling recognition of nested and matched context-free patterns while exposing the distinction between deterministic and nondeterministic stack behavior.",
    estimatedMinutes: 50,
    prerequisites: ["Context-free grammars", "Finite automata", "Stacks"],
    objectives: ["Trace PDA configurations", "Design stack actions for matched languages", "Relate PDAs and context-free grammars", "Distinguish acceptance by state and empty stack"],
    concepts: [
      concept(
        "Configurations and stack actions",
        "A PDA configuration records the control state, unread input, and complete stack. A transition may consume one symbol or epsilon, inspect the top stack symbol, and replace that symbol by a stack string. Because only the top is directly visible, a good design stores precisely the unmatched obligations needed for the future input.",
        ["The stack is last-in first-out", "Epsilon transitions consume no input", "A transition can push, pop, or replace the top"],
        "Write all three configuration components during a trace; ignoring unread input creates false accepting paths.",
        "Sketch a PDA strategy for L={a^n b^n | n≥0}.",
        "In the first phase, push one marker for every a. Nondeterministically or on the first b, enter the second phase and pop one marker per b. Accept only when the input is exhausted and the bottom marker is exposed; ε is accepted directly.",
      ),
      concept(
        "Nondeterminism and language power",
        "Nondeterministic PDAs recognize exactly the context-free languages. Unlike finite automata, deterministic and nondeterministic pushdown automata do not have equal power: some context-free languages need a nondeterministic choice about where the input changes role. A transition trace therefore asks whether at least one legal computation accepts, not whether all choices succeed.",
        ["NPDA equals context-free language power", "DPDA languages form a proper subset", "Acceptance is existential across computation branches"],
        "A failed branch does not reject an NPDA input if another branch consumes the full string and accepts.",
        "Why can a palindrome PDA use nondeterminism?",
        "While pushing the first part, the machine may guess the midpoint without a separator. The successful branch switches at the true midpoint and compares the remaining symbols by popping; incorrect guesses die, but existential acceptance preserves the successful one.",
      ),
      concept(
        "CFG-PDA correspondence",
        "A CFG can be simulated by pushing its start symbol and nondeterministically replacing a nonterminal on the stack by a production right side, while terminals are matched against input. Conversely, PDA behavior can be encoded by grammar variables describing state-to-state stack removal. These constructions establish equivalence of language classes, though not identical operational efficiency.",
        ["Grammar expansion corresponds to stack replacement", "Terminal matching consumes input", "Equivalence concerns accepted languages"],
        "Keep the order of pushed symbols consistent with which symbol must be processed first at the stack top.",
        "For S→aSb | ε, what stack replacement supports the production aSb?",
        "If the implementation processes the leftmost grammar symbol first, replace S so that a becomes the next stack top, followed by S and b underneath in the representation's chosen push order. Then match a, expand S recursively, and finally match b.",
      ),
    ],
    formulae: [
      { label: "PDA transition type", expression: "δ(q, a or ε, X) ⊆ Q × Γ*", useWhen: "Interpreting a transition that reads input and rewrites the stack top" },
      { label: "Class equivalence", expression: "Languages accepted by NPDAs = Context-free languages", useWhen: "Comparing grammar and automaton expressive power" },
    ],
    checkpoints: [
      { question: "May a PDA transition read no input?", answer: "Yes. An epsilon transition can change state or stack while leaving the unread input unchanged, provided its stack condition is met." },
      { question: "Does a PDA have random access to its stack?", answer: "No. It can inspect and replace only the top symbol in one transition; deeper symbols become visible after intervening symbols are popped." },
      { question: "Are DPDAs as powerful as NPDAs?", answer: "No. Deterministic context-free languages are a proper subset of context-free languages, unlike the DFA-NFA equivalence for regular languages." },
      { question: "What must an accepting PDA path do with the input?", answer: "It must consume the entire input under the stated acceptance convention; reaching a final state early while symbols remain is not sufficient." },
      { question: "Can acceptance by empty stack and final state define the same CFL class?", answer: "Yes for nondeterministic PDAs. Standard constructions convert between the two conventions while preserving the accepted language." },
    ],
  }),
  lesson({
    subjectCode: "TOC",
    subjectId: "theory-of-computation",
    topicId: "pumping-lemmas-and-language-properties",
    title: "Pumping Lemmas and Language Properties",
    summary: "Pumping lemmas supply necessary repetition properties for regular and context-free languages, while closure and decision properties offer complementary tools for proving non-membership and classifying language operations.",
    estimatedMinutes: 55,
    prerequisites: ["Regular languages", "Context-free grammars", "Proof by contradiction"],
    objectives: ["Use quantifiers in pumping arguments correctly", "Choose effective witness strings", "Apply closure properties to language proofs", "Separate necessary conditions from sufficient conditions"],
    concepts: [
      concept(
        "Regular pumping lemma",
        "If a language is regular, every sufficiently long accepted string contains an early nonempty segment that can be repeated any number of times without leaving the language. In a nonregularity proof, the adversary chooses a legal split after the learner chooses the witness, so the contradiction must work for every split meeting the length constraints.",
        ["Choose a string at least the pumping length", "The pumped segment is nonempty and lies early", "One pumping exponent must break every legal split"],
        "Respect the quantifier order; selecting the decomposition yourself does not disprove regularity.",
        "Show why L={0^n1^n | n≥0} violates the regular pumping property.",
        "Assume pumping length p and choose 0^p1^p. Every legal y within the first p symbols contains only zeros and at least one zero. Pumping y twice increases zeros without changing ones, producing unequal counts, so the pumped string leaves L for every legal split.",
      ),
      concept(
        "Context-free pumping lemma",
        "For a sufficiently long string in a CFL, a decomposition uvxyz exists where v and y are pumped together, at least one is nonempty, and the combined window vxy is bounded by the pumping length. The extra freedom makes CFL non-membership proofs harder; the witness and case analysis must defeat all placements of both pumped pieces.",
        ["v and y pump synchronously", "|vy| is positive", "|vxy| is bounded"],
        "Partition possible locations of v and y systematically; do not assume both occupy the same symbol block.",
        "Why is 0^p1^p2^p a useful witness against context-freeness?",
        "The bounded window vxy cannot cover all three long blocks. Pumping v and y therefore changes at most two blocks while leaving at least one count fixed, or disrupts block order. In every case the equality among all three counts fails.",
      ),
      concept(
        "Closure and decision properties",
        "Regular languages are closed under union, intersection, complement, difference, concatenation, star, and reversal. CFLs are closed under union, concatenation, star, reversal, and intersection with a regular language, but not under arbitrary intersection or complement. Closure proofs often convert a supposed language membership into a known impossible language through intersection or complement.",
        ["DFA product handles Boolean operations", "CFL intersection with regular is context free", "Nonclosure needs a counterexample pair"],
        "Use only properties guaranteed for the class; CFL complement cannot be assumed during a proof.",
        "If L is context free and R is regular, what can be said about L∩R?",
        "It is context free. A PDA for L can track the state of a DFA for R in its finite control while retaining its stack behavior, accepting only when both components accept.",
      ),
    ],
    formulae: [
      { label: "Regular pumping constraints", expression: "s=xyz, |xy|≤p, |y|>0, and xy^iz∈L for all i≥0", useWhen: "Deriving a contradiction from assumed regularity" },
      { label: "CFL pumping constraints", expression: "s=uvxyz, |vxy|≤p, |vy|>0, and uv^ixy^iz∈L", useWhen: "Deriving a contradiction from assumed context-freeness" },
    ],
    checkpoints: [
      { question: "Can the pumping lemma prove that a language is regular?", answer: "Not by itself. It gives a necessary property of regular languages, and some nonregular languages may still satisfy that property." },
      { question: "Who chooses the regular pumping decomposition in a contradiction proof?", answer: "After the learner selects the witness, an adversary may choose any legal decomposition; the learner must then find a pumping exponent that fails." },
      { question: "Are CFLs closed under intersection?", answer: "Not under arbitrary intersection. They are closed when intersected with a regular language, an especially useful proof technique." },
      { question: "Why must the witness depend on pumping length p?", answer: "The lemma guarantees decomposition only for strings at least p long, so the chosen witness must meet that threshold and expose the language's dependency." },
      { question: "What error occurs if v and y are pumped independently in the CFL lemma?", answer: "The lemma requires the same exponent for both pieces. Pumping them separately reasons about strings the lemma never promises to preserve." },
    ],
  }),
  lesson({
    subjectCode: "TOC",
    subjectId: "theory-of-computation",
    topicId: "turing-machines-and-undecidability",
    title: "Turing Machines and Undecidability",
    summary: "Turing machines model general effective computation with an unbounded tape, and recognizability, decidability, reductions, and diagonal arguments explain why some precisely stated problems have no terminating algorithm.",
    estimatedMinutes: 65,
    prerequisites: ["Finite automata", "Context-free languages", "Logical implication"],
    objectives: ["Trace a Turing-machine computation", "Distinguish deciders from recognizers", "Use mapping reductions in the correct direction", "Classify standard undecidable problems"],
    concepts: [
      concept(
        "Turing-machine computation",
        "A deterministic Turing machine has finite control, an unbounded tape divided into cells, and a head that reads, writes, and moves. Its configuration includes the state, tape contents, and head position. The machine accepts or rejects by halting in designated states; without a decider guarantee, it may also run forever on some inputs.",
        ["The tape supplies unbounded working storage", "A transition reads, writes, and moves", "Nonhalting is distinct from rejection"],
        "When tracing, record overwritten symbols and head position; retaining the old symbol changes later behavior.",
        "How can a TM decide whether a binary string has equal numbers of 0s and 1s?",
        "Repeatedly mark one unmarked 0, scan for and mark one unmarked 1, then return and repeat symmetrically. Reject if a matching symbol is unavailable. When no unmarked symbols remain, accept. Each round reduces the unmarked count, so the procedure halts.",
      ),
      concept(
        "Decidable and recognizable languages",
        "A decider halts on every input and answers membership correctly. A recognizer must accept members but may reject or loop on nonmembers. Decidable languages are therefore recognizable, and a language is decidable exactly when both it and its complement are recognizable. This distinction is central when interpreting acceptance problems for encoded machines.",
        ["Deciders always halt", "Recognizers guarantee acceptance only for members", "Recognizable plus co-recognizable implies decidable"],
        "Do not treat an infinite loop as an explicit no answer when classifying a recognizer.",
        "A recognizer for L and a recognizer for complement(L) are available. How can L be decided?",
        "Dovetail the two simulations, taking one step of each alternately. Exactly one recognizer must eventually accept. Accept when the L recognizer accepts and reject when the complement recognizer accepts, guaranteeing termination.",
      ),
      concept(
        "Reductions and undecidability",
        "A mapping reduction from A to B transforms each instance x into f(x) so that x belongs to A exactly when f(x) belongs to B. If A is known undecidable and A reduces to B, then a decider for B would decide A, which is impossible. Reversing the direction does not establish B's hardness.",
        ["Preserve yes and no instances", "Transformations must be computable", "Reduce known-hard source to target"],
        "State the hypothetical target decider and show explicitly how it would solve the source problem.",
        "To prove problem P undecidable using ATM, which reduction direction is required?",
        "Construct ATM ≤m P. Convert an encoded machine-input pair into an instance of P with matching answer. If P had a decider, running the conversion and that decider would decide ATM, contradicting ATM's undecidability.",
      ),
    ],
    formulae: [
      { label: "Mapping reduction", expression: "A ≤m B iff x∈A ⇔ f(x)∈B for computable f", useWhen: "Transferring undecidability from a known problem" },
      { label: "Decidability criterion", expression: "L decidable ⇔ L and complement(L) are recognizable", useWhen: "Combining recognizers or classifying complements" },
    ],
    checkpoints: [
      { question: "May a recognizer loop on a string outside its language?", answer: "Yes. It must accept every member, but on a nonmember it may either reject explicitly or continue forever." },
      { question: "Why does a decider also qualify as a recognizer?", answer: "It accepts every member as required, and its additional guarantee of halting on nonmembers is stronger than recognizability demands." },
      { question: "Which reduction direction proves target B undecidable?", answer: "Reduce a known undecidable source A to B. Then any hypothetical decider for B would provide a decider for A." },
      { question: "Does nondeterminism make Turing machines recognize more languages?", answer: "No in the standard model. Deterministic machines can simulate nondeterministic computation by dovetailing branches, though efficiency may differ." },
      { question: "What is the key difference between rejection and nontermination?", answer: "Rejection is a halting no answer, while nontermination produces no answer at all; only a decider rules out the latter." },
    ],
  }),
];

const compilerTopics: LearningTopic[] = [
  lesson({
    subjectCode: "CD",
    subjectId: "compiler-design",
    topicId: "lexical-analysis",
    title: "Lexical Analysis",
    summary: "Lexical analysis turns source characters into tokens using regular-language machinery, applying longest-match and priority rules while separating token categories, lexemes, attributes, whitespace, comments, and lexical errors.",
    estimatedMinutes: 45,
    prerequisites: ["Regular expressions", "Finite automata"],
    objectives: ["Distinguish tokens, patterns, and lexemes", "Construct automata for token classes", "Apply longest-match and rule priority", "Identify responsibilities of lexer and symbol table"],
    concepts: [
      concept(
        "Tokens, patterns, and lexemes",
        "A token is the category passed to the parser, a pattern describes which character strings belong to that category, and a lexeme is the actual source substring. Attributes carry details such as a symbol-table pointer or numeric value. The distinction lets many identifiers share one token category while retaining their individual spellings and declarations.",
        ["Token is a category", "Lexeme is source text", "An attribute preserves semantic detail"],
        "Count token occurrences rather than distinct token categories when a question presents source code.",
        "Classify the source fragment total = total + 12.",
        "The lexer can emit ID(total), ASSIGN, ID(total), PLUS, NUM(12), and SEMICOLON. ID is one token category but occurs twice, and both occurrences can reference the same symbol-table entry for the lexeme total.",
      ),
      concept(
        "Automata-based recognition",
        "Regular expressions for token patterns are combined into an epsilon-NFA, converted to a DFA, and often minimized or represented as a transition table. Accepting states remember which token rule matched. The lexer advances until no transition is possible, then returns the last accepting prefix rather than the point where the scan failed.",
        ["Token patterns are regular languages", "A combined DFA recognizes many token classes", "Remember the last accepting state"],
        "A scan may pass through an accepting state and continue; the accepted lexeme ends at the last viable accepting position.",
        "Rules recognize < and <=. What token is produced from input <=x?",
        "After reading < the DFA is accepting, but it can continue on = to another accepting state. The next character x cannot extend the operator, so longest match returns the two-character <= token and leaves x for the next scan.",
      ),
      concept(
        "Disambiguation and errors",
        "When several rules match the same longest prefix, the lexer uses declared priority, commonly placing keywords before the general identifier rule. Whitespace and comments may be recognized and discarded. A lexical error occurs when no token pattern can consume the next character; grammatical misuse of valid tokens belongs to parsing rather than lexical analysis.",
        ["Longest valid prefix wins", "Priority breaks equal-length ties", "Valid tokens can still form a syntax error"],
        "Separate an illegal character from an illegal token sequence; they are reported by different compiler phases.",
        "Both IF and ID match the characters if. Which token should be returned?",
        "Both matches have length two, so longest match does not decide. If the keyword rule has higher priority, the lexer returns IF. The spelling gift would be one ID because its longer identifier match defeats the shorter keyword prefix.",
      ),
    ],
    formulae: [
      { label: "Longest-match rule", expression: "Choose the longest input prefix accepted by any token pattern", useWhen: "Resolving token boundaries in a source stream" },
      { label: "Tie-breaking rule", expression: "Equal match length ⇒ choose the earliest or highest-priority rule", useWhen: "A keyword and identifier pattern accept the same lexeme" },
    ],
    checkpoints: [
      { question: "Is the spelling count a token or a lexeme?", answer: "It is a lexeme. The category returned for that source substring is typically the token ID with a symbol-table attribute." },
      { question: "Why must a lexer remember its last accepting state?", answer: "The scan can move beyond an accepted prefix into a dead transition, so it must retract to the longest prefix that was actually valid." },
      { question: "Are nested parentheses normally checked by the lexer?", answer: "No. Arbitrary nesting is not regular and is handled by the parser using the grammar's recursive structure." },
      { question: "What happens to whitespace tokens?", answer: "The lexer usually recognizes and skips them, while still updating position information needed for diagnostics." },
      { question: "Why are keyword rules often prioritized over identifiers?", answer: "A word such as while matches both patterns with equal length; priority ensures it receives its reserved-keyword token rather than ID." },
    ],
  }),
  lesson({
    subjectCode: "CD",
    subjectId: "compiler-design",
    topicId: "parsing",
    title: "Parsing",
    summary: "Parsing checks whether a token stream follows a context-free grammar, using FIRST and FOLLOW for predictive parsing and viable-prefix machinery for shift-reduce methods such as LR, SLR, CLR, and LALR.",
    estimatedMinutes: 70,
    prerequisites: ["Context-free grammars", "Stacks", "Lexical analysis"],
    objectives: ["Compute FIRST and FOLLOW sets", "Build an LL(1) parsing table", "Remove left recursion and left-factor grammars", "Analyze LR items and shift-reduce conflicts"],
    concepts: [
      concept(
        "FIRST, FOLLOW, and LL(1)",
        "FIRST of a sequence lists terminals that can begin strings derived from it, including epsilon when the whole sequence is nullable. FOLLOW of a nonterminal lists terminals that may immediately follow it in a sentential form. An LL(1) table uses these sets so one nonterminal and one lookahead select at most one production.",
        ["FIRST concerns derived beginnings", "FOLLOW concerns right context", "One table entry must contain at most one production"],
        "For a nullable right side, add its production under FOLLOW of the left-hand nonterminal, never under an epsilon input column.",
        "Given A→aB | ε and FOLLOW(A)={$, )}, where is A→ε placed?",
        "FIRST(ε) contains ε, so the predictive table places A→ε under every terminal in FOLLOW(A): columns $ and ). The alternative A→aB is placed under column a. No table cell conflicts in this fragment.",
      ),
      concept(
        "Grammar preparation for top-down parsing",
        "Immediate left recursion makes a recursive-descent procedure call itself before consuming input, so A→Aα | β is transformed using a helper nonterminal. Left factoring extracts a common prefix when one lookahead cannot choose between alternatives. These transformations aim to enable prediction while preserving the generated language, not necessarily the original parse-tree shape.",
        ["Left recursion blocks ordinary LL parsing", "Left factoring delays a decision", "Transformations preserve language but may change trees"],
        "Perform left-recursion elimination before computing the final parsing sets because the transformed nonterminals change FIRST and FOLLOW.",
        "Eliminate immediate left recursion from E→E+T | T.",
        "Use E→TE′ and E′→+TE′ | ε. E first consumes a T, and E′ represents zero or more +T continuations. The transformed grammar can be parsed top down without repeatedly expanding E before input is consumed.",
      ),
      concept(
        "Bottom-up LR parsing",
        "An LR parser shifts input symbols and reduces handles so that it constructs a rightmost derivation in reverse. LR(0) items mark a position in a production; closure adds productions expected after a nonterminal, and goto advances the dot. SLR uses FOLLOW sets for reductions, CLR carries item-specific lookahead, and LALR merges CLR states with equal cores.",
        ["Shift advances input", "Reduce replaces a handle by its left side", "CLR lookahead is more precise than SLR FOLLOW"],
        "Classify a conflict by the competing actions in one state and lookahead cell, not merely by seeing multiple items in a state.",
        "A table cell contains shift 7 and reduce A→β. What conflict is this?",
        "It is a shift-reduce conflict because the same state and lookahead permit either consuming the next token into state 7 or replacing β by A. A reduce-reduce conflict would instead contain two different reductions.",
      ),
    ],
    formulae: [
      { label: "Nullable sequence FIRST", expression: "FIRST(XY) includes FIRST(X)−{ε}; include FIRST(Y) if ε∈FIRST(X)", useWhen: "Computing FIRST of a right-hand side" },
      { label: "Immediate left-recursion removal", expression: "A→Aα|β becomes A→βA′, A′→αA′|ε", useWhen: "Preparing a grammar for LL parsing" },
    ],
    checkpoints: [
      { question: "When is a grammar LL(1)?", answer: "Its predictive parsing table has at most one production in every nonterminal-lookahead cell after required grammar transformations." },
      { question: "Why is end marker $ put in FOLLOW of the start symbol?", answer: "After the start symbol derives the complete input, the only valid next marker is end of input, so $ belongs to its FOLLOW set." },
      { question: "What derivation does an LR parser construct?", answer: "It performs the reverse of a rightmost derivation by repeatedly reducing handles while scanning input from left to right." },
      { question: "Is every LR(0) grammar also SLR(1)?", answer: "Yes. If no action conflicts exist without lookahead, adding FOLLOW-restricted reductions cannot introduce a conflict that LR(0) lacked." },
      { question: "What information is lost when CLR states are merged into LALR states?", answer: "States with the same LR(0) core combine their lookahead sets, which may introduce a reduce-reduce conflict even though the CLR table was conflict free." },
    ],
  }),
  lesson({
    subjectCode: "CD",
    subjectId: "compiler-design",
    topicId: "syntax-directed-translation",
    title: "Syntax-Directed Translation",
    summary: "Syntax-directed definitions attach attributes and semantic rules to grammar productions, allowing parse structures to compute types, values, declarations, intermediate forms, and translations in an order consistent with dependency edges.",
    estimatedMinutes: 50,
    prerequisites: ["Parsing", "Parse trees", "Expression evaluation"],
    objectives: ["Distinguish synthesized and inherited attributes", "Build attribute dependency graphs", "Recognize S-attributed and L-attributed definitions", "Place semantic actions in translation schemes"],
    concepts: [
      concept(
        "Attributes and semantic rules",
        "An attribute stores information associated with a grammar symbol occurrence, while a semantic rule computes it from other attributes in the same production. Synthesized attributes flow from children toward a parent; inherited attributes obtain information from a parent or permitted siblings. The resulting annotated parse tree combines syntax with the values needed for later compilation phases.",
        ["Attributes belong to symbol occurrences", "Synthesized values flow upward", "Inherited values carry context downward or sideways"],
        "Identify the direction of every dependency before naming an attribute synthesized or inherited.",
        "For E→E1+T with E.val=E1.val+T.val, classify E.val.",
        "E.val is synthesized because the left-hand occurrence E receives its value from attributes of right-hand children E1 and T. The rule evaluates after both child values are available, naturally fitting bottom-up evaluation.",
      ),
      concept(
        "Dependency graphs and evaluation order",
        "A dependency graph has one node per attribute occurrence and an edge from each used attribute to the attribute it computes. Any topological order is a valid evaluation order; a cycle means the specified attributes cannot be evaluated by a simple finite ordering. Parse-tree traversal orders are conveniences only when they respect these dependencies.",
        ["Edges point from prerequisite to result", "Topological order gives evaluation order", "A dependency cycle is invalid for ordered evaluation"],
        "Draw dependencies for the specific parse tree rather than assuming one grammar-wide left-to-right order.",
        "Rules are A.x=B.y and B.y=A.z. Which value must be known first?",
        "A.z has no dependency shown and must be available first. It enables B.y, which then enables A.x. The graph has edges A.z→B.y→A.x, so that sequence is a valid topological evaluation order.",
      ),
      concept(
        "S-attributed and L-attributed definitions",
        "An S-attributed definition uses only synthesized attributes and is convenient for bottom-up parsing. An L-attributed definition permits an inherited attribute of a right-hand symbol to depend on the parent and on attributes of symbols to its left, but not on symbols to its right. This restriction supports one left-to-right depth-first traversal.",
        ["S-attributed implies synthesized only", "Every S-attributed definition is L-attributed", "L-attributed inherited dependencies cannot look right"],
        "Check each inherited rule separately; one forbidden right-sibling dependency is enough to violate L-attribution.",
        "In A→BCD, may C.in depend on B.out in an L-attributed definition?",
        "Yes. B is to the left of C, so C.in may use an attribute of B, as well as inherited attributes of A. It may not depend on D.out because D is to C's right.",
      ),
    ],
    formulae: [
      { label: "Synthesized rule shape", expression: "A.s = f(X1.a1, …, Xn.an) for A→X1…Xn", useWhen: "Computing a parent result from right-hand symbols" },
      { label: "L-attributed restriction", expression: "Xi.in may depend on A.in and attributes of X1…Xi−1", useWhen: "Testing whether inherited attributes allow left-to-right evaluation" },
    ],
    checkpoints: [
      { question: "Can an inherited attribute depend on a parent attribute?", answer: "Yes. Passing contextual information from the parent to a child is a standard use of inherited attributes." },
      { question: "Why does a dependency graph use attribute occurrences rather than names alone?", answer: "The same grammar symbol can appear at multiple parse-tree nodes with different values and dependencies, so each occurrence needs its own node." },
      { question: "Is every L-attributed definition S-attributed?", answer: "No. L-attributed definitions may use restricted inherited attributes, while S-attributed definitions use only synthesized attributes." },
      { question: "What does a cycle in an attribute dependency graph indicate?", answer: "No topological evaluation order exists for those rules on that parse tree, because each value ultimately requires itself." },
      { question: "Where may semantic actions be placed in a translation scheme?", answer: "They may be embedded among production symbols, but each action must execute only after all attributes it reads have been computed." },
    ],
  }),
  lesson({
    subjectCode: "CD",
    subjectId: "compiler-design",
    topicId: "runtime-environments",
    title: "Runtime Environments",
    summary: "Runtime environments organize procedure calls through activation records, stack and static storage, parameter passing, access and control links, return values, local variables, temporaries, and support for recursion and nested scopes.",
    estimatedMinutes: 60,
    prerequisites: ["Procedure calls in C", "Scope and lifetime", "Stacks"],
    objectives: ["Identify activation-record fields", "Trace calls, returns, and recursion", "Distinguish control and access links", "Compare parameter-passing and storage-allocation strategies"],
    concepts: [
      concept(
        "Activation records and call stacks",
        "Each active procedure invocation needs its own activation record containing the return address, saved machine state, parameters, local data, temporaries, and links required by the language implementation. Stack allocation works when calls and returns are properly nested. Recursion is possible because different invocations receive distinct records even though they execute the same procedure code.",
        ["One record per active invocation", "Return removes the most recent record", "Code may be shared while locals remain private"],
        "Count simultaneously active calls, not the total number of calls completed, when finding maximum stack depth.",
        "A recursive function f(3) calls f(2), f(1), and f(0) before returning. How many f records coexist at maximum?",
        "Four records coexist: f(3), f(2), f(1), and f(0). Once f(0) returns its record is popped before f(1) continues, so the maximum depth is based on the longest active chain, not all invocations over time.",
      ),
      concept(
        "Control links, access links, and scope",
        "The control or dynamic link points to the caller's activation record and supports stack unwinding. The access or static link points toward the activation of the lexically enclosing procedure, enabling nonlocal-variable access under static scope. These links can differ when a nested procedure is called by a procedure that is not its lexical parent.",
        ["Control link follows call history", "Access link follows lexical nesting", "Static chains resolve nonlocal names"],
        "Use the program's nesting structure for access links and the actual runtime call sequence for control links.",
        "Procedure Outer defines Inner, but Helper calls Inner. Where do Inner's links point?",
        "Inner's control link points to Helper because Helper is the runtime caller. Its access link points to the currently active Outer record because Outer is the lexical parent whose nonlocal variables Inner may reference.",
      ),
      concept(
        "Storage allocation and parameters",
        "Static allocation fixes addresses before execution and cannot naturally provide separate locals for recursive activations. Stack allocation supports nested lifetimes, while heap allocation handles values that outlive the creating call or have unpredictable lifetime. Parameter modes differ: call by value copies a value, while reference-like modes let the callee affect caller-visible storage.",
        ["Static storage has program-long lifetime", "Stack storage follows nested calls", "Heap storage supports non-LIFO lifetime"],
        "Separate aliasing effects from value copying when evaluating assignments through formal parameters.",
        "Procedure swap(x,y) receives both arguments by reference and is called swap(a,a). What aliasing occurs?",
        "Both formals denote the same caller location. Assigning through x immediately changes the value observed through y, so the usual three-assignment swap cannot exchange two distinct cells and ends with that one cell holding its original value or an intermediate depending on code.",
      ),
    ],
    formulae: [
      { label: "Maximum stack use", expression: "max active call depth × activation-record size (when sizes are equal)", useWhen: "Computing peak runtime stack storage" },
      { label: "Static-chain distance", expression: "Number of access-link hops = lexical-depth difference", useWhen: "Locating a nonlocal variable under static scope" },
    ],
    checkpoints: [
      { question: "Why does recursion conflict with pure static allocation of locals?", answer: "Multiple active calls need distinct copies of the same procedure's locals, but one fixed static location would make the activations overwrite each other." },
      { question: "What does a dynamic link represent?", answer: "It points from the current activation to its caller's activation, recording the runtime call chain and helping restore the caller on return." },
      { question: "What does a static link represent?", answer: "It points toward the activation of the lexically enclosing scope so the callee can find nonlocal variables under static scoping." },
      { question: "When is heap allocation necessary?", answer: "It is needed for objects whose lifetime is not nested within procedure calls, such as data that survives after its creating procedure returns." },
      { question: "Does call by value permit the callee to rebind the caller's variable?", answer: "No. The formal receives a copy of the value; assigning the formal does not change the caller's variable, although referenced heap objects may still be mutable." },
    ],
  }),
  lesson({
    subjectCode: "CD",
    subjectId: "compiler-design",
    topicId: "intermediate-code-generation",
    title: "Intermediate Code Generation",
    summary: "Intermediate code represents source computations independently of a target machine through syntax trees, DAGs, three-address statements, quadruples, triples, temporaries, labels, and explicit control flow suitable for analysis and translation.",
    estimatedMinutes: 50,
    prerequisites: ["Syntax-directed translation", "Expression trees", "Basic control flow"],
    objectives: ["Generate three-address code for expressions", "Represent TAC as quadruples and triples", "Translate Boolean and control-flow constructs", "Distinguish syntax trees from DAGs"],
    concepts: [
      concept(
        "Three-address code",
        "Three-address code breaks a complex expression into simple statements with at most one operator on the right and explicit temporary names. Evaluation order becomes visible, which helps later analyses and machine-code generation. Unary operations, copies, indexed access, addresses, conditional jumps, unconditional jumps, labels, calls, and returns are common statement forms.",
        ["One principal operator per instruction", "Temporaries name intermediate results", "Control flow uses explicit labels and jumps"],
        "Preserve precedence and associativity from the source expression when choosing the temporary sequence.",
        "Generate three-address code for the expression x=(a+b)*(c-d).",
        "Emit t1=a+b, t2=c-d, t3=t1*t2, and x=t3. Each instruction has one arithmetic operator, and the two parenthesized subexpressions are evaluated before multiplication as required.",
      ),
      concept(
        "Trees, DAGs, and value reuse",
        "A syntax tree records each operator occurrence separately, while a DAG can share a node for repeated subexpressions whose operands represent the same values. Sharing exposes possible common-subexpression reuse. It is unsafe when an operand may be redefined between occurrences, so data-flow facts are needed before global reuse across statements or basic blocks.",
        ["Tree nodes need not be shared", "DAG sharing represents repeated values", "Redefinition can kill reuse"],
        "Check whether operand definitions remain unchanged, not merely whether the source text looks identical.",
        "For a+b+(a+b) with unchanged a and b, how can a DAG reduce work?",
        "Create one node for a+b and let both uses point to it, then create the final addition whose two operands are that shared result. TAC may compute t1=a+b once and t2=t1+t1.",
      ),
      concept(
        "Control-flow translation",
        "Boolean expressions can be translated as numeric values or by short-circuit control flow. In jumping code, true and false exits are lists of unresolved branches patched when labels become known. If, while, and relational expressions then become combinations of conditional jumps, labels, and back edges, preserving source evaluation rules without first materializing every Boolean value.",
        ["Short-circuiting may skip operands", "Backpatching fills unknown targets", "Loop back edges repeat the condition"],
        "Do not evaluate the right operand of && when the left operand already determines false.",
        "Translate if (a<b) x=1; else x=2 using labels.",
        "Emit if a<b goto Ltrue; goto Lfalse; Ltrue: x=1; goto Lnext; Lfalse: x=2; Lnext:. The unconditional jump after the true arm prevents accidental fall-through into the else arm.",
      ),
    ],
    formulae: [
      { label: "Quadruple layout", expression: "(op, arg1, arg2, result)", useWhen: "Encoding a three-address instruction with explicit result names" },
      { label: "Short-circuit AND", expression: "B1 true → evaluate B2; B1 false → false exit", useWhen: "Generating control-flow code for B1 && B2" },
    ],
    checkpoints: [
      { question: "Why is three-address code called machine independent?", answer: "Its operations and temporaries describe computation without committing to a particular target's registers, instruction encoding, or addressing constraints." },
      { question: "How does a quadruple identify an intermediate result?", answer: "The result field contains an explicit temporary name, so instructions can be reordered without renumbering references to earlier positions." },
      { question: "When may a DAG share two source subexpressions?", answer: "They may share when they compute the same operator on the same still-valid operand values and no intervening redefinition changes those values." },
      { question: "What does backpatching solve?", answer: "It records incomplete branch target lists and fills them once the target labels or instruction addresses become known." },
      { question: "Why is an unconditional jump needed after a translated then arm with an else arm?", answer: "Without it, normal fall-through would execute the else code immediately after completing the then code." },
    ],
  }),
  lesson({
    subjectCode: "CD",
    subjectId: "compiler-design",
    topicId: "code-optimization-and-data-flow-analysis",
    title: "Code Optimization and Data-Flow Analysis",
    summary: "Code optimization preserves program meaning while improving local or global code, using basic blocks, control-flow graphs, constant propagation, liveness, reaching definitions, common-subexpression elimination, dead-code removal, and loop transformations.",
    estimatedMinutes: 70,
    prerequisites: ["Intermediate code", "Graph traversal", "Sets and fixed points"],
    objectives: ["Form basic blocks and control-flow graphs", "Solve forward and backward data-flow equations", "Compute liveness and reaching definitions", "Justify standard local and global optimizations"],
    concepts: [
      concept(
        "Basic blocks and control-flow graphs",
        "A basic block is a maximal straight-line sequence entered only at its first instruction and exited only at its last. Leaders include the first instruction, jump targets, and instructions immediately following jumps. A control-flow graph connects blocks when execution can pass directly between them, supplying the structure on which global data-flow facts are propagated.",
        ["Only the first instruction is an entry", "Only the last instruction branches out", "CFG edges represent possible next execution"],
        "Mark every leader before grouping instructions; missing the statement after a conditional branch merges distinct paths incorrectly.",
        "Instructions 1: a=1, 2: if p goto 5, 3: b=2, 4: goto 6, 5: b=3, 6: print b. Identify leaders.",
        "Instruction 1 is first, 3 follows a conditional jump, 5 is a jump target, and 6 is a jump target and follows instruction 4's jump. Thus leaders are 1,3,5,6, giving blocks [1-2], [3-4], [5], and [6].",
      ),
      concept(
        "Liveness and backward analysis",
        "A variable is live at a program point when its current value may be read on some future path before being overwritten. Liveness flows backward: a block's OUT is the union of successor IN sets, and IN contains uses plus values needed at exit that the block does not redefine. A dead assignment defines a value not live afterward and has no other side effect.",
        ["Liveness asks about future use", "Successor information flows backward", "A definition kills the previous value"],
        "Use union across successors because existence of one path using the value is enough to make it live.",
        "For x=y+1; z=x*2; print z, what is live just before the first statement?",
        "y is live because its current value is read immediately. x and z are not yet live there because the statements define them before their uses. After the first statement x is live; after the second z is live.",
      ),
      concept(
        "Forward facts and safe optimization",
        "Reaching definitions and available expressions flow forward. A definition reaches a point if some path carries it without redefining the variable. An expression is available only if every incoming path has evaluated it and none of its operands was subsequently redefined, so predecessor information uses intersection. Constant propagation substitutes a value only when the reaching information supports one unambiguous constant.",
        ["Reaching definitions usually merge by union", "Available expressions merge by intersection", "Operand redefinition kills expression availability"],
        "Match the meet operator to the question's quantifier: may information uses union, must information uses intersection.",
        "Both predecessors compute t=a+b, but one predecessor later redefines a. Is a+b available at the join?",
        "No. Although both paths once computed the expression, redefining a kills that value on one path. Availability requires the expression to remain valid on every incoming path, so common-subexpression elimination at the join is unsafe.",
      ),
    ],
    formulae: [
      { label: "Live variables", expression: "IN[B]=USE[B]∪(OUT[B]−DEF[B]); OUT[B]=⋃ IN[S]", useWhen: "Solving backward liveness over successors S" },
      { label: "Reaching definitions", expression: "OUT[B]=GEN[B]∪(IN[B]−KILL[B]); IN[B]=⋃ OUT[P]", useWhen: "Solving forward may-analysis over predecessors P" },
      { label: "Available expressions meet", expression: "IN[B]=⋂ OUT[P]", useWhen: "Checking expressions valid on every incoming path" },
    ],
    checkpoints: [
      { question: "Why is liveness a backward analysis?", answer: "Whether a current value matters depends on uses that can occur later, so information is propagated from successor blocks toward predecessors." },
      { question: "What kills a reaching definition of x?", answer: "Any later assignment to x kills the older definition along that path because future reads obtain the newer value." },
      { question: "Why does available-expression analysis use intersection at joins?", answer: "An expression is safely reusable only if it has been computed and remains unmodified on every incoming path." },
      { question: "When can an assignment be removed as dead code?", answer: "Its defined value must not be live afterward, and evaluating the assignment must have no observable side effect such as I/O, a call effect, or exception." },
      { question: "What is the purpose of iterating data-flow equations?", answer: "Loops create cyclic dependencies among block facts, so iteration continues until a fixed point is reached and no IN or OUT set changes." },
    ],
  }),
];

const operatingSystemTopics: LearningTopic[] = [
  lesson({
    subjectCode: "OS",
    subjectId: "operating-systems",
    topicId: "system-calls",
    title: "System Calls",
    summary: "System calls form the controlled interface from user programs to kernel services, explaining traps, privilege modes, process creation, program replacement, file operations, blocking, return values, and the cost of crossing protection boundaries.",
    estimatedMinutes: 40,
    prerequisites: ["CPU privilege modes", "C functions and processes"],
    objectives: ["Distinguish API calls from system calls", "Trace user-kernel mode transitions", "Explain fork and exec semantics", "Classify blocking and nonblocking kernel services"],
    concepts: [
      concept(
        "Protected kernel entry",
        "User code cannot execute privileged operations directly. A system-call wrapper places a call number and arguments where the operating-system convention expects them, executes a trap instruction, and transfers control to a validated kernel entry. The kernel checks permissions and arguments, performs the service, records a result or error, and returns to user mode.",
        ["Trap is a controlled synchronous exception", "Kernel validates caller requests", "Mode switch is not necessarily a process switch"],
        "Count every user-to-kernel entry and kernel-to-user return separately from any scheduler-driven process context switch.",
        "A program performs three non-nested read system calls, each returning normally. How many privilege-mode transitions occur?",
        "Each call enters kernel mode once and returns to user mode once, for two transitions. Three calls therefore cause six mode transitions. A call may block and trigger context switches, but none are implied by the question.",
      ),
      concept(
        "Process-control calls",
        "A fork-like call creates a child process whose initial state largely copies the parent, but parent and child receive different return values. An exec-like call does not create another process; it replaces the calling process's program image while preserving the process identity and selected resources. Waiting lets a parent synchronize with child termination.",
        ["fork creates a new process", "exec replaces the current image", "wait can block until child state changes"],
        "Trace both execution branches after every successful fork and do not add a process for exec.",
        "One process executes fork(); fork(); with no failure or conditional branch. How many processes exist afterward?",
        "The first fork doubles one process to two. Both processes execute the second fork, doubling the population to four. The number of newly created children is three, while total processes including the original is four.",
      ),
      concept(
        "I/O calls and blocking",
        "File and device system calls use descriptors or handles that the kernel maps to open objects and access state. A read may return available bytes, reach end of file, report an error, or block until data arrives. Blocking changes the process state and permits another ready process to use the CPU; it is not busy waiting by the blocked process.",
        ["Descriptors index per-process open-object references", "Blocking relinquishes the CPU", "Return values distinguish data, EOF, and error"],
        "Do not assume one read call returns the entire requested byte count, especially for streams.",
        "A pipe is empty but still has a writer. What happens to a blocking read?",
        "The kernel places the reader in a waiting state until data arrives or all write ends close. When data becomes available the process becomes ready; closing every writer can instead make the read return end of file.",
      ),
    ],
    formulae: [
      { label: "Normal mode transitions", expression: "2 × number of completed non-nested system calls", useWhen: "Counting entry and return transitions without extra scheduling assumptions" },
      { label: "Repeated unconditional forks", expression: "Total processes after n forks executed by every process = 2^n", useWhen: "No failures, exits, or conditional execution intervene" },
    ],
    checkpoints: [
      { question: "Is every library function a system call?", answer: "No. Many library functions execute entirely in user space, while some wrap one or more system calls when kernel service is required." },
      { question: "Does entering kernel mode always switch to another process?", answer: "No. A mode switch can execute the call on behalf of the same process; a context switch occurs only if scheduling changes the running process." },
      { question: "What does exec do to process identity?", answer: "It replaces the program image of the calling process but normally retains its process identifier rather than creating a child." },
      { question: "Why can a system call block?", answer: "The requested event or resource may not yet be available, so the kernel waits the process and schedules another ready process." },
      { question: "Why are system-call arguments checked in the kernel?", answer: "User programs are untrusted and may supply invalid addresses, lengths, descriptors, or permissions that must not compromise protected state." },
    ],
  }),
  lesson({
    subjectCode: "OS",
    subjectId: "operating-systems",
    topicId: "processes-and-threads",
    title: "Processes and Threads",
    summary: "Processes and threads organize execution, state transitions, context switching, address-space sharing, user and kernel threading models, and inter-process communication through shared memory or message-oriented mechanisms.",
    estimatedMinutes: 55,
    prerequisites: ["System calls", "CPU registers and memory"],
    objectives: ["Trace process-state transitions", "Identify context-switch state", "Compare processes and threads", "Reason about IPC and threading models"],
    concepts: [
      concept(
        "Process states and context switches",
        "A process combines an executing program with its address space, resources, and saved execution context. Typical states are new, ready, running, waiting, and terminated. A context switch saves the current CPU state in a process control block and restores another process's state; this overhead performs no direct application work.",
        ["Ready means eligible but not running", "Waiting means an event is required", "PCB preserves resumable execution state"],
        "A waiting process normally becomes ready before it can become running; the scheduler selects from the ready set.",
        "A running process requests disk input. Trace its next states until it runs again.",
        "It moves from running to waiting because the request cannot complete immediately. On I/O completion an interrupt makes it ready. A dispatcher later selects it, restores its context, and moves it from ready to running.",
      ),
      concept(
        "Thread resource sharing",
        "Threads within one process share code, global data, heap, address space, and usually open files, but each thread needs its own program counter, registers, stack, and scheduling state. Sharing makes communication cheap but removes memory protection between peer threads. A blocking effect depends on whether threads are visible and schedulable by the kernel.",
        ["Address space is shared", "Stacks and registers are private", "One faulty thread can corrupt process memory"],
        "Classify each resource by whether it describes the process container or one independent execution stream.",
        "A process has four threads, each with a 32 KiB private stack. What private stack storage is required?",
        "Each execution stream needs its own 32 KiB stack, so total private stack storage is 4×32=128 KiB. Shared code and heap are not multiplied by the thread count.",
      ),
      concept(
        "IPC and threading models",
        "Processes exchange data through shared memory, messages, pipes, or related kernel mechanisms. Shared memory is fast after setup but needs synchronization; message passing packages communication and synchronization through send and receive operations. Many-to-one user threads cannot run in parallel on multiple cores and one blocking kernel call can block the mapped kernel thread, while one-to-one permits kernel scheduling per thread.",
        ["Shared memory needs explicit synchronization", "Message passing crosses a defined channel", "Kernel visibility controls parallel scheduling"],
        "Do not infer parallelism from concurrency; many user threads may still map to one kernel execution entity.",
        "Why might two processes choose shared memory plus semaphores?",
        "Shared memory avoids copying every payload through repeated messages, while semaphores coordinate ownership and data availability. The memory supplies communication capacity; the semaphore supplies ordering and mutual exclusion that shared bytes alone do not provide.",
      ),
    ],
    formulae: [
      { label: "Private thread storage", expression: "thread count × per-thread stack size", useWhen: "Only private stacks are requested and sizes are equal" },
      { label: "Turnaround identity", expression: "Turnaround time = Completion time − Arrival time", useWhen: "Relating process lifetime to scheduling timestamps" },
    ],
    checkpoints: [
      { question: "Can a waiting process be selected directly by the CPU scheduler?", answer: "No. It must first receive its event and become ready before the dispatcher can move it to running." },
      { question: "Which memory do threads of one process share?", answer: "They share the process address space, including code, globals, and heap, while retaining separate stacks and register contexts." },
      { question: "Why is a process context switch usually costlier than a thread switch?", answer: "Switching processes may change address-space mappings and protection context in addition to execution registers, causing more cache and translation disruption." },
      { question: "What does shared-memory IPC fail to provide by itself?", answer: "It provides common bytes but not safe ordering or mutual exclusion, so synchronization is still required for concurrent access." },
      { question: "Can many-to-one user threads execute truly in parallel on two cores?", answer: "No. They map to one kernel-schedulable entity, so at most one of those user threads executes at a time." },
    ],
  }),
  lesson({
    subjectCode: "OS",
    subjectId: "operating-systems",
    topicId: "concurrency-and-synchronization",
    title: "Concurrency and Synchronization",
    summary: "Concurrency creates interleavings over shared state, requiring critical-section correctness, atomic operations, mutexes, semaphores, monitors, and disciplined solutions to producer-consumer, readers-writers, and dining-philosophers problems.",
    estimatedMinutes: 65,
    prerequisites: ["Processes and threads", "Interleaving of instructions"],
    objectives: ["Identify race conditions", "Evaluate critical-section algorithms", "Trace semaphore values and blocked queues", "Solve classical synchronization patterns"],
    concepts: [
      concept(
        "Race conditions and critical sections",
        "A race condition occurs when a result depends on the timing of unsynchronized accesses to shared state. Increment is normally a read-modify-write sequence, so two executions can both read the same old value and lose one update. A correct critical-section protocol provides mutual exclusion, progress, and bounded waiting under its stated assumptions.",
        ["Source-level assignment may not be atomic", "Mutual exclusion allows one critical execution", "Progress and bounded waiting prevent indefinite postponement"],
        "Expand compact statements into their load, compute, and store steps before enumerating interleavings.",
        "Two threads increment x from 0 once using non-atomic read-modify-write. What final values are possible?",
        "If one increment completes before the other reads, x becomes 2. If both read 0 before either stores, each computes 1 and both store 1, so the final value can also be 1. It cannot be 0 under these operations.",
      ),
      concept(
        "Semaphores and mutex discipline",
        "A semaphore supports atomic wait and signal operations. A counting semaphore represents multiple available units, while a binary semaphore can enforce mutual exclusion when initialized and used correctly. Wait decrements or blocks according to the adopted definition; signal releases a unit and may wake a blocked process. Reversing acquisition order can introduce deadlock.",
        ["Semaphore operations are atomic", "Initial value encodes available capacity", "Operation order carries correctness"],
        "State the semaphore convention before tracing negative values or queue length, because textbook definitions encode waiting differently.",
        "A buffer has N slots. Which semaphore initialization models empty and full slots?",
        "Set empty=N and full=0, with mutex=1. A producer waits on empty then mutex, inserts, signals mutex then full. A consumer waits on full then mutex, removes, signals mutex then empty.",
      ),
      concept(
        "Monitors and classical problems",
        "A monitor packages shared data and procedures with implicit mutual exclusion, while condition variables let a thread wait for a state predicate and later be signaled. Classical problems test whether a design enforces safety without deadlock or starvation. Readers-writers variants differ in which class receives preference, so their starvation behavior must be stated explicitly.",
        ["One monitor procedure executes at a time", "Condition wait releases the monitor lock", "Preference policy affects starvation"],
        "A signal announces that a condition may now hold; a resumed thread should recheck the predicate rather than assume it remains true.",
        "Why should a bounded-buffer consumer wait while count==0 inside a monitor?",
        "It cannot remove an item safely when the buffer is empty. Waiting releases the monitor so a producer can enter and insert. On wakeup, the consumer rechecks count because another consumer may have taken the available item first.",
      ),
    ],
    formulae: [
      { label: "Bounded-buffer capacity invariant", expression: "0 ≤ full ≤ N and empty + full = N", useWhen: "Checking producer-consumer semaphore accounting across buffer operations" },
      { label: "Critical-section requirements", expression: "Mutual exclusion + Progress + Bounded waiting", useWhen: "Evaluating a software or hardware synchronization solution" },
    ],
    checkpoints: [
      { question: "Why is count=count+1 vulnerable without synchronization?", answer: "It normally expands into separate load, arithmetic, and store operations that can interleave with another thread and lose an update." },
      { question: "What should a mutex semaphore normally be initialized to?", answer: "One, representing one available permission to enter the protected critical section; zero would block every initial entrant." },
      { question: "Does mutual exclusion alone guarantee bounded waiting?", answer: "No. A solution can allow only one entrant while repeatedly favoring the same process and starving another indefinitely." },
      { question: "Why does condition-variable wait release a monitor lock?", answer: "Holding the lock while waiting would prevent another thread from entering the monitor and making the awaited predicate true." },
      { question: "How can inconsistent lock order cause deadlock?", answer: "One thread can hold A while waiting for B as another holds B while waiting for A, creating a circular wait." },
    ],
  }),
  lesson({
    subjectCode: "OS",
    subjectId: "operating-systems",
    topicId: "deadlocks",
    title: "Deadlocks",
    summary: "Deadlock reasoning connects the four necessary conditions with resource-allocation graphs, safe states, Banker's avoidance, prevention policies, detection, and recovery for systems containing single or multiple resource instances.",
    estimatedMinutes: 55,
    prerequisites: ["Processes and resources", "Graphs", "Vector arithmetic"],
    objectives: ["Recognize the four deadlock conditions", "Interpret resource-allocation graphs", "Run a safety check", "Distinguish prevention, avoidance, detection, and recovery"],
    concepts: [
      concept(
        "Necessary conditions and graphs",
        "Deadlock requires mutual exclusion, hold and wait, no preemption, and circular wait to hold simultaneously. With one instance of every resource type, a cycle in a resource-allocation graph is necessary and sufficient for deadlock. With multiple instances, a cycle remains necessary but may not be sufficient because another instance can permit progress.",
        ["All four conditions are jointly necessary", "Single-instance cycle implies deadlock", "Multiple instances weaken the cycle conclusion"],
        "Check every resource type's instance count before treating a resource-allocation graph cycle as conclusive proof of deadlock.",
        "P1 holds R1 and requests R2; P2 holds R2 and requests R1, with one instance each. What follows?",
        "The graph contains P1→R2→P2→R1→P1. Each process waits for the only instance held by the other, so no process can proceed and the cycle proves deadlock.",
      ),
      concept(
        "Safe states and Banker's algorithm",
        "A state is safe when some sequence lets every process obtain its remaining maximum need and finish. Banker's safety test repeatedly finds an unfinished process whose Need is component-wise no greater than Work, then adds that process's current Allocation to Work. An unsafe state is not necessarily already deadlocked, but granting a request that makes it unsafe is avoided.",
        ["Need equals Max minus Allocation", "Comparison is component-wise", "Finishing releases Allocation, not Max"],
        "A safe sequence is an existence proof; the system need not execute processes in that exact order afterward.",
        "Work=2. P1 needs 1 and holds 3; P2 needs 4 and holds 1. Is there a safe order?",
        "P1 can finish because 1≤2, then releases its allocation so Work becomes 5. P2's need 4 now fits, so P2 can finish. The sequence P1,P2 proves the state safe.",
      ),
      concept(
        "Handling strategies",
        "Prevention structurally breaks a necessary condition, avoidance examines future claims before grants, detection allows deadlock and later discovers it, and recovery terminates processes or preempts resources after detection. Each strategy trades utilization, information requirements, overhead, and disruption. Starvation is different: a process may wait indefinitely even though the system as a whole keeps making progress.",
        ["Prevention constrains requests", "Avoidance requires maximum claims", "Detection needs a recovery policy"],
        "Name the strategy from when it acts: before requests, at each grant, after formation, or during recovery.",
        "A system requires processes to request all resources before starting. Which condition is broken?",
        "The rule prevents hold and wait because a process never holds a partial set while requesting more. It may reduce utilization substantially, but it is a deadlock-prevention policy.",
      ),
    ],
    formulae: [
      { label: "Remaining claim", expression: "Need = Max − Allocation", useWhen: "Preparing Banker's safety or request algorithm" },
      { label: "Safety step", expression: "Need[i] ≤ Work ⇒ Work := Work + Allocation[i]", useWhen: "Constructing a candidate safe sequence" },
    ],
    checkpoints: [
      { question: "Is every unsafe state deadlocked?", answer: "No. Unsafe means no guaranteed safe completion sequence under maximum claims; the processes may still finish without entering deadlock." },
      { question: "When does a resource-allocation graph cycle prove deadlock?", answer: "It is sufficient when every resource type in the relevant graph has only one instance; otherwise further analysis is required." },
      { question: "Why is mutual exclusion hard to eliminate?", answer: "Some resources are intrinsically nonshareable while in use, so allowing simultaneous access would violate their correct operation." },
      { question: "What information does avoidance usually require?", answer: "It needs declared maximum future resource claims so the system can test whether each tentative grant preserves a safe state." },
      { question: "How does starvation differ from deadlock?", answer: "In starvation other processes continue progressing while one is postponed indefinitely; in deadlock the involved set cannot progress because of circular waits." },
    ],
  }),
  lesson({
    subjectCode: "OS",
    subjectId: "operating-systems",
    topicId: "cpu-and-i-o-scheduling",
    title: "CPU and I/O Scheduling",
    summary: "Scheduling selects among ready CPU work and pending I/O requests, requiring accurate timelines, preemption rules, response, waiting and turnaround metrics, time quanta, priority behavior, and disk-head movement policies.",
    estimatedMinutes: 65,
    prerequisites: ["Process states", "Queues", "Basic arithmetic"],
    objectives: ["Draw scheduling Gantt charts", "Compute waiting, response, and turnaround times", "Compare preemptive and nonpreemptive policies", "Trace disk scheduling head movement"],
    concepts: [
      concept(
        "CPU scheduling metrics",
        "Arrival time determines when a process enters the ready queue, burst time gives required CPU service, and completion time comes from the schedule. Turnaround covers the full interval in the system, waiting removes CPU execution time, and response measures delay until the first dispatch. These metrics differ when a process is preempted and resumes later.",
        ["Turnaround uses completion minus arrival", "Waiting excludes CPU burst", "Response uses first start only"],
        "Build the complete timeline before averaging metrics; choosing jobs correctly but using arrival zero for all processes gives wrong answers.",
        "P arrives at 2, first runs at 5, has burst 4, and completes at 11. Find its metrics.",
        "Turnaround is 11−2=9. Waiting is turnaround minus burst, 9−4=5. Response is first start minus arrival, 5−2=3. The gap between first execution and completion reflects possible preemption or idle intervals.",
      ),
      concept(
        "Common CPU policies",
        "FCFS is nonpreemptive and can suffer a convoy effect. SJF minimizes average waiting time when all relevant burst lengths are known, while SRTF is its preemptive form. Round robin cycles through the ready queue for at most one quantum per turn. Priority scheduling can starve low-priority work unless aging raises waiting priorities.",
        ["SRTF compares remaining times", "Round robin depends on quantum", "Aging counters priority starvation"],
        "At each arrival or completion event, reevaluate only if the policy is preemptive; nonpreemptive jobs retain the CPU until blocking or finishing.",
        "A process needs 10 ms CPU under round robin with quantum 4 ms and never blocks. How many slices?",
        "It receives 4 ms, then 4 ms, then the remaining 2 ms, so it needs ceil(10/4)=3 slices. Queue waiting between slices depends on competing ready processes and is not inferable here.",
      ),
      concept(
        "Disk and I/O scheduling",
        "Disk scheduling orders pending cylinder requests to reduce seek movement while considering fairness. FCFS follows arrival order; SSTF selects the closest request and may starve distant requests; SCAN sweeps in a direction then reverses, while C-SCAN services in one direction and returns to the beginning. LOOK variants reverse at the last pending request rather than the physical edge.",
        ["Seek cost depends on head movement", "SCAN has a direction", "LOOK stops at the furthest pending request"],
        "For SCAN-family questions, record initial head position, current direction, cylinder limits, and whether the method visits an edge.",
        "Head is at 50 moving upward; requests are 20, 55, and 80. Give LOOK order.",
        "LOOK services requests in the current direction: 55 then 80. With no larger request it reverses at 80 rather than traveling to the disk's maximum cylinder, and then services 20.",
      ),
    ],
    formulae: [
      { label: "Scheduling metrics", expression: "TAT=CT−AT; WT=TAT−BT; RT=first start−AT", useWhen: "Computing per-process CPU scheduling results" },
      { label: "Round-robin slices", expression: "ceil(CPU burst / quantum)", useWhen: "A process never blocks and each turn uses up to one quantum" },
    ],
    checkpoints: [
      { question: "Which policy minimizes average waiting time when exact bursts are known together?", answer: "Shortest-job-first does so for the nonpreemptive case by placing shorter bursts before longer ones." },
      { question: "What happens to round robin as quantum becomes very large?", answer: "Preemption becomes rare and the schedule approaches FCFS order for the current ready queue." },
      { question: "Can response time equal waiting time?", answer: "Yes for a process that runs once without preemption, but generally waiting also includes delays after the process has already responded." },
      { question: "Why can SSTF starve a request?", answer: "A continuing stream of requests near the current head can repeatedly be chosen before a far-away request." },
      { question: "How does LOOK differ from SCAN?", answer: "LOOK reverses after the furthest pending request in the current direction, whereas SCAN conventionally travels to the physical end before reversing." },
    ],
  }),
  lesson({
    subjectCode: "OS",
    subjectId: "operating-systems",
    topicId: "memory-and-virtual-memory",
    title: "Memory and Virtual Memory",
    summary: "Memory management maps logical addresses to physical storage through contiguous allocation, paging, segmentation, page tables and TLBs, while virtual memory adds demand paging, replacement, effective-access calculations, working sets, and thrashing.",
    estimatedMinutes: 70,
    prerequisites: ["Binary addressing", "Computer memory hierarchy", "Processes"],
    objectives: ["Translate paged and segmented addresses", "Compute fragmentation and page-table sizes", "Evaluate TLB and page-fault performance", "Trace page-replacement algorithms"],
    concepts: [
      concept(
        "Allocation and address translation",
        "Contiguous allocation places a process in one physical region and suffers external fragmentation, while paging divides logical memory into fixed-size pages mapped to equal-size frames. The page number indexes a page table and the offset is copied unchanged into the physical address. Segmentation instead uses variable-length logical regions checked against bounds.",
        ["Page and frame sizes match", "Offset is preserved", "Segmentation checks offset against segment limit"],
        "Derive offset bits from page size before splitting an address; do not use the number of page-table entries as the offset width.",
        "Page size is 1 KiB and logical address is 2500. Find page number and offset.",
        "One page holds 1024 bytes. Integer division gives page=floor(2500/1024)=2, and remainder gives offset 2500−2048=452. The page-table entry for page 2 supplies the physical frame.",
      ),
      concept(
        "Page tables and TLB performance",
        "A page table stores a frame mapping plus status bits for each virtual page, and multilevel organization avoids allocating every lower-level table for sparse address spaces. A TLB caches recent translations. On a TLB hit, translation and memory access are faster; on a miss, page-table access precedes the data access unless a page fault is discovered.",
        ["TLB caches translations, not data", "A miss need not be a page fault", "Multilevel tables save unused table space"],
        "Write the exact access sequence assumed by the problem; simultaneous TLB and cache lookup changes a formula.",
        "TLB lookup is 10 ns, memory access 100 ns, hit ratio 0.9, and a miss needs two memory accesses total. Find EAT.",
        "A hit costs 10+100=110 ns. A miss costs 10+200=210 ns. Weighted EAT is 0.9×110+0.1×210=120 ns, assuming no page faults and serial lookup.",
      ),
      concept(
        "Demand paging and replacement",
        "Demand paging loads a page only when referenced. A page fault traps to the kernel, obtains a free frame or selects a victim, writes a dirty victim if necessary, loads the requested page, updates tables, and restarts the instruction. FIFO can show Belady's anomaly; stack algorithms such as LRU and optimal do not as frame count increases.",
        ["Page fault service is much slower than memory access", "Dirty victims need write-back", "LRU and optimal are stack algorithms"],
        "Maintain frame contents after every reference and distinguish a hit from a replacement even when the same page reappears.",
        "With three empty frames and FIFO, trace 1,2,3,1,4.",
        "References 1,2,3 cause three faults and fill frames. The next 1 is a hit and does not change FIFO arrival order. Reference 4 faults and replaces page 1, the oldest loaded page, for four total faults.",
      ),
    ],
    formulae: [
      { label: "Paged address split", expression: "page=floor(address/page size); offset=address mod page size", useWhen: "Page size is given in bytes" },
      { label: "Effective access with faults", expression: "EAT=(1−p)×normal access + p×page-fault service", useWhen: "Page-fault probability p and service cost are given" },
      { label: "Page-table entries", expression: "virtual address-space size / page size", useWhen: "A single-level table has one entry per virtual page" },
    ],
    checkpoints: [
      { question: "What fragmentation does fixed-size paging primarily cause?", answer: "Internal fragmentation, usually in the final partially used page of an allocation; physical frames need not be contiguous." },
      { question: "Does a TLB miss imply a page fault?", answer: "No. The translation may simply be absent from the TLB while a valid page-table entry maps a resident page." },
      { question: "Why is page-fault probability so influential in EAT?", answer: "Fault service includes disk or backing-store work and is orders of magnitude slower than ordinary memory access, so even a small probability can dominate." },
      { question: "Which replacement algorithms can show Belady's anomaly?", answer: "FIFO can show more faults with more frames; stack algorithms such as LRU and optimal cannot." },
      { question: "What does virtual-memory thrashing mean?", answer: "The system spends most of its time handling page faults because active working sets do not fit in allocated physical frames, reducing useful CPU progress." },
    ],
  }),
  lesson({
    subjectCode: "OS",
    subjectId: "operating-systems",
    topicId: "file-systems",
    title: "File Systems",
    summary: "File systems name persistent data and organize metadata, directories, access methods, contiguous, linked and indexed allocation, inodes, free-space tracking, block addressing, and the trade-offs among sequential and direct access.",
    estimatedMinutes: 50,
    prerequisites: ["Secondary storage", "Pointers and trees"],
    objectives: ["Interpret directory and metadata structures", "Compare file-allocation methods", "Compute indexed-addressing capacity", "Explain free-space management"],
    concepts: [
      concept(
        "Files, directories, and metadata",
        "A file is a named persistent byte or record sequence accompanied by metadata such as size, owner, permissions, timestamps, and block locations. Directories map names to file identifiers or metadata structures, allowing hierarchical paths. Opening a file resolves its path and creates kernel state so later reads can use a descriptor and current offset efficiently.",
        ["Name resolution is separate from file contents", "Metadata describes and locates data", "Open descriptors retain per-open state"],
        "Distinguish links to a file object from independent copies of its data when counting directory entries and storage.",
        "Two directory names are hard links to one inode. What happens when one name is removed?",
        "Only that directory entry and one link count are removed. The inode and data blocks remain accessible through the other hard link, and storage is reclaimed only after the link count reaches zero and no open reference remains.",
      ),
      concept(
        "Allocation methods",
        "Contiguous allocation stores consecutive blocks and supports fast sequential and direct access but makes growth difficult and causes external fragmentation. Linked allocation avoids external fragmentation and grows easily but direct access is slow and pointers consume space. Indexed allocation stores block addresses in an index structure, supporting direct access at the cost of index overhead.",
        ["Contiguous allocation needs start and length", "Linked allocation follows block pointers", "Indexed allocation centralizes addresses"],
        "Choose the method from the access requirement and growth pattern rather than memorizing one universally best scheme.",
        "Which allocation best supports direct access for a growing file without requiring contiguous free space?",
        "Indexed allocation fits: the index maps logical block numbers to physical blocks, so blocks may be scattered and new block addresses can be added. Index structures consume space and may require multiple levels for large files.",
      ),
      concept(
        "Inodes and free-space management",
        "Unix-like inodes combine direct block pointers with single, double, and triple indirect pointers so small files avoid large index overhead while large files remain addressable. Free blocks can be tracked by bitmaps, free lists, grouping, or counting. A bitmap uses one bit per block and makes runs of free blocks easier to locate.",
        ["Direct pointers favor small files", "Indirect levels multiply address capacity", "Bitmap size depends on block count"],
        "At each indirect level, count how many addresses fit in one block before multiplying capacities.",
        "Block size is 4096 bytes and an address is 4 bytes. How many data blocks can one single-indirect block reference?",
        "It holds 4096/4=1024 block addresses. Therefore the single-indirect pointer can reach 1024 data blocks, separate from any direct blocks in the inode.",
      ),
    ],
    formulae: [
      { label: "Pointers per index block", expression: "block size / pointer size", useWhen: "Computing single or multilevel indexed capacity" },
      { label: "Free-space bitmap size", expression: "number of disk blocks bits", useWhen: "One bitmap bit represents each block" },
    ],
    checkpoints: [
      { question: "Why does contiguous allocation support fast direct access?", answer: "Logical block i is found arithmetically as start+i, without following pointers or consulting a separate per-block chain." },
      { question: "What is the main direct-access weakness of linked allocation?", answer: "Finding logical block i requires following the chain from earlier blocks because the physical addresses are not indexed by logical position." },
      { question: "What does an inode normally not store?", answer: "The human-readable filename is normally stored in a directory entry; the inode stores metadata and data-block addressing information." },
      { question: "Why are direct pointers useful even with indirect pointers available?", answer: "Small files can reach their data without allocating and reading a separate index block, reducing space and access overhead." },
      { question: "How does a bitmap help find contiguous free blocks?", answer: "Runs of free bits can be scanned as groups, making adjacent free blocks more visible than an unordered free-block list." },
    ],
  }),
];

const databaseTopics: LearningTopic[] = [
  lesson({
    subjectCode: "DBMS",
    subjectId: "databases",
    topicId: "er-model",
    title: "ER Model",
    summary: "Entity-relationship modeling captures entities, attributes, keys, weak entities, relationship degree, cardinality and participation constraints, then maps the conceptual design into relations without losing identity or relationship information.",
    estimatedMinutes: 45,
    prerequisites: ["Sets and relations", "Basic database terminology"],
    objectives: ["Identify entities, attributes, and keys", "Interpret cardinality and participation", "Model weak entities", "Map ER constructs to relational schemas"],
    concepts: [
      concept(
        "Entities, attributes, and keys",
        "An entity is a distinguishable object, an entity set groups similar objects, and attributes describe them. A key attribute set uniquely identifies each entity. Composite attributes have components, multivalued attributes may hold several values, and derived attributes are computed from stored facts. Good ER modeling records semantics rather than simply turning every noun into a table.",
        ["Keys identify entities", "Composite attributes can be decomposed", "Derived values need not be stored"],
        "When several candidate identifiers exist, mark candidate keys and choose a primary key only during relational design.",
        "A Student has roll number, name, birth date, and age. Which attribute is naturally derived?",
        "Age is derived from birth date and the current date, so storing both creates update inconsistency. Roll number can serve as a key, name is descriptive, and birth date is a stored simple or composite date value.",
      ),
      concept(
        "Relationships and constraints",
        "A relationship associates participating entities and may itself carry attributes. Mapping cardinality states the maximum association count, such as one-to-one, one-to-many, or many-to-many. Participation states a minimum requirement: total participation means every entity must appear in the relationship, while partial participation permits entities with no relationship occurrence.",
        ["Cardinality gives a maximum", "Participation gives a minimum", "Relationship attributes describe the association"],
        "Read constraints from each side independently; a one-to-many relationship has different meanings in the two directions.",
        "Each employee works in exactly one department, while a department may have many employees. State the constraints.",
        "The relationship is many employees to one department. Employee participation is total because every employee must work in one department. Department participation may be partial if an empty department is permitted.",
      ),
      concept(
        "Weak entities and relational mapping",
        "A weak entity lacks a complete key of its own and is identified through an owner entity plus a partial key. It participates totally in its identifying relationship. When mapped, the weak relation includes the owner's primary key and the partial key, with their combination forming the weak entity's primary key and the owner component also acting as a foreign key.",
        ["Weak identity depends on an owner", "Partial key distinguishes dependents of one owner", "Identifying participation is total"],
        "Do not mistake any entity with a foreign key for a weak entity; identity dependence is the defining property.",
        "Employee is keyed by emp_id; Dependent has dependent_name unique only within an employee. Give the Dependent key.",
        "Create Dependent(emp_id, dependent_name, ...). Its primary key is (emp_id, dependent_name), and emp_id is a foreign key to Employee. Removing the owner normally removes the identifying basis for its dependents.",
      ),
    ],
    formulae: [
      { label: "Weak-entity key", expression: "owner primary key ∪ weak partial key", useWhen: "Mapping an identifying relationship to a relation" },
      { label: "Many-to-many mapping", expression: "Relationship relation primary key usually combines participating entity keys", useWhen: "Creating a separate relation for an M:N relationship" },
    ],
    checkpoints: [
      { question: "What does total participation mean?", answer: "Every entity in that entity set must participate in at least one instance of the specified relationship." },
      { question: "Can a relationship have attributes?", answer: "Yes. An attribute such as hours on an Employee-Project relationship describes the association rather than either entity alone." },
      { question: "How is a multivalued attribute usually mapped?", answer: "Create a separate relation containing the owner's key and one value per row, commonly using their combination as the primary key." },
      { question: "Why is a weak entity's partial key insufficient globally?", answer: "It distinguishes weak entities only under the same owner, so the owner's key is also required for global identity." },
      { question: "Where is the foreign key placed for a one-to-many relationship?", answer: "It is normally placed on the many side, referencing the primary key of the one side, along with relationship attributes when appropriate." },
    ],
  }),
  lesson({
    subjectCode: "DBMS",
    subjectId: "databases",
    topicId: "relational-model",
    title: "Relational Model",
    summary: "The relational model represents data as sets of tuples governed by schemas and keys, queried through relational algebra and tuple relational calculus with precise semantics for selection, projection, joins, division, quantifiers, and safety.",
    estimatedMinutes: 70,
    prerequisites: ["Sets, predicates, and quantifiers", "ER modeling"],
    objectives: ["Apply relational algebra operators", "Translate joins and division", "Write tuple relational calculus expressions", "Evaluate keys, degree, and cardinality"],
    concepts: [
      concept(
        "Relations and algebra",
        "A relation is a set of tuples over named attributes, so duplicate tuples and row order have no logical significance. Selection chooses rows satisfying a predicate, projection chooses attributes and removes duplicates, and rename resolves names for self-products. Union, intersection, and difference require union-compatible schemas, while Cartesian product combines every tuple pair.",
        ["Relations are sets", "Selection preserves attributes", "Projection can reduce cardinality through duplicate removal"],
        "Separate degree, the number of attributes, from cardinality, the number of tuples, after every operator.",
        "R(A,B) has tuples (1,x),(1,y),(2,x). What is πA(R)?",
        "Projection keeps only attribute A, producing values 1,1,2 before set semantics remove duplicates. The result is the one-attribute relation {(1),(2)} with degree 1 and cardinality 2.",
      ),
      concept(
        "Joins and division",
        "A theta join selects matching pairs from a Cartesian product, an equijoin uses equality predicates, and a natural join equates all same-named attributes and keeps one copy of each. Division expresses a for-all query: R(X,Y)÷S(Y) returns X values paired in R with every Y value present in S.",
        ["Join combines related tuples", "Natural join uses every common attribute", "Division encodes universal coverage"],
        "Check whether an empty divisor or repeated input rows affect the result under relational set semantics.",
        "Enroll(student,course) contains (A,DB),(A,OS),(B,DB); Required contains DB and OS. Evaluate Enroll÷Required.",
        "Student A is paired with both required courses and is returned. B lacks OS and is excluded. The result is a one-column relation containing only A.",
      ),
      concept(
        "Tuple relational calculus",
        "Tuple relational calculus is declarative: an expression {t | P(t)} returns tuples t satisfying predicate P. Tuple variables range over relations, and formulas combine membership, attribute comparisons, Boolean connectives, and existential or universal quantifiers. A safe expression restricts output values to the active database domain, avoiding infinite results such as all values not appearing in a relation.",
        ["TRC states what result must satisfy", "Existential quantification models some", "Universal requirements can use implication or negated existence"],
        "Bind every helper tuple variable and ensure each output attribute is range restricted by database tuples.",
        "Write TRC for employee names belonging to department 5 from Emp(eid,name,dept).",
        "Use {t | ∃e (e∈Emp ∧ e.dept=5 ∧ t.name=e.name)}. The variable e is bound to Emp, the predicate filters its department, and the result tuple receives only a name drawn from an existing tuple, so the expression is safe.",
      ),
    ],
    formulae: [
      { label: "Theta join", expression: "R ⋈θ S = σθ(R × S)", useWhen: "Rewriting a join using primitive relational algebra" },
      { label: "Universal condition in TRC", expression: "∀x(P→Q) ≡ ¬∃x(P∧¬Q)", useWhen: "Expressing every or division-like queries" },
      { label: "Division intent", expression: "x∈R÷S iff ∀y∈S, (x,y)∈R", useWhen: "Queries asking for entities related to every required value" },
    ],
    checkpoints: [
      { question: "Why can projection reduce tuple count?", answer: "Removing attributes can make formerly distinct tuples identical, and relation set semantics retain only one copy of each result tuple." },
      { question: "What attributes does a natural join compare?", answer: "It equates all attributes with the same names in both inputs and normally keeps one copy of each common attribute." },
      { question: "What kind of query suggests relational division?", answer: "A query asking which X values are related to every Y in a required set is the standard division pattern." },
      { question: "How does TRC differ from relational algebra?", answer: "TRC declaratively states a predicate the result must satisfy, whereas relational algebra specifies a sequence of operations to construct the result." },
      { question: "Why must a TRC expression be safe?", answer: "Safety ensures a finite, domain-independent result whose values come from the active database rather than an unbounded external universe." },
    ],
  }),
  lesson({
    subjectCode: "DBMS",
    subjectId: "databases",
    topicId: "sql",
    title: "SQL",
    summary: "SQL expresses relational queries and updates through SELECT-FROM-WHERE, joins, grouping, aggregates, HAVING, nested and correlated subqueries, set operations, null-aware logic, data definition, and views.",
    estimatedMinutes: 65,
    prerequisites: ["Relational model", "Boolean logic"],
    objectives: ["Trace logical SQL query processing", "Write joins and grouped queries", "Evaluate nested and correlated subqueries", "Reason about NULL and three-valued logic"],
    concepts: [
      concept(
        "Query blocks and joins",
        "A query block conceptually forms sources in FROM, applies join and WHERE predicates, creates groups, filters them with HAVING, computes SELECT expressions, removes duplicates if requested, and orders the final rows. SQL uses bag semantics by default, so duplicate rows remain unless DISTINCT or a set operator removes them.",
        ["FROM and WHERE precede SELECT conceptually", "SQL defaults to bags", "Join conditions prevent unintended Cartesian products"],
        "When counting rows, decide whether duplicates survive at each stage instead of assuming pure relational set semantics.",
        "R has 3 rows and S has 4 rows, with no join predicate. How many rows can FROM R,S produce?",
        "It forms a Cartesian product containing 3×4=12 row combinations before later filtering. Adding a join condition in WHERE may reduce that count, but none is present here.",
      ),
      concept(
        "Grouping and aggregation",
        "GROUP BY partitions surviving rows by equal grouping values, aggregate functions compute one result per group, and HAVING filters groups after aggregation. WHERE cannot directly filter an aggregate of the group because it acts earlier. COUNT(*) counts rows, whereas COUNT(column) ignores null values in that column, a common source of different answers.",
        ["WHERE filters rows", "HAVING filters groups", "COUNT(column) ignores NULL"],
        "Every selected nonaggregate expression must be compatible with the grouping rule used by the question's SQL dialect.",
        "Table T has values 3,NULL,3 in column x. Compare COUNT(*), COUNT(x), and COUNT(DISTINCT x).",
        "COUNT(*) is 3 because all rows count. COUNT(x) is 2 because NULL is ignored. COUNT(DISTINCT x) is 1 because the two nonnull values are equal and duplicates are removed.",
      ),
      concept(
        "Subqueries, correlation, and NULL",
        "An uncorrelated subquery can be evaluated independently, while a correlated subquery references the current outer row and is conceptually reevaluated for each candidate. EXISTS checks whether any subquery row exists. Comparisons involving NULL usually produce UNKNOWN; WHERE retains only TRUE, so NOT IN can behave unexpectedly if its subquery contains NULL.",
        ["Correlation references an outer query", "EXISTS tests row existence", "UNKNOWN is filtered by WHERE"],
        "Before simplifying NOT IN, check whether the subquery result can contain NULL; NOT EXISTS is often semantically safer.",
        "Why can x NOT IN (1,NULL) return no row even when x=2?",
        "The condition expands to 2<>1 AND 2<>NULL. The first part is TRUE but the second is UNKNOWN, so the conjunction is UNKNOWN. WHERE does not retain UNKNOWN rows.",
      ),
    ],
    formulae: [
      { label: "Logical query order", expression: "FROM/JOIN → WHERE → GROUP BY → HAVING → SELECT → DISTINCT → ORDER BY", useWhen: "Explaining aliases, aggregates, and row counts" },
      { label: "Aggregate counting", expression: "COUNT(*) counts rows; COUNT(A) counts non-NULL A values", useWhen: "NULL values appear in an aggregate question" },
    ],
    checkpoints: [
      { question: "Does SELECT DISTINCT remove duplicates before WHERE?", answer: "No. WHERE first filters source rows; DISTINCT removes duplicate selected result rows later in logical processing." },
      { question: "When should HAVING be used?", answer: "Use it to filter groups based on aggregate or grouping conditions after GROUP BY has formed those groups." },
      { question: "What makes a subquery correlated?", answer: "It references a column from an outer query block, so its result depends on the particular outer row or group being tested." },
      { question: "How does EXISTS treat columns in the subquery SELECT list?", answer: "It tests only whether a row exists; the selected expression's value is irrelevant to that existence test." },
      { question: "Why is a NULL comparison not simply false?", answer: "NULL represents unknown or missing information, so most comparisons produce UNKNOWN, preserving SQL's three-valued logic." },
    ],
  }),
  lesson({
    subjectCode: "DBMS",
    subjectId: "databases",
    topicId: "integrity-constraints",
    title: "Integrity Constraints",
    summary: "Integrity constraints restrict valid database states through domains, keys, entity integrity, referential integrity, checks, and foreign-key actions, separating structural guarantees from application assumptions and transactional enforcement timing.",
    estimatedMinutes: 40,
    prerequisites: ["Relations and keys", "ER model"],
    objectives: ["Classify integrity constraints", "Identify candidate and foreign keys", "Evaluate insert, delete, and update effects", "Reason about cascade, restrict, and null actions"],
    concepts: [
      concept(
        "Domains, keys, and entity integrity",
        "A domain constrains an attribute's type and admissible values. A superkey uniquely identifies tuples; a candidate key is a minimal superkey, and a chosen candidate becomes the primary key. Entity integrity forbids NULL in primary-key attributes because an entity represented by a row must remain identifiable.",
        ["Candidate keys are minimal", "Primary key is chosen from candidates", "Primary-key components cannot be NULL"],
        "Test minimality by removing each attribute from a proposed key, not merely by showing the full set is unique.",
        "In R(A,B,C), both A and BC uniquely identify rows and no proper subset of BC does. What are candidate keys?",
        "A is a candidate key because it is unique and already minimal. BC is another candidate key because its combination is unique and neither B nor C alone is. All supersets are superkeys but not candidates.",
      ),
      concept(
        "Referential integrity",
        "A foreign key in a referencing relation must either match an existing candidate-key value in the referenced relation or be NULL when its attributes and constraint permit NULL. Inserts into the child and updates to its foreign key are checked against the parent; parent deletion or key update must follow the declared action.",
        ["Foreign keys reference candidate keys", "NULL may represent no relationship", "Parent changes can affect children"],
        "Identify parent and child directions before judging an operation; inserting a parent usually needs no matching child.",
        "Dept has keys 10 and 20. May Emp insert a row with dept_id 30 under a normal foreign key?",
        "No, because 30 matches no referenced Dept key. A NULL dept_id may be allowed if the column and relationship are optional, but a nonnull unmatched value violates referential integrity.",
      ),
      concept(
        "Constraint actions and timing",
        "RESTRICT or NO ACTION rejects a parent change that would leave references dangling, CASCADE propagates the key update or deletion, and SET NULL disconnects children when NULL is allowed. Some systems check constraints immediately after each statement, while deferrable constraints may be checked at transaction end, allowing temporary intermediate violations that are repaired before commit.",
        ["Restrict blocks invalid parent change", "Cascade propagates change", "Deferred checking still requires validity at commit"],
        "A referential action can trigger further constraints, so trace the complete cascade rather than only its first table.",
        "Deleting Dept 10 uses ON DELETE SET NULL, but Emp.dept_id is NOT NULL. Is the action viable?",
        "No. The referential action would try to assign NULL to referencing employees, contradicting the NOT NULL constraint. The schema must choose a compatible action or permit NULL.",
      ),
    ],
    formulae: [
      { label: "Candidate-key test", expression: "K is candidate iff K is a superkey and no proper subset of K is a superkey", useWhen: "Distinguishing candidate keys from arbitrary superkeys" },
      { label: "Foreign-key validity", expression: "FK tuple ∈ referenced key values, or FK is permitted NULL", useWhen: "Checking child insert or update operations" },
    ],
    checkpoints: [
      { question: "Can a relation have several candidate keys?", answer: "Yes. Each is a distinct minimal attribute set that uniquely identifies tuples; one may be selected as the primary key." },
      { question: "May a foreign key reference a nonprimary candidate key?", answer: "Yes. Referential integrity can target a candidate or otherwise declared unique key, not only the chosen primary key." },
      { question: "Why is a primary-key attribute not nullable?", answer: "A NULL component would make the represented entity's identity unknown and violate entity integrity." },
      { question: "What does ON DELETE CASCADE do?", answer: "Deleting a referenced parent row automatically deletes referencing child rows, potentially triggering further cascades." },
      { question: "Does deferred checking permanently permit a violation?", answer: "No. It only postpones the check; all deferred constraints must hold when the transaction commits." },
    ],
  }),
  lesson({
    subjectCode: "DBMS",
    subjectId: "databases",
    topicId: "normal-forms",
    title: "Normal Forms",
    summary: "Normalization uses functional dependencies, closures, keys, minimal covers, lossless joins and dependency preservation to recognize and decompose schemas through 2NF, 3NF and BCNF without inventing dependencies from sample rows.",
    estimatedMinutes: 70,
    prerequisites: ["Relational model", "Set closure"],
    objectives: ["Compute attribute closures and candidate keys", "Find minimal covers", "Test 2NF, 3NF, and BCNF", "Evaluate lossless and dependency-preserving decompositions"],
    concepts: [
      concept(
        "Functional dependencies and closure",
        "A functional dependency X→Y states that every valid pair of tuples agreeing on X must also agree on Y. Attribute closure begins with X and repeatedly adds attributes implied by dependencies whose left sides are already present. X is a superkey when its closure contains the entire schema; it is a candidate key when no attribute can be removed.",
        ["FDs constrain every legal instance", "Closure applies dependencies repeatedly", "Candidate keys are minimal superkeys"],
        "After adding a new attribute, rescan dependencies because it can unlock a chain that was unavailable earlier.",
        "For R(A,B,C,D) with A→B, B→C, AC→D, find A+.",
        "Start {A}; A→B adds B, then B→C adds C. Now AC→D applies because A and C are present, adding D. Thus A+={A,B,C,D}, so A is a candidate key.",
      ),
      concept(
        "Normal-form tests",
        "Second normal form removes partial dependencies of nonprime attributes on proper subsets of candidate keys. Third normal form requires every nontrivial FD X→A to have X as a superkey or A as prime. BCNF is stricter: every nontrivial determinant must be a superkey. These tests apply to dependencies projected onto the relation.",
        ["Prime means part of some candidate key", "3NF has a prime-attribute exception", "BCNF has no exception"],
        "Find all candidate keys before classifying prime attributes; using only one chosen key can misclassify 3NF.",
        "R(A,B,C) has FDs AB→C and C→B. Is C→B a BCNF violation?",
        "C is not a superkey because C+={B,C}, so C→B violates BCNF. B is prime, however, because candidate keys include AB and AC; therefore the dependency can satisfy 3NF's prime-right-side exception.",
      ),
      concept(
        "Decomposition properties",
        "A decomposition is lossless when joining its projections always reconstructs exactly the original relation without spurious tuples. For a binary decomposition R1,R2, the common attributes must functionally determine R1 or R2. Dependency preservation means original dependencies can be enforced using dependencies local to components without performing a join. BCNF decomposition is lossless but may sacrifice preservation.",
        ["Lossless join prevents spurious tuples", "Binary lossless test uses the intersection", "Dependency preservation concerns local enforcement"],
        "Do not equate losslessness with preservation; they answer reconstruction and enforcement questions separately.",
        "Decompose R(A,B,C) into R1(A,B) and R2(A,C) with A→B. Is it lossless?",
        "The intersection is {A}. Since A→AB, the common attributes determine all of R1. The binary lossless-join condition holds, so natural joining the projections cannot introduce spurious tuples.",
      ),
    ],
    formulae: [
      { label: "Superkey test", expression: "X is a superkey iff X+ contains every attribute of R", useWhen: "Finding keys and checking BCNF determinants" },
      { label: "3NF test", expression: "For each nontrivial X→A: X is superkey OR A is prime", useWhen: "Classifying a relation under functional dependencies" },
      { label: "Binary lossless test", expression: "(R1∩R2)→R1 or (R1∩R2)→R2 in F+", useWhen: "Checking whether a two-way relational decomposition is lossless" },
    ],
    checkpoints: [
      { question: "Can one sample table prove a functional dependency?", answer: "No. A sample can disprove an FD through a counterexample, but the FD is a semantic constraint over every valid instance." },
      { question: "What is a prime attribute?", answer: "An attribute is prime if it belongs to at least one candidate key, even if it is not in the chosen primary key." },
      { question: "Why is every BCNF relation in 3NF?", answer: "BCNF requires every nontrivial determinant to be a superkey, which always satisfies the first alternative of the 3NF test." },
      { question: "Can a lossless decomposition fail dependency preservation?", answer: "Yes. It may reconstruct relations correctly while requiring a join to check an original dependency whose attributes are split across components." },
      { question: "What makes an extraneous attribute removable from an FD?", answer: "Removing it from the relevant side leaves the same implied dependency set, as verified by closure under the modified cover." },
    ],
  }),
  lesson({
    subjectCode: "DBMS",
    subjectId: "databases",
    topicId: "file-organization-and-indexing",
    title: "File Organization and Indexing",
    summary: "Physical database access depends on heap, ordered and hashed files plus dense, sparse, clustered and multilevel indexes, with B and B+ trees supporting balanced search, insertion, deletion, equality and range queries.",
    estimatedMinutes: 60,
    prerequisites: ["Trees and hashing", "Disk blocks"],
    objectives: ["Compare file organizations", "Classify primary, clustered, dense, and sparse indexes", "Compute B+ tree height and fan-out", "Trace search and insertion in B/B+ trees"],
    concepts: [
      concept(
        "File organizations and index density",
        "Heap files place records without key order and support inexpensive insertion, while sorted files aid ordered scans but make insertion costly. Hash organization maps keys to buckets for expected fast equality access but does not preserve order for range queries. A dense index has an entry for every search-key value or record; a sparse index has fewer entries and requires ordered data.",
        ["Heap favors insertion", "Hash favors equality", "Sparse indexing relies on ordered data"],
        "Match the organization to equality, range, insertion, and ordering requirements rather than only comparing search steps.",
        "Can a sparse primary index be used on an unordered heap file?",
        "Not in the standard block-anchor form. A sparse entry directs the search to a range of ordered data blocks; without data ordering, the omitted keys have no predictable nearby block.",
      ),
      concept(
        "B and B+ tree structure",
        "B-family trees remain height balanced by splitting and merging nodes. In a B tree, records or data pointers may appear in internal and leaf nodes. In a B+ tree, internal nodes guide search and all data entries reside at leaves; linked leaves make range scans efficient. Node occupancy bounds keep fan-out high and height small.",
        ["All leaves have equal depth", "B+ data entries are at leaves", "Leaf links support sequential range access"],
        "Follow the problem's definition of order because textbooks use order for either maximum children or minimum degree.",
        "Why does a B+ tree repeat separator keys in internal nodes?",
        "The internal copy routes searches, while the leaf copy remains the actual data entry or record pointer. Repetition lets internal nodes stay compact guides and keeps all data entries in one linked leaf level.",
      ),
      concept(
        "Index selection and cost",
        "A primary index is built on the ordering primary key, while a clustering index follows an ordering nonkey; secondary indexes use a different search order and are generally dense enough to locate scattered records. Multilevel indexing applies an index over index blocks until the top level fits in a small number of blocks, reducing disk I/O logarithmically.",
        ["Clustering follows physical order", "Only one physical ordering exists", "Secondary matches may point to many locations"],
        "Count index traversal I/Os and data-block I/Os separately, including whether the root is assumed memory resident.",
        "A three-level B+ index has its root cached. How many index-block reads does a point lookup need before the leaf?",
        "With root cached, only the next internal level and the leaf need disk reads, so two index-block I/Os occur before any separate data-record block access required by the leaf entry.",
      ),
    ],
    formulae: [
      { label: "Approximate B+ height", expression: "ceil(log_f N) levels for effective fan-out f and N leaf-scale entries", useWhen: "Estimating balanced-tree access depth for indexed records" },
      { label: "Index blocking factor", expression: "floor(block size / index-entry size)", useWhen: "Computing entries or fan-out that fit in a block" },
    ],
    checkpoints: [
      { question: "Which organization is usually best for exact-key lookup without range scans?", answer: "Hash organization is a strong choice because it maps the key directly to a bucket, assuming a suitable hash and controlled overflow." },
      { question: "Why are B+ tree leaves linked?", answer: "After locating the first qualifying key, a range scan can continue through adjacent leaves without returning through internal levels." },
      { question: "Can a relation have several clustering orders?", answer: "No. The physical records can be ordered in only one way at a time, though several secondary indexes may exist." },
      { question: "Why can a secondary index require multiple record pointers for one key?", answer: "The indexed attribute may be nonunique, so one search-key value can identify many records scattered across data blocks." },
      { question: "What keeps B+ tree search logarithmic?", answer: "Every node has bounded high fan-out and all leaves stay at the same depth through split, redistribution, and merge operations." },
    ],
  }),
  lesson({
    subjectCode: "DBMS",
    subjectId: "databases",
    topicId: "transactions-and-concurrency-control",
    title: "Transactions and Concurrency Control",
    summary: "Transactions preserve ACID properties under interleaving and failure through serializability analysis, recoverability, locking protocols, timestamp concepts, logging, checkpoints, and recovery rules that distinguish committed, uncommitted, and cascading effects.",
    estimatedMinutes: 70,
    prerequisites: ["Directed graphs", "SQL updates", "File storage basics"],
    objectives: ["Build precedence graphs", "Classify recoverable and cascadeless schedules", "Apply two-phase locking", "Reason about write-ahead logging and recovery"],
    concepts: [
      concept(
        "Schedules and serializability",
        "A schedule interleaves operations while preserving each transaction's internal order. Two operations conflict when they access the same item, belong to different transactions, and at least one writes. A precedence graph adds Ti→Tj when a conflicting operation of Ti occurs first. The schedule is conflict serializable exactly when this graph is acyclic.",
        ["Read-read does not conflict", "Edges follow operation order", "Acyclic graph has a serial topological order"],
        "Create edges per data item and deduplicate them; a visual operation crossing is irrelevant without a same-item conflict.",
        "Schedule r1(X), w1(X), r2(X), w2(X). What graph edge appears?",
        "The write by T1 precedes T2's read and write on X, creating T1→T2. No T2 operation precedes a conflicting T1 operation, so the graph is acyclic and equivalent to serial order T1,T2.",
      ),
      concept(
        "Recoverability and locking",
        "A recoverable schedule delays a reader's commit until the transaction whose value it read commits. A cascadeless schedule delays the read itself until the writer commits, and a strict schedule prevents other transactions from reading or writing an item written by an uncommitted transaction. Two-phase locking grows by acquiring locks and then shrinks by releasing them, guaranteeing conflict serializability.",
        ["Recoverable constrains commit order", "Cascadeless prevents dirty reads", "Strict 2PL holds exclusive locks to commit"],
        "Do not infer deadlock freedom from 2PL; locking can guarantee serializability while creating waits in a cycle.",
        "T2 reads X written by uncommitted T1, then T2 commits before T1. Is the schedule recoverable?",
        "No. T2 committed based on a value whose producer had not committed. If T1 later aborts, T2 cannot be safely undone after its commit. Recoverability requires T1 to commit before T2.",
      ),
      concept(
        "Logging and recovery",
        "Write-ahead logging requires the relevant log record to reach stable storage before a changed data page is written, and a commit record must be durable before commit is acknowledged. Update records preserve old and/or new values for undo and redo. A checkpoint limits how far recovery must scan, but it does not by itself make every earlier page durable unless the checkpoint protocol states so.",
        ["Log precedes data page", "Commit record precedes acknowledgement", "Undo targets losers and redo targets required winners"],
        "Classify transactions from log records at crash time before deciding which actions to undo or redo.",
        "At crash, T1 has a commit record and T2 has updates but no commit. What is the basic recovery intent?",
        "T1 is a winner and may need redo so its committed effects appear on disk. T2 is a loser and its effects must be undone if they reached disk. Exact passes depend on the recovery algorithm.",
      ),
    ],
    formulae: [
      { label: "Conflict condition", expression: "Different transactions, same item, and at least one write", useWhen: "Constructing a transaction precedence graph from schedule operations" },
      { label: "Conflict serializability", expression: "Schedule is conflict serializable iff precedence graph is acyclic", useWhen: "Testing and deriving equivalent serial orders" },
      { label: "WAL rule", expression: "log record durable before corresponding data page; commit record durable before success", useWhen: "Reasoning about undo and redo safety" },
    ],
    checkpoints: [
      { question: "Do two reads of the same item conflict?", answer: "No. Neither changes the value, so swapping their order cannot affect either transaction's observed database state." },
      { question: "How is an equivalent serial order obtained from an acyclic precedence graph?", answer: "Any topological ordering of the transaction vertices gives a serial order conflict equivalent to the schedule." },
      { question: "Does basic two-phase locking prevent deadlock?", answer: "No. Transactions can acquire locks in opposing orders and wait cyclically even though completed schedules are conflict serializable." },
      { question: "Why is a strict schedule useful for recovery?", answer: "No transaction observes or overwrites uncommitted writes, so aborting a writer cannot force cascading rollback of dependent transactions." },
      { question: "What is the main purpose of write-ahead logging?", answer: "It ensures recovery information is durable before an uncommitted or committed update can appear on disk, enabling correct undo and redo." },
    ],
  }),
];

const networkTopics: LearningTopic[] = [
  lesson({
    subjectCode: "CN",
    subjectId: "computer-networks",
    topicId: "layering-and-switching",
    title: "Layering and Switching",
    summary: "Layering divides communication responsibilities into service boundaries and protocol peers, while encapsulation, multiplexing, circuit switching, datagram packet switching, and virtual circuits explain how end systems and networks organize delivery.",
    estimatedMinutes: 45,
    prerequisites: ["Binary data units", "Basic computer communication"],
    objectives: ["Explain services, interfaces, and protocols", "Trace encapsulation and demultiplexing", "Compare switching techniques", "Compute basic store-and-forward timelines"],
    concepts: [
      concept(
        "Services, protocols, and encapsulation",
        "A layer offers a service to the layer above through an interface and communicates logically with its peer using a protocol. As a message moves downward, layers add control information in headers or trailers; the receiver removes them in reverse. Multiplexing identifies which upper-layer conversation should receive each arriving unit.",
        ["Service describes what is offered", "Protocol governs peer communication", "Encapsulation carries layer control information"],
        "Do not claim adjacent layers on different machines communicate directly; peer communication is logical and uses lower-layer services.",
        "An application sends 1000 bytes; transport and network each add 20-byte headers. What reaches the link layer before its own overhead?",
        "Transport creates 1020 bytes, then the network layer adds another 20, producing a 1040-byte network packet. Link framing overhead is excluded because the question stops before that layer adds it.",
      ),
      concept(
        "Circuit and datagram switching",
        "Circuit switching reserves an end-to-end path or resource allocation during setup, giving predictable service after establishment but potentially wasting idle capacity. Datagram packet switching sends independently addressed packets over shared links, supports statistical multiplexing, and can reorder or drop packets. Store-and-forward nodes normally receive a complete packet before transmitting it onward.",
        ["Circuit service has setup", "Datagrams may follow different routes", "Shared packet links improve utilization"],
        "Include setup delay only for the circuit case and distinguish one packet's delay from a train of packets that can pipeline.",
        "A packet of L bits crosses k store-and-forward links of rate R with no propagation or queueing. Delay?",
        "Each link needs L/R seconds to place the full packet on that link, and the next link starts only after receiving it. Across k links, the first packet's transmission delay is kL/R.",
      ),
      concept(
        "Virtual circuits and forwarding state",
        "A virtual-circuit network establishes a route before data transfer and stores per-connection forwarding state in intermediate switches. Packets carry a short local identifier whose value may change at each hop. This combines packetized sharing with connection-oriented forwarding; unlike a physical circuit, capacity need not be exclusively reserved unless the service explicitly does so.",
        ["Setup installs switch state", "Identifiers are local to links", "All packets normally follow the established route"],
        "Do not equate virtual circuit with dedicated bandwidth; connection state and resource reservation are separate features.",
        "VC identifier 7 arrives on input port 2 and table maps (2,7) to (5,11). What does the switch do?",
        "It sends the packet through output port 5 and replaces the local identifier 7 with 11. The next switch interprets 11 in the context of that next link rather than as a global address.",
      ),
    ],
    formulae: [
      { label: "Encapsulated length", expression: "payload + sum of headers and trailers added so far", useWhen: "Computing protocol overhead at a specified layer" },
      { label: "First-packet store-and-forward delay", expression: "kL/R over k equal-rate links", useWhen: "Ignoring propagation, processing, and queueing" },
    ],
    checkpoints: [
      { question: "How does a service differ from a protocol?", answer: "A service states what a layer offers upward, while a protocol defines messages and rules used by peer entities to implement communication." },
      { question: "Why can packet switching use link capacity efficiently?", answer: "Different flows statistically share a link, so idle periods in one flow can be used by packets from another instead of remaining reserved." },
      { question: "Can datagram packets arrive out of order?", answer: "Yes. Independent routing and variable queueing may make later packets reach the destination before earlier ones." },
      { question: "What state distinguishes virtual-circuit forwarding?", answer: "Intermediate switches keep mappings from an incoming port and VC identifier to an outgoing port and replacement identifier." },
      { question: "Does a virtual circuit necessarily reserve a dedicated physical path?", answer: "No. It establishes logical forwarding state; resource reservation depends on the particular virtual-circuit service." },
    ],
  }),
  lesson({
    subjectCode: "CN",
    subjectId: "computer-networks",
    topicId: "data-link-layer",
    title: "Data Link Layer",
    summary: "The data-link layer frames packets for one link, detects corruption with parity, checksum or CRC, coordinates medium access, and explains Ethernet addresses, switching, collision domains, CSMA behavior, and transparent bridging.",
    estimatedMinutes: 60,
    prerequisites: ["Polynomial arithmetic over bits", "Layering"],
    objectives: ["Compute CRC and detection conditions", "Compare medium-access methods", "Trace Ethernet switching", "Reason about framing and bridge learning"],
    concepts: [
      concept(
        "Framing and error detection",
        "Framing marks boundaries in a stream using length fields, delimiters with stuffing, or physical coding conventions. Error detection adds redundancy. Parity detects every odd number of bit flips but can miss even errors, while CRC treats a bit string as a polynomial over GF(2), appending a remainder so the transmitted polynomial is divisible by a generator.",
        ["Framing separates consecutive units", "Detection does not guarantee correction", "CRC division uses XOR without carries"],
        "Append exactly generator-degree zero bits before division and report a remainder with that many bits, including leading zeros.",
        "Data 1101 uses generator 1011. How is the CRC codeword formed?",
        "The generator degree is 3, so divide 1101000 by 1011 using XOR long division. The remainder is 001, and replacing the appended zeros gives codeword 1101001, which divides by 1011 with zero remainder.",
      ),
      concept(
        "Medium access",
        "A shared broadcast medium needs rules for deciding who transmits. Random-access methods such as slotted ALOHA and CSMA accept collision risk, while controlled approaches schedule turns. Ethernet CSMA/CD senses the channel, detects a collision while transmitting, aborts, and uses binary exponential backoff; switched full-duplex Ethernet has no shared collision domain and does not need collision detection.",
        ["Carrier sensing cannot remove propagation delay", "Backoff spreads retransmissions", "Full-duplex switching removes collisions"],
        "Use the specified Ethernet generation and duplex mode; applying CSMA/CD to a full-duplex switched link is incorrect.",
        "Why can two distant CSMA stations still collide after both sense idle?",
        "A signal takes time to propagate. Each station can sense before the other's transmission reaches it, decide the medium is idle, and begin. Their signals then overlap on the shared medium.",
      ),
      concept(
        "Ethernet switching and learning",
        "An Ethernet switch learns a source MAC address on the port where a frame arrives. For a known destination it forwards only to the learned port, for an unknown destination it floods other ports, and for a destination learned on the incoming port it filters the frame. Broadcast frames are flooded within the broadcast domain.",
        ["Learning uses source address", "Forwarding lookup uses destination address", "Unknown unicast is flooded"],
        "Update the source entry before deciding destination forwarding, and expire stale entries only if an aging rule is stated.",
        "A frame from A arrives on port 1 for unknown B. What occurs?",
        "The switch learns A→port 1, then finds no B entry and floods the frame through every other forwarding port. When B replies, the switch learns B's incoming port and can thereafter unicast between A and B.",
      ),
    ],
    formulae: [
      { label: "CRC redundancy", expression: "r = degree of generator; append r zeros and transmit data followed by r-bit remainder", useWhen: "Constructing a CRC codeword from data and generator" },
      { label: "Slotted ALOHA throughput", expression: "S = G e^(−G), maximum 1/e at G=1", useWhen: "A syllabus-aligned random-access throughput question explicitly gives slotted ALOHA" },
    ],
    checkpoints: [
      { question: "Can CRC correct a corrupted frame by itself?", answer: "Normally it only detects corruption; recovery requires retransmission or a separate error-correcting code." },
      { question: "Why is XOR used in CRC division?", answer: "Polynomial coefficients are in GF(2), where addition and subtraction are identical XOR operations without carries or borrows." },
      { question: "What address does an Ethernet switch learn?", answer: "It learns the source MAC address and associates it with the incoming port, because that shows where the source is reachable." },
      { question: "When is an unknown unicast flooded?", answer: "When the destination MAC is absent from the forwarding table, the switch sends the frame on eligible ports other than the incoming one." },
      { question: "Why is CSMA/CD unnecessary on full-duplex switched Ethernet?", answer: "Each endpoint has a dedicated transmit and receive path, so simultaneous transmissions do not collide on a shared medium." },
    ],
  }),
  lesson({
    subjectCode: "CN",
    subjectId: "computer-networks",
    topicId: "routing-algorithms",
    title: "Routing Algorithms",
    summary: "Routing algorithms compute paths using graph costs, flooding, distance-vector exchanges and link-state databases, with Bellman-Ford and Dijkstra reasoning explaining convergence, loops, count-to-infinity, shortest-path trees, and forwarding-table updates.",
    estimatedMinutes: 60,
    prerequisites: ["Weighted graphs", "Shortest paths", "Layering"],
    objectives: ["Run Dijkstra and Bellman-Ford updates", "Compare link-state and distance-vector routing", "Explain routing loops and convergence", "Separate route computation from packet forwarding"],
    concepts: [
      concept(
        "Shortest paths and forwarding",
        "A routing algorithm treats routers as vertices and links as weighted edges, where weights may encode delay, cost, or another metric. It computes a least-cost path or next hop for destinations, while forwarding applies the installed table independently to each packet. Equal-cost paths can exist even when one shortest-path tree representation selects one parent.",
        ["Metric defines path cost", "Routing computes tables", "Forwarding uses next-hop entries"],
        "Add link costs along complete paths and do not choose a next hop merely because its first edge is cheapest.",
        "Links A-B=2, B-C=2, A-C=7. What route from A to C is least cost?",
        "Direct A-C costs 7. The path A-B-C costs 2+2=4, so A forwards toward B for destination C and records total distance 4.",
      ),
      concept(
        "Distance-vector routing",
        "Each distance-vector router advertises its current destination distances to neighbors and applies the Bellman-Ford recurrence using neighbor link cost plus advertised distance. Information is local and iterative. After failures, stale mutually dependent advertisements can create loops and count-to-infinity; split horizon and poison reverse reduce some cases but do not make convergence instantaneous.",
        ["Routers exchange vectors with neighbors", "Updates use neighbor cost plus advertised distance", "Failures can converge slowly"],
        "An advertised distance from a neighbor excludes the cost of reaching that neighbor, which must be added exactly once.",
        "A reaches neighbors B at cost 3 and C at cost 5; they advertise distance to D as 4 and 1. What does A choose?",
        "Via B the cost is 3+4=7. Via C it is 5+1=6. A records distance 6 with next hop C, assuming no policy or loop-prevention rule changes the choice.",
      ),
      concept(
        "Link-state routing",
        "A link-state router discovers neighbor link costs, floods authenticated sequence-numbered advertisements, builds a common topology database, and runs Dijkstra from itself. Flooding supplies global topology knowledge, while sequence numbers and age help suppress duplicates and stale information. Every router computes its own shortest-path tree even from the same link-state database.",
        ["Link states are flooded", "Every router builds a topology graph", "Dijkstra finalizes minimum tentative distances"],
        "During Dijkstra, only the minimum tentative unvisited vertex is finalized; a tentative path can still improve beforehand.",
        "Dijkstra from A has tentative B=4 and C=7; relaxing B finds path to C of 5. Which value is finalized next?",
        "B is finalized first at 4 because it was the smallest tentative value. Its edge improves C from 7 to 5. If no other unvisited vertex is below 5, C is finalized next at 5.",
      ),
    ],
    formulae: [
      { label: "Distance-vector update", expression: "Dx(y) = min_v { c(x,v) + Dv(y) }", useWhen: "Router x evaluates routes through neighbors v" },
      { label: "Path cost", expression: "Sum of link costs along the path", useWhen: "Comparing candidate routes under additive metrics" },
    ],
    checkpoints: [
      { question: "What information does a distance-vector router normally know?", answer: "It knows costs to direct neighbors and distance estimates advertised by those neighbors, not necessarily the complete network topology." },
      { question: "What information does a link-state router build?", answer: "It builds a topology database of advertised links and costs, then computes shortest paths locally." },
      { question: "Why can count-to-infinity occur?", answer: "After a failure, neighbors can incorrectly treat one another's stale route as an alternate path and repeatedly increase the metric." },
      { question: "Does a shortest-path tree uniquely determine all equal-cost routes?", answer: "No. Equal-cost alternatives may exist; a particular tree selects representatives, while forwarding may support multiple next hops." },
      { question: "How does forwarding differ from routing?", answer: "Routing calculates and updates paths or tables; forwarding is the per-packet operation of selecting an output using the installed table." },
    ],
  }),
  lesson({
    subjectCode: "CN",
    subjectId: "computer-networks",
    topicId: "ipv4-addressing-and-forwarding",
    title: "IPv4 Addressing and Forwarding",
    summary: "IPv4 forwarding combines CIDR prefixes, longest-prefix match, fragmentation fields, ARP, DHCP, ICMP, and network address translation, including port translation and the end-to-end limitations introduced by shared public addresses.",
    estimatedMinutes: 70,
    prerequisites: ["Binary numbers", "Routing", "Data-link addresses"],
    objectives: ["Compute CIDR networks and ranges", "Apply longest-prefix forwarding", "Trace IPv4 fragmentation", "Explain ARP, DHCP, ICMP, NAT, and PAT"],
    concepts: [
      concept(
        "CIDR and longest-prefix match",
        "A CIDR prefix fixes the first p bits of a 32-bit address, leaving 32−p host bits. Masking an address with the prefix mask yields its network prefix. A forwarding table can contain overlapping prefixes; the router selects the matching entry with greatest prefix length before using route metric to choose among entries of equal specificity.",
        ["Prefix length counts fixed leading bits", "Masking finds the network", "Most specific matching route wins"],
        "Test prefix matching bitwise; numerical closeness between destination and network address does not define a route match.",
        "Which route handles 10.2.3.7 among 10.0.0.0/8, 10.2.0.0/16, and default /0?",
        "All three match, but /16 fixes the most leading bits and is therefore the longest matching prefix. The router uses the next hop on 10.2.0.0/16.",
      ),
      concept(
        "Fragmentation and support protocols",
        "An IPv4 router may fragment a datagram exceeding an outgoing MTU unless DF is set. All fragments share the identification value; fragment offset is measured in 8-byte units, and MF is one except on the final fragment. ARP resolves a next-hop IPv4 address to a link address, DHCP supplies configuration, and ICMP reports control and error information.",
        ["Fragment offsets count 8-byte units", "Nonfinal payloads align to 8 bytes", "Reassembly occurs at the destination"],
        "Subtract each fragment's IP header from MTU before choosing a payload, and set offset from original payload position rather than fragment number.",
        "A 2020-byte IPv4 datagram has a 20-byte header and crosses MTU 1020. How is payload split?",
        "Original payload is 2000 bytes. Each fragment can carry at most 1000 payload bytes, but nonfinal payload must be a multiple of 8, so use 1000 and 1000 since 1000 is divisible by 8. Offsets are 0 and 125; MF is 1 then 0.",
      ),
      concept(
        "NAT, PAT, and sockets at the boundary",
        "Basic NAT rewrites private and public IP addresses at an administrative boundary. Port address translation also rewrites transport ports so many internal connections share one public address, maintaining a mapping keyed by protocol and endpoint information. Return packets use that state to recover the internal destination. Unsolicited inbound connections need a configured mapping because no dynamic entry exists.",
        ["Private addresses are not globally routed", "PAT multiplexes flows with ports", "Translation state supports return traffic"],
        "Track checksum-relevant header changes and distinguish a transport port from an IP address in every mapping tuple.",
        "Hosts 10.0.0.2:5000 and 10.0.0.3:5000 share public 203.0.113.8. How can PAT distinguish them?",
        "The translator assigns distinct public source ports, for example 40001 and 40002, and records each mapping. Replies to public port 40001 return to 10.0.0.2:5000, while 40002 maps to 10.0.0.3:5000.",
      ),
    ],
    formulae: [
      { label: "CIDR address count", expression: "2^(32−p) addresses in an IPv4 /p block", useWhen: "Computing the total address count of an IPv4 prefix" },
      { label: "Fragment offset", expression: "starting original payload byte / 8", useWhen: "Filling the IPv4 fragment-offset field" },
      { label: "Maximum aligned fragment payload", expression: "floor((MTU−header)/8)×8", useWhen: "Sizing nonfinal IPv4 fragment payloads for a given MTU" },
    ],
    checkpoints: [
      { question: "Which route wins when several prefixes match?", answer: "The route with the greatest prefix length wins; metrics compare alternatives only after prefix specificity is resolved." },
      { question: "In what units is the IPv4 fragment offset stored?", answer: "It is stored in units of eight payload bytes measured from the beginning of the original datagram's payload." },
      { question: "What happens when DF is set and an outgoing MTU is too small?", answer: "The router drops the datagram and normally sends an ICMP message indicating fragmentation is needed rather than fragmenting it." },
      { question: "Does ARP find a remote destination's MAC across the Internet?", answer: "No. A host resolves the link-layer address of its next hop on the local link, often the default router." },
      { question: "Why does PAT need a table?", answer: "It must map each translated public protocol-port combination back to the correct private address and port for returning traffic." },
    ],
  }),
  lesson({
    subjectCode: "CN",
    subjectId: "computer-networks",
    topicId: "transport-layer",
    title: "Transport Layer",
    summary: "The transport layer provides process-to-process delivery through ports and sockets, contrasting UDP with TCP reliability, sequencing, acknowledgements, sliding-window flow control, connection establishment, retransmission, and congestion-window behavior.",
    estimatedMinutes: 70,
    prerequisites: ["IPv4 forwarding", "Sliding windows", "Basic probability"],
    objectives: ["Distinguish UDP and TCP service", "Identify connections and sockets", "Trace TCP sequence and acknowledgement numbers", "Reason about flow and congestion control"],
    concepts: [
      concept(
        "Ports, sockets, and demultiplexing",
        "A transport endpoint is identified by an IP address and port; a socket is the operating-system abstraction an application uses to send or receive. A TCP connection is commonly identified by source IP, source port, destination IP, and destination port, allowing one server port to support many clients. UDP demultiplexing is connectionless and preserves message boundaries.",
        ["Ports identify application endpoints", "TCP connections use a four-tuple", "UDP preserves datagram boundaries"],
        "Do not identify a TCP connection by server port alone; simultaneous clients differ in source endpoint information.",
        "Two clients connect to server 192.0.2.9:443 using source ports 51000 and 51001. Are these distinct TCP connections?",
        "Yes. Their four-tuples differ in source port, so the server kernel demultiplexes them to separate connected sockets even though both use the same destination address and port.",
      ),
      concept(
        "TCP reliability and flow control",
        "TCP is a byte-stream protocol: sequence numbers count bytes, acknowledgements are cumulative and name the next expected byte, and retransmission handles loss. The receiver advertises available buffer space as a window so the sender does not overrun it. SYN and FIN each consume one sequence number even when they carry no application payload.",
        ["Sequence space counts bytes", "ACK is next expected byte", "Receiver window protects buffer capacity"],
        "Advance sequence numbers by payload length and control-byte consumption, not by the number of segments.",
        "A segment starts at sequence 1000 and carries 300 bytes. What cumulative ACK follows if all arrive in order?",
        "The bytes are numbered 1000 through 1299, so the next expected byte is 1300. The receiver sends ACK 1300, assuming no earlier gap remains.",
      ),
      concept(
        "Connection and congestion control",
        "TCP's three-way handshake synchronizes initial sequence numbers and confirms bidirectional reachability. Congestion control limits in-flight data using a congestion window, while flow control uses the receiver window; the usable amount is bounded by both. Slow start grows rapidly per RTT, congestion avoidance grows roughly linearly, and loss signals trigger reductions under the stated TCP variant.",
        ["Handshake uses SYN, SYN-ACK, ACK", "Effective send window is bounded by cwnd and rwnd", "Congestion control protects the network"],
        "Keep receiver limitation and network-congestion limitation separate even though both constrain outstanding bytes.",
        "cwnd is 12 KiB and advertised rwnd is 8 KiB. Ignoring already outstanding data, how much may be sent?",
        "The sender is limited by min(cwnd,rwnd)=8 KiB because both network congestion and receiver capacity must permit the outstanding data. A larger congestion window cannot override the receiver's smaller available-buffer advertisement, so at most 8 KiB may be newly sent under the stated assumption that no earlier bytes remain unacknowledged.",
      ),
    ],
    formulae: [
      { label: "TCP connection identity", expression: "(source IP, source port, destination IP, destination port)", useWhen: "Distinguishing simultaneous TCP connections at a shared server endpoint" },
      { label: "Usable TCP window", expression: "min(cwnd, rwnd) minus outstanding unacknowledged bytes", useWhen: "Finding additional data the sender may transmit" },
      { label: "Next cumulative ACK", expression: "segment sequence + payload bytes (+ SYN/FIN if applicable)", useWhen: "Data arrive in order with no earlier gap" },
    ],
    checkpoints: [
      { question: "Does UDP guarantee delivery or ordering?", answer: "No. UDP provides checksum-based error detection and process demultiplexing but no retransmission, ordering, or congestion-control guarantee." },
      { question: "Does TCP preserve application write boundaries?", answer: "No. TCP presents an ordered byte stream, so receivers must define their own message framing if boundaries matter." },
      { question: "What does cumulative ACK 500 mean?", answer: "Every byte through 499 has been received in order and byte 500 is the next expected byte." },
      { question: "How do flow control and congestion control differ?", answer: "Flow control protects the receiving endpoint's buffer, while congestion control limits traffic to reduce overload inside the network." },
      { question: "Why is the third handshake message necessary?", answer: "It confirms to the server that the client received the server's initial sequence number and that the return path works." },
    ],
  }),
  lesson({
    subjectCode: "CN",
    subjectId: "computer-networks",
    topicId: "application-layer",
    title: "Application Layer",
    summary: "Application protocols define end-system messages and behavior for DNS naming, HTTP request-response exchange, SMTP mail transfer, FTP control and data connections, and mailbox access, while relying on transport services beneath them.",
    estimatedMinutes: 50,
    prerequisites: ["TCP and UDP", "Client-server architecture"],
    objectives: ["Trace DNS resolution and caching", "Compare HTTP connection behavior", "Explain email protocol roles", "Distinguish FTP control and data connections"],
    concepts: [
      concept(
        "DNS hierarchy and resolution",
        "DNS maps names to resource records through a hierarchy of root, top-level-domain, and authoritative servers. A client normally asks a local resolver, which can answer from cache or perform iterative queries. TTL limits cache lifetime. DNS commonly uses UDP for ordinary queries and TCP when required by response size, transfer, or protocol conditions.",
        ["Hierarchy delegates authority", "Resolvers cache records", "TTL bounds cached freshness"],
        "Differentiate recursive service requested by a client from iterative referrals followed by a resolver.",
        "A resolver has an unexpired A record cached for example.com. Must it contact a root server?",
        "No. It can answer immediately from cache until the record's TTL expires. Caching reduces delay and load but may temporarily retain an old value within its permitted lifetime.",
      ),
      concept(
        "HTTP exchanges and connections",
        "HTTP uses request and response messages containing methods, status codes, headers, and optional bodies. Nonpersistent operation creates a separate TCP connection per object, while persistent operation can reuse a connection, reducing repeated handshake delay. Cookies add application state across otherwise stateless request handling; caching can satisfy a request without fetching the full object again.",
        ["HTTP follows request-response", "Persistent connections reuse transport state", "Caching and cookies serve different purposes"],
        "When counting RTTs, state whether DNS, TCP setup, parallel connections, transmission time, and persistent pipelining are included.",
        "Ignoring DNS and transmission, one object uses nonpersistent HTTP over a fresh TCP connection. Approximate RTT count?",
        "One RTT establishes TCP and another carries the HTTP request until the first response bytes return, giving about two RTTs under the simplified model.",
      ),
      concept(
        "Email and file transfer",
        "SMTP pushes mail from a client to a mail server and between mail servers, while IMAP or POP lets a recipient access stored mail. MIME describes non-ASCII content and attachments. FTP uses a persistent control connection and separate data connections, so commands and transferred bytes travel on different transport connections and may have different lifetimes.",
        ["SMTP sends mail", "IMAP or POP retrieves mail", "FTP separates control and data"],
        "Match a protocol to its direction and role; SMTP does not provide the recipient's mailbox browsing interface.",
        "Which protocols participate when Alice sends mail and Bob later reads it with synchronized folders?",
        "Alice's client submits through SMTP, and mail servers relay through SMTP. Bob's client uses IMAP to access and synchronize messages stored on his server. MIME may encode attachments but does not itself transfer the mail.",
      ),
    ],
    formulae: [
      { label: "Simplified nonpersistent HTTP latency", expression: "1 RTT for TCP setup + 1 RTT for request/first response + transmission", useWhen: "One object, no DNS, no parallelism" },
      { label: "DNS cache validity", expression: "usable until stored time + TTL", useWhen: "Determining whether a resolver may answer without a new query" },
    ],
    checkpoints: [
      { question: "What server is authoritative for a DNS name?", answer: "A server holding the delegated source records for that name or zone, rather than merely a cached copy from another server." },
      { question: "Why can persistent HTTP reduce latency?", answer: "Multiple requests reuse one established TCP connection, avoiding a new transport handshake and related startup for every object." },
      { question: "Are cookies the same as HTTP caching?", answer: "No. Cookies carry application state or identifiers, while caches store reusable responses to reduce transfer and server work." },
      { question: "Which protocol transfers mail between mail servers?", answer: "SMTP handles submission and relay, while IMAP or POP provides recipient access to stored mailbox content." },
      { question: "Why does FTP use separate control and data connections?", answer: "Commands and session control remain on a persistent channel while each file or listing can use a distinct data-transfer connection." },
    ],
  }),
  lesson({
    subjectCode: "CN",
    subjectId: "computer-networks",
    topicId: "network-performance",
    title: "Network Performance",
    summary: "Network performance separates transmission, propagation, processing and queueing delays from bandwidth, throughput, utilization, bandwidth-delay product, pipelining, and bottleneck behavior so timing calculations reflect the actual path and traffic assumptions.",
    estimatedMinutes: 55,
    prerequisites: ["Layering and switching", "Units and rates", "Basic probability"],
    objectives: ["Compute all four delay components", "Distinguish bandwidth from throughput", "Use bandwidth-delay product", "Analyze packet trains and bottlenecks"],
    concepts: [
      concept(
        "Delay components",
        "Transmission delay is the time to place packet bits onto a link and depends on packet length and rate. Propagation delay is travel time through the medium and depends on distance and propagation speed. Processing covers header work, while queueing depends on contention and is variable. End-to-end delay sums applicable components at every hop.",
        ["Transmission uses L/R", "Propagation uses distance/speed", "Queueing depends on offered load"],
        "Keep bits and bytes consistent, and multiply per-hop transmission only when store-and-forward actually repeats it.",
        "A 1500-byte packet uses a 12 Mbps link. Find transmission delay.",
        "The packet has 1500×8=12000 bits. Dividing by 12,000,000 bits/s gives 0.001 s, or 1 ms. Distance is irrelevant to transmission delay.",
      ),
      concept(
        "Throughput and bottlenecks",
        "Link bandwidth is the nominal transmission rate, while throughput is the achieved delivery rate after bottlenecks, contention, protocol overhead, and losses. Along a simple steady path, the slowest link limits long-run throughput. A file's completion time also includes startup delays, so dividing file size by bottleneck rate alone may omit important latency for short transfers.",
        ["Bandwidth is capacity", "Throughput is achieved rate", "Slowest path link limits steady flow"],
        "Use minimum link rate for steady-state throughput but still add propagation and setup when total completion time is requested.",
        "A path has links of 10, 4, and 20 Mbps with no competing traffic. Maximum steady throughput?",
        "The 4 Mbps link is the bottleneck, so the path cannot sustain more than 4 Mbps. Faster links may transmit in bursts but cannot raise long-run delivery past the bottleneck.",
      ),
      concept(
        "Bandwidth-delay product and utilization",
        "Bandwidth-delay product measures the number of bits that can be in flight over a path or link during a propagation or round-trip interval, depending on the definition used. Sliding-window protocols need enough outstanding data to fill this pipe. Stop-and-wait wastes capacity when the frame transmission time is small compared with round-trip propagation and acknowledgement delay.",
        ["BDP is rate times delay", "Window must cover in-flight data", "Large RTT can lower stop-and-wait utilization"],
        "Check whether the problem uses one-way delay or RTT and whether acknowledgement transmission time is negligible.",
        "A 5 Mbps path has RTT 40 ms. What window fills the path ignoring overhead?",
        "Rate×RTT is 5,000,000×0.04=200,000 bits, or 25,000 bytes. At least that much unacknowledged data is needed to keep the path continuously occupied under the simplified model.",
      ),
    ],
    formulae: [
      { label: "Transmission delay", expression: "d_trans = L/R", useWhen: "L bits are serialized onto a link of R bits/s" },
      { label: "Propagation delay", expression: "d_prop = distance / propagation speed", useWhen: "Computing signal travel time across a physical communication medium" },
      { label: "Bandwidth-delay product", expression: "BDP = rate × relevant path delay", useWhen: "Estimating in-flight bits or required window" },
    ],
    checkpoints: [
      { question: "Does increasing link rate reduce propagation delay?", answer: "No. Propagation depends on distance and signal speed; link rate reduces the time needed to serialize the packet." },
      { question: "Why is queueing delay not normally a fixed packet property?", answer: "It depends on other traffic, service rate, arrival timing, and queue occupancy encountered by that packet." },
      { question: "What limits end-to-end steady throughput on a serial path?", answer: "The bottleneck link or resource with the smallest available service rate limits the long-run delivery rate." },
      { question: "What does bandwidth-delay product represent?", answer: "It estimates how much data can be outstanding in the path during the chosen delay interval, often one RTT for window sizing." },
      { question: "Why can stop-and-wait have poor utilization on a long-delay path?", answer: "The sender transmits one frame quickly and then remains idle for most of the round trip while waiting for its acknowledgement." },
    ],
  }),
];

const aptitudeTopics: LearningTopic[] = [
  lesson({
    subjectCode: "GA",
    subjectId: "general-aptitude",
    topicId: "verbal-aptitude",
    title: "Verbal Aptitude",
    summary: "Verbal aptitude tests grammar, vocabulary in context, sentence completion, logical connectors, reading comprehension, inference, and narrative sequencing, rewarding evidence-based interpretation rather than isolated memorization or outside assumptions.",
    estimatedMinutes: 55,
    prerequisites: ["Basic English reading"],
    objectives: ["Apply core grammar agreements", "Infer word meaning from context", "Separate stated facts from inferences", "Arrange sentences into a coherent narrative"],
    concepts: [
      concept(
        "Grammar and sentence structure",
        "A well-formed sentence coordinates subject-verb agreement, pronoun reference, tense, modifiers, articles, prepositions, and parallel structure. Agreement follows the grammatical head rather than the nearest noun. A modifier should sit near what it describes, and items joined in a list or comparison should use matching grammatical forms so meaning remains unambiguous.",
        ["Find the grammatical subject", "Keep tense consistent with timeline", "Use parallel forms for coordinated ideas"],
        "Read the complete clause before selecting an option; nearby plural nouns often distract from a singular head subject.",
        "Choose: The quality of the reports is/are improving.",
        "The head subject is quality, which is singular. The phrase of the reports modifies quality but does not control agreement, so the correct verb is is: The quality of the reports is improving.",
      ),
      concept(
        "Vocabulary and logical connectors",
        "Word meaning is often recoverable from contrast, cause, example, tone, and nearby restatement. Connectors encode relationships: however signals contrast, therefore signals a conclusion, because introduces a reason, and moreover adds supporting information. The best completion must fit both grammar and the argument's direction, not merely sound familiar in isolation.",
        ["Context constrains meaning", "Connectors express argument structure", "Tone distinguishes near-synonyms"],
        "Substitute each candidate into the sentence and paraphrase the logical link in plain language before choosing.",
        "Complete: The method is inexpensive; ___, it is too inaccurate for safety-critical use.",
        "The second clause contrasts a benefit with a serious limitation, so however is appropriate. Therefore would incorrectly present inaccuracy as a consequence of low cost, and moreover would imply both facts support the same direction.",
      ),
      concept(
        "Comprehension and sequencing",
        "Reading-comprehension answers must be supported by the passage's claims, examples, qualifications, or necessary implications. A plausible outside fact is not evidence. Narrative sequencing uses reference words, chronology, cause-effect links, general-to-specific movement, and introduction before elaboration. Pronouns and definite phrases normally follow the sentence that introduces their referent.",
        ["Use passage evidence only", "Necessary inference is stronger than possibility", "References and chronology constrain order"],
        "For every answer, point to the sentence or relationship that supports it and test whether the wording is stronger than the source.",
        "Arrange: (P) This reduced waiting time. (Q) The clinic introduced online appointments. (R) Earlier, patients queued at dawn.",
        "R establishes the earlier problem, Q introduces the change, and P describes its result. The coherent order is R-Q-P. The word This in P refers to the appointment change, so P cannot precede Q.",
      ),
    ],
    formulae: [
      { label: "Evidence rule", expression: "Valid answer = stated claim or necessary inference from the passage", useWhen: "Eliminating attractive but unsupported comprehension choices" },
      { label: "Connector map", expression: "contrast: however; cause: because; result: therefore; addition: moreover", useWhen: "Selecting a sentence connector that preserves the intended logical relation" },
    ],
    checkpoints: [
      { question: "What controls agreement in 'A set of tools is available'?", answer: "The head noun set is singular, so the verb is singular even though the modifying phrase contains plural tools." },
      { question: "How should an unfamiliar word be handled in comprehension?", answer: "Use surrounding contrast, examples, tone, and grammatical role to infer the meaning required in that particular context." },
      { question: "What makes an inference valid?", answer: "It must follow necessarily or with the strength requested from passage evidence, without adding an unsupported outside premise." },
      { question: "Why do pronouns help sentence sequencing?", answer: "A pronoun usually refers to an entity introduced earlier, constraining the reference sentence to follow its antecedent." },
      { question: "What is wrong with an answer stronger than the passage?", answer: "Words such as always or impossible may turn a qualified statement into an unsupported absolute, even when the general topic matches." },
    ],
  }),
  lesson({
    subjectCode: "GA",
    subjectId: "general-aptitude",
    topicId: "quantitative-aptitude",
    title: "Quantitative Aptitude",
    summary: "Quantitative aptitude combines numerical estimation, ratios, percentages, powers, logarithms, counting, probability, sequences, data interpretation, elementary statistics, geometry, and mensuration through unit-aware calculation and efficient comparison.",
    estimatedMinutes: 70,
    prerequisites: ["Arithmetic", "Fractions and algebra"],
    objectives: ["Solve ratio and percentage changes", "Interpret tables and charts", "Apply counting and probability", "Use geometry, mensuration, statistics, powers, and logarithms"],
    concepts: [
      concept(
        "Ratios, percentages, and estimation",
        "A ratio compares quantities in the same units, while a percentage expresses a part per hundred. Successive changes multiply scale factors rather than add signed percentages. Estimation checks magnitude and can eliminate choices before exact arithmetic. Weighted averages must weight each group by its count or contribution instead of averaging group averages directly.",
        ["Convert percentage change to a multiplier", "Successive changes compound", "Weighted mean uses group sizes"],
        "Keep the base quantity explicit; a percentage increase and decrease of equal size do not cancel because their bases differ.",
        "A price rises 20% and then falls 20%. What is the net change?",
        "Use multipliers 1.20 and 0.80. Their product is 0.96, so the final price is 96% of the original, a net decrease of 4%, not zero.",
      ),
      concept(
        "Counting, probability, powers, and series",
        "The product rule counts independent sequential choices, permutations count ordered selections, and combinations count unordered selections. Probability divides favorable equally likely outcomes by total outcomes or uses complements and conditional structure. Exponent and logarithm laws simplify multiplicative growth, while arithmetic and geometric sequences provide direct term and sum relationships.",
        ["Order determines permutation versus combination", "Complement handles at least one", "Logarithms convert products to sums"],
        "Define the sample space and whether repetition is allowed before choosing a counting formula.",
        "From five people, how many two-person committees can be formed, and why?",
        "A committee does not assign roles, so order is irrelevant. Choose 2 of 5: C(5,2)=5×4/(2×1)=10. Counting AB and BA separately would double the answer incorrectly.",
      ),
      concept(
        "Data, statistics, and mensuration",
        "Data interpretation requires reading labels, scales, units, totals, and whether values are absolute or percentage-based before computing. Mean uses all observations, median follows sorted position, mode is most frequent, and standard deviation describes spread. Geometry and mensuration reduce figures to standard lengths, areas, and volumes, with unit conversion applied before combining measurements.",
        ["Read chart scale before arithmetic", "Median requires ordering", "Area and volume use squared and cubed units"],
        "Write the requested denominator and units beside each intermediate value; many options reflect a wrong base or unit conversion.",
        "A rectangle is 8 m by 5 m. A path 1 m wide runs inside its boundary. Find path area.",
        "Outer area is 8×5=40 m². The inner rectangle loses 1 m from both sides of each dimension, becoming 6×3=18 m². The path area is 40−18=22 m².",
      ),
    ],
    formulae: [
      { label: "Successive percentage factors", expression: "final = initial × (1+a/100) × (1+b/100)", useWhen: "Applying consecutive percentage changes to the same evolving quantity" },
      { label: "Combinations", expression: "nCr = n! / (r!(n−r)!)", useWhen: "Selecting r unordered items without repetition" },
      { label: "Arithmetic-series sum", expression: "Sn = n/2 [2a+(n−1)d]", useWhen: "Summing n terms of an arithmetic progression" },
    ],
    checkpoints: [
      { question: "Why do equal percentage increase and decrease not cancel?", answer: "The decrease is applied to the already increased value, so the two percentages use different bases and their multipliers produce a net loss." },
      { question: "When is nPr used instead of nCr?", answer: "Use permutations when the selected items occupy distinct positions or order matters; use combinations when only membership matters." },
      { question: "What is often the fastest way to compute at least one success?", answer: "Compute one minus the probability of no successes, provided the sample model and any independence assumptions are valid." },
      { question: "Can two datasets have the same mean but different standard deviations?", answer: "Yes. Their centers may match while one dataset is more spread around that center, producing a larger standard deviation." },
      { question: "Why must length units be converted before an area calculation?", answer: "Area squares the chosen length unit, so mixing metres and centimetres directly creates a scale error that is also squared." },
    ],
  }),
  lesson({
    subjectCode: "GA",
    subjectId: "general-aptitude",
    topicId: "analytical-aptitude",
    title: "Analytical Aptitude",
    summary: "Analytical aptitude converts verbal conditions into precise logical constraints, supporting deduction, induction, analogy, ordering, grouping, implication, truth evaluation, numerical relationships, and elimination of arrangements that violate even one rule.",
    estimatedMinutes: 60,
    prerequisites: ["Basic logic", "Tables and ordering"],
    objectives: ["Translate statements into constraints", "Derive valid conclusions", "Solve ordering and grouping problems", "Recognize analogies and numerical patterns"],
    concepts: [
      concept(
        "Deduction and implication",
        "Deductive reasoning asks what must follow from stated premises. If P implies Q, observing P permits Q, and observing not-Q permits not-P by contraposition; observing Q does not prove P. Words such as all, some, only, unless, necessary, and sufficient must be translated carefully because their directions determine which conclusions are valid.",
        ["Modus ponens uses P and P→Q", "Contrapositive is logically equivalent", "Affirming the consequent is invalid"],
        "Test a proposed conclusion by constructing a counterexample that satisfies every premise; one such model disproves necessity.",
        "All coders are logical. Mira is logical. Must Mira be a coder?",
        "No. The premise says coder→logical, not logical→coder. Mira could be logical for another reason. Concluding coder would affirm the consequent and is not deductively valid.",
      ),
      concept(
        "Ordering, grouping, and constraint propagation",
        "Arrangement problems become manageable when each sentence is converted into a position, adjacency, exclusion, or membership constraint. Place the strongest fixed relations first, propagate consequences, and branch only when alternatives remain. A candidate arrangement is valid only if every condition holds; satisfying most constraints does not earn partial logical validity.",
        ["Translate prose into compact constraints", "Propagate before branching", "Verify every original rule at the end"],
        "Distinguish immediately before from somewhere before, and either-or inclusive from exactly-one exclusive wording.",
        "A,B,C sit in a row. A is left of B, and C is not at an end. Find the order.",
        "C must occupy the middle. A must be left of B, so A cannot be right end and B cannot be left end. The only order satisfying both constraints is A-C-B.",
      ),
      concept(
        "Analogy, induction, and numerical relations",
        "An analogy compares relationships rather than surface appearance: object-function, part-whole, cause-effect, degree, or transformation. Inductive pattern questions infer a rule from examples, but the simplest consistent operation is preferred within the options. Numerical sequences may use differences, ratios, alternating subsequences, position-based formulas, or combinations of these.",
        ["Match relationship type", "Check alternating patterns", "Use all given terms before extending"],
        "A rule that fits only the last transition is weaker than one explaining the entire sequence and the answer choices.",
        "Find the next term: 2, 6, 12, 20, 30, ...",
        "Successive differences are 4,6,8,10, increasing by 2, so the next difference is 12 and the term is 42. Equivalently term n is n(n+1), which also gives 6×7=42 for n=6.",
      ),
    ],
    formulae: [
      { label: "Contrapositive", expression: "P→Q is equivalent to ¬Q→¬P", useWhen: "Deriving a valid implication from a necessary condition" },
      { label: "Constraint validity", expression: "candidate is valid iff every stated constraint evaluates true", useWhen: "Checking arrangements or grouping options" },
    ],
    checkpoints: [
      { question: "From P→Q and Q, may P be concluded?", answer: "No. That is affirming the consequent; Q may hold for reasons other than P." },
      { question: "What does 'A only if B' mean?", answer: "It means A→B: B is necessary for A, although B alone need not be sufficient to establish A." },
      { question: "Why should fixed constraints be placed first in an arrangement?", answer: "They reduce the remaining possibilities and propagate consequences, avoiding unnecessary case branches and repeated checking." },
      { question: "How should an analogy option be judged?", answer: "It should reproduce the same relationship between the new pair, not merely share a topic or a superficial property." },
      { question: "Why test alternating subsequences in a number series?", answer: "Odd and even positions may follow separate simple rules even when consecutive-term differences look irregular." },
    ],
  }),
  lesson({
    subjectCode: "GA",
    subjectId: "general-aptitude",
    topicId: "spatial-aptitude",
    title: "Spatial Aptitude",
    summary: "Spatial aptitude tracks translation, rotation, reflection, scaling, assembly, grouping, paper folding, cutting, and two- or three-dimensional patterns by preserving adjacency, orientation, chirality, symmetry, and repeated transformations.",
    estimatedMinutes: 55,
    prerequisites: ["Basic geometry", "Visualizing directions"],
    objectives: ["Track rotations and reflections", "Preserve adjacency in cube and assembly problems", "Reverse paper folds and cuts", "Identify transformed 2D and 3D patterns"],
    concepts: [
      concept(
        "Transformations and orientation",
        "Translation moves every point equally, rotation turns a figure around a center, reflection reverses handedness across a line or plane, and scaling changes size while preserving shape under uniform scale. A rotation preserves clockwise order and chirality, whereas a mirror reflection reverses them. Tracking one asymmetric marker prevents confusion when a symmetric outline looks unchanged.",
        ["Rotation preserves handedness", "Reflection reverses orientation", "Translation changes position but not facing"],
        "Follow a marked corner or arrow through every operation instead of mentally rotating the whole unmarked outline at once.",
        "An arrow points north and rotates 90° clockwise twice. Where does it point?",
        "The first rotation points east and the second points south. Two 90° clockwise turns equal one 180° rotation, so the final direction is opposite the original.",
      ),
      concept(
        "Folding, cutting, and symmetry",
        "Each paper fold maps points across a fold line and places layers together. A cut through folded layers appears at all reflected positions when folds are reversed, except holes on a fold line can coincide with their reflections. Solve backward by unfolding the last fold first and reflecting every current mark across that line.",
        ["Unfold in reverse order", "Reflect cuts across each fold", "Marks on fold axes may overlap"],
        "Do not simply double the hole count at every unfolding; symmetry-axis holes and coincident images require position tracking.",
        "A square is folded once vertically and one hole is punched away from the fold. How many holes after unfolding?",
        "Unfolding reflects the punch across the vertical fold line, giving two symmetric holes. Because the punch is not on the fold, the original and reflected locations are distinct.",
      ),
      concept(
        "Cubes, nets, and assembly",
        "Cube problems depend on face adjacency and opposition, not the page positions of a net after folding. Faces sharing an edge remain adjacent, opposite faces never meet, and three mutually adjacent faces can meet at a vertex. For assemblies, boundary contours, connector compatibility, and occupied volume help eliminate pieces that cannot fit even after rotation.",
        ["Opposite cube faces never share an edge", "A net changes planar orientation when folded", "Rigid rotation preserves adjacency"],
        "Create an adjacency table from the net before imagining colors or symbols in three dimensions.",
        "On a standard cube, U is opposite D and F is opposite B. Can U, D, and F meet at one vertex?",
        "No. U and D are opposite faces and can never share an edge or vertex. A valid vertex uses one face from each opposite pair, such as U, F, and R.",
      ),
    ],
    formulae: [
      { label: "Planar quarter-turn", expression: "90° clockwise: (x,y)→(y,−x) about the origin", useWhen: "Coordinates or marked points are rotated in 2D" },
      { label: "Single off-axis fold", expression: "one punch produces a reflected pair after complete unfolding", useWhen: "There is one fold and the punch is not on its axis" },
    ],
    checkpoints: [
      { question: "Which transformation reverses handedness?", answer: "A reflection reverses orientation or chirality, whereas translations and rotations preserve it." },
      { question: "In what order should several paper folds be undone?", answer: "Undo them in reverse order, reflecting all existing cut positions across the most recently removed fold each time." },
      { question: "Why might hole count fail to double after a fold is opened?", answer: "A hole on the fold axis reflects to the same position, and multiple reflected images can coincide." },
      { question: "Can opposite cube faces meet at a vertex?", answer: "No. Opposite faces are disjoint and parallel; every cube vertex contains one face from each of three opposite pairs." },
      { question: "What properties remain unchanged under rigid rotation of a puzzle piece?", answer: "Distances, angles, connectivity, adjacency, and handedness remain unchanged, although absolute direction and position change." },
    ],
  }),
];

export const SYSTEMS_LEARNING_TOPICS: LearningTopic[] = [
  ...tocTopics,
  ...compilerTopics,
  ...operatingSystemTopics,
  ...databaseTopics,
  ...networkTopics,
  ...aptitudeTopics,
];
