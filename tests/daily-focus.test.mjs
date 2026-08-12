import assert from "node:assert/strict";
import test from "node:test";
import { loadTypeScriptModule } from "./load-typescript-module.mjs";

const {
  istDayNumber,
  millisecondsUntilNextIstMidnight,
  selectDailyFocus,
} = loadTypeScriptModule("lib/daily-focus.ts");

const candidates = Array.from({ length: 64 }, (_, index) => ({
  key: `topic-${String(index).padStart(2, "0")}`,
}));

test("IST day changes at exactly 00:00:00 India time", () => {
  const before = Date.parse("2026-08-11T18:29:59.999Z");
  const boundary = Date.parse("2026-08-11T18:30:00.000Z");

  assert.equal(istDayNumber(boundary), istDayNumber(before) + 1);
  assert.equal(millisecondsUntilNextIstMidnight(before), 1);
  assert.equal(millisecondsUntilNextIstMidnight(boundary), 86_400_000);
});

test("daily selection is deterministic and input-order independent", () => {
  const day = istDayNumber(Date.parse("2026-08-12T08:00:00.000Z"));
  const selected = selectDailyFocus(candidates, day);

  assert.deepEqual(selectDailyFocus(candidates, day), selected);
  assert.deepEqual(selectDailyFocus([...candidates].reverse(), day), selected);
});

test("every topic appears exactly once in each syllabus cycle", () => {
  const cycleStart = candidates.length * 12;
  const selectedKeys = Array.from({ length: candidates.length }, (_, offset) =>
    selectDailyFocus(candidates, cycleStart + offset)?.key,
  );

  assert.equal(new Set(selectedKeys).size, candidates.length);
  assert.deepEqual([...selectedKeys].sort(), candidates.map(({ key }) => key));
});

test("a cycle boundary never repeats yesterday's focus", () => {
  for (let cycle = 1; cycle < 30; cycle += 1) {
    const boundary = cycle * candidates.length;
    assert.notEqual(
      selectDailyFocus(candidates, boundary - 1)?.key,
      selectDailyFocus(candidates, boundary)?.key,
    );
  }
});

test("empty and one-topic pools behave safely", () => {
  assert.equal(selectDailyFocus([], 20_000), null);
  assert.equal(selectDailyFocus([{ key: "only" }], 20_000)?.key, "only");
});
