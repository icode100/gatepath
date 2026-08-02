import type { LearningTopic } from "./types";

const EXPECTED_TOPIC_IDS: Record<string, string[]> = {
  "engineering-mathematics": [
    "discrete-mathematics",
    "linear-algebra",
    "calculus",
    "probability-and-statistics",
  ],
  "digital-logic": [
    "boolean-algebra",
    "combinational-circuits",
    "sequential-circuits",
    "number-representation-and-arithmetic",
  ],
  "computer-organization-and-architecture": [
    "machine-instructions-and-addressing-modes",
    "alu-datapath-and-control",
    "instruction-pipelining",
    "memory-hierarchy",
    "i-o-interface",
    "interrupts-and-dma",
  ],
  "programming-and-data-structures": [
    "programming-in-c",
    "recursion",
    "arrays",
    "stacks-and-queues",
    "linked-lists",
    "trees-and-binary-search-trees",
    "heaps",
    "graphs",
  ],
  algorithms: [
    "searching-sorting-and-hashing",
    "complexity-analysis",
    "divide-and-conquer",
    "greedy-algorithms",
    "dynamic-programming",
    "graph-algorithms",
  ],
  "theory-of-computation": [
    "regular-expressions-and-finite-automata",
    "context-free-grammars",
    "pushdown-automata",
    "pumping-lemmas-and-language-properties",
    "turing-machines-and-undecidability",
  ],
  "compiler-design": [
    "lexical-analysis",
    "parsing",
    "syntax-directed-translation",
    "runtime-environments",
    "intermediate-code-generation",
    "code-optimization-and-data-flow-analysis",
  ],
  "operating-systems": [
    "system-calls",
    "processes-and-threads",
    "concurrency-and-synchronization",
    "deadlocks",
    "cpu-and-i-o-scheduling",
    "memory-and-virtual-memory",
    "file-systems",
  ],
  databases: [
    "er-model",
    "relational-model",
    "sql",
    "integrity-constraints",
    "normal-forms",
    "file-organization-and-indexing",
    "transactions-and-concurrency-control",
  ],
  "computer-networks": [
    "layering-and-switching",
    "data-link-layer",
    "routing-algorithms",
    "ipv4-addressing-and-forwarding",
    "transport-layer",
    "application-layer",
    "network-performance",
  ],
  "general-aptitude": [
    "verbal-aptitude",
    "quantitative-aptitude",
    "analytical-aptitude",
    "spatial-aptitude",
  ],
};

const words = (value: string) =>
  value.trim().split(/\s+/).filter(Boolean).length;

const requireText = (
  errors: string[],
  key: string,
  label: string,
  value: string,
  minimumWords: number,
) => {
  if (words(value) < minimumWords) {
    errors.push(`${key}: ${label} needs at least ${minimumWords} words`);
  }
};

/**
 * Treat the learning library as a checked curriculum, not an unvalidated blob.
 * This runs during `next build`, so syllabus drift or accidentally thin content
 * cannot be deployed unnoticed.
 */
export const validateLearningTopics = (topics: LearningTopic[]): void => {
  const errors: string[] = [];
  const expectedKeys = new Set(
    Object.entries(EXPECTED_TOPIC_IDS).flatMap(([subjectId, topicIds]) =>
      topicIds.map((topicId) => `${subjectId}:${topicId}`),
    ),
  );
  const seenKeys = new Set<string>();

  if (topics.length !== expectedKeys.size) {
    errors.push(
      `expected ${expectedKeys.size} syllabus chapters, received ${topics.length}`,
    );
  }

  topics.forEach((topic) => {
    const key = `${topic.subjectId}:${topic.topicId}`;
    if (seenKeys.has(key)) errors.push(`${key}: duplicate chapter key`);
    seenKeys.add(key);
    if (!expectedKeys.has(key)) errors.push(`${key}: outside the canonical syllabus map`);

    requireText(errors, key, "summary", topic.summary, 35);
    if (topic.estimatedMinutes < 35 || topic.estimatedMinutes > 70) {
      errors.push(`${key}: estimatedMinutes must be between 35 and 70`);
    }
    if (topic.prerequisites.length < 1) {
      errors.push(`${key}: add at least one prerequisite`);
    }
    if (topic.objectives.length < 4) {
      errors.push(`${key}: add at least four learning objectives`);
    }
    if (topic.concepts.length < 3) {
      errors.push(`${key}: add at least three concept lessons`);
    }
    if (topic.formulae.length < 2) {
      errors.push(`${key}: add at least two formula or method cards`);
    }
    if (topic.checkpoints.length < 5) {
      errors.push(`${key}: add at least five checkpoint questions`);
    }

    topic.concepts.forEach((concept, conceptIndex) => {
      const conceptKey = `${key} concept ${conceptIndex + 1}`;
      requireText(errors, conceptKey, "explanation", concept.explanation, 70);
      requireText(errors, conceptKey, "exam focus", concept.examFocus, 12);
      requireText(errors, conceptKey, "example prompt", concept.example.prompt, 6);
      requireText(
        errors,
        conceptKey,
        "example walkthrough",
        concept.example.walkthrough,
        20,
      );
      if (concept.keyIdeas.length < 3) {
        errors.push(`${conceptKey}: add at least three key ideas`);
      }
    });

    topic.formulae.forEach((formula, formulaIndex) => {
      const formulaKey = `${key} formula ${formulaIndex + 1}`;
      requireText(errors, formulaKey, "usage guidance", formula.useWhen, 5);
      if (!formula.label.trim() || !formula.expression.trim()) {
        errors.push(`${formulaKey}: label and expression are required`);
      }
    });

    topic.checkpoints.forEach((checkpoint, checkpointIndex) => {
      const checkpointKey = `${key} checkpoint ${checkpointIndex + 1}`;
      requireText(errors, checkpointKey, "question", checkpoint.question, 4);
      requireText(errors, checkpointKey, "answer", checkpoint.answer, 8);
    });
  });

  expectedKeys.forEach((key) => {
    if (!seenKeys.has(key)) errors.push(`${key}: syllabus chapter is missing`);
  });

  if (errors.length) {
    throw new Error(
      `Learning library validation failed (${errors.length} issue${
        errors.length === 1 ? "" : "s"
      }):\n${errors.slice(0, 40).join("\n")}${
        errors.length > 40 ? `\n…plus ${errors.length - 40} more` : ""
      }`,
    );
  }
};

