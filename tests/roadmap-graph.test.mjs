import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import test from "node:test";
import { fileURLToPath } from "node:url";
import ts from "typescript";

import { loadTypeScriptModule } from "./load-typescript-module.mjs";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const GRAPH = loadTypeScriptModule("lib/roadmap-graph.ts");
const COMPONENT_SOURCE = readFileSync(
  resolve(ROOT, "components", "roadmap", "RoadmapMap.tsx"),
  "utf8",
);
const CSS = readFileSync(resolve(ROOT, "app", "globals.css"), "utf8");

const CANONICAL_CODES = [
  "EM",
  "PDS",
  "DL",
  "GA",
  "ALG",
  "TOC",
  "COA",
  "CD",
  "OS",
  "DBMS",
  "CN",
];
const CANONICAL_EDGES = [
  "ALG->CN",
  "ALG->DBMS",
  "CD->EXAM",
  "CN->EXAM",
  "COA->OS",
  "DBMS->EXAM",
  "DL->COA",
  "EM->ALG",
  "GA->EXAM",
  "OS->CN",
  "OS->DBMS",
  "PDS->ALG",
  "PDS->TOC",
  "TOC->CD",
];

function edgeKey(edge) {
  return `${edge.from}->${edge.to}`;
}

function assertValidDag(nodes, edges) {
  const exam = GRAPH.ROADMAP_EXAM_CODE;
  const codes = new Set(nodes.map((node) => node.code));
  assert.equal(codes.size, nodes.length, "graph node codes must be unique");
  const edgeKeys = edges.map(edgeKey);
  assert.equal(new Set(edgeKeys).size, edgeKeys.length, "graph edges must be unique");

  for (const edge of edges) {
    assert.ok(codes.has(edge.from), `edge starts at missing node ${edge.from}`);
    assert.ok(edge.to === exam || codes.has(edge.to), `edge ends at missing node ${edge.to}`);
    assert.notEqual(edge.from, edge.to, `self dependency ${edgeKey(edge)} is invalid`);
  }

  const outgoing = new Map([...codes, exam].map((code) => [code, []]));
  for (const edge of edges) outgoing.get(edge.from).push(edge.to);
  const visiting = new Set();
  const visited = new Set();
  const visit = (code) => {
    if (visiting.has(code)) throw new Error(`dependency cycle includes ${code}`);
    if (visited.has(code)) return;
    visiting.add(code);
    for (const next of outgoing.get(code) ?? []) visit(next);
    visiting.delete(code);
    visited.add(code);
  };
  for (const code of outgoing.keys()) visit(code);
}

