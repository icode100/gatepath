import type { LearningTopic } from "../types";

export const FOUNDATION_LEARNING_TOPICS: LearningTopic[] = [
  {
    subjectCode: "EM",
    subjectId: "engineering-mathematics",
    topicId: "discrete-mathematics",
    title: "Discrete Mathematics",
    summary:
      "Discrete mathematics supplies the language used to reason about finite structures in computer science. This lesson connects logic, sets, relations, algebraic structures, graphs, counting, and recurrences while emphasizing the definitions and invariants that GATE questions repeatedly test.",
    estimatedMinutes: 65,
    prerequisites: ["Basic algebra", "Comfort with symbolic notation"],
    objectives: [
      "Translate statements between English, propositional logic, and quantified logic",
      "Classify relations and functions from their defining properties",
      "Use graph invariants and counting principles without double-counting",
      "Solve standard recurrences and identify elementary algebraic structures",
    ],
    concepts: [
      {
        title: "Logic, sets, relations, and functions",
        explanation:
          "A proposition has a definite truth value, and compound propositions are evaluated by their logical connectives. Quantifiers extend this reasoning to a domain: negating a universal statement produces an existential counterexample, while negating an existential statement produces a universal denial. Sets provide the objects on which relations and functions act. A binary relation is classified by checking reflexivity, symmetry, antisymmetry, and transitivity independently. Equivalence relations partition a set into disjoint classes; partial orders instead organize comparable elements and may produce lattices when every pair has a meet and join.",
        keyIdeas: [
          "Negation swaps universal and existential quantifiers",
          "Equivalence means reflexive, symmetric, and transitive",
          "A partial order is reflexive, antisymmetric, and transitive",
        ],
        examFocus:
          "GATE often gives a small relation or quantified formula and asks which properties hold; test each definition directly instead of relying on its appearance.",
        example: {
          prompt:
            "On the integers, define a relation aRb when a-b is divisible by 4. Determine its type and describe the resulting classes.",
          walkthrough:
            "Because a-a=0 is divisible by 4, the relation is reflexive. If 4 divides a-b, it also divides b-a, so it is symmetric. Divisibility of a-b and b-c implies divisibility of a-c, giving transitivity. It is therefore an equivalence relation with four residue classes: integers congruent to 0, 1, 2, or 3 modulo 4.",
        },
      },
      {
        title: "Counting, recurrences, and algebraic structure",
        explanation:
          "The sum rule counts mutually exclusive alternatives, whereas the product rule counts sequences of choices. Inclusion-exclusion corrects the overcount created by overlapping sets, and the pigeonhole principle guarantees repetition when more objects occupy fewer containers. Permutations preserve order and combinations ignore it. A recurrence specifies a sequence through earlier values; substitution, characteristic roots, or generating functions can expose its closed form. Monoids and groups are recognized from closure, associativity, an identity, and—only for groups—inverses. Commutativity is an additional property rather than part of the basic group definition.",
        keyIdeas: [
          "Use inclusion-exclusion whenever counted cases overlap",
          "Choose permutations only when order changes an outcome",
          "A group adds inverses to the monoid requirements",
        ],
        examFocus:
          "Expect short counting problems, coefficient questions, and property-based MSQs in which one missing group or recurrence condition changes the answer.",
        example: {
          prompt:
            "How many length-five binary strings contain at least one pair of consecutive 1s?",
          walkthrough:
            "Count the complement. Binary strings of length n with no consecutive 1s satisfy a_n=a_(n-1)+a_(n-2), because a valid string ends in 0 after any valid prefix or in 10 after a shorter valid prefix. With a_1=2 and a_2=3, a_5=13. There are 2^5=32 total strings, so 32-13=19 contain consecutive 1s.",
        },
      },
      {
        title: "Graphs, trees, and structural invariants",
        explanation:
          "A graph is described by vertices and edges, with adjacency, degree, paths, cycles, and connectivity providing the central vocabulary. The handshaking lemma states that the sum of all vertex degrees in an undirected graph is twice the number of edges, immediately implying an even number of odd-degree vertices. A tree is a connected acyclic graph; for n vertices it has exactly n-1 edges, and any two vertices have a unique simple path. Directed graphs require separate in-degree and out-degree accounting, while bipartite graphs are exactly those containing no odd cycle.",
        keyIdeas: [
          "Degree sum equals twice the number of undirected edges",
          "A tree is connected, acyclic, and has n-1 edges",
          "A graph is bipartite exactly when it has no odd cycle",
        ],
        examFocus:
          "GATE graph questions frequently collapse to one invariant; check edge count, degree parity, connectivity, and cycles before attempting a longer construction.",
        example: {
          prompt:
            "A connected graph has 12 vertices and 12 edges. What can be concluded about its cycles?",
          walkthrough:
            "A connected graph on 12 vertices needs at least 11 edges, and with exactly 11 it would be a tree. The additional twelfth edge joins two vertices already connected by a unique tree path, creating one cycle. Thus the graph is unicyclic: removing an edge from that cycle yields a spanning tree.",
        },
      },
    ],
    formulae: [
      {
        label: "Inclusion-exclusion for two sets",
        expression: "|A union B| = |A| + |B| - |A intersection B|",
        useWhen: "Two counted properties can occur together",
      },
      {
        label: "Handshaking lemma",
        expression: "sum(deg(v)) = 2|E|",
        useWhen: "Relating vertex degrees to the number of undirected edges",
      },
      {
        label: "Linear recurrence",
        expression: "a_n = c1 a_(n-1) + ... + ck a_(n-k)",
        useWhen: "A sequence is defined by a fixed linear combination of earlier terms",
      },
    ],
    checkpoints: [
      {
        question: "What is the negation of: every process holds a resource?",
        answer:
          "There exists at least one process that does not hold a resource. Negation swaps the universal quantifier for an existential quantifier and negates the predicate.",
      },
      {
        question: "Why can an equivalence relation not have overlapping equivalence classes?",
        answer:
          "If two classes share an element, symmetry and transitivity make every member of either class related to every member of the other, so the two classes are actually identical.",
      },
      {
        question: "How many edges does a tree with 25 vertices contain?",
        answer:
          "It contains 24 edges. Every finite tree with n vertices has exactly n-1 edges; adding an edge creates a cycle and removing one disconnects it.",
      },
      {
        question: "When should combinations replace permutations?",
        answer:
          "Use combinations when only the selected members matter and rearranging them does not create a new outcome. Use permutations when different orders are distinct outcomes.",
      },
      {
        question: "What distinguishes a group from a monoid?",
        answer:
          "Both require closure, associativity, and an identity. A group additionally requires every element to have an inverse within the set under the same operation.",
      },
    ],
  },
  {
    subjectCode: "DL",
    subjectId: "digital-logic",
    topicId: "boolean-algebra",
    title: "Boolean Algebra",
    summary:
      "Boolean algebra turns logical conditions into expressions that can be analyzed, minimized, and implemented with gates. GATE problems reward precise use of duality, complements, canonical forms, and Karnaugh-map adjacency rather than lengthy expansion by trial and error.",
    estimatedMinutes: 50,
    prerequisites: ["Binary values", "Elementary set logic"],
    objectives: [
      "Apply Boolean identities and De Morgan laws",
      "Convert between truth tables, minterms, maxterms, SOP, and POS",
      "Minimize small functions algebraically and with Karnaugh maps",
      "Recognize equivalent gate-level realizations",
    ],
    concepts: [
      {
        title: "Boolean identities and duality",
        explanation:
          "Boolean variables take values 0 and 1, with OR, AND, and complement forming the basic operations. Identity, null, idempotent, complement, absorption, and distributive laws permit exact symbolic simplification. De Morgan's laws complement an entire expression by swapping AND with OR and complementing each operand. The dual of a valid identity is formed by interchanging 0 with 1 and AND with OR while leaving variables and complements unchanged. XOR represents inequality of two bits and is useful for parity, whereas XNOR represents equality.",
        keyIdeas: [
          "Absorption removes redundant terms quickly",
          "De Morgan swaps operators while complementing operands",
          "Duality transforms one valid identity into another",
        ],
        examFocus:
          "GATE expressions often contain a hidden absorption or consensus pattern; simplify locally before expanding products into many terms.",
        example: {
          prompt: "Simplify F = A + A'B + AB'.",
          walkthrough:
            "Apply A+A'B=A+B. Then F=A+B+AB'. Absorption gives A+AB'=A, leaving A+B. A truth-table check confirms the only zero occurs when A=0 and B=0.",
        },
      },
      {
        title: "Canonical forms and truth-table translation",
        explanation:
          "A minterm is an AND term containing every variable once and evaluates to one for exactly one assignment. A maxterm is an OR term containing every variable once and evaluates to zero for exactly one assignment. Canonical sum-of-products lists minterms where the function is one; canonical product-of-sums lists maxterms where it is zero. Indexing convention reads an assignment as a binary number, usually with the first named variable as the most significant bit. Noncanonical expressions can be expanded to canonical form, but a truth table is often safer for checking indexes.",
        keyIdeas: [
          "Minterms identify rows where a function equals one",
          "Maxterms identify rows where a function equals zero",
          "Variable order determines canonical indexes",
        ],
        examFocus:
          "Write the declared variable order beside the table; reversed significance is a frequent source of otherwise correct but wrongly indexed answers.",
        example: {
          prompt:
            "For variables A,B,C, write the minterm and maxterm associated with assignment 101.",
          walkthrough:
            "The minterm must be one at A=1,B=0,C=1, so it is AB'C and has index 5. The maxterm must be zero at the same row; a variable appears uncomplemented when its row value is 0 and complemented when it is 1, giving A'+B+C', also index 5.",
        },
      },
      {
        title: "Karnaugh maps and implicants",
        explanation:
          "A Karnaugh map arranges truth-table cells in Gray-code order so adjacent cells differ in one variable. Grouping adjacent ones in powers of two produces product implicants for SOP minimization; grouping zeros similarly produces sum terms for POS. Groups may wrap across edges and overlap, and every required cell must be covered. A prime implicant cannot be enlarged, while an essential prime implicant uniquely covers at least one required minterm. Don't-care cells may join a group when they help create a larger implicant, but they need not be covered.",
        keyIdeas: [
          "Valid group sizes are powers of two",
          "Map edges wrap but diagonal cells are not adjacent",
          "Use don't-cares only when they improve minimization",
        ],
        examFocus:
          "Choose the largest groups first and then identify essential coverage; GATE may ask for all valid minimal forms when choices are nonunique.",
        example: {
          prompt: "Minimize the three-variable function F(A,B,C)=Sigma m(1,3,5,7).",
          walkthrough:
            "The listed assignments are 001,011,101,111. In every one, C=1 while A and B take all possibilities. The four cells form one group of four, eliminating A and B. Therefore the minimal function is simply F=C.",
        },
      },
    ],
    formulae: [
      {
        label: "De Morgan laws",
        expression: "(XY)'=X'+Y' and (X+Y)'=X'Y'",
        useWhen: "Pushing a complement through a Boolean expression or changing gate type",
      },
      {
        label: "Absorption",
        expression: "X+XY=X and X(X+Y)=X",
        useWhen: "One term already covers every assignment of a more specific term",
      },
      {
        label: "Consensus",
        expression: "XY + X'Z + YZ = XY + X'Z",
        useWhen: "Removing a term implied by two complementary-variable terms",
      },
    ],
    checkpoints: [
      {
        question: "What is the complement of X+YZ?",
        answer:
          "By De Morgan's law it is X'(YZ)'=X'(Y'+Z'). Both the outer OR and inner AND change operators as complements move inward.",
      },
      {
        question: "How does a minterm differ from a general product term?",
        answer:
          "A minterm contains every variable exactly once, complemented or not, and selects one truth-table row. A general product term may omit variables and cover several rows.",
      },
      {
        question: "Can diagonal Karnaugh-map cells form a group?",
        answer:
          "No. Diagonal cells differ in two variables. Only horizontal or vertical Gray-code neighbors, including wrap-around edge neighbors, differ in one variable.",
      },
      {
        question: "Must every don't-care cell be grouped?",
        answer:
          "No. A don't-care may be treated as either value. Include it only when it enlarges a useful group or reduces the final implementation.",
      },
      {
        question: "Why is X XOR X always zero?",
        answer:
          "XOR is one only when its inputs differ. The two copies of X always have equal values, so inequality never occurs and the result is zero.",
      },
    ],
  },
  {
    subjectCode: "DL",
    subjectId: "digital-logic",
    topicId: "combinational-circuits",
    title: "Combinational Circuits",
    summary:
      "Combinational circuits produce outputs determined solely by current inputs. This lesson develops a disciplined path from specification to truth table, minimized logic, and realization using adders, multiplexers, decoders, encoders, and comparators within the GATE syllabus.",
    estimatedMinutes: 55,
    prerequisites: ["Boolean algebra", "Binary arithmetic"],
    objectives: [
      "Design half and full adders from truth tables",
      "Realize Boolean functions with multiplexers and decoders",
      "Interpret encoder, decoder, and comparator behavior",
      "Estimate data-input and select-line requirements",
    ],
    concepts: [
      {
        title: "Specification and arithmetic building blocks",
        explanation:
          "Combinational design begins by naming inputs and outputs, enumerating valid input combinations, and deriving one Boolean function per output. A half adder adds two bits and produces sum A XOR B and carry AB. A full adder includes a carry-in; its sum is the parity of three input bits, and its carry is one when at least two inputs are one. Multi-bit addition chains full adders, causing ripple-carry delay. Subtraction can be built from addition by complementing the subtrahend and supplying the initial carry for two's-complement arithmetic.",
        keyIdeas: [
          "Combinational outputs have no stored history",
          "Full-adder carry is a three-input majority function",
          "Ripple delay grows with the carry chain",
        ],
        examFocus:
          "GATE often asks the number of adders, carry expression, or longest propagation path in a small arithmetic circuit.",
        example: {
          prompt:
            "Use full-addition reasoning to add one-bit inputs A=1, B=1, Cin=0.",
          walkthrough:
            "There are two one inputs, so the three-input parity is even and Sum=0. At least two inputs are one, so Cout=1. The output pair 10 represents decimal two, matching 1+1+0.",
        },
      },
      {
        title: "Multiplexers as selectors and function generators",
        explanation:
          "A multiplexer routes one of several data inputs to a single output according to binary select inputs. With s select lines, a conventional multiplexer selects among 2^s data inputs. It can realize a Boolean function by assigning some variables to selects and expressing the remaining dependence on data inputs as 0, 1, a variable, or its complement. Shannon expansion explains this construction: a function is split according to a selected variable's zero and one cofactors. Cascading smaller multiplexers builds larger selectors, with enable pins controlling active stages.",
        keyIdeas: [
          "s select lines address 2^s data inputs",
          "Data inputs may be constants or residual variable functions",
          "Shannon expansion underlies MUX realization",
        ],
        examFocus:
          "When a MUX is smaller than the truth table, choose select variables strategically and compute each data input from the remaining rows.",
        example: {
          prompt:
            "Realize F(A,B,C)=Sigma m(1,2,6,7) using a 4-to-1 MUX with A and B as selects.",
          walkthrough:
            "Inspect pairs of rows for each AB. For 00, F follows C, so I0=C. For 01, F is one only at C=0, so I1=C'. For 10, neither minterm appears, so I2=0. For 11, both 6 and 7 appear, so I3=1.",
        },
      },
      {
        title: "Decoders, encoders, and comparators",
        explanation:
          "An n-to-2^n decoder activates the output corresponding to the binary input, effectively generating minterms. OR-ing selected decoder outputs realizes any SOP function of those inputs. An encoder performs the reverse mapping when exactly one input is active; a priority encoder resolves multiple active inputs according to a declared priority. A magnitude comparator reports whether one binary word is less than, equal to, or greater than another. Comparison proceeds from the most significant unequal bit, because lower positions cannot override its greater positional weight.",
        keyIdeas: [
          "Decoder outputs correspond to minterms",
          "Priority encoders define behavior for multiple active inputs",
          "Magnitude comparison starts at the most significant bit",
        ],
        examFocus:
          "Watch active-low notation and enable inputs in decoder questions; a bubble may complement the apparent asserted level without changing the decoded index.",
        example: {
          prompt:
            "How can a 3-to-8 decoder implement F(A,B,C)=Sigma m(0,3,5)?",
          walkthrough:
            "Connect A,B,C to the decoder address inputs. Its outputs D0 through D7 represent the eight minterms. OR D0, D3, and D5 to produce F, assuming active-high outputs. For active-low outputs, the combining gate polarity must be adjusted using De Morgan's law.",
        },
      },
    ],
    formulae: [
      {
        label: "Full-adder outputs",
        expression: "S=A xor B xor Cin; Cout=AB+ACin+BCin",
        useWhen: "Adding two bits and a carry-in",
      },
      {
        label: "Multiplexer capacity",
        expression: "data inputs = 2^(select lines)",
        useWhen: "Sizing or cascading a selector",
      },
      {
        label: "Shannon expansion",
        expression: "F = X' F|_(X=0) + X F|_(X=1)",
        useWhen: "Decomposing a function for multiplexer realization",
      },
    ],
    checkpoints: [
      {
        question: "What distinguishes a full adder from a half adder?",
        answer:
          "A full adder accepts a carry-in in addition to two operand bits and produces sum and carry-out. A half adder has only the two operand inputs.",
      },
      {
        question: "How many select lines does a 32-to-1 MUX require?",
        answer:
          "It requires log2(32)=5 select lines, because five binary bits identify one of 32 data inputs.",
      },
      {
        question: "Why can a decoder implement any Boolean function of its inputs?",
        answer:
          "Its outputs generate every minterm. OR-ing precisely the minterms where the desired function is one produces its canonical sum-of-products form.",
      },
      {
        question: "What problem does a priority encoder solve?",
        answer:
          "It defines a unique encoded result when several inputs are asserted by selecting the active input with the highest specified priority.",
      },
      {
        question: "Which bit decides comparison of two unequal binary words first?",
        answer:
          "The most significant position at which they differ decides. Its positional weight exceeds the combined effect of all less significant positions.",
      },
    ],
  },
  {
    subjectCode: "DL",
    subjectId: "digital-logic",
    topicId: "sequential-circuits",
    title: "Sequential Circuits",
    summary:
      "Sequential circuits combine combinational logic with stored state, making outputs depend on present inputs and earlier events. GATE questions emphasize latch and flip-flop behavior, characteristic and excitation tables, register movement, counter sequences, and finite-state reasoning.",
    estimatedMinutes: 60,
    prerequisites: ["Boolean algebra", "Combinational circuits", "Clocked timing basics"],
    objectives: [
      "Distinguish latches from edge-triggered flip-flops",
      "Use characteristic and excitation relations for common flip-flops",
      "Analyze registers and synchronous or ripple counters",
      "Derive state tables and outputs for finite-state circuits",
    ],
    concepts: [
      {
        title: "Storage elements and timing behavior",
        explanation:
          "An SR latch stores one bit through feedback and is level-sensitive; its set and reset controls must avoid the forbidden simultaneous assertion for the usual implementation. A D latch removes that ambiguity by deriving complementary set and reset actions from one data input. A flip-flop samples only on its active clock edge, separating input changes from state updates. Setup and hold requirements define the interval around that edge during which data must remain stable. Violating them can cause metastability, so clocked analysis assumes those timing constraints are satisfied unless stated otherwise.",
        keyIdeas: [
          "Latches are level-sensitive and flip-flops are edge-triggered",
          "State changes only at the declared active event",
          "Setup and hold constraints protect reliable sampling",
        ],
        examFocus:
          "Read whether a symbol is active-high, active-low, level-sensitive, or edge-triggered before tracing a waveform; the same data pattern can produce different states.",
        example: {
          prompt:
            "A positive-edge D flip-flop sees D values 0,1,0 immediately before three rising edges. What are its successive Q values?",
          walkthrough:
            "At each rising edge the flip-flop copies the stable D value. Therefore Q becomes 0 after the first edge, 1 after the second, and 0 after the third. Changes between rising edges do not alter Q.",
        },
      },
      {
        title: "Characteristic and excitation reasoning",
        explanation:
          "A characteristic relation predicts next state from current state and inputs; an excitation table works backward, identifying inputs needed for a desired transition. A D flip-flop has Q_next=D. A T flip-flop holds for T=0 and toggles for T=1. A JK flip-flop holds at 00, resets at 01, sets at 10, and toggles at 11, avoiding the forbidden SR combination. Converting one flip-flop type into another means equating its characteristic behavior to the required next-state function and simplifying the necessary input logic.",
        keyIdeas: [
          "Characteristic tables analyze; excitation tables design",
          "T=1 and JK=11 both toggle the stored bit",
          "D directly specifies the next state",
        ],
        examFocus:
          "For circuit synthesis, first create the present-state/next-state table, then use excitation requirements; guessing input equations usually misses don't-care opportunities.",
        example: {
          prompt:
            "Implement a T flip-flop behavior using a D flip-flop. What D input is required?",
          walkthrough:
            "A T flip-flop requires Q_next=Q when T=0 and Q_next=Q' when T=1, which is Q xor T. Since a D flip-flop sets Q_next equal to D, connect D=Q xor T.",
        },
      },
      {
        title: "Registers, counters, and state machines",
        explanation:
          "A register groups flip-flops under a shared clock to store a word, with shift registers moving bits left or right each active edge. Counters visit a prescribed state sequence. In an asynchronous ripple counter, one stage clocks the next and delays accumulate; a synchronous counter clocks all stages together and uses logic to decide which bits toggle. A modulo-m counter needs at least ceiling(log2 m) flip-flops, though unused binary states may require recovery logic. Finite-state machines generalize this idea through a state table; Moore outputs depend on state, while Mealy outputs also depend directly on input.",
        keyIdeas: [
          "Registers store and shift multi-bit state",
          "Synchronous counters avoid cumulative ripple delay",
          "Moore outputs use state; Mealy outputs use state and input",
        ],
        examFocus:
          "Trace counters only at active clock events and list unused states; GATE may ask whether a proposed design is self-starting after entering an invalid state.",
        example: {
          prompt:
            "How many flip-flops are minimally required for a modulo-10 counter, and how many binary states remain unused?",
          walkthrough:
            "Three flip-flops provide only eight states, so four are required because 2^4=16 covers ten states. The intended sequence uses ten states and leaves six unused states, whose transitions should be considered in a robust design.",
        },
      },
    ],
    formulae: [
      {
        label: "D flip-flop",
        expression: "Q_next = D",
        useWhen: "The desired next-state function can directly drive D",
      },
      {
        label: "T flip-flop",
        expression: "Q_next = Q xor T",
        useWhen: "A state bit should conditionally toggle",
      },
      {
        label: "Counter state-bit lower bound",
        expression: "n = ceiling(log2 m)",
        useWhen: "Finding the minimum flip-flops for a modulo-m sequence",
      },
    ],
    checkpoints: [
      {
        question: "What is the main timing difference between a latch and a flip-flop?",
        answer:
          "A latch can follow its input throughout an active level, while an edge-triggered flip-flop samples only at a specified clock transition.",
      },
      {
        question: "What does a JK flip-flop do when J=K=1?",
        answer:
          "It toggles: the next state is the complement of the present state. This replaces the forbidden simultaneous set/reset behavior of a basic SR element.",
      },
      {
        question: "Why is a synchronous counter faster than a ripple counter?",
        answer:
          "All its flip-flops receive the clock together, so a clock transition does not have to ripple through each preceding stage's propagation delay.",
      },
      {
        question: "How many states can six flip-flops represent?",
        answer:
          "They represent 2^6=64 distinct binary states, although a particular counter or state machine may intentionally use fewer.",
      },
      {
        question: "How do Moore and Mealy outputs differ?",
        answer:
          "A Moore output is determined only by the current state. A Mealy output is a function of both current state and current input, so it may respond sooner.",
      },
    ],
  },
  {
    subjectCode: "DL",
    subjectId: "digital-logic",
    topicId: "number-representation-and-arithmetic",
    title: "Number Representation and Arithmetic",
    summary:
      "Digital systems represent integers and real values with finite bit patterns, so range, sign, precision, and overflow must be interpreted deliberately. This lesson covers positional conversion, signed representations, fixed-point and floating-point ideas, and binary arithmetic used in GATE.",
    estimatedMinutes: 60,
    prerequisites: ["Powers of two", "Binary addition"],
    objectives: [
      "Convert values among common positional bases",
      "Interpret unsigned, sign-magnitude, one's-complement, and two's-complement words",
      "Detect signed and unsigned overflow",
      "Reason about fixed-point and floating-point range and precision",
    ],
    concepts: [
      {
        title: "Positional systems and unsigned arithmetic",
        explanation:
          "In a radix-r positional system, each digit multiplies a power of r. Binary, octal, and hexadecimal conversions are especially direct because groups of three or four binary bits map to one digit. An n-bit unsigned word represents values 0 through 2^n-1. Addition discards any carry beyond the fixed width, effectively computing modulo 2^n; that discarded carry signals unsigned overflow. Subtraction can be performed by adding a radix complement, which is why complement representations are central to hardware arithmetic.",
        keyIdeas: [
          "An n-bit unsigned word has 2^n patterns",
          "Fixed-width addition operates modulo 2^n",
          "Hexadecimal groups binary digits in fours",
        ],
        examFocus:
          "Write the word width beside every operation. The same bit pattern has different numeric meaning under unsigned and signed interpretations.",
        example: {
          prompt:
            "Add unsigned 8-bit values 250 and 20 and report the stored result and overflow indication.",
          walkthrough:
            "The mathematical sum is 270, beyond the unsigned 8-bit maximum 255. Modulo 256, the stored word represents 14. A carry leaves the most significant position, so unsigned overflow is indicated even though the hardware still stores a valid eight-bit pattern.",
        },
      },
      {
        title: "Signed integers and overflow",
        explanation:
          "Sign-magnitude and one's-complement representations each have separate positive and negative zero patterns. Two's complement avoids that duplication and lets the same adder handle signed addition and subtraction. An n-bit two's-complement word ranges from -2^(n-1) through 2^(n-1)-1; negation complements every bit and adds one, except that the most negative value has no positive counterpart in the same width. Signed overflow occurs when adding equal-sign operands produces an opposite-sign result, not merely when a final carry appears.",
        keyIdeas: [
          "Two's complement has one zero and an asymmetric range",
          "Sign extension preserves a two's-complement value",
          "Signed overflow depends on operand and result signs",
        ],
        examFocus:
          "Separate carry-out from signed overflow. GATE frequently presents a bitwise sum where one occurs without the other.",
        example: {
          prompt:
            "In 8-bit two's complement, add 100 and 40. Interpret the stored pattern and identify overflow.",
          walkthrough:
            "100 is 01100100 and 40 is 00101000. Their sum is 10001100, which as an 8-bit two's-complement value represents -116. Two positive operands produced a negative sign bit, so signed overflow occurred; the true sum 140 exceeds the maximum 127.",
        },
      },
      {
        title: "Fixed-point and floating-point reasoning",
        explanation:
          "Fixed-point representation assigns an implicit binary point, giving constant spacing between representable values but trading integer range for fractional precision. Floating-point separates sign, exponent, and significand so spacing scales with magnitude. A normalized value has a leading nonzero significand digit, avoiding multiple encodings and maximizing precision. Exponent bias permits unsigned storage of positive and negative exponents. Arithmetic may require exponent alignment and rounding, so finite precision introduces representation error; increasing exponent bits mainly extends range, while increasing significand bits mainly improves precision.",
        keyIdeas: [
          "Fixed point has uniform resolution",
          "Exponent width controls floating range",
          "Significand width controls floating precision",
        ],
        examFocus:
          "For a simplified floating format, account separately for sign, biased exponent, hidden leading bit if specified, and the requested rounding rule.",
        example: {
          prompt:
            "A fixed-point unsigned word has 8 bits with 3 fractional bits. What are its resolution and maximum value?",
          walkthrough:
            "Three fractional bits make the least significant weight 2^-3=0.125, which is the resolution. All eight bits set give the integer pattern 255 scaled by 2^-3, so the maximum represented value is 255/8=31.875.",
        },
      },
    ],
    formulae: [
      {
        label: "Unsigned range",
        expression: "0 to 2^n - 1",
        useWhen: "Interpreting an n-bit word without a sign",
      },
      {
        label: "Two's-complement range",
        expression: "-2^(n-1) to 2^(n-1)-1",
        useWhen: "Interpreting an n-bit signed integer",
      },
      {
        label: "Fixed-point value",
        expression: "stored integer * 2^(-fractional bits)",
        useWhen: "An implicit binary point divides integer and fractional positions",
      },
    ],
    checkpoints: [
      {
        question: "What is the unsigned range of a 12-bit word?",
        answer:
          "It is 0 through 2^12-1=4095, providing 4096 distinct bit patterns in total.",
      },
      {
        question: "How is a two's-complement number negated?",
        answer:
          "Complement every bit and add one within the same width. The most negative value is exceptional because its positive magnitude is not representable.",
      },
      {
        question: "When does signed addition overflow?",
        answer:
          "It overflows when two positive operands yield a negative stored result or two negative operands yield a nonnegative result. Opposite-sign addition cannot overflow.",
      },
      {
        question: "What does sign extension do?",
        answer:
          "It copies the sign bit into new higher positions when widening a two's-complement word, preserving the represented numeric value.",
      },
      {
        question: "Which floating-point field primarily improves precision?",
        answer:
          "Additional significand or fraction bits improve precision by placing representable values closer together. Additional exponent bits primarily extend range.",
      },
    ],
  },
  {
    subjectCode: "EM",
    subjectId: "engineering-mathematics",
    topicId: "linear-algebra",
    title: "Linear Algebra",
    summary:
      "Linear algebra for GATE centers on matrices as transformations and systems of equations. The important habits are tracking legal row operations, interpreting rank and determinants, recognizing eigen-information, and understanding why triangular factorization simplifies repeated solution work.",
    estimatedMinutes: 55,
    prerequisites: ["Simultaneous linear equations", "Polynomial algebra"],
    objectives: [
      "Determine consistency and solution count using ranks",
      "Compute determinants efficiently and interpret singularity",
      "Find and reason about eigenvalues and eigenvectors",
      "Use triangular systems and LU decomposition correctly",
    ],
    concepts: [
      {
        title: "Systems, elimination, and rank",
        explanation:
          "Gaussian elimination replaces a system by an equivalent echelon-form system through row swaps, nonzero row scaling, and adding a multiple of one row to another. Rank is the number of pivots and measures the dimension of the row or column space. For Ax=b, consistency requires rank(A)=rank([A|b]). If that common rank equals the number of unknowns, the solution is unique; if it is smaller, free variables create infinitely many solutions. A greater augmented rank identifies a contradictory row and therefore no solution.",
        keyIdeas: [
          "Elementary row operations preserve the solution set",
          "Rank counts independent rows, columns, or pivots",
          "Compare coefficient and augmented ranks for consistency",
        ],
        examFocus:
          "GATE often embeds a parameter in a matrix; locate the parameter value that removes a pivot or creates an inconsistent augmented row.",
        example: {
          prompt:
            "For which k does x+y=2 and 2x+2y=k have infinitely many solutions, and when is it inconsistent?",
          walkthrough:
            "The second equation has the same left side as twice the first. If k=4, both equations represent one line, rank(A)=rank([A|b])=1<2, so infinitely many solutions exist. If k differs from 4, elimination gives 0=k-4, making the augmented rank 2 while rank(A)=1; the system is inconsistent.",
        },
      },
      {
        title: "Determinants and matrix structure",
        explanation:
          "The determinant is a scalar that records whether a square matrix is invertible and how its transformation scales signed volume. It is zero exactly when rows or columns are linearly dependent. Swapping two rows changes its sign, scaling a row scales the determinant, and adding a multiple of another row leaves it unchanged. Cofactor expansion is useful for sparse matrices, while elimination or triangular form is usually faster. For a triangular matrix, the determinant is simply the product of diagonal entries, which also reveals singularity immediately.",
        keyIdeas: [
          "A matrix is nonsingular exactly when its determinant is nonzero",
          "Row swaps reverse determinant sign",
          "Triangular determinants are diagonal products",
        ],
        examFocus:
          "Keep a ledger of determinant changes during elimination; many one-mark questions are designed around a missed row-scaling or row-swap factor.",
        example: {
          prompt:
            "A matrix is reduced to diag(2,3,5) using one row swap and otherwise only row additions. Find its original determinant.",
          walkthrough:
            "The diagonal matrix has determinant 2*3*5=30. Row additions do not alter a determinant, but the single row swap multiplies it by -1. Therefore the reduced determinant is the negative of the original determinant, so the original determinant equals -30.",
        },
      },
      {
        title: "Eigenvalues, eigenvectors, and LU factorization",
        explanation:
          "An eigenvector keeps its direction under a linear transformation: Av=lambda v for a nonzero v. Eigenvalues are roots of det(A-lambda I)=0. Their sum equals the trace and their product equals the determinant when algebraic multiplicity is counted. Distinct eigenvalues have linearly independent eigenvectors, but repeated eigenvalues do not guarantee diagonalizability. LU decomposition writes A as a lower-triangular matrix times an upper-triangular matrix, turning Ax=b into two inexpensive triangular solves and becoming especially useful for several right-hand sides.",
        keyIdeas: [
          "Eigenvalues solve the characteristic equation",
          "Trace and determinant give eigenvalue sum and product",
          "LU reduces a solve to forward and backward substitution",
        ],
        examFocus:
          "Exploit triangular matrices, trace, determinant, and known eigenvectors before expanding a characteristic polynomial; GATE rewards structural shortcuts.",
        example: {
          prompt:
            "A 2x2 matrix has trace 7 and determinant 10. Determine its eigenvalues and whether they must be distinct.",
          walkthrough:
            "The characteristic polynomial is lambda^2-7lambda+10. Factoring gives (lambda-5)(lambda-2), so the eigenvalues are 5 and 2. They are distinct, which guarantees two linearly independent eigenvectors and hence diagonalizability for this 2x2 matrix.",
        },
      },
    ],
    formulae: [
      {
        label: "Consistency criterion",
        expression: "rank(A) = rank([A|b])",
        useWhen: "Deciding whether Ax=b has at least one solution",
      },
      {
        label: "Characteristic equation",
        expression: "det(A - lambda I) = 0",
        useWhen: "Finding eigenvalues of a square matrix",
      },
      {
        label: "Eigenvalue invariants",
        expression: "sum(lambda_i)=trace(A), product(lambda_i)=det(A)",
        useWhen: "Checking or inferring eigenvalues without full expansion",
      },
    ],
    checkpoints: [
      {
        question: "What does rank(A)<rank([A|b]) imply?",
        answer:
          "It implies Ax=b is inconsistent. Elimination has produced a constraint in the augmented column that cannot be generated by the coefficient columns.",
      },
      {
        question: "How does multiplying one row by c affect a determinant?",
        answer:
          "It multiplies the determinant by c. When elimination scales rows, that factor must be removed or recorded when recovering the original determinant.",
      },
      {
        question: "What does a zero eigenvalue say about a square matrix?",
        answer:
          "The matrix is singular because the product of eigenvalues, equal to its determinant, is zero. A nonzero vector also lies in its null space.",
      },
      {
        question: "Do repeated eigenvalues always prevent diagonalization?",
        answer:
          "No. Diagonalization depends on having enough independent eigenvectors. A repeated eigenvalue may have a full eigenspace, as the identity matrix demonstrates.",
      },
      {
        question: "Why is LU useful for multiple right-hand sides?",
        answer:
          "The expensive factorization of A is performed once. Each new b then requires only forward substitution in Ly=b and backward substitution in Ux=y.",
      },
    ],
  },
  {
    subjectCode: "EM",
    subjectId: "engineering-mathematics",
    topicId: "calculus",
    title: "Calculus",
    summary:
      "GATE calculus questions test whether a function's local behavior supports a claimed limit, derivative, extremum, or integral. A disciplined solution checks domain, continuity, differentiability, endpoints, and theorem hypotheses before applying familiar computational rules, then verifies the result against graph or sign behavior.",
    estimatedMinutes: 50,
    prerequisites: ["Functions and graphs", "Algebraic manipulation"],
    objectives: [
      "Evaluate standard limits and distinguish continuity from differentiability",
      "Use derivative tests to classify extrema",
      "Apply Rolle and mean-value theorems only when their hypotheses hold",
      "Connect definite integrals with antiderivatives and signed area",
    ],
    concepts: [
      {
        title: "Limits, continuity, and differentiability",
        explanation:
          "A limit describes values approached near a point and need not equal the function's assigned value there. Continuity at a requires the limit to exist, equal f(a), and use a defined f(a). Differentiability is stronger: a finite two-sided derivative implies continuity, but a continuous corner such as |x| need not be differentiable. For piecewise functions, compare left and right limits first, then match the common limit to the function value. Algebraic cancellation is valid near a removable point even when the original expression is undefined exactly there.",
        keyIdeas: [
          "A two-sided limit requires matching one-sided limits",
          "Differentiability implies continuity, not conversely",
          "Piecewise boundary checks must include the assigned value",
        ],
        examFocus:
          "Parameter questions commonly ask for continuity or differentiability at a join; solve the continuity condition before equating one-sided derivatives.",
        example: {
          prompt:
            "Choose a and b so f(x)=ax+b for x<1 and f(x)=x^2 for x>=1 is differentiable at 1.",
          walkthrough:
            "Continuity requires a+b=1. The left derivative is a, while the right derivative of x^2 at 1 is 2, so differentiability requires a=2. Substituting into the continuity equation gives b=-1. Both value and slope now agree at the join.",
        },
      },
      {
        title: "Derivatives, extrema, and mean values",
        explanation:
          "A derivative measures instantaneous rate of change. Interior differentiable local extrema must occur at critical points where f'=0, but a stationary point may also be an inflection point. The sign change of f' gives the most direct classification: positive-to-negative indicates a local maximum and negative-to-positive a local minimum. On a closed interval, absolute extrema can also occur at endpoints, so every critical point and endpoint must be evaluated. Rolle's and the mean-value theorem require continuity on the closed interval and differentiability inside it.",
        keyIdeas: [
          "Stationary does not automatically mean extreme",
          "Derivative sign changes classify local extrema",
          "Closed-interval optimization includes endpoints",
        ],
        examFocus:
          "Do not apply the mean-value theorem across a discontinuity or corner; checking hypotheses is often the entire conceptual test in an MSQ.",
        example: {
          prompt:
            "Find the absolute extrema of f(x)=x^3-3x on [-2,2].",
          walkthrough:
            "Differentiate to get f'=3x^2-3, so critical points are x=-1 and x=1. Evaluate all candidates: f(-2)=-2, f(-1)=2, f(1)=-2, and f(2)=2. Thus the absolute maximum is 2 at x=-1 and 2, while the absolute minimum is -2 at x=-2 and 1.",
        },
      },
      {
        title: "Integration and the fundamental theorem",
        explanation:
          "An indefinite integral represents a family of antiderivatives, while a definite integral is a number measuring signed accumulation. The fundamental theorem states that if F'=f, then the integral of f from a to b is F(b)-F(a). Substitution reverses the chain rule, and integration by parts reverses the product rule. Symmetry offers fast checks: an odd integrand integrates to zero on [-a,a], while an even integrand contributes twice its integral over [0,a]. Signed area can cancel, so geometric area may require splitting where the function changes sign.",
        keyIdeas: [
          "Definite integration evaluates an antiderivative at bounds",
          "Odd functions cancel over symmetric intervals",
          "Geometric area and signed integral are not always equal",
        ],
        examFocus:
          "Before performing lengthy integration, inspect symmetry, interval orientation, and sign changes; these often reduce a GATE numerical answer to one step.",
        example: {
          prompt:
            "Evaluate the integral of x^3+2x^2 from -1 to 1.",
          walkthrough:
            "The x^3 term is odd, so its contribution over the symmetric interval is zero. The 2x^2 term is even, giving twice the integral from 0 to 1: 2 times integral(2x^2)=4[x^3/3]_0^1=4/3. The required value is therefore 4/3.",
        },
      },
    ],
    formulae: [
      {
        label: "Derivative definition",
        expression: "f'(a) = lim_(h->0) (f(a+h)-f(a))/h",
        useWhen: "Checking differentiability or deriving a derivative from first principles",
      },
      {
        label: "Mean-value theorem",
        expression: "f'(c) = (f(b)-f(a))/(b-a) for some c in (a,b)",
        useWhen: "f is continuous on [a,b] and differentiable on (a,b)",
      },
      {
        label: "Fundamental theorem",
        expression: "integral_a^b f(x)dx = F(b)-F(a), where F'=f",
        useWhen: "Evaluating a definite integral through an antiderivative",
      },
    ],
    checkpoints: [
      {
        question: "Can a function be continuous but not differentiable at a point?",
        answer:
          "Yes. The absolute-value function is continuous at zero but has different left and right slopes there, so its derivative does not exist.",
      },
      {
        question: "Why is f'(c)=0 insufficient to prove a local maximum?",
        answer:
          "A stationary point may be a minimum or an inflection point. The derivative sign change or an appropriate higher-derivative test is needed for classification.",
      },
      {
        question: "Which points must be tested for an absolute extremum on [a,b]?",
        answer:
          "Test every interior critical point where the derivative is zero or undefined, and also both endpoints, provided the function is continuous on the interval.",
      },
      {
        question: "What is the integral of an odd function over [-a,a]?",
        answer:
          "It is zero because values at x and -x cancel exactly. This is signed cancellation, not a claim that the enclosed geometric area is zero.",
      },
      {
        question: "When may Rolle's theorem be applied?",
        answer:
          "The function must be continuous on the closed interval, differentiable on its interior, and have equal endpoint values. Then some interior derivative equals zero.",
      },
    ],
  },
  {
    subjectCode: "EM",
    subjectId: "engineering-mathematics",
    topicId: "probability-and-statistics",
    title: "Probability and Statistics",
    summary:
      "Probability and statistics questions in GATE combine careful event modeling with compact distribution facts. The goal is to identify the experiment, condition on the correct information, and use expectation, variance, and standard named distributions without confusing independence with exclusivity.",
    estimatedMinutes: 65,
    prerequisites: ["Sets and counting", "Basic calculus"],
    objectives: [
      "Apply conditional probability, independence, and Bayes theorem",
      "Compute expectation, variance, and descriptive statistics",
      "Recognize binomial, Poisson, exponential, uniform, and normal models",
      "Use distribution properties to simplify numerical questions",
    ],
    concepts: [
      {
        title: "Events, conditioning, and Bayes reasoning",
        explanation:
          "A probability space assigns probabilities to events within a sample space. Conditional probability P(A|B) restricts attention to outcomes where B occurred. Independence means learning B does not change the probability of A, equivalently P(A intersection B)=P(A)P(B); mutually exclusive nonempty events are therefore not independent. The total-probability rule partitions an observation across possible causes, and Bayes theorem reverses the conditioning direction by weighting each prior cause by its likelihood. Drawing a tree or table prevents denominator errors when populations have different base rates.",
        keyIdeas: [
          "Conditioning changes the effective sample space",
          "Independence is not mutual exclusivity",
          "Bayes combines prior probability with likelihood",
        ],
        examFocus:
          "Base-rate problems are common: normalize all prior-times-likelihood products rather than comparing likelihoods alone.",
        example: {
          prompt:
            "A server is overloaded 10% of the time. An alarm fires with probability 0.9 when overloaded and 0.2 otherwise. Find P(overloaded | alarm).",
          walkthrough:
            "The overload-and-alarm probability is 0.1*0.9=0.09. Total alarm probability is 0.09+0.9*0.2=0.27. Bayes theorem gives 0.09/0.27=1/3. The high alarm sensitivity does not make overload overwhelmingly likely because overload has a small prior probability.",
        },
      },
      {
        title: "Random variables, expectation, and spread",
        explanation:
          "A random variable maps outcomes to numbers and is described by a probability mass function in the discrete case or density in the continuous case. Expectation is a probability-weighted average and is linear even when variables are dependent. Variance measures squared deviation: Var(X)=E[X^2]-E[X]^2. Adding a constant shifts the mean but not variance, while multiplying by a scales variance by a^2. Covariance captures joint linear variation; independence implies zero covariance when moments exist, but zero covariance alone does not generally prove independence.",
        keyIdeas: [
          "Expectation is linear without an independence assumption",
          "Variance equals the second moment minus squared mean",
          "Scaling by a multiplies variance by a squared",
        ],
        examFocus:
          "GATE frequently asks transformed-variable means and variances; apply shift and scale rules before expanding a probability table.",
        example: {
          prompt:
            "A random variable X has mean 4 and variance 9. Find the mean and variance of Y=3X-2.",
          walkthrough:
            "Linearity gives E[Y]=3E[X]-2=10. Subtracting 2 has no effect on spread, and multiplying X by 3 multiplies its variance by 3^2. Therefore Var(Y)=9*9=81, with standard deviation 9.",
        },
      },
      {
        title: "Named distributions and statistical summaries",
        explanation:
          "A binomial variable counts successes in a fixed number of independent Bernoulli trials with constant success probability. Poisson models counts in a fixed interval and can approximate a binomial with large n and small p. Exponential waiting times are memoryless and pair naturally with Poisson arrivals. Uniform variables assign equal density across an interval, while the normal distribution is symmetric about its mean and standardized using Z=(X-mu)/sigma. Sample mean, median, mode, and standard deviation summarize center and spread but react differently to outliers.",
        keyIdeas: [
          "Binomial mean and variance are np and np(1-p)",
          "Poisson mean equals its variance",
          "Exponential waiting time is memoryless",
        ],
        examFocus:
          "Identify what is being counted or timed before choosing a distribution; fixed trials, interval counts, and waiting times point to different models.",
        example: {
          prompt:
            "Each transmitted bit is wrong independently with probability 0.01. For 100 bits, estimate the probability of exactly one error using Poisson approximation.",
          walkthrough:
            "The binomial parameters are n=100 and p=0.01, giving lambda=np=1. Poisson approximation gives P(X=1)=e^-1 * 1^1/1!=e^-1, approximately 0.3679. The approximation is suitable because n is large and p is small.",
        },
      },
    ],
    formulae: [
      {
        label: "Bayes theorem",
        expression: "P(A|B) = P(B|A)P(A)/P(B)",
        useWhen: "Reversing a conditional probability after observing evidence",
      },
      {
        label: "Variance identity",
        expression: "Var(X) = E[X^2] - (E[X])^2",
        useWhen: "The first two raw moments are easier to calculate than deviations",
      },
      {
        label: "Binomial moments",
        expression: "E[X]=np, Var(X)=np(1-p)",
        useWhen: "X counts successes in n independent Bernoulli trials",
      },
    ],
    checkpoints: [
      {
        question: "Can two nonempty mutually exclusive events be independent?",
        answer:
          "No. Their intersection has probability zero, while independence would require the positive product P(A)P(B). They can only be both exclusive and independent if one has zero probability.",
      },
      {
        question: "Does linearity of expectation require independent variables?",
        answer:
          "No. E[X+Y]=E[X]+E[Y] always holds when expectations exist. Independence becomes relevant for products and for adding variances without covariance terms.",
      },
      {
        question: "How does adding 7 to X change its mean and variance?",
        answer:
          "The mean increases by 7 because the whole distribution shifts. Variance remains unchanged because all deviations from the new mean are the same as before.",
      },
      {
        question: "What distribution models the waiting time between Poisson arrivals?",
        answer:
          "The exponential distribution models that waiting time. Its memoryless property means elapsed waiting does not alter the distribution of the remaining wait.",
      },
      {
        question: "Why is the median often more robust than the mean?",
        answer:
          "The median depends on order rather than magnitude, so one extreme outlier moves it little or not at all, while the mean directly incorporates the outlier's size.",
      },
    ],
  },
  {
    subjectCode: "COA",
    subjectId: "computer-organization-and-architecture",
    topicId: "machine-instructions-and-addressing-modes",
    title: "Machine Instructions and Addressing Modes",
    summary:
      "Machine instructions encode operations, operand locations, and sequencing information within finite instruction words. GATE questions connect instruction formats with address calculation, register and memory traffic, alignment, and the trade-off between compact encodings and directly addressable resources.",
    estimatedMinutes: 50,
    prerequisites: ["Binary representation", "Registers and memory basics"],
    objectives: [
      "Interpret opcode and operand fields in instruction formats",
      "Compute effective addresses for standard addressing modes",
      "Distinguish register, memory, immediate, indirect, and PC-relative operands",
      "Relate field width to opcode, register, and address capacity",
    ],
    concepts: [
      {
        title: "Instruction formats and operand roles",
        explanation:
          "An instruction communicates an operation and the operands or locations involved. Its opcode field selects an operation, while register, addressing-mode, displacement, or immediate fields describe sources and destinations. A fixed-length format simplifies fetch and decode but may waste bits; variable-length formats can be denser but complicate decoding. The number of explicit addresses does not equal the number of values an operation conceptually uses because accumulators, stacks, or implicit program-counter updates supply hidden operands. Field width imposes a direct capacity limit: k bits distinguish at most 2^k alternatives.",
        keyIdeas: [
          "Opcode width limits distinct encoded operations",
          "Operands may be explicit or implicit",
          "Format choices trade encoding density against decode simplicity",
        ],
        examFocus:
          "GATE commonly asks how many opcodes remain after allocating register and address fields; account for every bit and any reserved encoding class.",
        example: {
          prompt:
            "A 24-bit fixed instruction has three 4-bit register fields and no other control fields besides its opcode. How many opcodes can it encode?",
          walkthrough:
            "The register fields consume 12 bits, leaving 24-12=12 opcode bits. Twelve bits provide 2^12=4096 possible opcode encodings, assuming none is reserved for another format.",
        },
      },
      {
        title: "Effective-address calculation",
        explanation:
          "An addressing mode defines how an instruction obtains its operand. Immediate mode places the value in the instruction; register mode names a register; direct mode supplies a memory address. Indirect mode treats the named register or memory word as a pointer, adding another level of access. Base-plus-displacement adds a usually sign-extended offset to a base register. Indexed addressing adds an index suited to arrays, and scaled indexing multiplies that index by element size. Effective-address questions should separate address calculation from the later memory access that retrieves the operand.",
        keyIdeas: [
          "Immediate operands require no data-memory lookup",
          "Indirect modes dereference a stored address",
          "Displacements are often sign-extended before addition",
        ],
        examFocus:
          "Write EA first, then state whether memory[EA] or EA itself is the operand; confusing those two stages changes both value and access count.",
        example: {
          prompt:
            "A base register holds 4000, an index register holds 6, the scale is 4, and displacement is -8. Find the effective address.",
          walkthrough:
            "Scaled index contributes 6*4=24. Add the base and signed displacement: EA=4000+24-8=4016. If this is a memory operand, a subsequent access retrieves memory[4016].",
        },
      },
      {
        title: "PC-relative control flow and access accounting",
        explanation:
          "Sequential execution advances the program counter to the next instruction. A PC-relative branch forms its target by adding a sign-extended displacement—often scaled for alignment—to the architecturally defined PC value. This makes nearby code relocatable because both instruction and target move together. Stack addressing uses an implicit stack pointer and is natural for zero-address operations. When comparing modes, count instruction fetch separately from operand fetches and pointer dereferences. Register operands avoid data-memory accesses, while memory-indirect addressing may require pointer and final-operand reads.",
        keyIdeas: [
          "PC-relative targets move with the code",
          "Aligned branch displacements may be scaled",
          "Pointer dereference adds a memory access",
        ],
        examFocus:
          "Use the PC value specified by the architecture or question—current, incremented, and byte-scaled conventions can produce different branch targets.",
        example: {
          prompt:
            "After fetching a 4-byte instruction, PC=1004. A branch contains signed word displacement -5, where each word is 4 bytes. Find the target.",
          walkthrough:
            "Scale the displacement: -5*4=-20 bytes. Add it to the given post-fetch PC, 1004-20=984. No data-memory access is needed merely to compute this PC-relative target.",
        },
      },
    ],
    formulae: [
      { label: "Encoding capacity", expression: "choices = 2^(field bits)", useWhen: "Sizing opcode, register, or mode fields" },
      { label: "Base-index address", expression: "EA = base + scale*index + displacement", useWhen: "Accessing arrays, records, or stack-frame data" },
      { label: "PC-relative target", expression: "target = PC_base + sign_extend(offset)*alignment", useWhen: "Decoding and evaluating a relative branch target" },
    ],
    checkpoints: [
      { question: "What does immediate addressing store in the instruction?", answer: "It stores the operand value itself, so obtaining that value needs no separate data-memory read beyond instruction fetch." },
      { question: "Why does indirect addressing cost an extra access?", answer: "The named location contains an address rather than the final operand. That pointer must be read and then dereferenced to reach the operand." },
      { question: "Why sign-extend a negative displacement?", answer: "Sign extension preserves its two's-complement numeric value when it is widened before addition to the address register." },
      { question: "What is the main benefit of PC-relative branches?", answer: "Their target depends on distance from the instruction rather than an absolute address, allowing nearby code to be relocated without changing the displacement." },
      { question: "How many registers can a 6-bit register field name?", answer: "It can distinguish 2^6=64 registers, assuming all encodings are available." },
    ],
  },
  {
    subjectCode: "COA",
    subjectId: "computer-organization-and-architecture",
    topicId: "alu-datapath-and-control",
    title: "ALU, Datapath and Control",
    summary:
      "A processor datapath moves values among registers, the ALU, memory interfaces, and the program counter, while control signals select each movement and operation. GATE analysis follows values cycle by cycle and connects instruction semantics to hardwired or microprogrammed control.",
    estimatedMinutes: 55,
    prerequisites: ["Digital combinational circuits", "Machine instructions"],
    objectives: [
      "Identify the roles of datapath storage, buses, and functional units",
      "Trace fetch, decode, execute, memory, and write-back actions",
      "Derive control signals from an instruction's required micro-operations",
      "Compare hardwired and microprogrammed control",
    ],
    concepts: [
      {
        title: "Datapath resources and data movement",
        explanation:
          "The datapath contains state elements such as the program counter and register file, functional units such as the ALU, and interconnections controlled by multiplexers and enables. A register file commonly offers multiple read ports and a write port so two source operands can feed one operation while a result returns later. Buses reduce wiring by sharing paths but may create resource conflicts. A micro-operation describes one elementary transfer or transformation in a clock interval. Legal simultaneous micro-operations must not drive one bus from two sources or require more ports than hardware provides.",
        keyIdeas: ["Registers hold architectural state", "Multiplexers select datapath sources", "Hardware ports constrain simultaneous transfers"],
        examFocus:
          "When given register-transfer notation, group operations by resource compatibility rather than assuming every independent-looking assignment fits one cycle.",
        example: {
          prompt: "Can R1<-R2+R3 and R4<-R5+R6 execute together with one ALU and one register-file write port?",
          walkthrough:
            "Both transfers require an ALU computation and a register write. A single ALU cannot form both sums in the same cycle, and one write port cannot commit both results. They therefore require separate cycles unless additional resources exist.",
        },
      },
      {
        title: "Instruction execution through the datapath",
        explanation:
          "Instruction processing is decomposed into fetch, decode and operand read, execution or address generation, optional data-memory access, and result write-back. An arithmetic instruction uses the ALU result as write-back data; a load uses the ALU for its effective address and memory output for write-back; a store writes memory without changing a destination register. A branch compares operands and conditionally selects a new PC. In a single-cycle processor all required actions fit one long clock period, whereas a multicycle processor reuses units across shorter cycles and stores intermediate results.",
        keyIdeas: ["Loads use both address generation and memory read", "Stores have no register write-back", "Branches select the next PC"],
        examFocus:
          "Trace the selected multiplexer input and each write-enable for the specific instruction; one incorrect enable can modify state even if the ALU result is correct.",
        example: {
          prompt: "List the essential actions for load R1, 12(R2).",
          walkthrough:
            "Fetch and decode the instruction, read R2, sign-extend 12, compute EA=R2+12 in the ALU, read data memory at EA, and enable the register-file write port with destination R1 and memory data selected as its input.",
        },
      },
      {
        title: "Hardwired and microprogrammed control",
        explanation:
          "The control unit converts opcode, timing state, and condition flags into datapath control signals. Hardwired control realizes this mapping with finite-state and combinational logic, generally offering fast operation but making complex changes difficult. Microprogrammed control stores control words in a control memory; a microsequencer selects the next microinstruction based on sequencing fields and conditions. Horizontal microcode exposes many control bits and can perform parallel actions, while vertical microcode encodes operations more compactly but requires decoding and may offer less parallelism.",
        keyIdeas: ["Hardwired control is logic-derived", "Microcode sequences stored control words", "Encoding trades width for decode work and parallelism"],
        examFocus:
          "Control-memory size questions multiply the number of microinstructions by control-word width; include next-address and condition fields as well as datapath signals.",
        example: {
          prompt: "A control store has 512 words, each containing 30 control bits and a 9-bit next address. What is its raw size?",
          walkthrough:
            "Each word has 30+9=39 bits. Total storage is 512*39=19,968 bits. If bytes are requested, round according to the specified physical organization rather than silently discarding leftover bits.",
        },
      },
    ],
    formulae: [
      { label: "Clock constraint", expression: "clock period >= longest active combinational path + register overhead", useWhen: "Finding a safe datapath clock" },
      { label: "Control-store bits", expression: "words * bits per control word", useWhen: "Sizing a microprogrammed control memory" },
      { label: "Micro-operation scheduling rule", expression: "one source per bus and no more operations than available units/ports", useWhen: "Packing transfers into a clock cycle" },
    ],
    checkpoints: [
      { question: "What is stored in a register file?", answer: "It stores the processor's general-purpose register values and provides read and write ports for instruction operands and results." },
      { question: "Why does a load need write-back but a store does not?", answer: "A load places memory data into a destination register. A store sends register data to memory and has no register result to commit." },
      { question: "What usually determines a single-cycle processor's clock period?", answer: "The longest instruction datapath, commonly a load path, plus storage-element timing overhead determines the minimum safe period." },
      { question: "Why can hardwired control be faster?", answer: "Control signals are produced directly by logic instead of fetching and sequencing stored microinstructions, reducing control-path work." },
      { question: "What is horizontal microcode?", answer: "It uses a wide control word with relatively direct control bits, enabling several compatible micro-operations in parallel at the cost of larger control memory." },
    ],
  },
  {
    subjectCode: "COA",
    subjectId: "computer-organization-and-architecture",
    topicId: "instruction-pipelining",
    title: "Instruction Pipelining",
    summary:
      "Instruction pipelining overlaps stages of several instructions to improve throughput. Accurate GATE solutions distinguish throughput from latency, draw cycle timing, identify structural, data, and control hazards, and apply forwarding, stalls, or flushing only where the pipeline permits.",
    estimatedMinutes: 65,
    prerequisites: ["Datapath stages", "Instruction dependencies"],
    objectives: [
      "Compute ideal and nonideal pipeline execution time and speedup",
      "Classify structural, data, and control hazards",
      "Determine forwarding opportunities and required stalls",
      "Evaluate branch penalties and pipeline efficiency",
    ],
    concepts: [
      {
        title: "Pipeline timing, throughput, and latency",
        explanation:
          "A k-stage pipeline divides instruction work so different instructions occupy different stages simultaneously. After filling, an ideal single-issue pipeline completes one instruction per clock, improving throughput but not necessarily the latency of one instruction. The clock period must accommodate the slowest stage plus pipeline-register overhead, so balanced stages matter. For n instructions without stalls, k+n-1 cycles are required. Speedup approaches k only for many instructions, balanced stage delays, and negligible register overhead; fill and drain costs dominate short instruction sequences.",
        keyIdeas: ["Ideal cycles equal fill plus one per additional instruction", "Slowest stage sets the clock", "Pipelining improves throughput more than individual latency"],
        examFocus:
          "Use actual stage delays rather than simply dividing unpipelined time by stage count; latch overhead and imbalance often decide the numeric answer.",
        example: {
          prompt: "A five-stage ideal pipeline executes 20 instructions. How many cycles are needed from first entry to final completion?",
          walkthrough:
            "The first instruction needs five cycles to emerge. Each of the remaining 19 completes one cycle later, so total cycles are 5+20-1=24. This assumes no hazards and one instruction issued each cycle.",
        },
      },
      {
        title: "Structural and data hazards",
        explanation:
          "A structural hazard occurs when simultaneous stages need the same insufficient resource, such as one memory serving instruction fetch and load access. A data hazard arises from dependence between instructions. In a classic in-order pipeline, read-after-write is the central true dependence; forwarding can route a produced value directly from a later pipeline register to a consumer without waiting for register write-back. A load-use pair may still need a stall because loaded data becomes available after the consumer's required ALU input time. Scheduling independent instructions can fill such delay slots when semantics permit.",
        keyIdeas: ["Structural hazards reflect resource conflicts", "RAW is a true data dependence", "Forwarding cannot make a value available before production"],
        examFocus:
          "Mark when each producer creates its value and when each consumer needs it. Stage names alone do not prove forwarding is sufficient.",
        example: {
          prompt: "In a five-stage IF-ID-EX-MEM-WB pipeline, why may `load R1,0(R2)` followed immediately by `add R3,R1,R4` stall even with forwarding?",
          walkthrough:
            "The load obtains data only at the end of MEM, while the following add needs R1 at the beginning of its EX stage in the same cycle. The value arrives too late, so one bubble delays the add; then forwarding can supply the loaded value.",
        },
      },
      {
        title: "Control hazards and overall performance",
        explanation:
          "A conditional branch creates uncertainty about the next instruction address. Waiting for resolution wastes fetch slots, while fetching the predicted path risks flushing wrong-path instructions. Resolving the branch earlier reduces penalty. Static policies use a fixed rule; dynamic prediction is outside what is needed unless a question supplies its behavior. Overall CPI starts from the ideal value and adds average stall contributions from hazards, commonly branch frequency times misprediction rate times penalty plus data and structural stalls. Separate frequencies carefully so the same lost cycle is not counted twice.",
        keyIdeas: ["Wrong-path work is flushed", "Earlier resolution lowers branch penalty", "Average CPI adds weighted stall costs"],
        examFocus:
          "Translate every percentage into a per-instruction contribution. A penalty applies only to the branch subset that actually triggers it under the stated policy.",
        example: {
          prompt: "Base CPI is 1. Branches are 20% of instructions, 10% are mispredicted, and each misprediction costs 3 cycles. Find CPI ignoring other stalls.",
          walkthrough:
            "Mispredictions per instruction are 0.20*0.10=0.02. Each loses three cycles, adding 0.06 cycles per instruction. Therefore the average CPI becomes 1+0.06=1.06 cycles per completed instruction.",
        },
      },
    ],
    formulae: [
      { label: "Ideal pipeline cycles", expression: "cycles = k + n - 1", useWhen: "n instructions cross k stages without stalls" },
      { label: "Pipeline clock", expression: "Tclk = max(stage delay) + register overhead", useWhen: "Converting cycles to elapsed time" },
      { label: "Average CPI", expression: "CPI = ideal CPI + sum(event frequency * event penalty)", useWhen: "Combining branch and hazard effects" },
    ],
    checkpoints: [
      { question: "Does pipelining reduce one instruction's logical work?", answer: "No. It overlaps different instructions. Pipeline registers may even increase individual latency, while throughput improves after filling." },
      { question: "What causes a structural hazard?", answer: "Two active stages require the same hardware resource in the same cycle and the processor lacks enough copies or ports." },
      { question: "Which dependence does forwarding primarily address in an in-order pipeline?", answer: "It addresses read-after-write dependence by bypassing a not-yet-written result directly to the consuming stage." },
      { question: "Why may a load-use pair still stall?", answer: "The memory value can be produced later in the cycle than the next instruction needs it, so forwarding cannot violate availability time." },
      { question: "What happens to instructions fetched after a mispredicted branch?", answer: "They are wrong-path instructions and must be flushed so they cannot modify architectural state." },
    ],
  },
  {
    subjectCode: "COA",
    subjectId: "computer-organization-and-architecture",
    topicId: "memory-hierarchy",
    title: "Memory Hierarchy",
    summary:
      "Memory hierarchy exploits temporal and spatial locality to present a large, economical address space with performance near small fast storage. GATE questions focus on address decomposition, cache mapping, misses, replacement and writes, effective access time, and secondary-storage timing.",
    estimatedMinutes: 70,
    prerequisites: ["Binary addresses", "Powers of two", "Basic processor timing"],
    objectives: [
      "Explain locality and hierarchy operation",
      "Derive tag, index, offset, set, and line counts",
      "Analyze cache hits, misses, replacement, and write policies",
      "Calculate average memory and secondary-storage access time",
    ],
    concepts: [
      {
        title: "Locality, blocks, and average access",
        explanation:
          "Temporal locality predicts reuse of recently accessed data, while spatial locality predicts access to nearby addresses. A cache transfers a fixed-size block containing multiple addressable units and records whether each line contains a valid copy. On a hit, the cache supplies data quickly; on a miss, a lower level provides the block and incurs a miss penalty. Average memory access time is hit time plus miss rate times the complete miss penalty. Larger blocks may improve spatial benefit but also increase transfer cost and reduce the number of simultaneously resident blocks.",
        keyIdeas: ["Temporal locality favors recent blocks", "Spatial locality favors neighboring addresses", "Miss penalty includes lower-level service and refill work"],
        examFocus:
          "Keep hit time outside the miss-rate product unless the question defines penalty differently, and convert all time units before averaging.",
        example: {
          prompt: "A cache hits in 2 ns, misses 4% of accesses, and a miss adds 80 ns. Find AMAT.",
          walkthrough:
            "Every access pays the 2 ns lookup. Four percent additionally pay 80 ns, contributing 0.04*80=3.2 ns on average. AMAT=2+3.2=5.2 ns.",
        },
      },
      {
        title: "Mapping and address decomposition",
        explanation:
          "A byte address divides into block offset, set index, and tag. The offset selects a byte within a block. A cache of capacity C, block size B, and associativity A has C/B lines and C/(B*A) sets. Direct mapping has one line per set, full associativity has one set, and set associativity lies between them. Index bits select a set, while tags distinguish memory blocks mapped there. Fully associative placement removes index bits but requires comparing the requested tag against every resident line.",
        keyIdeas: ["Offset bits are log2(block bytes)", "Set count equals capacity divided by block size and associativity", "Tag uses all remaining address bits"],
        examFocus:
          "Use set count—not line count—for index bits in an associative cache, and confirm whether addresses name bytes or words.",
        example: {
          prompt: "Find the address split for a 32 KiB, 4-way cache with 64-byte blocks and 32-bit byte addresses.",
          walkthrough:
            "There are 32768/64=512 lines and 512/4=128 sets. Offset bits=log2(64)=6 and index bits=log2(128)=7. The remaining tag width is 32-6-7=19 bits, completing the address split.",
        },
      },
      {
        title: "Misses, replacement, writes, and storage timing",
        explanation:
          "Compulsory misses occur on first use, capacity misses because the working set exceeds cache capacity, and conflict misses because mapping forces competing blocks into too few sets. Associative caches need a replacement rule such as LRU or FIFO within a set. Write-through updates the lower level on every cache write, often buffered; write-back marks a line dirty and writes it only on eviction. Write-allocate fetches a missed block before writing, while no-write-allocate bypasses cache. Secondary-storage questions add seek, rotational, and transfer components rather than treating all access time as one constant.",
        keyIdeas: ["Associativity reduces conflict misses", "Write-back requires a dirty bit", "Disk access separates positioning and transfer time"],
        examFocus:
          "Trace each reference with set and tag, updating replacement order and dirty state only when the stated policy requires it.",
        example: {
          prompt: "In a write-back cache, a dirty line is selected for replacement after a miss. What lower-level transfers occur?",
          walkthrough:
            "First the dirty victim must be written to the lower level so its newer data is preserved. Then the requested missed block is fetched into the freed line. A clean victim would skip the write-back transfer.",
        },
      },
    ],
    formulae: [
      { label: "Cache geometry", expression: "lines=C/B; sets=C/(B*A)", useWhen: "Deriving line and set counts from capacity C, block B, associativity A" },
      { label: "Address split", expression: "tag bits = address bits - index bits - offset bits", useWhen: "Finding metadata and mapping fields" },
      { label: "Average memory access", expression: "AMAT = hit time + miss rate * miss penalty", useWhen: "Combining frequent hits with infrequent misses" },
    ],
    checkpoints: [
      { question: "What does temporal locality predict?", answer: "A recently accessed block is likely to be accessed again soon, making it valuable to retain in faster storage." },
      { question: "How many sets are in a 16 KiB, 2-way cache with 32-byte blocks?", answer: "There are 16384/32=512 cache lines, and dividing those lines by two ways gives 256 sets." },
      { question: "Which miss type can greater associativity reduce?", answer: "It primarily reduces conflict misses by allowing a memory block to occupy more than one line within its indexed set." },
      { question: "When does a write-back cache update lower memory?", answer: "It updates lower memory when a dirty cache line is evicted, rather than on every write hit." },
      { question: "What components form a typical disk access time?", answer: "Seek time positions the head, rotational latency waits for the sector, and transfer time moves the requested data; controller overhead may also be stated." },
    ],
  },
  {
    subjectCode: "COA",
    subjectId: "computer-organization-and-architecture",
    topicId: "i-o-interface",
    title: "I/O Interface",
    summary:
      "An I/O interface bridges processor and device differences in speed, data format, and control. GATE questions compare programmed and interrupt-driven transfer, memory-mapped and isolated addressing, interface registers, handshaking, and the performance cost of polling under realistic device event rates.",
    estimatedMinutes: 40,
    prerequisites: ["Processor datapath", "Memory addressing"],
    objectives: [
      "Identify data, status, and control register roles",
      "Compare memory-mapped and isolated I/O",
      "Analyze programmed polling and interrupt-driven transfer",
      "Reason about synchronous and asynchronous handshaking",
    ],
    concepts: [
      {
        title: "Interface registers and device coordination",
        explanation:
          "Devices rarely match processor timing or word format, so an interface presents stable registers and control logic. A data register buffers transferred information, a status register reports conditions such as ready or error, and a control register carries commands or mode bits. The processor and device follow a protocol so data is not overwritten or sampled prematurely. Serial and parallel transfers differ in wires and bit timing, but both require agreement on readiness and completion. Buffering absorbs short speed differences; sustained producer-consumer imbalance still limits throughput.",
        keyIdeas: ["Data registers buffer values", "Status reports device state", "Control registers issue commands"],
        examFocus:
          "Map each read or write to the correct interface register; a ready flag is status, not the payload itself.",
        example: {
          prompt: "A device exposes DATA, STATUS, and CONTROL. Describe the safe sequence for output when STATUS bit 0 means ready.",
          walkthrough:
            "The processor first reads STATUS until bit 0 is one, then writes the outgoing value to DATA. If the protocol requires a start command, it writes that command to CONTROL. It must not overwrite DATA before the device accepts the previous value.",
        },
      },
      {
        title: "Memory-mapped, isolated, and polling I/O",
        explanation:
          "Memory-mapped I/O assigns device registers ordinary addresses, allowing normal load and store instructions and addressing modes but consuming part of the address space. Isolated I/O uses a separate I/O space and dedicated instructions or signals. In programmed I/O, the processor repeatedly checks a ready flag and explicitly transfers each unit. Polling is simple and can offer predictable short response, but it wastes processor cycles while slow devices remain busy. Poll frequency must balance detection delay against processor overhead.",
        keyIdeas: ["Memory-mapped I/O shares the memory address space", "Isolated I/O uses a separate operation space", "Polling consumes CPU attention while waiting"],
        examFocus:
          "When calculating polling overhead, distinguish time spent per poll from the interval between polls and from actual data-transfer work.",
        example: {
          prompt: "A CPU polls a device every 20 microseconds, and each poll occupies 1 microsecond of CPU time. What CPU fraction is used by polling?",
          walkthrough:
            "One microsecond is consumed in each 20-microsecond interval. The fraction is 1/20=0.05, so polling uses 5% of CPU time, excluding any separate service after readiness.",
        },
      },
      {
        title: "Interrupt-driven I/O and handshaking",
        explanation:
          "Interrupt-driven I/O lets the processor execute other work until a device requests service. On acceptance, the processor preserves enough context, identifies the source, runs an interrupt service routine, acknowledges the device, and resumes. Interrupt overhead makes this unsuitable for every tiny high-rate unit, but it avoids continuous polling for sporadic events. Asynchronous interfaces use request and acknowledge handshakes rather than a shared clock: the sender holds data stable with request asserted, and the receiver acknowledges after capturing it. This accommodates components with variable delays.",
        keyIdeas: ["Interrupts replace continuous waiting with event notification", "Service incurs context and control overhead", "Handshake signals tolerate variable timing"],
        examFocus:
          "Average interrupt cost equals event rate times service cost; include context and acknowledgement overhead if the question states them.",
        example: {
          prompt: "A device interrupts 2000 times per second and each service consumes 3000 CPU cycles on a 1 GHz processor. Find CPU utilization.",
          walkthrough:
            "Service consumes 2000*3000=6,000,000 cycles each second. The processor provides 1,000,000,000 cycles per second, so interrupt utilization is 0.006, or 0.6% of total processor capacity.",
        },
      },
    ],
    formulae: [
      { label: "Polling utilization", expression: "poll cost / polling interval", useWhen: "Polling executes once per fixed interval" },
      { label: "Interrupt utilization", expression: "event rate * service cycles / CPU cycles per second", useWhen: "Estimating processor overhead from repeated device interrupts" },
      { label: "Handshake rule", expression: "sender holds data until acknowledgement", useWhen: "Reasoning about asynchronous transfer correctness" },
    ],
    checkpoints: [
      { question: "What is the purpose of an I/O status register?", answer: "It reports device conditions such as ready, busy, completion, or error so software can decide when and how to transfer." },
      { question: "What is a benefit of memory-mapped I/O?", answer: "Normal memory instructions and addressing modes can access device registers, simplifying the instruction set and programming model." },
      { question: "Why is frequent polling expensive?", answer: "The processor repeatedly executes status checks even when no useful device event has occurred, consuming cycles that could run other work." },
      { question: "What work does an interrupt service routine perform?", answer: "It identifies or handles the event, exchanges data or status, acknowledges the device as required, restores context, and returns to interrupted execution." },
      { question: "Why does asynchronous handshaking not need a common clock?", answer: "Request and acknowledge transitions explicitly mark when data is valid and accepted, allowing each side to operate with variable delay." },
    ],
  },
  {
    subjectCode: "COA",
    subjectId: "computer-organization-and-architecture",
    topicId: "interrupts-and-dma",
    title: "Interrupts and DMA",
    summary:
      "Interrupts redirect execution to service asynchronous events, while direct memory access transfers blocks between devices and memory with limited processor involvement. GATE questions cover priority, masking, vectoring, context, DMA modes, bus contention, and timing advantages.",
    estimatedMinutes: 45,
    prerequisites: ["I/O interfaces", "Processor and memory buses"],
    objectives: [
      "Trace interrupt recognition and return",
      "Distinguish vectored, non-vectored, maskable, and non-maskable interrupts",
      "Resolve interrupt priority and nesting scenarios",
      "Analyze DMA setup, bus use, and transfer modes",
    ],
    concepts: [
      {
        title: "Interrupt entry, context, and vectoring",
        explanation:
          "An interrupt is considered at an architecturally safe boundary, commonly after completing the current instruction. The processor saves a return address and required status, changes privilege or masking state, and transfers control to an interrupt service routine. A vectored interrupt supplies or selects a service-entry identifier directly; a non-vectored scheme uses a common entry or software/hardware polling to discover the source. Returning restores saved state so interrupted execution continues as if only delayed. Precise handling ensures earlier instructions are complete and later ones have not committed visible effects.",
        keyIdeas: ["Context enables exact resumption", "Vectoring accelerates source-specific dispatch", "Interrupt acceptance occurs at a defined boundary"],
        examFocus:
          "Track which PC value is saved and whether the triggering instruction completes; exceptions and external interrupts may use different stated conventions.",
        example: {
          prompt: "The next sequential PC is 204 after an instruction completes at address 200 and an interrupt is accepted. What return address should normally be saved?",
          walkthrough:
            "Because the instruction at 200 completed, normal execution should resume at the next instruction. Saving 204 allows the interrupt return to continue there without re-executing the completed instruction.",
        },
      },
      {
        title: "Priority, masking, and nesting",
        explanation:
          "When several devices request service, priority logic chooses one according to fixed or rotating policy. Mask bits temporarily prevent selected maskable interrupts from being accepted, while a non-maskable interrupt is reserved for urgent conditions and is not blocked by ordinary masks. Nested interrupts allow a higher-priority request to preempt a lower-priority service routine, requiring another protected context save. Daisy-chain priority is simple but position-dependent; parallel priority logic resolves requests faster with more hardware. Starvation is possible under unchanging strict priority if high-priority traffic never stops.",
        keyIdeas: ["Masks selectively defer service", "Nesting requires ordered context saves", "Fixed priority can starve low-priority devices"],
        examFocus:
          "Apply both the priority ordering and current mask state; the highest raw request is not necessarily the next accepted interrupt.",
        example: {
          prompt: "Requests I1, I2, I3 have descending priority I1>I2>I3, but I1 is masked. I2 and I3 arrive together. Which is accepted?",
          walkthrough:
            "The mask removes I1 from eligible requests. Between the remaining active requests, I2 has higher priority than I3, so I2 is accepted first. I3 remains pending if the interface latches requests.",
        },
      },
      {
        title: "DMA operation and bus modes",
        explanation:
          "A DMA controller is initialized with device direction, memory start address, and transfer count. It then arbitrates for the bus, moves data between the device interface and memory, updates address and count, and interrupts the processor on completion or error. Burst mode holds the bus for a block, giving high transfer efficiency but delaying CPU memory access. Cycle stealing takes individual bus cycles, interleaving CPU and DMA work. Transparent DMA uses bus opportunities when the processor does not need them. DMA removes per-word instruction overhead but still requires setup and shared-bus bandwidth.",
        keyIdeas: ["CPU configures DMA once per block", "Burst mode favors DMA throughput", "Cycle stealing spreads CPU delay across transfers"],
        examFocus:
          "Compare total setup plus transfer time, and count only bus cycles actually denied to the CPU under the stated DMA mode.",
        example: {
          prompt: "A DMA transfer has 2000 setup cycles and moves 1024 words at one bus cycle per word. What is controller work in cycles before completion notification?",
          walkthrough:
            "Setup contributes 2000 cycles and movement contributes 1024 bus cycles, for 3024 cycles of specified work. CPU stall may be less than 3024 if setup executes on the CPU and transfers steal only selected bus cycles, so report the metric asked.",
        },
      },
    ],
    formulae: [
      { label: "DMA block time", expression: "setup time + words * transfer time per word", useWhen: "Estimating a complete unoverlapped DMA operation" },
      { label: "Priority selection", expression: "highest-priority active and unmasked request", useWhen: "Resolving several simultaneous pending interrupt requests" },
      { label: "DMA speed benefit", expression: "saved CPU work approximately per-word programmed overhead minus setup overhead per block", useWhen: "Comparing DMA with programmed transfer" },
    ],
    checkpoints: [
      { question: "Why must interrupt context be saved?", answer: "The service routine changes registers and control flow; saved context lets the processor restore the interrupted program's exact continuation state." },
      { question: "What is a vectored interrupt?", answer: "It provides or selects information that leads directly to the appropriate service routine entry rather than requiring general source polling." },
      { question: "What does masking an interrupt mean?", answer: "It temporarily makes a maskable request ineligible for acceptance; the device may remain pending for later service." },
      { question: "How does burst DMA affect the CPU?", answer: "The DMA controller keeps the bus for a block, maximizing transfer efficiency but potentially stalling CPU memory accesses for the burst duration." },
      { question: "Does DMA eliminate all processor work?", answer: "No. The processor configures the controller and handles completion or errors, while DMA eliminates most per-word transfer instructions." },
    ],
  },
  {
    subjectCode: "PDS",
    subjectId: "programming-and-data-structures",
    topicId: "programming-in-c",
    title: "Programming in C",
    summary:
      "C questions in GATE test exact execution rather than programming style. Mastery comes from tracking types, scopes, storage, evaluation, arrays, pointers, structures, and function calls while refusing to assign a definite result to undefined or unspecified behavior.",
    estimatedMinutes: 70,
    prerequisites: ["Basic algorithms", "Binary representation"],
    objectives: [
      "Trace declarations, expressions, control flow, and function calls",
      "Reason about arrays and pointer arithmetic",
      "Distinguish scope, lifetime, and storage duration",
      "Identify defined, implementation-dependent, unspecified, and undefined behavior",
    ],
    concepts: [
      {
        title: "Types, expressions, and control flow",
        explanation:
          "Every C expression has a type that influences conversion, arithmetic, comparison, and storage. Integer promotion can widen smaller integer types, while mixed arithmetic follows conversion rules supplied or implied by the question. Integer division truncates toward zero for modern C, and remainder follows the corresponding quotient. Short-circuit operators evaluate the right operand only when needed, which can suppress side effects. Loops and conditionals are traced most safely by recording values at sequence points and respecting pre-increment versus post-increment. An expression with unsequenced conflicting modifications has no reliable numeric result.",
        keyIdeas: ["Types govern conversion and arithmetic", "Logical AND and OR short-circuit", "Unsequenced conflicting side effects are undefined"],
        examFocus:
          "If a code fragment modifies one scalar multiple times without sequencing, classify the behavior instead of choosing an attractive trace.",
        example: {
          prompt: "What does `int x=3; if (x>0 && ++x==4) printf(\"%d\",x);` print?",
          walkthrough:
            "The left operand x>0 is true, so short-circuit AND evaluates the right operand. Prefix increment changes x to 4 before comparison, and 4==4 is true. The body executes and prints 4.",
        },
      },
      {
        title: "Arrays, pointers, and memory objects",
        explanation:
          "An array stores same-type elements contiguously. In most expressions its name converts to a pointer to the first element, but the array object and pointer variable remain different concepts. Pointer arithmetic is scaled by the pointed-to type: p+1 advances by sizeof(*p). Array indexing obeys a[i]=*(a+i). A pointer may safely range within one array object and one position past it, but dereferencing the one-past pointer is invalid. Multidimensional C arrays are row-major, so all later dimension sizes are needed to calculate a row stride.",
        keyIdeas: ["Array elements are contiguous", "Pointer increments scale by element size", "C multidimensional arrays use row-major order"],
        examFocus:
          "Distinguish `sizeof(array)` in its declaring scope from `sizeof(pointer)` after an array parameter has adjusted to pointer type.",
        example: {
          prompt: "An int array begins at byte address 1000 and sizeof(int)=4. What address is `&a[7]`?",
          walkthrough:
            "The seventh indexed element is seven integer positions beyond a[0]. Pointer scaling contributes 7*4=28 bytes, so &a[7] has address 1028.",
        },
      },
      {
        title: "Functions, storage, and structures",
        explanation:
          "C passes every ordinary function argument by value; apparent reference behavior is achieved by passing a pointer value and dereferencing it. Automatic local objects normally exist for one function activation, while static objects retain one stored value across calls. Scope controls where a name is visible and differs from lifetime. Recursive calls receive distinct automatic locals. Structures group named fields and may include padding to satisfy alignment, so total size need not equal the sum of field sizes. The dot operator selects a member of an object, and arrow selects through a structure pointer.",
        keyIdeas: ["Arguments are passed by value", "Static locals persist across calls", "Structure layout may contain padding"],
        examFocus:
          "Draw separate activation records for recursive calls and apply any alignment assumptions stated in a structure-size problem.",
        example: {
          prompt: "What values are returned by three calls to `int f(){ static int x=1; return x++; }`?",
          walkthrough:
            "The static x is initialized once and persists. Post-increment returns the old value then increments it. The calls return 1, 2, and 3 respectively, leaving x equal to 4 after the third call.",
        },
      },
    ],
    formulae: [
      { label: "Pointer stepping", expression: "address(p+k) = address(p) + k*sizeof(*p)", useWhen: "Moving within an array through a typed pointer" },
      { label: "Row-major address", expression: "base + ((i*columns)+j)*element_size", useWhen: "Addressing element a[i][j] of a two-dimensional C array" },
      { label: "Pass-by-pointer method", expression: "pass &object; update through *parameter", useWhen: "A function must modify the caller's object" },
    ],
    checkpoints: [
      { question: "Does C pass arrays by reference?", answer: "No. In a function parameter declaration an array parameter adjusts to a pointer. That pointer value is passed by value, though it can access the caller's elements." },
      { question: "What does p+1 mean for an int pointer?", answer: "It advances to the next int object, increasing the byte address by sizeof(int), not necessarily by one byte." },
      { question: "Why may `sizeof(struct)` exceed its field-size sum?", answer: "The implementation may insert padding between or after fields to satisfy alignment requirements for efficient and valid access." },
      { question: "How does a static local differ from an automatic local?", answer: "A static local retains its stored value for the entire program while keeping local scope; an automatic local normally exists only during each call." },
      { question: "When does `A && B` avoid evaluating B?", answer: "When A evaluates to false, the whole conjunction is already false, so short-circuit evaluation skips B and any side effects within it." },
    ],
  },
  {
    subjectCode: "PDS",
    subjectId: "programming-and-data-structures",
    topicId: "recursion",
    title: "Recursion",
    summary:
      "Recursion expresses a problem through smaller instances of itself. GATE questions require tracing activation records, verifying base cases and progress, deriving call counts or recurrences, and separating mathematical recursion depth from the total number of calls.",
    estimatedMinutes: 50,
    prerequisites: ["C functions", "Mathematical induction"],
    objectives: [
      "Trace recursive calls and return-value unwinding",
      "Identify base cases and prove termination",
      "Derive time and stack-space recurrences",
      "Recognize tree, divide-and-conquer, and tail-recursive patterns",
    ],
    concepts: [
      {
        title: "Activation records and unwinding",
        explanation:
          "Each active function call has an activation record containing its parameters, automatic locals, return address, and saved execution context. A recursive call does not overwrite an earlier call's local variables; it creates another frame. Evaluation descends until a base case returns directly, then pending operations execute during unwinding in reverse call order. Printing before a recursive call follows descent order, while printing after it follows ascent order. Maximum simultaneous frames determine auxiliary stack space and may be much smaller than the total calls made across a branching recursion tree.",
        keyIdeas: ["Each active call owns distinct automatic state", "Pending work executes during unwinding", "Stack depth counts simultaneous calls, not total calls"],
        examFocus:
          "For output-trace problems, annotate each print as pre-call or post-call and draw frames only until the base case becomes clear.",
        example: {
          prompt: "What is printed by `f(n){ if(n==0)return; print(n); f(n-1); print(n); }` for n=3?",
          walkthrough:
            "Descent prints 3,2,1. The n=0 call returns without printing. Unwinding then prints 1,2,3. The complete sequence is 3 2 1 1 2 3.",
        },
      },
      {
        title: "Termination and recursive correctness",
        explanation:
          "A sound recursive definition has one or more base cases and guarantees that every recursive branch moves toward them according to a well-founded measure, such as a decreasing nonnegative integer or smaller tree. Correctness is often argued inductively: assume recursive calls solve smaller instances, then prove the current call combines them correctly. Missing progress produces infinite recursion; overlapping cases may produce incorrect double counting even when termination occurs. Mutual recursion follows the same principle but requires examining the combined call graph and progress across both functions.",
        keyIdeas: ["Base cases stop decomposition", "Every branch must make measurable progress", "Induction mirrors recursive correctness"],
        examFocus:
          "Check all branches, not just the obvious one. A conditional branch that leaves its argument unchanged can destroy termination for a subset of inputs.",
        example: {
          prompt: "Why does Euclid's `gcd(a,b)=gcd(b,a mod b)` terminate for positive b?",
          walkthrough:
            "The remainder satisfies 0 <= a mod b < b, so the second argument strictly decreases while remaining nonnegative. Eventually it becomes zero, the base case, and the final nonzero argument is returned as the gcd.",
        },
      },
      {
        title: "Call trees, time, and stack complexity",
        explanation:
          "A single recursive call on n-1 typically gives linear depth and call count. Two calls on n-1 create an exponential call tree unless repeated subproblems are stored. Divide-and-conquer instead uses smaller fractions such as n/2 and adds combine work, producing logarithmic depth even when total work is larger. Stack space follows the longest root-to-leaf chain; calls in separate branches do not remain active together after the first branch returns. Tail recursion leaves no computation after the recursive call, but C does not guarantee eliminating its stack frames.",
        keyIdeas: ["Branching can make calls exponential", "Fractional shrinkage gives logarithmic depth", "Tail-call optimization is not guaranteed by C"],
        examFocus:
          "Write separate recurrences for time and maximum stack depth; using total node count as stack space is a common mistake.",
        example: {
          prompt: "For T(n)=2T(n/2)+n work and depth D(n)=D(n/2)+1, state asymptotic time and stack depth.",
          walkthrough:
            "Each recursion-tree level performs total linear work, and there are log2 n levels, so T(n)=Theta(n log n). Only one root-to-leaf path is active at a time, giving D(n)=Theta(log n) frames.",
        },
      },
    ],
    formulae: [
      { label: "Linear recursion", expression: "T(n)=T(n-1)+Theta(1) => Theta(n)", useWhen: "One constant-work call reduces n by one" },
      { label: "Binary decrement recursion", expression: "T(n)=2T(n-1)+Theta(1) => Theta(2^n)", useWhen: "Two uncached calls each reduce n by one" },
      { label: "Stack rule", expression: "space proportional to maximum active call depth", useWhen: "Finding auxiliary stack space used by recursion" },
    ],
    checkpoints: [
      { question: "What two ingredients are needed for recursive termination?", answer: "A reachable base case and guaranteed progress toward it on every recursive branch under a well-founded measure." },
      { question: "Are local variables shared across recursive calls?", answer: "Automatic locals are not shared; each active call has its own frame. Static or global objects are shared separately." },
      { question: "Why can total calls exceed stack depth?", answer: "Completed branches release their frames before later branches run, so only one active path contributes to maximum stack depth." },
      { question: "What makes recursion tail-recursive?", answer: "The recursive call is the final operation and its returned value requires no further computation in the current frame." },
      { question: "Does C guarantee tail-call optimization?", answer: "No. A compiler may optimize it, but portable complexity reasoning must not assume stack-frame elimination unless stated." },
    ],
  },
  {
    subjectCode: "PDS",
    subjectId: "programming-and-data-structures",
    topicId: "arrays",
    title: "Arrays",
    summary:
      "Arrays store homogeneous elements in contiguous memory and provide constant-time indexed access. GATE questions test address calculation, row-major multidimensional layout, insertion and deletion costs, in-place manipulation, and the distinction between logical size and allocated capacity.",
    estimatedMinutes: 40,
    prerequisites: ["C pointers", "Basic complexity analysis"],
    objectives: [
      "Compute one- and multidimensional array addresses",
      "Analyze access, search, insertion, and deletion costs",
      "Trace in-place scans and boundary conditions",
      "Distinguish static capacity from current element count",
    ],
    concepts: [
      {
        title: "Contiguous layout and indexing",
        explanation:
          "An array allocates equal-size elements consecutively, so an index is converted directly to a byte displacement from the base. For zero-based indexing, address(A[i])=base+i*w, where w is element size. If indexing begins at lower bound L, the displacement is (i-L)w. Constant-time random access follows from this arithmetic and does not require visiting preceding elements. Contiguity also improves spatial locality during sequential scans. However, an array name alone does not store its runtime length, so algorithms must receive or maintain valid bounds separately.",
        keyIdeas: ["Indexing is direct address arithmetic", "Contiguous scans exploit spatial locality", "Bounds are not automatically stored or checked in C"],
        examFocus:
          "Use the declared lower bound and units of the base address; word-addressed and byte-addressed questions require different scaling.",
        example: {
          prompt: "A[5..20] stores 8-byte elements and A[5] begins at byte 600. Find address(A[13]).",
          walkthrough:
            "The logical offset is 13-5=8 elements from the declared lower bound. Eight elements at 8 bytes each contribute 64 bytes, so address(A[13])=600+64=664.",
        },
      },
      {
        title: "Multidimensional row-major layout",
        explanation:
          "C stores a multidimensional array in row-major order: the last index varies fastest. For A[R][C], all C elements of row zero precede row one. Addressing A[i][j] linearizes the pair as i*C+j for zero-based bounds. Higher-dimensional arrays repeat this rule using products of later dimension sizes as strides. A pointer to a row therefore needs the column count in its type so pointer arithmetic can skip an entire row. Confusing row-major with column-major reverses which dimension contributes the larger stride.",
        keyIdeas: ["The rightmost index varies fastest", "Row stride equals columns times element size", "Later dimensions determine earlier-index strides"],
        examFocus:
          "Write the linearized index before multiplying by element size; this separates dimension mistakes from byte-scaling mistakes.",
        example: {
          prompt: "A zero-based int matrix A[6][10] starts at 1000 and int size is 4. Find &A[3][7].",
          walkthrough:
            "Because each row contains ten integers, the row-major linear index is 3*10+7=37. Its byte displacement is 37*4=148, so the address is 1000+148=1148.",
        },
      },
      {
        title: "Operations, shifting, and capacity",
        explanation:
          "Reading or replacing a known array position takes constant time. Searching an unsorted array is linear in the worst case; a sorted array permits binary search but still needs shifting for insertion or deletion while preserving order. Inserting at position i moves all occupied elements from i onward one place right, provided spare capacity exists. Deletion shifts later elements left. A dynamic-array abstraction can resize occasionally and achieve amortized constant append, but a plain fixed C array does not resize itself. Logical length must never exceed allocated capacity.",
        keyIdeas: ["Known-index access is constant time", "Middle insertion and deletion require shifts", "Capacity and logical length are different"],
        examFocus:
          "Count moved elements rather than just comparisons; questions may ask data movement even when the insertion position is already known.",
        example: {
          prompt: "An array has n occupied elements. How many assignments shift elements when inserting at zero-based position i?",
          walkthrough:
            "Existing elements i through n-1 move one place right. That interval contains n-i elements, so n-i element assignments perform the shift before the new value is stored at i.",
        },
      },
    ],
    formulae: [
      { label: "One-dimensional address", expression: "base + (i-L)*w", useWhen: "Array lower bound is L and element width is w" },
      { label: "Two-dimensional row-major address", expression: "base + ((i-Lr)*C + (j-Lc))*w", useWhen: "A matrix has C columns" },
      { label: "Insertion shifts", expression: "n-i elements for insertion at zero-based position i", useWhen: "Spare capacity exists and order is preserved" },
    ],
    checkpoints: [
      { question: "Why is array indexing constant time?", answer: "The address is computed directly from base, index, lower bound, and fixed element size without traversing earlier elements." },
      { question: "Which index changes fastest in a C multidimensional array?", answer: "The rightmost index changes fastest because C uses row-major layout." },
      { question: "What is the worst-case search time in an unsorted array?", answer: "Theta(n), because the target may be absent or located at the final inspected position." },
      { question: "Why can sorted-array insertion still be linear?", answer: "Even if binary search finds the position quickly, up to n elements must shift to preserve contiguous sorted order." },
      { question: "Does a C array know its logical length?", answer: "No. The program must track length separately and keep it within the allocated capacity." },
    ],
  },
  {
    subjectCode: "PDS",
    subjectId: "programming-and-data-structures",
    topicId: "stacks-and-queues",
    title: "Stacks and Queues",
    summary:
      "Stacks and queues restrict where elements enter and leave, turning simple storage into powerful ordering tools. GATE problems use them for expression processing, recursion, breadth-first exploration, buffering, and circular-array index reasoning while testing exact overflow, underflow, and operand-order behavior.",
    estimatedMinutes: 50,
    prerequisites: ["Arrays", "Linked structures basics"],
    objectives: [
      "Implement and analyze stack operations",
      "Evaluate postfix expressions and apply operator precedence",
      "Implement linear and circular queues without false overflow",
      "Choose stacks or queues for traversal and scheduling patterns",
    ],
    concepts: [
      {
        title: "Stack discipline and applications",
        explanation:
          "A stack follows last-in, first-out order. Push inserts at the top, pop removes the top, and peek reads it without removal; each is constant time with an array top index or linked-list head. The runtime call stack stores active function frames. Algorithmic stacks support depth-first traversal, delimiter matching, undo, and expression conversion. Correct use requires detecting underflow before pop and overflow for fixed capacity. A sequence of pushes and pops can often be analyzed through the invariant that only the most recently unremoved item is accessible.",
        keyIdeas: ["Only the top is directly accessible", "Push and pop are constant time", "Stacks naturally represent nested unfinished work"],
        examFocus:
          "For stack-permutation questions, simulate only legal top removals; an earlier buried element cannot leave before every element above it.",
        example: {
          prompt: "Starting empty, perform push 2, push 7, push 5, pop, push 9, pop. What values are popped and what remains?",
          walkthrough:
            "The first pop removes 5. After pushing 9, the next pop removes 9. The stack then contains 2 below 7, with 7 at the top.",
        },
      },
      {
        title: "Expression evaluation and conversion",
        explanation:
          "Postfix notation places an operator after its operands and can be evaluated with one stack: scan left to right, push operands, and on an operator pop the right operand then the left operand, apply it, and push the result. Prefix uses a mirrored scan direction. Infix-to-postfix conversion uses an operator stack governed by precedence, associativity, and parentheses. Parentheses control popping but do not appear in the postfix result. Operand order matters for subtraction and division, so the first popped value is not automatically the left operand.",
        keyIdeas: ["Postfix needs no parentheses", "First pop is the right operand", "Precedence and associativity govern operator-stack popping"],
        examFocus:
          "Write `left operator right` beside every postfix reduction; reversed operand order is the most common numerical error.",
        example: {
          prompt: "Evaluate postfix expression `8 3 2 * - 4 +`.",
          walkthrough:
            "Push 8,3,2. Operator * pops 2 and 3, pushing 6. Operator - pops right 6 and left 8, pushing 2. Push 4, then + produces 2+4=6.",
        },
      },
      {
        title: "Queues and circular representation",
        explanation:
          "A queue follows first-in, first-out order. Enqueue inserts at the rear and dequeue removes from the front, supporting breadth-first search, producer-consumer buffers, and fair waiting lines. A simple array queue can waste freed prefix slots. Circular indexing reuses them by advancing front and rear modulo capacity. One representation reserves an empty slot so front==rear means empty and the next rear equaling front means full; another stores an explicit count and uses all slots. The chosen convention must remain consistent across initialization, insertion, and deletion.",
        keyIdeas: ["Queues expose the oldest retained element", "Modulo arithmetic wraps array indexes", "Full and empty tests depend on representation convention"],
        examFocus:
          "Do not mix the reserved-slot and explicit-count formulas. State which index denotes the next insertion and which denotes the next removal.",
        example: {
          prompt: "A capacity-8 circular queue reserves one slot. If front=3 and rear=2, how many elements are stored?",
          walkthrough:
            "Stored count is (rear-front+capacity) mod capacity=(2-3+8) mod 8=7. That is the maximum usable occupancy when one of eight slots is reserved to distinguish full from empty.",
        },
      },
    ],
    formulae: [
      { label: "Circular advance", expression: "next(i)=(i+1) mod capacity", useWhen: "Moving front or rear with wrap-around" },
      { label: "Reserved-slot occupancy", expression: "(rear-front+capacity) mod capacity", useWhen: "front is next removal and rear is next insertion" },
      { label: "Postfix reduction", expression: "right=pop(); left=pop(); push(left op right)", useWhen: "Evaluating a binary postfix operator" },
    ],
    checkpoints: [
      { question: "What ordering does a stack enforce?", answer: "Last-in, first-out: the newest element that has not been removed is the next one accessible." },
      { question: "Which postfix operand is popped first?", answer: "The right operand is popped first; the next pop provides the left operand for a binary operator." },
      { question: "Why use a circular queue?", answer: "It reuses array positions freed at the front without shifting elements, keeping enqueue and dequeue constant time." },
      { question: "What data structure drives breadth-first search?", answer: "A FIFO queue, because vertices discovered earlier must be expanded before vertices discovered later at greater distance." },
      { question: "How can front==rear represent both full and empty?", answer: "It cannot without extra information. Reserve a slot, keep a count, or store an additional full flag to disambiguate the states." },
    ],
  },
  {
    subjectCode: "PDS",
    subjectId: "programming-and-data-structures",
    topicId: "linked-lists",
    title: "Linked Lists",
    summary:
      "Linked lists store elements in separately allocated nodes connected by pointers. They trade direct indexing and locality for flexible relinking, making GATE questions focus on pointer updates, traversal, insertion, deletion, reversal, cycle detection, and sentinel conventions.",
    estimatedMinutes: 50,
    prerequisites: ["C pointers", "Dynamic memory concepts"],
    objectives: [
      "Trace singly, doubly, and circular linked structures",
      "Perform insertion and deletion with safe pointer ordering",
      "Reverse a list iteratively and reason about invariants",
      "Analyze traversal, cycle detection, and operation costs",
    ],
    concepts: [
      {
        title: "Node structure and traversal",
        explanation:
          "A singly linked node stores data and a pointer to its successor. The head identifies the first node, and a null successor marks the end unless a circular or sentinel convention is used. Traversal follows links one by one, so reaching the ith node takes linear time and there is no constant-time random access. Nodes need not occupy adjacent addresses, which eases growth but adds pointer storage and often weakens spatial locality. An empty-list representation and ownership rule should be established before interpreting any code fragment.",
        keyIdeas: ["Links define logical order", "Indexed access requires traversal", "Null, circular, and sentinel endings differ"],
        examFocus:
          "Draw node identities and arrows rather than copying data values; duplicate values can conceal that two pointers reference different nodes.",
        example: {
          prompt: "A list contains nodes 4->9->4->null. How many link traversals are needed to reach the second node storing 4 from head?",
          walkthrough:
            "The target is the third node despite sharing data with the head. Move head to the 9 node once and then to the final 4 node a second time, requiring two link traversals.",
        },
      },
      {
        title: "Insertion, deletion, and list variants",
        explanation:
          "Given a pointer to the predecessor, inserting a node requires linking the new node to the old successor before redirecting the predecessor to the new node. Deletion similarly bypasses the target before its storage is released. At the head, the external head pointer must change. A doubly linked list stores predecessor and successor links, permitting constant-time deletion with a target pointer but requiring more updates. A circular list links the last node back to the first and needs a stopping condition based on returning to the start rather than finding null.",
        keyIdeas: ["Preserve the old successor before overwriting a link", "Head updates change the external entry pointer", "Doubly linked deletion repairs both directions"],
        examFocus:
          "Evaluate pointer assignments in their written order. Reversing two apparently equivalent statements can lose the remainder of the list.",
        example: {
          prompt: "Insert new node X after node P in a singly linked list without losing P's current successor.",
          walkthrough:
            "First set X->next=P->next so X remembers the old continuation. Then set P->next=X. Performing the second assignment first would overwrite the only link to the old successor unless it had been saved elsewhere.",
        },
      },
      {
        title: "Reversal, cycles, and complexity",
        explanation:
          "Iterative reversal maintains three roles: previous points to the reversed prefix, current points to the node being processed, and next temporarily preserves the unreversed suffix. Each step saves current->next, reverses that link, and advances both pointers. Floyd's cycle method moves one pointer one step and another two steps; if a cycle exists they eventually meet, while a fast pointer reaching null proves no cycle. Insertion or deletion is constant time only when the required node or predecessor pointer is already available; locating it may still cost linear time.",
        keyIdeas: ["Reversal must preserve the suffix before changing a link", "Different-speed pointers detect cycles with constant space", "Search cost may dominate a constant-time relink"],
        examFocus:
          "Separate the complexity of finding a position from the complexity of modifying links once the necessary pointer is supplied.",
        example: {
          prompt: "Reverse A->B->C->null and state the invariant after processing B.",
          walkthrough:
            "After A, previous=A->null and current=B. Save C, set B->next=A, then advance previous=B and current=C. The invariant is that previous heads the correctly reversed processed prefix B->A->null, while current heads the untouched suffix C->null.",
        },
      },
    ],
    formulae: [
      { label: "Singly linked insertion", expression: "new.next=pred.next; pred.next=new", useWhen: "Inserting after a known predecessor" },
      { label: "Reversal step", expression: "next=cur.next; cur.next=prev; prev=cur; cur=next", useWhen: "Reversing a singly linked list in place" },
      { label: "Floyd movement", expression: "slow=slow.next; fast=fast.next.next", useWhen: "Detecting a reachable cycle with constant extra space" },
    ],
    checkpoints: [
      { question: "Why is linked-list indexed access linear?", answer: "Nodes are reached through predecessor links rather than an address formula, so the traversal must follow each earlier link." },
      { question: "Which pointer assignment comes first when inserting after P?", answer: "Set the new node's next pointer to P's current successor before changing P's next pointer to the new node." },
      { question: "What extra ability does a doubly linked list provide?", answer: "Given a node pointer, its predecessor is directly available, enabling deletion or backward traversal without searching from the head." },
      { question: "How does traversal stop in a circular list?", answer: "It stops when the traversal pointer returns to a designated starting node or sentinel, not when it becomes null." },
      { question: "What does Floyd's meeting of slow and fast pointers prove?", answer: "It proves the reachable successor path contains a cycle, because a faster pointer has lapped the slower one within that finite cycle." },
    ],
  },
  {
    subjectCode: "PDS",
    subjectId: "programming-and-data-structures",
    topicId: "trees-and-binary-search-trees",
    title: "Trees and Binary Search Trees",
    summary:
      "Trees model hierarchical relationships through parent-child links. GATE problems emphasize structural counting, recursive traversals, reconstructing trees from traversal orders, and maintaining the binary-search-tree ordering invariant during search, insertion, and deletion while relating each operation to the resulting height.",
    estimatedMinutes: 60,
    prerequisites: ["Recursion", "Linked structures"],
    objectives: [
      "Use tree terminology and structural bounds correctly",
      "Trace preorder, inorder, postorder, and level-order traversals",
      "Search and update binary search trees",
      "Relate tree height to operation complexity",
    ],
    concepts: [
      {
        title: "Tree structure and counting",
        explanation:
          "A rooted tree gives every nonroot node exactly one parent and a unique path from the root. Depth counts edges from the root, while height is the longest downward edge path under the common convention; questions may explicitly use node counts instead. A binary tree permits at most two ordered children per node. At level d there are at most 2^d nodes, and a height-h binary tree has at most 2^(h+1)-1 nodes when root depth is zero. A full binary tree has zero or two children per internal node, implying leaves equal internal nodes plus one.",
        keyIdeas: ["Every tree with n nodes has n-1 edges", "Binary level d holds at most 2^d nodes", "Full binary trees satisfy leaves=internal+1"],
        examFocus:
          "Confirm whether height is measured in edges or nodes before applying a bound; both conventions appear in textbooks and alter exponents by one.",
        example: {
          prompt: "A full binary tree has 15 internal nodes. How many leaves and total nodes does it contain?",
          walkthrough:
            "For a full binary tree, leaves=internal+1=16. Total nodes are 15+16=31. Equivalently, the number of edges 30 equals total nodes minus one.",
        },
      },
      {
        title: "Traversal and reconstruction",
        explanation:
          "Preorder visits root, left subtree, then right; inorder visits left, root, right; postorder visits left, right, root. Level order uses a queue to visit nodes by increasing depth. A binary tree with distinct labels can be reconstructed uniquely from inorder paired with preorder or postorder, because the first preorder or last postorder label identifies the root and splits the inorder sequence. Preorder plus postorder alone is generally insufficient unless additional structure such as fullness is guaranteed. Recursive traversal time is linear because each node is visited once.",
        keyIdeas: ["Inorder fixes the left/right split around a root", "Preorder reveals each subtree root first", "Level order uses a queue"],
        examFocus:
          "For reconstruction, split both traversal sequences into matching label sets after locating the root; do not assume equal-sized subtrees.",
        example: {
          prompt: "Reconstruct the root and subtrees from preorder A B D E C and inorder D B E A C.",
          walkthrough:
            "Preorder makes A the root. In inorder, labels D B E lie left of A and C lies right. The left preorder segment B D E makes B that subtree's root with D left and E right; C is A's right child.",
        },
      },
      {
        title: "Binary search tree operations",
        explanation:
          "A binary search tree orders keys so every left-subtree key is smaller and every right-subtree key is larger under the selected duplicate policy. Search and insertion follow one root-to-leaf comparison path. Inorder traversal therefore yields sorted order. Deleting a leaf simply removes it; deleting a one-child node splices in its child; deleting a two-child node replaces its key with its inorder successor or predecessor and then deletes that replacement node from its original position. Operation time is proportional to tree height, which can range from logarithmic to linear.",
        keyIdeas: ["Inorder traversal of a BST is sorted", "Two-child deletion uses successor or predecessor", "Performance depends on height, not merely node count"],
        examFocus:
          "Preserve the global ordering invariant after deletion. Drawing only parent-child shape without key ranges can hide an invalid replacement.",
        example: {
          prompt: "Delete key 40 from a BST where 40 has two children and its inorder successor is 45, a leaf.",
          walkthrough:
            "Copy 45 into the node currently holding 40, preserving left keys below 40 and right keys at least 45 under distinct-key assumptions. Then remove the original leaf node 45. The tree loses exactly one node and remains ordered.",
        },
      },
    ],
    formulae: [
      { label: "Tree edges", expression: "edges=n-1", useWhen: "Any finite tree has n nodes" },
      { label: "Binary-tree node bound", expression: "max nodes through height h = 2^(h+1)-1", useWhen: "Root depth is zero and height counts edges" },
      { label: "BST operation cost", expression: "Theta(height)", useWhen: "Analyzing search, insertion, or deletion" },
    ],
    checkpoints: [
      { question: "How many edges does a rooted tree with 80 nodes have?", answer: "It has 79 edges. Rooting changes orientation and terminology but not the tree edge invariant n-1." },
      { question: "Which traversal lists BST keys in sorted order?", answer: "Inorder traversal, because it visits every smaller left-subtree key before the root and every larger right-subtree key afterward." },
      { question: "Can preorder and postorder always reconstruct a unique binary tree?", answer: "No. Without inorder or extra structural constraints, different unary-child placements can share the same preorder and postorder sequences." },
      { question: "How is a two-child BST node deleted?", answer: "Replace its key using its inorder successor or predecessor, then delete that replacement node from its original location where it has at most one child." },
      { question: "What is worst-case BST search time with n nodes?", answer: "Theta(n) when the tree degenerates into a chain; balanced height would instead make it Theta(log n)." },
    ],
  },
  {
    subjectCode: "PDS",
    subjectId: "programming-and-data-structures",
    topicId: "heaps",
    title: "Heaps",
    summary:
      "A binary heap combines a complete-tree shape with a local parent-child order, supporting fast access to one extreme key. GATE questions test array indexes, build-heap complexity, insertion and deletion traces, heapsort, and the distinction between heap order and total sorting.",
    estimatedMinutes: 45,
    prerequisites: ["Arrays", "Binary trees", "Asymptotic notation"],
    objectives: [
      "Map complete binary trees to array indexes",
      "Restore heap order using sift-up and sift-down",
      "Explain linear-time bottom-up heap construction",
      "Trace heapsort and priority-queue operations",
    ],
    concepts: [
      {
        title: "Shape, order, and array mapping",
        explanation:
          "A binary heap is a complete binary tree: every level is full except possibly the last, which fills left to right. This shape permits a compact array without child pointers. In a zero-based array, parent(i)=floor((i-1)/2), left(i)=2i+1, and right(i)=2i+2 when those indexes are valid. A max-heap requires every parent key to be at least its children; a min-heap reverses the relation. This is only a partial order, so siblings and distant subtrees need not be sorted relative to each other.",
        keyIdeas: ["Completeness gives compact array storage", "Heap order is local parent-child order", "The root stores the selected extreme"],
        examFocus:
          "Do not treat the heap array as sorted. Only ancestor-descendant comparisons implied by the heap property are guaranteed.",
        example: {
          prompt: "In a zero-based heap, identify the parent and children indexes of position 5.",
          walkthrough:
            "Parent=floor((5-1)/2)=2. Left child=2*5+1=11 and right child=12, provided those indexes are below heap size. The formulas concern positions, independent of stored keys.",
        },
      },
      {
        title: "Insertion, deletion, and priority queues",
        explanation:
          "Insertion places a new key at the next array position to preserve completeness, then sifts it upward while it violates the parent relation. Removing the root replaces it with the final key, shrinks the heap, and sifts that key downward by exchanging with the more appropriate child. Each operation crosses at most the heap height, giving logarithmic worst-case time. Peek at the root is constant time. A heap therefore implements a priority queue efficiently, but searching for an arbitrary non-extreme key remains linear because heap order does not select one search branch.",
        keyIdeas: ["Insertion repairs upward", "Root deletion repairs downward", "Arbitrary search is not logarithmic"],
        examFocus:
          "During max-heap sift-down, compare with the larger child before swapping; choosing the smaller child can leave an immediate violation.",
        example: {
          prompt: "Insert 50 into max-heap array [40,30,35,10,20].",
          walkthrough:
            "Append 50 at index 5. Its parent at index 2 is 35, so swap to get [40,30,50,10,20,35]. Now parent index 0 holds 40; swap again. The result is [50,30,40,10,20,35].",
        },
      },
      {
        title: "Build-heap and heapsort",
        explanation:
          "Bottom-up build-heap treats all leaves as one-element heaps and calls sift-down on internal nodes from the last parent back to the root. Although one sift can take logarithmic time, most nodes are near the leaves and move only a short distance, so total construction is Theta(n), not Theta(n log n). Heapsort builds a max-heap, repeatedly swaps the root with the final element of the active heap, reduces heap size, and restores order. It runs Theta(n log n) in the worst case and sorts in place, but standard heapsort is not stable.",
        keyIdeas: ["Bottom-up heap construction is linear", "Each extraction fixes one final sorted position", "Heapsort is in-place but not stable"],
        examFocus:
          "Distinguish inserting n keys one by one, which can cost n log n, from Floyd's bottom-up build, which is linear.",
        example: {
          prompt: "Why does build-heap not cost n log n even though root sift-down may cost log n?",
          walkthrough:
            "Only very few nodes occur near the root and can move far. Roughly half the nodes are leaves and do no work, a quarter move at most one level, an eighth at most two, and the weighted sum is bounded by a constant times n.",
        },
      },
    ],
    formulae: [
      { label: "Zero-based heap indexes", expression: "parent=floor((i-1)/2), left=2i+1, right=2i+2", useWhen: "Navigating parent and child positions in an array heap" },
      { label: "Heap height", expression: "floor(log2 n)", useWhen: "Bounding sift-up or sift-down for n stored keys" },
      { label: "Bottom-up build", expression: "Theta(n)", useWhen: "Heapifying an existing array from its last internal node" },
    ],
    checkpoints: [
      { question: "Is a max-heap array sorted?", answer: "No. Every parent is at least its children, but no total order is guaranteed among siblings or across separate subtrees." },
      { question: "Where is a new heap key first inserted?", answer: "At the next open array position, preserving the complete-tree shape, before it is sifted upward if necessary." },
      { question: "What replaces a deleted heap root?", answer: "The last key in the active heap moves to the root, the heap shrinks, and that key sifts downward to restore order." },
      { question: "What is arbitrary-key search complexity in a heap?", answer: "Theta(n) in the worst case because the partial order does not identify one branch containing a non-extreme target." },
      { question: "Why is bottom-up build-heap linear?", answer: "Most nodes have small height and require little or no sift work; summing node count times height over all levels yields Theta(n)." },
    ],
  },
  {
    subjectCode: "PDS",
    subjectId: "programming-and-data-structures",
    topicId: "graphs",
    title: "Graphs",
    summary:
      "Graph data structures represent arbitrary pairwise relationships. This lesson focuses on the GATE programming-and-data-structures scope: directed and undirected representations, degree and storage accounting, traversal-support operations, and choosing adjacency matrices or lists for density and query needs.",
    estimatedMinutes: 45,
    prerequisites: ["Arrays", "Linked lists", "Stacks and queues"],
    objectives: [
      "Represent directed and undirected graphs with matrices and lists",
      "Calculate representation space and degree information",
      "Perform elementary adjacency and neighborhood operations",
      "Choose a representation for sparse or dense workloads",
    ],
    concepts: [
      {
        title: "Vertices, edges, and representation semantics",
        explanation:
          "A graph consists of vertices and edges. Undirected edges connect unordered pairs and contribute one to each endpoint's degree; directed edges have a tail and head, contributing to out-degree and in-degree respectively. A simple graph has no self-loops or parallel edges. Representation must preserve whether direction, weights, and multiplicity matter. Labeling vertices with compact integer indexes makes array-based structures convenient, while arbitrary labels may require a mapping. The sum of degrees is 2|E| for undirected graphs, and total in-degree equals total out-degree equals |E| for directed graphs.",
        keyIdeas: ["Undirected edges appear at two endpoints", "Directed edges separate in-degree and out-degree", "Representation must retain direction and any weights"],
        examFocus:
          "When counting stored adjacency entries, double undirected non-loop edges but count each directed edge once unless the representation deliberately stores reverse links.",
        example: {
          prompt: "An undirected graph has degrees 3,3,2,2,2,2. How many edges does it have?",
          walkthrough:
            "The degree sum is 3+3+2+2+2+2=14. By the handshaking lemma, 2|E|=14, so |E|=7. The even total also verifies that the supplied degree sequence is arithmetically consistent.",
        },
      },
      {
        title: "Adjacency matrices and adjacency lists",
        explanation:
          "An adjacency matrix uses a V by V table, giving constant-time edge-existence queries and Theta(V^2) space regardless of edge count. For a simple undirected graph it is symmetric, and row sums give degrees. An adjacency list stores a collection of neighbors for each vertex, using Theta(V+E) space for directed graphs and Theta(V+2E) entries for undirected graphs. Iterating a vertex's neighbors is proportional to its degree. Lists favor sparse graphs and traversals, while matrices favor dense graphs or workloads dominated by repeated adjacency tests.",
        keyIdeas: ["Matrix space is quadratic", "List space follows vertices plus edges", "Neighbor iteration in a list follows degree"],
        examFocus:
          "Separate asymptotic storage from exact entries; an undirected list stores each edge in both endpoint lists.",
        example: {
          prompt: "Compare neighbor scanning for one vertex of degree 4 in a 1000-vertex graph.",
          walkthrough:
            "An adjacency list examines its four stored neighbors, Theta(4). An adjacency-matrix row has 1000 columns and must inspect all to enumerate neighbors, Theta(1000), though checking one specified edge is constant time in the matrix.",
        },
      },
      {
        title: "Elementary traversal support and operations",
        explanation:
          "Graph processing marks visited vertices to prevent repeated work on cycles. Depth-first exploration uses a stack, explicitly or through recursion, while breadth-first exploration uses a queue. With adjacency lists, either traversal examines each vertex and each stored edge entry, giving Theta(V+E) asymptotically. Adding an edge to an unsorted list can be constant time, but testing or deleting a particular edge may scan a degree-sized list. A matrix reverses that trade-off: edge test, add, and delete are constant time after vertex indexing, at the cost of quadratic initialization and storage.",
        keyIdeas: ["Visited state prevents cycling", "DFS uses stack discipline and BFS uses queue discipline", "Representation changes operation costs"],
        examFocus:
          "Use the representation specified when reporting traversal complexity; a matrix traversal may inspect V^2 entries even for a sparse graph.",
        example: {
          prompt: "Why must a DFS of an undirected triangle mark vertices?",
          walkthrough:
            "Without marks, visiting A leads to B, B leads to C, and C can lead back to A indefinitely. Marking on discovery ensures each vertex is pushed or recursively entered once, while already visited neighbors are skipped.",
        },
      },
    ],
    formulae: [
      { label: "Undirected degree sum", expression: "sum deg(v)=2|E|", useWhen: "Checking degree data or deriving edge count" },
      { label: "Adjacency-list space", expression: "Theta(V+E)", useWhen: "Representing a sparse graph asymptotically" },
      { label: "List-based traversal", expression: "Theta(V+E)", useWhen: "DFS or BFS marks every vertex and examines every adjacency entry" },
    ],
    checkpoints: [
      { question: "How many adjacency-list entries represent one undirected non-loop edge?", answer: "Two entries, one in each endpoint's neighbor list, unless a specialized shared-edge representation is explicitly stated." },
      { question: "What is adjacency-matrix space for V vertices?", answer: "Theta(V^2), independent of how many edges are actually present." },
      { question: "Which representation gives constant-time specified-edge lookup?", answer: "An adjacency matrix gives direct indexed lookup. A basic unsorted adjacency list may scan one endpoint's neighbor list." },
      { question: "What prevents DFS from looping on a cycle?", answer: "A visited mark recorded when a vertex is discovered prevents the algorithm from entering that vertex repeatedly." },
      { question: "Why are adjacency lists suitable for sparse graphs?", answer: "Their storage and neighbor scanning track actual edges rather than allocating and scanning all V^2 possible vertex pairs." },
    ],
  },
  {
    subjectCode: "ALG",
    subjectId: "algorithms",
    topicId: "searching-sorting-and-hashing",
    title: "Searching, Sorting and Hashing",
    summary:
      "Searching, sorting, and hashing organize access to collections under different assumptions. GATE questions compare worst-case and average costs, trace partitioning or merging, test stability and in-place behavior, and calculate hash probe sequences under stated collision policies.",
    estimatedMinutes: 70,
    prerequisites: ["Arrays", "Asymptotic notation", "Basic probability"],
    objectives: [
      "Trace linear and binary search with correct boundaries",
      "Compare standard comparison sorts by time, space, and stability",
      "Explain comparison-sorting lower bounds",
      "Analyze chaining and open-addressed hashing",
    ],
    concepts: [
      {
        title: "Linear and binary search",
        explanation:
          "Linear search checks candidates sequentially and works without ordering, taking constant best-case and linear worst-case time. Binary search requires a sorted random-access sequence and maintains an interval that can still contain the key. Each comparison discards roughly half, giving logarithmic worst-case comparisons. Correct variants decide whether the interval is closed [low,high] or half-open [low,high), update boundaries consistently, and compute the midpoint without accidental nonprogress. Finding the first occurrence, last occurrence, or insertion position changes the equality case rather than merely stopping at any match.",
        keyIdeas: ["Binary search needs a monotone decision over sorted data", "Its invariant defines the surviving interval", "Boundary variants continue after equality"],
        examFocus:
          "Trace low, mid, and high using the code's exact interval convention; off-by-one updates can create an infinite loop or skip a candidate.",
        example: {
          prompt: "Search for 23 in [4,9,12,17,23,31,40] using closed-interval binary search.",
          walkthrough:
            "Start low=0, high=6, mid=3 with value 17, so set low=4. Now mid=floor((4+6)/2)=5 with value 31, so set high=4. Mid=4 holds 23, and the search succeeds after three comparisons.",
        },
      },
      {
        title: "Sorting properties and mechanisms",
        explanation:
          "Insertion sort grows a sorted prefix and is stable, in-place, quadratic in the worst case, and linear on already sorted input. Selection sort repeatedly selects an extreme and remains quadratic even when ordered; a basic form is not stable. Merge sort combines sorted halves in linear time, guarantees n log n time, and typically uses extra array storage. Quicksort partitions around a pivot, is in-place in common forms and averages n log n, but poor pivots cause quadratic time. Heapsort guarantees n log n and constant auxiliary array space but is not stable. Stability preserves input order among equal keys.",
        keyIdeas: ["Stability concerns equal-key order", "Merge sort guarantees n log n with extra storage", "Quicksort performance depends on partition balance"],
        examFocus:
          "When identifying an algorithm from intermediate arrays, focus on its invariant: sorted prefix, selected suffix, merged runs, heap region, or pivot partition.",
        example: {
          prompt: "Why might stable sorting matter for records already ordered by name when sorting them by score?",
          walkthrough:
            "A stable score sort keeps equal-score records in their prior name order, effectively producing score as the primary key and name as the secondary key. An unstable sort may arbitrarily reorder equal-score records and destroy that useful earlier ordering.",
        },
      },
      {
        title: "Hash tables and collision resolution",
        explanation:
          "A hash function maps a large key space into a finite table, so collisions are unavoidable. Separate chaining stores collided keys in per-slot collections and can tolerate load factor above one, with expected cost tied to average chain length. Open addressing keeps every key in the table and probes alternative slots; its load factor must remain below one. Linear probing has excellent locality but primary clustering, quadratic probing changes step size, and double hashing uses a second hash as the probe stride. Deletion in open addressing needs a tombstone so later search paths are not broken.",
        keyIdeas: ["Load factor is stored keys divided by slots", "Open addressing follows the same probe sequence for search and insertion", "Tombstones preserve probe continuity"],
        examFocus:
          "Compute every probe modulo table size and follow the stated collision method exactly; a collision does not permit choosing any empty slot.",
        example: {
          prompt: "Insert keys 12, 23, 34 into size-11 table using h(k)=k mod 11 and linear probing.",
          walkthrough:
            "All three initially hash to 1. Place 12 at slot 1. Key 23 probes 1 then occupies 2. Key 34 probes occupied slots 1 and 2, then occupies 3. This contiguous cluster illustrates primary clustering.",
        },
      },
    ],
    formulae: [
      { label: "Binary-search bound", expression: "Theta(log2 n) comparisons in the worst case", useWhen: "Searching a sorted random-access sequence" },
      { label: "Comparison-sort lower bound", expression: "Omega(n log n)", useWhen: "Sorting arbitrary distinct keys using only comparisons" },
      { label: "Hash load factor", expression: "alpha=n/m", useWhen: "n keys occupy a table of m slots" },
    ],
    checkpoints: [
      { question: "What precondition does ordinary binary search need?", answer: "The searchable sequence or predicate must be ordered monotonically so a comparison can safely discard one side." },
      { question: "Which standard sort is linear on already sorted input?", answer: "Insertion sort with the usual stopping comparison is Theta(n) because each element needs no shifting beyond its initial position." },
      { question: "What does sorting stability preserve?", answer: "It preserves the relative input order of records whose comparison keys are equal." },
      { question: "Why can quicksort be quadratic?", answer: "Repeated highly unbalanced partitions, such as splitting sizes zero and n-1, produce linear work at each of n recursion levels." },
      { question: "Why use tombstones in open-address deletion?", answer: "Marking a slot deleted rather than empty preserves probe paths for keys inserted later in the same collision chain." },
    ],
  },
  {
    subjectCode: "ALG",
    subjectId: "algorithms",
    topicId: "complexity-analysis",
    title: "Complexity Analysis",
    summary:
      "Complexity analysis describes how resource use grows with input size independently of machine constants. GATE problems demand precise asymptotic bounds, loop and recurrence counting, best versus worst cases, and awareness that multiple input parameters may not collapse into one variable.",
    estimatedMinutes: 60,
    prerequisites: ["Functions and logarithms", "Summations"],
    objectives: [
      "Use O, Omega, and Theta definitions correctly",
      "Order common growth rates",
      "Analyze nested, dependent, and multiplicative loops",
      "Distinguish time, auxiliary space, and input storage",
    ],
    concepts: [
      {
        title: "Asymptotic notation and growth",
        explanation:
          "Big-O is an asymptotic upper bound, Omega a lower bound, and Theta a matching two-sided bound. They describe function families beyond a sufficiently large input, ignoring constant factors but not different growth classes. Saying an algorithm is O(n^2) does not imply its tight bound is quadratic because a linear function is also O(n^2). Logarithm bases differ only by constants, while polynomial degrees and exponential bases change asymptotic ordering. Best, average, and worst cases are separate functions and must be labeled rather than mixed.",
        keyIdeas: ["Theta gives a tight asymptotic class", "Upper bounds need not be tight", "Case assumptions belong in the complexity statement"],
        examFocus:
          "For true-or-false asymptotic claims, compare ratios or definitions; informal statements such as 'grows faster' can conceal a valid loose upper bound.",
        example: {
          prompt: "Classify f(n)=7n log n+20n+9 with a tight asymptotic bound.",
          walkthrough:
            "The n log n term dominates linear and constant terms for large n. Multiplying by 7 does not change the asymptotic class, so f(n)=Theta(n log n), and consequently it is also O(n^2) but that is not tight.",
        },
      },
      {
        title: "Loop and operation counting",
        explanation:
          "A single loop's complexity follows how many times its control variable changes before termination. Additive increments usually give linear counts; multiplicative growth or division gives logarithmic counts. Independent nested loops multiply iteration counts, but dependent bounds require a summation. A triangular nest with inner iterations proportional to the outer index sums 1+2+...+n=Theta(n^2). Sequential blocks add costs and the dominant term remains. When input has dimensions n and m, retain both unless the question supplies a relationship; replacing m by n without justification can produce a wrong bound.",
        keyIdeas: ["Multiplicative loop variables produce logarithms", "Dependent nests require sums", "Sequential costs add and nested independent costs multiply"],
        examFocus:
          "Count the body executions, not just syntactic loop depth; a three-level nest may be subquadratic or exponential depending on bounds.",
        example: {
          prompt: "Analyze the total work performed by these nested loops: `for(i=1;i<=n;i*=2) for(j=0;j<i;j++) work();`.",
          walkthrough:
            "Outer i values are 1,2,4,... up to n. Inner work totals 1+2+4+...+largest power at most n, a geometric sum below 2n and at least n for power-of-two n. Total time is Theta(n), not Theta(n log n).",
        },
      },
      {
        title: "Time-space reasoning and recurrences",
        explanation:
          "Time complexity counts selected primitive operations, while auxiliary space counts additional storage beyond the input. Recursive space depends on maximum active depth and per-frame storage. A recurrence captures recursive time by combining subproblem calls with nonrecursive work. Expansion, recursion trees, and substitution are general analysis tools; the Master theorem applies only to forms aT(n/b)+f(n) with appropriate regularity. Amortized analysis averages a guaranteed total cost over an operation sequence and differs from probabilistic average-case analysis, which assumes an input distribution.",
        keyIdeas: ["Auxiliary space excludes the given input unless stated", "Recurrence terms separate recursive and local work", "Amortized bounds cover operation sequences without probability"],
        examFocus:
          "Do not apply the Master theorem to unequal subproblem sizes or n-1 recurrences; expand or bound those with a suitable alternative.",
        example: {
          prompt: "A recursive procedure makes one call on n/2, performs constant local work, and stores a constant-size frame. Find time and stack space.",
          walkthrough:
            "Both the number of calls and maximum active depth are the number of halvings until one, namely Theta(log n). Constant work and constant frame size at each level make both time and auxiliary stack space Theta(log n).",
        },
      },
    ],
    formulae: [
      { label: "Arithmetic sum", expression: "1+2+...+n=n(n+1)/2=Theta(n^2)", useWhen: "A dependent inner loop runs proportional to the outer index" },
      { label: "Geometric sum", expression: "1+r+...+r^k=(r^(k+1)-1)/(r-1)", useWhen: "Loop work doubles or scales by a fixed ratio" },
      { label: "Master form", expression: "T(n)=aT(n/b)+f(n)", useWhen: "Equal-sized divide-and-conquer subproblems satisfy theorem conditions" },
    ],
    checkpoints: [
      { question: "Does O(n^2) mean an algorithm takes exactly quadratic time?", answer: "No. It is an upper bound; linear or n log n time also belongs to O(n^2). Theta(n^2) would state a tight quadratic class." },
      { question: "How many iterations does `i*=3` take from 1 to n?", answer: "Theta(log_3 n), which is Theta(log n) because changing logarithm base changes only a constant factor." },
      { question: "When do nested loop counts multiply?", answer: "They multiply when each inner loop performs an independent fixed count for every outer iteration; dependent bounds must instead be summed." },
      { question: "What is amortized analysis?", answer: "It bounds average cost per operation over every sufficiently long sequence by spreading occasional expensive operations across many cheap ones, without a probability assumption." },
      { question: "What determines recursive auxiliary stack space?", answer: "Maximum simultaneous call depth multiplied by per-frame storage, plus any other live auxiliary objects—not the total number of calls." },
    ],
  },
  {
    subjectCode: "ALG",
    subjectId: "algorithms",
    topicId: "divide-and-conquer",
    title: "Divide and Conquer",
    summary:
      "Divide and conquer splits a problem into smaller instances, solves them recursively, and combines their results. GATE questions connect algorithm structure to recurrences, recursion-tree levels, merge or partition work, base cases, and the consequences of balanced versus unbalanced splits.",
    estimatedMinutes: 55,
    prerequisites: ["Recursion", "Complexity analysis"],
    objectives: [
      "Identify divide, conquer, and combine phases",
      "Derive recurrences from recursive algorithms",
      "Analyze balanced and unbalanced recursion trees",
      "Explain merge sort, binary search, and partition-based behavior",
    ],
    concepts: [
      {
        title: "Design pattern and recurrence modeling",
        explanation:
          "A divide-and-conquer algorithm creates subproblems, solves them recursively until a base case, and combines their answers. The recurrence must count how many subproblems exist, their size, and all work outside recursive calls. Balanced division is powerful because repeated constant-factor shrinking gives logarithmic depth. Subproblems need not always be independent, but recomputing overlapping subproblems is usually better treated by dynamic programming. Correctness follows by showing the split covers the original problem, recursive answers are correct by induction, and the combine step produces the desired whole answer.",
        keyIdeas: ["Recurrences mirror subproblem count, size, and combine work", "Constant-factor shrinking gives logarithmic depth", "Combine correctness completes the inductive proof"],
        examFocus:
          "Derive the recurrence directly from code rather than selecting one from memory; a loop before two calls contributes differently from loops inside each call.",
        example: {
          prompt: "An algorithm makes four recursive calls on n/2 and then performs cn work. Write its recurrence.",
          walkthrough:
            "Each invocation generates four size-n/2 subproblems, contributing 4T(n/2). The stated combine or local work adds cn. Thus T(n)=4T(n/2)+cn with an appropriate constant base case.",
        },
      },
      {
        title: "Merge sort and balanced combination",
        explanation:
          "Merge sort divides an array into two near-equal halves, recursively sorts each, and merges two sorted sequences by repeatedly taking the smaller front item. A merge examines and copies a linear number of elements. Every recursion level covers all n elements across its subproblems, and there are logarithmically many levels, yielding Theta(n log n) time in best, average, and worst cases. Standard array merge sort needs linear auxiliary storage and is stable when ties are taken from the left half first. Its predictable time contrasts with input-sensitive partition quality in quicksort.",
        keyIdeas: ["Merge work is linear per level", "Balanced halves create logarithmic levels", "Tie handling determines merge stability"],
        examFocus:
          "Count merge comparisons carefully: merging lengths p and q takes at most p+q-1 comparisons, even though p+q elements are copied.",
        example: {
          prompt: "Merge sorted lists [2,7,10] and [3,7,12].",
          walkthrough:
            "Compare fronts and emit 2, then 3. Emit 7 from the left before equal 7 from the right to preserve stability. Next emit right 7, then left 10, and append 12. Result: [2,3,7,7,10,12].",
        },
      },
      {
        title: "Partition balance and recursion-tree consequences",
        explanation:
          "Not all divide-and-conquer splits are balanced. Quicksort partitions keys around a pivot so smaller keys precede it and larger keys follow, then recursively sorts the two regions. If partitions remain proportional, depth is logarithmic and total work is n log n. If a pivot repeatedly produces sizes zero and n-1, depth and time become linear and quadratic respectively. Binary search represents the one-subproblem case, discarding half each step for logarithmic time. Selection of a split rule therefore affects performance even when the combine work is unchanged.",
        keyIdeas: ["Balanced partitions control recursion depth", "Quicksort's worst split removes one element", "Binary search follows only one half"],
        examFocus:
          "When partition sizes are supplied, build the recurrence from those exact sizes; do not automatically assume equal halves or average behavior.",
        example: {
          prompt: "Compare the asymptotic solutions of recurrences T(n)=2T(n/2)+n and T(n)=T(n-1)+n.",
          walkthrough:
            "The balanced recurrence has log n levels with n work per level, giving Theta(n log n). The decrement recurrence sums n+(n-1)+...+1, giving Theta(n^2). Similar local work produces different totals because recursion depths differ.",
        },
      },
    ],
    formulae: [
      { label: "Balanced merge recurrence", expression: "T(n)=2T(n/2)+Theta(n)=Theta(n log n)", useWhen: "Two equal halves are combined linearly" },
      { label: "Binary-search recurrence", expression: "T(n)=T(n/2)+Theta(1)=Theta(log n)", useWhen: "One half survives each decision" },
      { label: "Worst partition recurrence", expression: "T(n)=T(n-1)+Theta(n)=Theta(n^2)", useWhen: "One pivot removes only itself at every level" },
    ],
    checkpoints: [
      { question: "What are the three divide-and-conquer phases?", answer: "Divide into smaller instances, conquer them recursively with base cases, and combine their results into the original problem's answer." },
      { question: "Why does repeated halving give logarithmic depth?", answer: "After k halvings size is n/2^k; reaching one requires k approximately log2 n." },
      { question: "What is merge sort's worst-case time?", answer: "Theta(n log n), because every input has logarithmically many balanced levels and linear total merging work at each level." },
      { question: "When is a merge stable?", answer: "When equal keys are emitted in their original relative order, commonly by choosing the left-run item first on a tie." },
      { question: "What causes quicksort's quadratic case?", answer: "Repeated maximally unbalanced partitions create linear recursion depth and sum linear partition costs over decreasing sizes." },
    ],
  },
  {
    subjectCode: "ALG",
    subjectId: "algorithms",
    topicId: "greedy-algorithms",
    title: "Greedy Algorithms",
    summary:
      "A greedy algorithm commits to the locally preferred feasible choice and never revisits it. GATE questions test when this strategy is justified, how exchange and cut arguments prove correctness, and why superficially similar problems may require different ordering rules.",
    estimatedMinutes: 55,
    prerequisites: ["Sorting", "Graph basics", "Proof by contradiction"],
    objectives: [
      "Identify greedy-choice and optimal-substructure requirements",
      "Construct exchange-style correctness arguments",
      "Solve interval selection and fractional-knapsack patterns",
      "Apply cut reasoning to minimum spanning trees",
    ],
    concepts: [
      {
        title: "Greedy choice and proof discipline",
        explanation:
          "A greedy rule selects the best-looking feasible next action under a defined criterion. Local appeal alone is not proof. Correctness typically needs an exchange argument showing an optimal solution can be modified to include the greedy choice without becoming worse, followed by optimal substructure for the remaining instance. A stays-ahead argument compares partial greedy progress with every competitor. Greedy algorithms often sort candidates first and scan once, so sorting dominates time. A counterexample with one irreversible bad choice is enough to reject an unjustified rule.",
        keyIdeas: ["Greedy choices are irrevocable", "Exchange arguments align an optimum with the greedy choice", "A plausible heuristic is not automatically correct"],
        examFocus:
          "When asked which strategy is valid, test each proposed ordering on a small adversarial instance before assuming a familiar greedy template applies.",
        example: {
          prompt: "Why is choosing the largest coin first not universally optimal for arbitrary coin denominations?",
          walkthrough:
            "With denominations 1,3,4 and amount 6, largest-first chooses 4+1+1, using three coins. The optimal solution is 3+3, using two. This counterexample disproves universal correctness of that greedy rule.",
        },
      },
      {
        title: "Activity selection and fractional knapsack",
        explanation:
          "For selecting the maximum number of nonoverlapping activities on one resource, choosing the compatible activity with earliest finish leaves at least as much future time as any alternative. Sorting by finish time and scanning yields an optimal set. Fractional knapsack permits taking part of an item, so selecting descending value-to-weight ratio is optimal: any solution using lower-ratio weight while higher-ratio weight remains can exchange those portions and improve value. The same ratio rule fails for zero-one knapsack because indivisible choices prevent such fractional exchange.",
        keyIdeas: ["Earliest finish maximizes remaining scheduling room", "Fractional knapsack sorts by value density", "Indivisibility can invalidate a fractional greedy proof"],
        examFocus:
          "Check whether endpoints that touch are compatible under the question's interval convention and whether items may be divided.",
        example: {
          prompt: "Activities (start,finish) are (0,3),(1,2),(2,5),(3,4). Apply earliest-finish selection.",
          walkthrough:
            "Choose (1,2), the earliest finisher. Among activities starting at or after 2, (3,4) finishes before (2,5), so choose (3,4). The selected two activities are compatible and optimal.",
        },
      },
      {
        title: "Minimum spanning trees and cut safety",
        explanation:
          "A spanning tree connects every vertex without cycles and has V-1 edges. For a weighted connected undirected graph, a minimum spanning tree minimizes total edge weight. The cut property states that a lightest edge crossing any cut is safe for some MST, supporting Kruskal's global lightest noncycle edge rule and Prim's lightest edge leaving the current tree rule. Kruskal uses disjoint sets to detect cycles; Prim uses frontier keys. Distinct edge weights guarantee a unique MST, though equal weights may still happen to yield uniqueness.",
        keyIdeas: ["An MST has V-1 edges", "Light cut edges are safe", "Kruskal prevents cycles and Prim grows one connected tree"],
        examFocus:
          "Use cut or cycle properties to answer edge-membership questions without constructing every spanning tree; handle tied weights with non-strict conclusions.",
        example: {
          prompt: "A graph triangle has edge weights 2,5,7. Which edges form its MST?",
          walkthrough:
            "A spanning tree needs two edges. Kruskal selects weight 2 and then weight 5; adding weight 7 would create the triangle cycle and is unnecessary. Total MST weight is 7.",
        },
      },
    ],
    formulae: [
      { label: "Activity rule", expression: "repeatedly choose the compatible activity with minimum finish time", useWhen: "Maximizing count of nonoverlapping single-resource activities" },
      { label: "Fractional density", expression: "value/weight", useWhen: "Items may be divided and capacity should receive highest value per unit" },
      { label: "MST size", expression: "V-1 edges", useWhen: "A connected undirected spanning tree covers V vertices" },
    ],
    checkpoints: [
      { question: "What must a greedy correctness proof establish?", answer: "It must show the greedy choice can belong to an optimum, often by exchange, and that the remaining subproblem can be solved optimally in the same manner." },
      { question: "Which activity-selection ordering is optimal?", answer: "Choose compatible activities by earliest finishing time, because that leaves maximal room for future choices." },
      { question: "Why does value density solve fractional knapsack?", answer: "Any lower-density portion can be exchanged for an available higher-density portion of equal weight to increase value." },
      { question: "What makes an MST edge safe across a cut?", answer: "An edge of minimum weight among those crossing the cut can be included in some MST without increasing optimal total weight." },
      { question: "How do Kruskal and Prim differ?", answer: "Kruskal builds a forest by globally adding light noncycle edges; Prim grows one connected tree using the lightest edge crossing its current cut." },
    ],
  },
  {
    subjectCode: "ALG",
    subjectId: "algorithms",
    topicId: "dynamic-programming",
    title: "Dynamic Programming",
    summary:
      "Dynamic programming solves overlapping subproblems once and combines their stored optimal values. GATE questions focus on choosing states, writing recurrences and base cases, respecting dependency order, reconstructing solutions, and calculating table time and space without accidentally changing the problem through an unsafe update order.",
    estimatedMinutes: 65,
    prerequisites: ["Recursion", "Complexity analysis", "Basic combinatorics"],
    objectives: [
      "Recognize overlapping subproblems and optimal substructure",
      "Design state definitions, transitions, and base cases",
      "Translate between memoization and tabulation",
      "Analyze classic sequence and knapsack-style tables",
    ],
    concepts: [
      {
        title: "State design and optimal substructure",
        explanation:
          "A dynamic-programming state must summarize all past information needed for future decisions while avoiding irrelevant history. A transition expresses that state through smaller states, and base cases anchor the dependency graph. Optimal substructure means an optimal whole solution contains optimal solutions to the subproblems selected by its first decision; overlapping subproblems mean naive recursion revisits the same states. Correctness follows by considering every possible final or first choice represented in the transition and proving the minimum or maximum over them includes an optimum.",
        keyIdeas: ["A state captures sufficient future-relevant information", "Transitions enumerate valid choices", "Base cases terminate the dependency graph"],
        examFocus:
          "State dimensions determine complexity. If a proposed state omits information that changes legal future choices, its recurrence is not valid even if examples happen to work.",
        example: {
          prompt: "Define a state for the minimum number of coins to form amount x with unlimited given denominations.",
          walkthrough:
            "Let dp[x] be the minimum coins needed for exactly x, with dp[0]=0. For x>0, try every coin c<=x and set dp[x]=1+min(dp[x-c]). Unreachable states remain infinity. The state needs only the remaining amount because coin reuse is unlimited.",
        },
      },
      {
        title: "Memoization, tabulation, and dependency order",
        explanation:
          "Top-down memoization keeps the recursive structure but caches each computed state, evaluating only states reached by the query. Bottom-up tabulation fills states iteratively in an order that guarantees every dependency is already available. Both have time proportional to number of states times transition work when implemented well. Memoization uses recursion stack and lookup overhead; tabulation can offer predictable memory access and easier space compression. Compression is safe only when overwritten entries will never be needed by later transitions, so loop direction becomes part of correctness.",
        keyIdeas: ["Memoization caches demanded recursive states", "Tabulation follows a dependency-valid order", "Space compression must preserve still-needed values"],
        examFocus:
          "For one-dimensional compressed knapsack, loop direction distinguishes zero-one from unbounded item reuse; an incorrect direction silently changes the problem.",
        example: {
          prompt: "Why must zero-one knapsack capacities run downward when updating a one-dimensional table for one item?",
          walkthrough:
            "Descending capacity reads dp[w-weight] from the previous-item state before it is updated by the current item. Ascending capacity could read a value already using that same item, allowing it multiple times and turning the recurrence into unbounded knapsack.",
        },
      },
      {
        title: "Sequence and selection recurrences",
        explanation:
          "Longest common subsequence uses state L[i][j] for prefixes of two sequences. Matching final symbols extend L[i-1][j-1]; otherwise the optimum drops one final symbol and takes max(L[i-1][j],L[i][j-1]). Zero-one knapsack uses item index and remaining or used capacity, choosing between excluding an item and including it once if it fits. Matrix-chain multiplication chooses the final split point and combines optimal left and right costs with the scalar multiplication cost. In every case, storing a predecessor choice enables reconstruction beyond just reporting the optimal value.",
        keyIdeas: ["LCS compares prefixes", "Zero-one knapsack branches include/exclude", "Matrix-chain DP chooses a split point"],
        examFocus:
          "Match table axes and base rows to the recurrence before filling cells; GATE may provide a partially filled table with a shifted indexing convention.",
        example: {
          prompt: "Find the LCS length of `AB` and `ACB`.",
          walkthrough:
            "A matches A, giving length one for those prefixes. The final B in the first string matches the final B in the second, extending the best preceding prefixes to length two. Thus `AB` is a common subsequence and the LCS length is 2.",
        },
      },
    ],
    formulae: [
      { label: "DP running time", expression: "number of states * transition work per state", useWhen: "Acyclic state dependencies are computed once" },
      { label: "LCS recurrence", expression: "match:1+L[i-1][j-1]; else:max(L[i-1][j],L[i][j-1])", useWhen: "Comparing prefixes of two symbol sequences for common order" },
      { label: "Zero-one knapsack", expression: "DP[i,w]=max(DP[i-1,w], value_i+DP[i-1,w-weight_i])", useWhen: "Item i fits and may be selected at most once" },
    ],
    checkpoints: [
      { question: "What two properties make dynamic programming useful?", answer: "Overlapping subproblems make caching valuable, and optimal substructure lets stored subproblem optima combine into a whole optimum." },
      { question: "How do memoization and tabulation differ?", answer: "Memoization recursively computes and caches reached states; tabulation iteratively fills states in a dependency-respecting order." },
      { question: "What determines DP time complexity?", answer: "The number of distinct states multiplied by the work needed to evaluate all transitions from each state." },
      { question: "Why can loop direction matter in compressed DP?", answer: "An update may read an entry already changed in the same iteration, unintentionally allowing reuse or destroying a previous-layer dependency." },
      { question: "How is an optimal solution reconstructed from a DP table?", answer: "Store or infer the transition chosen at each state, then follow predecessor states backward until a base case." },
    ],
  },
  {
    subjectCode: "ALG",
    subjectId: "algorithms",
    topicId: "graph-algorithms",
    title: "Graph Algorithms",
    summary:
      "Graph algorithms systematically explore connectivity and optimize paths or spanning structures. GATE questions trace BFS and DFS, classify traversal edges, find components and topological orders, compare shortest-path assumptions, and apply minimum-spanning-tree properties while respecting direction, weights, and representation-specific running time.",
    estimatedMinutes: 70,
    prerequisites: ["Graph representations", "Queues, stacks, and heaps", "Greedy algorithms"],
    objectives: [
      "Trace BFS and DFS and analyze their complexity",
      "Find connected components and topological orders",
      "Choose shortest-path algorithms from edge assumptions",
      "Apply spanning-tree and minimum-spanning-tree reasoning",
    ],
    concepts: [
      {
        title: "Breadth-first and depth-first exploration",
        explanation:
          "BFS marks a source, places it in a queue, and discovers all vertices at distance d before distance d+1. In an unweighted graph, first discovery therefore gives minimum edge-count distance and a shortest-path parent tree. DFS explores one path as deeply as possible using recursion or a stack, assigning discovery and finish structure useful for cycle detection and ordering. With adjacency lists, each vertex is processed once and each edge entry examined a constant number of times, producing Theta(V+E). Neighbor order can change the traversal tree but not fundamental correctness.",
        keyIdeas: ["BFS layers give unweighted shortest distances", "DFS follows stack discipline", "Adjacency-list traversals cost Theta(V+E)"],
        examFocus:
          "Use the exact adjacency order given when a question asks for a traversal sequence; several valid trees may exist when order is unspecified.",
        example: {
          prompt: "Edges are A-B, A-C, B-D, C-D. BFS starts at A and visits neighbors alphabetically. Give dequeue order and distances.",
          walkthrough:
            "Dequeue A first and discover B,C at distance 1. Dequeue B next and discover D at distance 2. Dequeue C, which finds D already marked, then dequeue D. Order is A,B,C,D with distances 0,1,1,2.",
        },
      },
      {
        title: "Components, cycles, and topological ordering",
        explanation:
          "Running DFS or BFS from every still-unvisited vertex identifies connected components in an undirected graph. In a directed acyclic graph, a topological order lists every edge u->v with u before v. Kahn's method repeatedly removes a zero-in-degree vertex and updates outgoing neighbors; processing fewer than V vertices proves a directed cycle. DFS can also produce a topological order by reverse finish time when no back edge exists. In undirected DFS, seeing a visited neighbor other than the parent indicates a cycle; directed cycle tests require recursion-stack or color state.",
        keyIdeas: ["One new traversal begins each undirected component", "Topological orders exist exactly for DAGs", "Directed cycle detection needs active-path information"],
        examFocus:
          "A topological ordering need not be unique. Multiple current zero-in-degree vertices signal alternative valid next choices.",
        example: {
          prompt: "A DAG has edges A->C, B->C, C->D. List all possible first vertices in Kahn's algorithm.",
          walkthrough:
            "A and B both have in-degree zero; C has two and D has one. Therefore either A or B may be selected first. C becomes eligible only after both A and B are removed.",
        },
      },
      {
        title: "Shortest paths and spanning structures",
        explanation:
          "BFS solves single-source shortest paths when every edge has equal unit cost. Dijkstra repeatedly finalizes the unsettled vertex with minimum tentative distance and relaxes outgoing edges; it requires nonnegative edge weights because a later negative edge could improve a finalized vertex. Bellman-Ford repeatedly relaxes every edge and can handle negative weights while detecting reachable negative cycles. A spanning tree connects all vertices with V-1 edges. Prim and Kruskal find a minimum spanning tree in weighted undirected graphs using greedy cut safety, but an MST minimizes total tree weight rather than source-to-vertex path distances.",
        keyIdeas: ["Relaxation tests whether an edge improves a known distance", "Dijkstra requires nonnegative weights", "MST and shortest-path trees optimize different objectives"],
        examFocus:
          "Choose the algorithm only after checking direction, weights, and optimization target; using Dijkstra on a negative edge or MST for shortest paths is invalid.",
        example: {
          prompt: "Edges S->A weight 4, S->B weight 1, B->A weight 2. What distance to A does Dijkstra find?",
          walkthrough:
            "Initial tentative distances are A=4 and B=1. Finalize B first, then relax B->A to 1+2=3, improving A. Finalize A with distance 3, corresponding to path S-B-A.",
        },
      },
    ],
    formulae: [
      { label: "Adjacency-list traversal", expression: "Theta(V+E)", useWhen: "BFS or DFS processes all reachable graph entries" },
      { label: "Relaxation", expression: "if d[v] > d[u]+w(u,v), set d[v]=d[u]+w(u,v)", useWhen: "Testing an edge for a shorter route" },
      { label: "Spanning-tree edge count", expression: "V-1", useWhen: "A tree spans every vertex of a connected graph" },
    ],
    checkpoints: [
      { question: "Why does BFS find shortest paths in an unweighted graph?", answer: "Its queue processes vertices by nondecreasing edge distance, so the first discovery of a vertex uses the fewest possible edges." },
      { question: "When does a topological order exist?", answer: "Exactly when the directed graph is acyclic. Any directed cycle would require one cycle vertex to appear before itself through the edge constraints." },
      { question: "What does edge relaxation do?", answer: "It checks whether reaching v through u improves the current distance estimate and updates distance and predecessor when it does." },
      { question: "Why does Dijkstra reject negative edges?", answer: "A path through a later vertex and negative edge could reduce a distance already finalized under the greedy minimum rule." },
      { question: "Does an MST preserve shortest paths from a chosen source?", answer: "Not necessarily. It minimizes the total weight of selected tree edges, which is a different objective from minimizing every source-to-vertex path." },
    ],
  },
];
