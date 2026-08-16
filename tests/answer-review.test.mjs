import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import test from "node:test";

import { loadTypeScriptModule } from "./load-typescript-module.mjs";

const {
  applyQuestionReviews,
  formatAcceptedAnswer,
  normalizeAcceptedAnswer,
  questionReviewsFromAttemptRows,
  resolveReviewCorrectness,
} = loadTypeScriptModule("lib/answer-review.ts");
const PAGE = readFileSync(resolve("app/page.tsx"), "utf8");

test("exact NAT answers remain numeric and render without object coercion", () => {
  assert.equal(normalizeAcceptedAnswer(42), 42);
  assert.equal(formatAcceptedAnswer(42), "42");
  assert.equal(formatAcceptedAnswer({ min: 2, max: 2 }), "2");
  assert.doesNotMatch(formatAcceptedAnswer({ min: 2, max: 2 }), /\[object Object\]/);
});

test("interval NAT answers render as an inclusive human-readable range", () => {
  const accepted = normalizeAcceptedAnswer({ min: 1.49, max: 1.51 });
  assert.deepEqual(accepted, { min: 1.49, max: 1.51 });
  assert.equal(formatAcceptedAnswer(accepted), "1.49 to 1.51 (inclusive)");
});

test("tolerance NAT answers render with an explicit plus-minus tolerance", () => {
  const accepted = normalizeAcceptedAnswer({ value: 3.14, tolerance: 0.01 });
  assert.deepEqual(accepted, { value: 3.14, tolerance: 0.01 });
  assert.equal(formatAcceptedAnswer(accepted), "3.14 ± 0.01");
});

test("wrong-answer review keeps server status authoritative", () => {
  const reviews = questionReviewsFromAttemptRows([
    {
      question_id: 17,
      status: "incorrect",
      correct_answer: { min: 10, max: 12 },
      explanation: "The accepted interval comes from the official key.",
    },
  ]);
  const [reviewed] = applyQuestionReviews(
    [
      {
        id: "17",
        type: "NAT",
        correct: [],
        explanation: "Hidden until submission.",
      },
    ],
    reviews,
  );

  assert.equal(reviewed.reviewStatus, "incorrect");
  assert.deepEqual(reviewed.acceptedAnswer, { min: 10, max: 12 });
  assert.deepEqual(reviewed.correct, [], "a NAT object must not become an option string");
  assert.equal(
    resolveReviewCorrectness(reviewed.reviewStatus, true),
    false,
    "client comparison must never override an authoritative incorrect status",
  );
  assert.equal(formatAcceptedAnswer(reviewed.acceptedAnswer), "10 to 12 (inclusive)");

  assert.match(PAGE, /applyQuestionReviews\(current, summary\?\.questionReviews/);
  assert.match(PAGE, /resolveReviewCorrectness\([\s\S]*question\.reviewStatus/);
  assert.doesNotMatch(PAGE, /String\(item\.correct_answer\)/);
});
