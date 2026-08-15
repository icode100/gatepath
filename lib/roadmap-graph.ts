export const ROADMAP_EXAM_CODE = "EXAM" as const;

export type RoadmapGraphNode = {
  code: string;
  level: number;
  column: number;
  prerequisites: readonly string[];
  parallel?: boolean;
};

export type RoadmapGraphEdge = {
  from: string;
  to: string;
  route?: "rail";
};

export type RoadmapGraphStage = {
  level: number;
  label: string;
  description: string;
};

export const ROADMAP_GRAPH_STAGES: readonly RoadmapGraphStage[] = [
  {
    level: 0,
    label: "Start",
    description: "Build the foundations that unlock the rest of the syllabus.",
  },
  {
    level: 1,
    label: "Build",
    description: "Turn the foundations into core CS reasoning skills.",
  },
  {
    level: 2,
    label: "Specialise",
    description: "Follow the language and computer-systems branches.",
  },
  {
    level: 3,
    label: "Integrate",
    description: "Combine algorithms and systems knowledge in applied subjects.",
  },
] as const;

export const ROADMAP_GRAPH_NODES: readonly RoadmapGraphNode[] = [
  { code: "EM", level: 0, column: 1, prerequisites: [] },
  { code: "PDS", level: 0, column: 2, prerequisites: [] },
  { code: "DL", level: 0, column: 3, prerequisites: [] },
  {
    code: "GA",
    level: 0,
    column: 4,
    prerequisites: [],
    parallel: true,
  },
  { code: "ALG", level: 1, column: 1, prerequisites: ["EM", "PDS"] },
  { code: "TOC", level: 1, column: 2, prerequisites: ["PDS"] },
  { code: "COA", level: 1, column: 3, prerequisites: ["DL"] },
  { code: "CD", level: 2, column: 2, prerequisites: ["TOC"] },
  { code: "OS", level: 2, column: 3, prerequisites: ["COA"] },
  { code: "DBMS", level: 3, column: 1, prerequisites: ["ALG", "OS"] },
  { code: "CN", level: 3, column: 3, prerequisites: ["ALG", "OS"] },
] as const;

const TERMINAL_CODES = ["CD", "DBMS", "CN", "GA"] as const;

export const ROADMAP_GRAPH_EDGES: readonly RoadmapGraphEdge[] = [
  ...ROADMAP_GRAPH_NODES.flatMap((node) =>
    node.prerequisites.map((from) => ({ from, to: node.code })),
  ),
  ...TERMINAL_CODES.map((from) => ({
    from,
    to: ROADMAP_EXAM_CODE,
    route: from === "GA" ? ("rail" as const) : undefined,
  })),
];

export function buildRoadmapGraph(codes: readonly string[]) {
  const uniqueCodes = [...new Set(codes.filter(Boolean))];
  const available = new Set(uniqueCodes);
  const configuredCodes = new Set(ROADMAP_GRAPH_NODES.map((node) => node.code));
  const configuredNodes = ROADMAP_GRAPH_NODES.filter((node) =>
    available.has(node.code),
  ).map((node) => ({
    ...node,
    prerequisites: node.prerequisites.filter((code) => available.has(code)),
  }));
  const extraNodes = uniqueCodes
    .filter((code) => !configuredCodes.has(code))
    .sort()
    .map((code, index) => ({
      code,
      level: ROADMAP_GRAPH_STAGES.length,
      column: (index % 4) + 1,
      prerequisites: [] as readonly string[],
      parallel: true,
    }));
  const nodes = [...configuredNodes, ...extraNodes];
  const graphCodes = new Set(nodes.map((node) => node.code));
  const edges = ROADMAP_GRAPH_EDGES.filter(
    (edge) =>
      graphCodes.has(edge.from) &&
      (edge.to === ROADMAP_EXAM_CODE || graphCodes.has(edge.to)),
  );

  const connectedSources = new Set(edges.map((edge) => edge.from));
  nodes.forEach((node) => {
    if (connectedSources.has(node.code)) return;
    edges.push({
      from: node.code,
      to: ROADMAP_EXAM_CODE,
      route: node.parallel ? "rail" : undefined,
    });
  });

  return { nodes, edges };
}

export function roadmapPrerequisiteLabel(node: RoadmapGraphNode) {
  if (node.parallel) return "Parallel track · practise throughout";
  if (!node.prerequisites.length) return "Start here";
  return `Builds on ${node.prerequisites.join(" + ")}`;
}

export function recommendRoadmapCode(
  nodes: readonly RoadmapGraphNode[],
  progressByCode: Readonly<Record<string, number>>,
) {
  const active = nodes.find((node) => {
    const progress = progressByCode[node.code] ?? 0;
    return progress > 0 && progress < 100;
  });
  if (active) return active.code;

  const ready = nodes.find(
    (node) =>
      (progressByCode[node.code] ?? 0) < 100 &&
      node.prerequisites.every(
        (code) => (progressByCode[code] ?? 0) >= 100,
      ),
  );
  if (ready) return ready.code;

  const incomplete = nodes.find(
    (node) => (progressByCode[node.code] ?? 0) < 100,
  );
  if (incomplete) return incomplete.code;
  return nodes.length ? ROADMAP_EXAM_CODE : undefined;
}
