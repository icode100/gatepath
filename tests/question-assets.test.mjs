import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { loadTypeScriptModule } from "./load-typescript-module.mjs";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const PAGE = readFileSync(resolve(ROOT, "app", "page.tsx"), "utf8");
const COMPONENT = readFileSync(
  resolve(ROOT, "components", "questions", "QuestionAssets.tsx"),
  "utf8",
);
const DRAFT = readFileSync(
  resolve(ROOT, "lib", "mobile", "session-draft.ts"),
  "utf8",
);
const {
  normalizeQuestionAssets,
  questionAssetPlacement,
} = loadTypeScriptModule("lib/question-assets.ts");

const sha = "a".repeat(64);
const valid = {
  role: "stem_diagram",
  url: `/question-assets/pyq/gate-cs-2025-set-1/${sha}.png`,
  alt_text: "A labelled processor data-path diagram.",
  sha256: sha,
};

test("question assets accept only immutable same-origin approved PNGs", () => {
  assert.deepEqual(normalizeQuestionAssets([valid]), [
    {
      role: "stem_diagram",
      url: valid.url,
      altText: valid.alt_text,
      sha256: sha,
    },
  ]);
  assert.deepEqual(
    normalizeQuestionAssets([
      { ...valid, url: "https://tracker.example/image.png" },
      { ...valid, url: "/question-assets/pyq/../../secret.png" },
      { ...valid, role: "raw_html" },
      { ...valid, sha256: "b".repeat(64) },
    ]),
    [],
  );
});

test("asset roles determine their non-duplicated rendering position", () => {
  assert.equal(questionAssetPlacement("answer_option_table"), "options");
  assert.equal(questionAssetPlacement("answer_option_diagrams"), "options");
  assert.equal(questionAssetPlacement("stem_diagram"), "stem");
  assert.equal(
    questionAssetPlacement("stem_and_answer_option_diagrams"),
    "stem",
  );
});

test("bank, practice, mock, and mobile drafts preserve question assets", () => {
  assert.match(PAGE, /normalizeQuestionAssets\(question\.assets\)/);
  assert.match(PAGE, /<QuestionAssets assets=\{question\.assets\} compact/);
  assert.equal(
    (PAGE.match(/<QuestionAssets assets=\{question\.assets\} placement="stem" eager \/>/g) ?? []).length,
    2,
  );
  assert.equal(
    (PAGE.match(/<QuestionAssets assets=\{question\.assets\} placement="options" eager \/>/g) ?? []).length,
    2,
  );
  assert.match(DRAFT, /assets:\s*assets\.length\s*\?\s*assets\s*:\s*undefined/);
  assert.ok((DRAFT.match(/normalizeQuestionAssets/g) ?? []).length >= 2);
});

test("renderer uses React image attributes and never injects asset HTML", () => {
  assert.match(COMPONENT, /<img/);
  assert.match(COMPONENT, /alt=\{asset\.altText\}/);
  assert.match(COMPONENT, /src=\{asset\.url\}/);
  assert.doesNotMatch(COMPONENT, /dangerouslySetInnerHTML/);
  assert.doesNotMatch(COMPONENT, /innerHTML/);
});
