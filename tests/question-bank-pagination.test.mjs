import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { loadTypeScriptModule } from "./load-typescript-module.mjs";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const PAGE = readFileSync(resolve(ROOT, "app", "page.tsx"), "utf8");
const CSS = readFileSync(resolve(ROOT, "app", "globals.css"), "utf8");
const {
  QUESTION_BANK_PAGE_SIZE,
  clampPaginationPage,
  paginationItems,
  paginationPageCount,
} = loadTypeScriptModule("lib/pagination.ts");

test("question bank uses a 50-item server page and computes page bounds", () => {
  assert.equal(QUESTION_BANK_PAGE_SIZE, 50);
  assert.equal(paginationPageCount(0, QUESTION_BANK_PAGE_SIZE), 1);
  assert.equal(paginationPageCount(40, QUESTION_BANK_PAGE_SIZE), 1);
  assert.equal(paginationPageCount(250, QUESTION_BANK_PAGE_SIZE), 5);
  assert.equal(paginationPageCount(251, QUESTION_BANK_PAGE_SIZE), 6);
  assert.equal(clampPaginationPage(0, 5), 1);
  assert.equal(clampPaginationPage(8, 5), 5);
});

test("large page counts expose nearby pages without an oversized control", () => {
  assert.deepEqual(paginationItems(1, 54), [1, 2, "ellipsis-end", 54]);
  assert.deepEqual(paginationItems(27, 54), [
    1,
    "ellipsis-start",
    26,
    27,
    28,
    "ellipsis-end",
    54,
  ]);
  assert.deepEqual(paginationItems(54, 54), [
    1,
    "ellipsis-start",
    53,
    54,
  ]);
});

test("question bank requests the selected server page and global search", () => {
  assert.match(PAGE, /limit:\s*String\(QUESTION_BANK_PAGE_SIZE\)/);
  assert.match(
    PAGE,
    /offset:\s*String\(\(bankPage\s*-\s*1\)\s*\*\s*QUESTION_BANK_PAGE_SIZE\)/,
  );
  assert.match(PAGE, /params\.set\(["']search["'],\s*search\)/);
  assert.match(PAGE, /maxLength=\{200\}/);
  assert.doesNotMatch(PAGE, /\.slice\(0,\s*30\)/);
  assert.match(PAGE, /bankOffset\s*\+\s*index\s*\+\s*1/);
});

test("filter changes reset pagination and stale requests are ignored", () => {
  assert.ok(
    (PAGE.match(/setBankPage\(1\)/g) ?? []).length >= 4,
    "course, topic, type, and search changes must reset to page one",
  );
  assert.match(PAGE, /requestId\s*!==\s*bankRequestId\.current/);
  assert.match(PAGE, /controller\.abort\(\)/);
  assert.match(PAGE, /setBankLoading\(false\)/);
});

test("pagination exposes an accessible current page and responsive layout", () => {
  assert.match(PAGE, /aria-label=["']Question bank pages["']/);
  assert.match(PAGE, /aria-current=\{item\s*===\s*bankPage\s*\?\s*["']page["']/);
  assert.match(PAGE, /Showing \$\{bankRangeStart\.toLocaleString\(\)\}/);
  assert.match(PAGE, /scrollIntoView/);
  assert.match(CSS, /\.bank-pagination\s*\{[^}]*display:\s*flex/s);
  assert.match(
    CSS,
    /\.bank-pagination button\s*\{[^}]*min-width:\s*44px[^}]*height:\s*44px/s,
  );
  assert.match(CSS, /\.bank-pagination\s*\{\s*flex-wrap:\s*wrap/s);
});

test("PYQ archive has independent 50-item filtering and pagination", () => {
  assert.match(PAGE, /library-tab-archive/);
  assert.match(PAGE, /fetch\(`\$\{API_BASE\}\/pyq-archive\?/);
  assert.match(
    PAGE,
    /offset:\s*String\(\(archivePage\s*-\s*1\)\s*\*\s*QUESTION_BANK_PAGE_SIZE\)/,
  );
  assert.match(PAGE, /params\.set\(["']subject_code["'],\s*archiveSubject\.code\)/);
  assert.match(PAGE, /params\.set\(["']topic_slug["'],\s*archiveTopicId\)/);
  assert.match(PAGE, /params\.set\(["']year["'],\s*archiveYear\)/);
  assert.match(PAGE, /params\.set\(["']item_type["'],\s*archiveType\)/);
  assert.ok(
    (PAGE.match(/setArchivePage\(1\)/g) ?? []).length >= 5,
    "course, topic, year, type and search must reset archive pagination",
  );
  assert.match(PAGE, /aria-label=["']PYQ archive pages["']/);
  assert.match(PAGE, /Archive practice is ungraded/);
  assert.match(PAGE, /never enter(?:s)? (?:full or course )?tests/i);
});

test("PYQ archive records ungraded synced coverage", () => {
  assert.match(PAGE, /fetchJson\("\/pyq-archive\/progress"/);
  assert.match(
    PAGE,
    /fetch\(`\$\{API_BASE\}\/pyq-archive\/\$\{archiveQuestion\.id\}\/practice`/,
  );
  assert.match(PAGE, /Archive coverage/);
  assert.match(PAGE, /Archive practised/);
  assert.match(PAGE, /archive-only records never enter tests or scored progress/);
});
