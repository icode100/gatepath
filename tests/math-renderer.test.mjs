import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import katex from "katex";
import { loadTypeScriptModule } from "./load-typescript-module.mjs";

const {
  normalizeLegacyFormula,
  parseLegacyMathSegments,
  parseMathSegments,
} = loadTypeScriptModule("components/math/MathText.tsx");
const { FOUNDATION_LEARNING_TOPICS } = loadTypeScriptModule(
  "app/learning/content/foundations.ts",
);
const { SYSTEMS_LEARNING_TOPICS } = loadTypeScriptModule(
  "app/learning/content/systems.ts",
);

const katexOptions = {
  displayMode: false,
  maxExpand: 500,
  maxSize: 20,
  output: "htmlAndMathml",
  strict: "ignore",
  throwOnError: true,
  trust: false,
};

const renderMixedText = (value, location) => {
  const segments = parseMathSegments(value).flatMap((segment) =>
    segment.kind === "text"
      ? parseLegacyMathSegments(segment.value)
      : segment,
  );
  for (const segment of segments) {
    if (segment.kind !== "math") continue;
    assert.doesNotThrow(
      () => katex.renderToString(segment.value, katexOptions),
      `${location}: ${segment.value}`,
    );
  }
};

test("legacy arrows, membership and sums remain valid LaTeX commands", () => {
  const examples = [
    ["E→O→O→E→O", "\\to"],
    ["q∈S", "\\in"],
    ["∑(x_i)", "\\sum"],
  ];

  for (const [source, expectedCommand] of examples) {
    const normalized = normalizeLegacyFormula(source);
    assert.match(normalized, new RegExp(`\\\\${expectedCommand.slice(1)}\\b`));
    assert.doesNotMatch(normalized, /\\\\text/);
    assert.doesNotThrow(() => katex.renderToString(normalized, katexOptions));
  }
});

test("the original double-backslash command corruption is detectable", () => {
  assert.match(String.raw`E\\text{ to }O`, /\\\\text/);
  assert.doesNotMatch(String.raw`E\to O`, /\\\\text/);
});

test("legacy compact powers are converted to grouped LaTeX exponents", () => {
  const segments = parseLegacyMathSegments(
    "Compare 2^p, 2^(n-1), and e^-1.",
  ).filter((segment) => segment.kind === "math");
  const rendered = segments.map((segment) => segment.value).join(" ");

  assert.match(rendered, /2\^\{p\}/);
  assert.match(rendered, /2\^\{n-1\}/);
  assert.match(rendered, /e\^\{-1\}/);
  for (const segment of segments) {
    assert.doesNotThrow(() => katex.renderToString(segment.value, katexOptions));
  }
});

test("C bitwise XOR caret notation stays ordinary text", () => {
  assert.deepEqual(
    parseLegacyMathSegments("The C expression x^y performs bitwise XOR."),
    [
      {
        kind: "text",
        value: "The C expression x^y performs bitwise XOR.",
      },
    ],
  );
});

test("all 64 lesson strings and math cards can be rendered", () => {
  const topics = [
    ...FOUNDATION_LEARNING_TOPICS,
    ...SYSTEMS_LEARNING_TOPICS,
  ];
  assert.equal(topics.length, 64);

  for (const topic of topics) {
    const prefix = `${topic.subjectCode}/${topic.topicId}`;
    const mixed = [
      ["summary", topic.summary],
      ...topic.prerequisites.map((value, index) => [`prerequisite.${index}`, value]),
      ...topic.objectives.map((value, index) => [`objective.${index}`, value]),
      ...topic.concepts.flatMap((concept, index) => [
        [`concept.${index}.title`, concept.title],
        [`concept.${index}.explanation`, concept.explanation],
        ...concept.keyIdeas.map((value, keyIndex) => [
          `concept.${index}.keyIdea.${keyIndex}`,
          value,
        ]),
        [`concept.${index}.examFocus`, concept.examFocus],
        [`concept.${index}.example.prompt`, concept.example.prompt],
        [`concept.${index}.example.walkthrough`, concept.example.walkthrough],
      ]),
      ...topic.formulae.map((formula, index) => [
        `formula.${index}.useWhen`,
        formula.useWhen,
      ]),
      ...topic.checkpoints.flatMap((checkpoint, index) => [
        [`checkpoint.${index}.question`, checkpoint.question],
        [`checkpoint.${index}.answer`, checkpoint.answer],
      ]),
    ];

    for (const [location, value] of mixed) {
      renderMixedText(value, `${prefix}.${location}`);
    }
    for (const [index, formula] of topic.formulae.entries()) {
      if (formula.presentation === "mixed") {
        renderMixedText(formula.expression, `${prefix}.formula.${index}`);
        continue;
      }
      if (formula.presentation && formula.presentation !== "math") continue;
      const normalized = normalizeLegacyFormula(formula.expression);
      assert.doesNotThrow(
        () => katex.renderToString(normalized, katexOptions),
        `${prefix}.formula.${index}: ${normalized}`,
      );
    }
  }
});

test("active-recall badge styling cannot capture the question text", () => {
  const css = readFileSync("app/globals.css", "utf8");
  const page = readFileSync("app/page.tsx", "utf8");

  assert.match(css, /\.checkpoint-number\s*\{/);
  assert.match(css, /\.checkpoint-list summary > \.math-text\s*\{/);
  assert.doesNotMatch(css, /\.checkpoint-list summary span\s*\{/);
  assert.match(page, /className="checkpoint-number"/);
});

test("inline notation does not become a miniature scroll container", () => {
  const css = readFileSync("app/globals.css", "utf8");
  const inlineRule = css.match(/\.math-inline\s*\{([^}]*)\}/)?.[1] ?? "";

  assert.match(inlineRule, /display:\s*inline;/);
  assert.match(inlineRule, /vertical-align:\s*baseline;/);
  assert.doesNotMatch(inlineRule, /overflow/);
  assert.match(css, /\.math-display,[\s\S]*?overflow-x:\s*auto;/);
});
