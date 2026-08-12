"use client";

import { useMemo, useState } from "react";
import type { CSSProperties } from "react";
import type { Subject } from "@/app/data";

type RoadmapMapProps = {
  subjects: Subject[];
  onOpenMock: () => void;
  onOpenSubject: (subject: Subject) => void;
};

const PHASES = ["Foundations", "Core reasoning", "Systems"] as const;

const progressStatus = (progress: number) => {
  if (progress >= 100) return { key: "complete", label: "Complete" };
  if (progress > 0) return { key: "active", label: "In progress" };
  return { key: "ready", label: "Ready" };
};

export function RoadmapMap({ subjects, onOpenMock, onOpenSubject }: RoadmapMapProps) {
  const recommended = useMemo(
    () =>
      subjects.find((subject) => subject.progress > 0 && subject.progress < 100) ??
      subjects.find((subject) => subject.progress < 100) ??
      subjects[0],
    [subjects],
  );
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const focused =
    subjects.find((subject) => subject.id === focusedId) ?? recommended;
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

  return (
    <div className="roadmap-map-shell">
      <div className="roadmap-map-toolbar">
        <div>
          <span className="map-overline">GATE CSE · recommended sequence</span>
          <strong>{overallProgress}% of the syllabus mastered</strong>
        </div>
        <div className="map-legend" aria-label="Roadmap status legend">
          <span><i className="complete" /> Complete</span>
          <span><i className="active" /> In progress</span>
          <span><i /> Ready</span>
        </div>
      </div>

      <div className="roadmap-map-layout">
        <ol className="roadmap-route" aria-label="GATE CSE subject roadmap">
          {PHASES.map((phase, phaseIndex) => {
            const phaseSubjects = subjects.filter((subject) => subject.phase === phase);
            return (
              <li className={`route-stage stage-${phaseIndex + 1}`} key={phase}>
                <div className="route-stage-heading">
                  <span>{String(phaseIndex + 1).padStart(2, "0")}</span>
                  <div>
                    <strong>{phase}</strong>
                    <small>{phaseSubjects.length} courses</small>
                  </div>
                </div>
                <ol className="route-nodes">
                  {phaseSubjects.map((subject, subjectIndex) => {
                    const status = progressStatus(subject.progress);
                    const isRecommended = subject.id === recommended.id;
                    return (
                      <li key={subject.id}>
                        <button
                          aria-current={isRecommended ? "step" : undefined}
                          aria-label={`${subject.title}, ${status.label}, ${subject.progress}% complete`}
                          className={`route-node ${status.key} ${focused.id === subject.id ? "focused" : ""}`}
                          onClick={() => onOpenSubject(subject)}
                          onFocus={() => setFocusedId(subject.id)}
                          onMouseEnter={() => setFocusedId(subject.id)}
                          style={{ "--subject-accent": subject.accent } as CSSProperties}
                        >
                          <span className="route-node-marker">
                            <b>{subject.code}</b>
                            <i aria-hidden="true">{status.key === "complete" ? "✓" : subjectIndex + 1}</i>
                          </span>
                          <span className="route-node-copy">
                            <strong>{subject.shortTitle}</strong>
                            <small>{subject.topics.length} chapters · {status.label}</small>
                          </span>
                          <span
                            aria-valuemax={100}
                            aria-valuemin={0}
                            aria-valuenow={subject.progress}
                            className="route-node-progress"
                            role="progressbar"
                          >
                            <i style={{ width: `${subject.progress}%` }} />
                          </span>
                          {isRecommended ? <em>Continue</em> : null}
                        </button>
                      </li>
                    );
                  })}
                </ol>
              </li>
            );
          })}
          <li className="route-finish">
            <button onClick={onOpenMock}>
              <span aria-hidden="true">◆</span>
              <span><strong>Exam summit</strong><small>65 questions · 180 minutes</small></span>
              <b>Open full mock →</b>
            </button>
          </li>
        </ol>

        <aside
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