function loadRoadmapComponent() {
  const filename = resolve(ROOT, "components", "roadmap", "RoadmapMap.tsx");
  const output = ts.transpileModule(COMPONENT_SOURCE, {
    compilerOptions: {
      esModuleInterop: true,
      jsx: ts.JsxEmit.ReactJSX,
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
    fileName: filename,
  }).outputText;
  const loaded = { exports: {} };
  const nativeRequire = createRequire(filename);
  const scopedRequire = (specifier) =>
    specifier === "@/lib/roadmap-graph" ? GRAPH : nativeRequire(specifier);
  const execute = new Function(
    "require",
    "module",
    "exports",
    "__filename",
    "__dirname",
    output,
  );
  execute(scopedRequire, loaded, loaded.exports, filename, dirname(filename));
  return loaded.exports.RoadmapMap;
}

const RoadmapMap = loadRoadmapComponent();

function subject(code, progress = 0) {
  return {
    id: code.toLowerCase(),
    code,
    title: `${code} full course`,
    shortTitle: `${code} course`,
    description: `${code} course description`,
    progress,
    mastery: progress,
    questionCount: 30,
    estimatedHours: 4,
    accent: "#666666",
    phase: "Foundations",
    topics: [
      {
        id: `${code.toLowerCase()}-topic`,
        title: `${code} first topic`,
        progress,
        questions: 30,
        duration: "1h",
      },
    ],
    note: {
      title: "",
      summary: "",
      intuition: "",
      formula: "",
      formulaHint: "",
      exampleTitle: "",
      exampleSteps: [],
      checkpoint: [],
      traps: [],
    },
  };
}

function renderRoadmap(subjects) {
  return renderToStaticMarkup(
    React.createElement(RoadmapMap, {
      subjects,
      onOpenMock() {},
      onOpenSubject() {},
    }),
  );
}

function cssRule(source, selector) {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = source.match(new RegExp(`${escaped}\\s*\\{([\\s\\S]*?)\\}`));
  assert.ok(match, `missing CSS rule for ${selector}`);
  return match[1];
}

test("canonical roadmap codes and prerequisite edges remain intentional", () => {
  assert.deepEqual(
    GRAPH.ROADMAP_GRAPH_NODES.map((node) => node.code),
    CANONICAL_CODES,
  );
  assert.deepEqual(
    GRAPH.ROADMAP_GRAPH_EDGES.map(edgeKey).sort(),
    [...CANONICAL_EDGES].sort(),
  );

  const byCode = new Map(GRAPH.ROADMAP_GRAPH_NODES.map((node) => [node.code, node]));
  for (const node of GRAPH.ROADMAP_GRAPH_NODES) {
    for (const prerequisite of node.prerequisites) {
      assert.ok(byCode.has(prerequisite), `${node.code} has unknown prerequisite ${prerequisite}`);
      assert.ok(
        byCode.get(prerequisite).level < node.level,
        `${prerequisite} must be positioned above ${node.code}`,
      );
    }
  }
});

test("canonical roadmap is a DAG and every course has a path to EXAM", () => {
  const nodes = GRAPH.ROADMAP_GRAPH_NODES;
  const edges = GRAPH.ROADMAP_GRAPH_EDGES;
  assertValidDag(nodes, edges);

  const outgoing = new Map(nodes.map((node) => [node.code, []]));
  for (const edge of edges) outgoing.get(edge.from)?.push(edge.to);
  const reachesExam = (code, seen = new Set()) => {
    if (code === GRAPH.ROADMAP_EXAM_CODE) return true;
    if (seen.has(code)) return false;
    const nextSeen = new Set(seen).add(code);
    return (outgoing.get(code) ?? []).some((next) => reachesExam(next, nextSeen));
  };
  for (const node of nodes) {
    assert.ok(reachesExam(node.code), `${node.code} has no route to EXAM`);
  }
});

test("partial and unknown course collections build safe deterministic graphs", () => {
  assert.deepEqual(GRAPH.buildRoadmapGraph([]), { nodes: [], edges: [] });

  const partial = GRAPH.buildRoadmapGraph(["ALG", "PDS", "EXTRA-B", "PDS", "", "EXTRA-A"]);
  assert.deepEqual(
    partial.nodes.map((node) => node.code),
    ["PDS", "ALG", "EXTRA-A", "EXTRA-B"],
  );
  assert.deepEqual(
    partial.nodes.find((node) => node.code === "ALG").prerequisites,
    ["PDS"],
  );
  assert.deepEqual(
    partial.nodes.filter((node) => node.code.startsWith("EXTRA-")).map((node) => ({
      code: node.code,
      parallel: node.parallel,
      level: node.level,
    })),
    [
      { code: "EXTRA-A", parallel: true, level: GRAPH.ROADMAP_GRAPH_STAGES.length },
      { code: "EXTRA-B", parallel: true, level: GRAPH.ROADMAP_GRAPH_STAGES.length },
    ],
  );
  assertValidDag(partial.nodes, partial.edges);
  for (const code of ["EXTRA-A", "EXTRA-B"]) {
    assert.ok(
      partial.edges.some(
        (edge) => edge.from === code && edge.to === GRAPH.ROADMAP_EXAM_CODE && edge.route === "rail",
      ),
      `${code} must remain connected to EXAM`,
    );
  }

  const isolated = GRAPH.buildRoadmapGraph(["ALG"]);
  assert.deepEqual(isolated.edges.map(edgeKey), ["ALG->EXAM"]);
});

test("recommendation continues active work then selects the first dependency-ready course", () => {
  const nodes = GRAPH.buildRoadmapGraph(["EM", "PDS", "ALG"]).nodes;
  assert.equal(
    GRAPH.recommendRoadmapCode(nodes, { ALG: 35 }),
    "ALG",
    "an active course should remain the continuation target",
  );
  assert.equal(
    GRAPH.recommendRoadmapCode(nodes, { EM: 100, PDS: 0, ALG: 0 }),
    "PDS",
    "blocked ALG must not be recommended before PDS",
  );
  assert.equal(
    GRAPH.recommendRoadmapCode(nodes, { EM: 100, PDS: 100, ALG: 0 }),
    "ALG",
  );
  assert.equal(
    GRAPH.recommendRoadmapCode(nodes, { EM: 100, PDS: 100, ALG: 100 }),
    GRAPH.ROADMAP_EXAM_CODE,
    "a completed roadmap should promote the full mock instead of a finished course",
  );
  assert.equal(GRAPH.recommendRoadmapCode([], {}), undefined);
});

test("a fully completed roadmap marks only the exam summit as the next step", () => {
  const html = renderRoadmap(
    CANONICAL_CODES.map((code) => subject(code, 100)),
  );
  assert.equal((html.match(/aria-current="step"/g) ?? []).length, 1);
  assert.match(
    html,
    /aria-label="Open full mock exam, the final roadmap step" aria-current="step" class="recommended"/,
  );
  assert.doesNotMatch(html, /class="route-node[^"]*"[^>]*aria-current="step"/);
});

test("rendered graph preserves topological DOM order and accessible dependency context", () => {
  const html = renderRoadmap(CANONICAL_CODES.map((code) => subject(code)));
  assert.match(html, /role="region"/);
  assert.match(html, /aria-label="GATE CSE recommended prerequisite roadmap"/);
  assert.match(html, /<svg[^>]*aria-hidden="true"[^>]*focusable="false"/);
  assert.equal((html.match(/aria-current="step"/g) ?? []).length, 1);
  assert.equal((html.match(/data-code="[^"]+"/g) ?? []).length, CANONICAL_CODES.length + 1);
  assert.doesNotMatch(html, /data-code="[^"]+"[^>]*disabled/);

  let previousPosition = -1;
  for (const code of [...CANONICAL_CODES, GRAPH.ROADMAP_EXAM_CODE]) {
    const position = html.indexOf(`data-code="${code}"`);
    assert.ok(position > previousPosition, `${code} is out of topological keyboard order`);
    previousPosition = position;
  }
  assert.match(html, /aria-labelledby="roadmap-stage-0"/);
  assert.match(html, /aria-label="Start roadmap subjects"/);
  assert.match(html, /EM full course\. Ready\. 0% complete\. Start here\./);
  assert.match(html, /ALG full course\. Ready\. 0% complete\. Builds on EM \+ PDS\./);
  assert.match(html, /GA full course\. Ready\. 0% complete\. Parallel track · practise throughout\./);
  assert.match(html, /aria-label="Open full mock exam, the final roadmap step"/);
  assert.match(html, /aria-label="EM full course roadmap details"/);
});

test("component source keeps connectors decorative and cleans up layout observers", () => {
  assert.match(COMPONENT_SOURCE, /aria-hidden="true"[\s\S]*?className="roadmap-connectors"/);
  assert.match(COMPONENT_SOURCE, /focusable="false"/);
  assert.match(COMPONENT_SOURCE, /pointer-events:\s*none|roadmap-connectors/);
  assert.match(COMPONENT_SOURCE, /new ResizeObserver\(scheduleMeasurement\)/);
  assert.match(COMPONENT_SOURCE, /resizeObserver\.disconnect\(\)/);
  assert.match(COMPONENT_SOURCE, /window\.removeEventListener\("resize", scheduleMeasurement\)/);
  assert.match(COMPONENT_SOURCE, /Every course remains available/);
});

test("responsive CSS collapses the dependency graph to one readable mobile column", () => {
  const connectorRule = cssRule(CSS, ".roadmap-connectors");
  assert.match(connectorRule, /pointer-events\s*:\s*none/);
  const panelRule = cssRule(CSS, ".roadmap-graph-panel");
  assert.match(panelRule, /min-width\s*:\s*0/);

  const mobileStart = CSS.indexOf("@media (max-width: 720px)");
  const mobileEnd = CSS.indexOf("@media (max-width: 430px)", mobileStart);
  assert.ok(mobileStart >= 0 && mobileEnd > mobileStart, "missing mobile roadmap breakpoint");
  const mobile = CSS.slice(mobileStart, mobileEnd);
  assert.match(
    mobile,
    /\.roadmap-level-nodes\s*\{[\s\S]*?grid-template-columns\s*:\s*1fr\s*;/,
    "mobile roadmap levels must collapse to one column",
  );
  assert.match(
    mobile,
    /\.roadmap-level-nodes\s*>\s*li\s*\{[\s\S]*?grid-column\s*:\s*1(?:\s*!important)?\s*;/,
    "mobile nodes must ignore desktop column coordinates",
  );
  assert.match(
    mobile,
    /\.roadmap-connectors\s*\{[\s\S]*?display\s*:\s*none\s*;/,
    "mobile layout must replace measured connectors with the compact spine",
  );
  assert.match(
    mobile,
    /\.roadmap-graph-canvas::before\s*\{[\s\S]*?content\s*:\s*["']{2}\s*;/,
    "mobile layout must retain a visible dependency spine",
  );
  assert.match(
    mobile,
    /\.roadmap-summit\s*\{[\s\S]*?width\s*:\s*(?:100%|auto)\s*;/,
    "mobile exam summit must fit the viewport",
  );
});
