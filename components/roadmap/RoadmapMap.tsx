"use client";

import { useLayoutEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import type { Subject } from "@/app/data";
import {
  buildRoadmapGraph,
  recommendRoadmapCode,
  ROADMAP_EXAM_CODE,
  ROADMAP_GRAPH_STAGES,
  roadmapPrerequisiteLabel,
} from "@/lib/roadmap-graph";

type RoadmapMapProps = {
  subjects: Subject[];
  onOpenMock: () => void;
  onOpenSubject: (subject: Subject) => void;
};

type ConnectorGeometry = {
  width: number;
  height: number;
  paths: Array<{
    id: string;
    d: string;
    status: "ready" | "active" | "complete";
  }>;
};

const progressStatus = (progress: number) => {
  if (progress >= 100) return { key: "complete", label: "Complete" };
  if (progress > 0) return { key: "active", label: "In progress" };
  return { key: "ready", label: "Ready" };
};

export function RoadmapMap({ subjects, onOpenMock, onOpenSubject }: RoadmapMapProps) {
  const graph = useMemo(
    () => buildRoadmapGraph(subjects.map((subject) => subject.code)),
    [subjects],
  );
  const subjectByCode = useMemo(
    () => new Map(subjects.map((subject) => [subject.code, subject])),
    [subjects],
  );
  const progressByCode = useMemo(
    () =>
      Object.fromEntries(
        subjects.map((subject) => [subject.code, subject.progress]),
      ),
    [subjects],
  );
  const recommendedCode = useMemo(
    () => recommendRoadmapCode(graph.nodes, progressByCode),
    [graph.nodes, progressByCode],
  );
  const [focusedCode, setFocusedCode] = useState<string | null>(null);
  const focused =
    subjectByCode.get(focusedCode ?? "") ??
    subjectByCode.get(recommendedCode ?? "") ??
    subjects[0];
  const canvasRef = useRef<HTMLDivElement | null>(null);
  const nodeRefs = useRef(new Map<string, HTMLButtonElement>());
  const [connectorGeometry, setConnectorGeometry] =
    useState<ConnectorGeometry>({ width: 1, height: 1, paths: [] });

  const stages = useMemo(() => {
    const configured = ROADMAP_GRAPH_STAGES.map((stage) => ({
      ...stage,
      nodes: graph.nodes.filter((node) => node.level === stage.level),
    })).filter((stage) => stage.nodes.length > 0);
    const extraNodes = graph.nodes.filter(
      (node) => node.level >= ROADMAP_GRAPH_STAGES.length,
    );
    if (extraNodes.length) {
      configured.push({
        level: ROADMAP_GRAPH_STAGES.length,
        label: "Extend",
        description: "Additional syllabus areas remain open throughout the plan.",
        nodes: extraNodes,
      });
    }
    return configured;
  }, [graph.nodes]);

  useLayoutEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    let animationFrame = 0;
    let active = true;

    const scheduleMeasurement = () => {
      window.cancelAnimationFrame(animationFrame);
      animationFrame = window.requestAnimationFrame(() => {
        if (!active || !canvasRef.current) return;
        const canvasBounds = canvasRef.current.getBoundingClientRect();
        const paths = graph.edges.flatMap((edge) => {
          const fromElement =
            nodeRefs.current.get(edge.from) ??
            canvasRef.current?.querySelector<HTMLButtonElement>(
              `[data-code="${edge.from}"]`,
            );
          const toElement =
            nodeRefs.current.get(edge.to) ??
            canvasRef.current?.querySelector<HTMLButtonElement>(
              `[data-code="${edge.to}"]`,
            );
          if (!fromElement || !toElement) return [];
          const from = fromElement.getBoundingClientRect();
          const to = toElement.getBoundingClientRect();
          const outgoingEdges = graph.edges.filter(
            (candidate) => candidate.from === edge.from,
          );
          const incomingEdges = graph.edges.filter(
            (candidate) => candidate.to === edge.to,
          );
          const outgoingIndex = outgoingEdges.findIndex(
            (candidate) => candidate.to === edge.to,
          );
          const incomingIndex = incomingEdges.findIndex(
            (candidate) => candidate.from === edge.from,
          );
          const anchorX = (
            bounds: DOMRect,
            index: number,
            count: number,
            maximumGap = 42,
          ) => {
            const center = bounds.left + bounds.width / 2 - canvasBounds.left;
            if (count <= 1) return center;
            const gap = Math.min(maximumGap, bounds.width / (count + 1));
            return center + (index - (count - 1) / 2) * gap;
          };
          const startX = anchorX(from, outgoingIndex, outgoingEdges.length);
          const startY = from.bottom - canvasBounds.top;
          const endX = anchorX(
            to,
            incomingIndex,
            incomingEdges.length,
            edge.to === ROADMAP_EXAM_CODE ? 62 : 42,
          );
          const endY = to.top - canvasBounds.top;
          const fromSubject = subjectByCode.get(edge.from);
          const toSubject = subjectByCode.get(edge.to);
          const status: ConnectorGeometry["paths"][number]["status"] =
            (fromSubject?.progress ?? 0) >= 100 &&
            (edge.to === ROADMAP_EXAM_CODE || (toSubject?.progress ?? 0) >= 100)
              ? "complete"
              : (fromSubject?.progress ?? 0) > 0 || (toSubject?.progress ?? 0) > 0
                ? "active"
                : "ready";
          let d: string;
          if (edge.route === "rail") {
            const railX = Math.max(startX + 24, canvasBounds.width - 10);
            const leaveY = Math.min(startY + 42, endY - 48);
            const enterY = Math.max(endY - 38, leaveY);
            d = `M ${startX} ${startY} C ${startX} ${leaveY} ${railX} ${leaveY} ${railX} ${leaveY} L ${railX} ${enterY} C ${railX} ${endY - 12} ${endX} ${endY - 18} ${endX} ${endY}`;
          } else {
            const horizontalDistance = Math.abs(endX - startX);
            if (horizontalDistance < 3) {
              d = `M ${startX} ${startY} L ${endX} ${endY}`;
            } else {
              const direction = endX > startX ? 1 : -1;
              const channelOffset = Math.max(0, incomingIndex) * 8;
              const channelY = Math.max(startY + 22, endY - 28 - channelOffset);
              const corner = Math.min(10, horizontalDistance / 3);
              d = `M ${startX} ${startY} L ${startX} ${channelY - corner} Q ${startX} ${channelY} ${startX + direction * corner} ${channelY} L ${endX - direction * corner} ${channelY} Q ${endX} ${channelY} ${endX} ${channelY + corner} L ${endX} ${endY}`;
            }
          }
          return [{ id: `${edge.from}-${edge.to}`, d, status }];
        });
        setConnectorGeometry({
          width: Math.max(1, Math.round(canvasBounds.width)),
          height: Math.max(1, Math.round(canvasBounds.height)),
          paths,
        });
      });
    };

    scheduleMeasurement();
    const resizeObserver = new ResizeObserver(scheduleMeasurement);
    resizeObserver.observe(canvas);
    canvas
      .querySelectorAll<HTMLButtonElement>("[data-code]")
      .forEach((node) => resizeObserver.observe(node));
    window.addEventListener("resize", scheduleMeasurement);
    void document.fonts?.ready.then(scheduleMeasurement);
    return () => {
      active = false;
      window.cancelAnimationFrame(animationFrame);
      resizeObserver.disconnect();
      window.removeEventListener("resize", scheduleMeasurement);
    };
  }, [graph.edges, subjectByCode]);

  const overallProgress = subjects.length
    ? Math.round(
        subjects.reduce((total, subject) => total + subject.progress, 0) /
          subjects.length,
      )
    : 0;

  if (!focused) return null;
  const focusedStatus = progressStatus(focused.progress);
  const nextTopic =
    focused.topics.find((topic) => topic.progress < 100) ?? focused.topics[0];
  const sequenceByCode = new Map(
    graph.nodes.map((node, index) => [node.code, index + 1]),
  );
  const isExamRecommended = recommendedCode === ROADMAP_EXAM_CODE;

  return (
    <div className="roadmap-map-shell">
      <div className="roadmap-map-toolbar">
        <div>
          <span className="map-overline">GATE CSE · prerequisite map</span>
          <strong>{overallProgress}% of the syllabus mastered</strong>
        </div>
        <div className="map-legend" aria-label="Roadmap status legend">
          <span><i className="complete" /> Complete</span>
          <span><i className="active" /> In progress</span>
          <span><i /> Ready</span>
        </div>
      </div>

      <div className="roadmap-map-layout">
        <div
          aria-label="GATE CSE recommended prerequisite roadmap"
          className="roadmap-graph-panel"
          role="region"
        >
          <div className="roadmap-graph-note">
            <span aria-hidden="true">↳</span>
            <p><strong>Follow the dependencies, not a lock.</strong> Every course remains available whenever you need it.</p>
          </div>
          <div className="roadmap-graph-canvas" ref={canvasRef}>
            <svg
              aria-hidden="true"
              className="roadmap-connectors"
              focusable="false"
              preserveAspectRatio="none"
              viewBox={`0 0 ${connectorGeometry.width} ${connectorGeometry.height}`}
            >
              <defs>
                {(["ready", "active", "complete"] as const).map((status) => (
                  <marker
                    id={`roadmap-arrow-${status}`}
                    key={status}
                    markerHeight="9"
                    markerUnits="userSpaceOnUse"
                    markerWidth="9"
                    orient="auto"
                    refX="8"
                    refY="4.5"
                  >
                    <path
                      className={`roadmap-arrow ${status}`}
                      d="M 0 0 L 9 4.5 L 0 9 z"
                    />
                  </marker>
                ))}
              </defs>
              {connectorGeometry.paths.map((path) => (
                <path
                  className={`roadmap-connector ${path.status}`}
                  d={path.d}
                  key={path.id}
                  markerEnd={`url(#roadmap-arrow-${path.status})`}
                  vectorEffect="non-scaling-stroke"
                />
              ))}
            </svg>

            <div className="roadmap-levels">
              {stages.map((stage, stageIndex) => {
                const headingId = `roadmap-stage-${stage.level}`;
                return (
                  <section
                    aria-labelledby={headingId}
                    className="roadmap-level"
                    key={stage.level}
                  >
                    <header className="roadmap-level-heading">
                      <span>{String(stageIndex + 1).padStart(2, "0")}</span>
                      <div>
                        <h3 id={headingId}>{stage.label}</h3>
                        <p>{stage.description}</p>
                      </div>
                    </header>
                    <ol
                      aria-label={`${stage.label} roadmap subjects`}
                      className="roadmap-level-nodes"
                    >
                      {stage.nodes.map((node) => {
                        const subject = subjectByCode.get(node.code);
                        if (!subject) return null;
                        const status = progressStatus(subject.progress);
                        const isRecommended = node.code === recommendedCode;
                        const prerequisiteLabel = roadmapPrerequisiteLabel(node);
                        return (
                          <li
                            key={node.code}
                            style={{ "--roadmap-column": node.column } as CSSProperties}
                          >
                            <button
                              aria-current={isRecommended ? "step" : undefined}
                              aria-label={`${subject.title}. ${status.label}. ${subject.progress}% complete. ${prerequisiteLabel}.`}
                              className={`route-node ${status.key} ${focused.code === subject.code ? "focused" : ""}`}
                              data-code={subject.code}
                              onClick={() => onOpenSubject(subject)}
                              onFocus={() => setFocusedCode(subject.code)}
                              onMouseEnter={() => setFocusedCode(subject.code)}
                              ref={(element) => {
                                if (element) nodeRefs.current.set(subject.code, element);
                                else nodeRefs.current.delete(subject.code);
                              }}
                              style={{ "--subject-accent": subject.accent } as CSSProperties}
                            >
                              <span className="route-node-marker">
                                <b>{subject.code}</b>
                                <i aria-hidden="true">
                                  {status.key === "complete"
                                    ? "✓"
                                    : String(sequenceByCode.get(subject.code) ?? 0).padStart(2, "0")}
                                </i>
                              </span>
                              <span className="route-node-copy">
                                <strong>{subject.shortTitle}</strong>
                                <small>{subject.topics.length} chapters · {status.label}</small>
                              </span>
                              <span className="route-prerequisites">
                                <span aria-hidden="true">↳</span> {prerequisiteLabel}
                              </span>
                              <span aria-hidden="true" className="route-node-progress">
                                <i style={{ width: `${subject.progress}%` }} />
                              </span>
                              {isRecommended ? <em>Continue</em> : null}
                            </button>
                          </li>
                        );
                      })}
                    </ol>
                  </section>
                );
              })}
            </div>

            <div className="roadmap-summit">
              <button
                aria-label="Open full mock exam, the final roadmap step"
                aria-current={isExamRecommended ? "step" : undefined}
                className={isExamRecommended ? "recommended" : undefined}
                data-code={ROADMAP_EXAM_CODE}
                onClick={onOpenMock}
                ref={(element) => {
                  if (element) nodeRefs.current.set(ROADMAP_EXAM_CODE, element);
                  else nodeRefs.current.delete(ROADMAP_EXAM_CODE);
                }}
              >
                <span aria-hidden="true">◆</span>
                <span><strong>Exam summit</strong><small>65 questions · 180 minutes</small></span>
                <b>Open full mock →</b>
                {isExamRecommended ? <em>Next</em> : null}
              </button>
            </div>
          </div>
        </div>

        <aside
          aria-label={`${focused.title} roadmap details`}
          className="roadmap-inspector"
          style={{ "--subject-accent": focused.accent } as CSSProperties}
        >
          <div className="inspector-status">
            <span>{focusedStatus.label}</span>
            <strong>{focused.progress}%</strong>
          </div>
          <div className="inspector-code">{focused.code}</div>
          <h3>{focused.title}</h3>
          <p>{focused.description}</p>
          <dl>
            <div><dt>Chapters</dt><dd>{focused.topics.length}</dd></div>
            <div><dt>Questions</dt><dd>{focused.questionCount}</dd></div>
            <div><dt>Mapped time</dt><dd>{focused.estimatedHours}h</dd></div>
          </dl>
          <div className="inspector-next">
            <span>Next chapter</span>
            <strong>{nextTopic?.title ?? "Course review"}</strong>
            <small>{nextTopic?.progress ?? 0}% complete</small>
          </div>
          <button className="button primary full" onClick={() => onOpenSubject(focused)}>
            Open {focused.code} workspace <span aria-hidden="true">→</span>
          </button>
          <small className="inspector-hint">Every course is open. The route is guidance, not a lock.</small>
        </aside>
      </div>
    </div>
  );
}
