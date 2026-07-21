"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  buildMockQuestions,
  practiceQuestions,
  subjects as localSubjects,
  weeklyActivity,
  type PracticeQuestion,
  type QuestionType,
  type Subject,
} from "./data";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "/api/v1";

const API_SUBJECT_SLUGS: Record<string, string> = {
  "computer-organization": "computer-organization-and-architecture",
  "programming-data-structures": "programming-and-data-structures",
  "theory-computation": "theory-of-computation",
};

const apiSubjectSlug = (subjectId: string) =>
  API_SUBJECT_SLUGS[subjectId] ?? subjectId;

type Screen =
  | "dashboard"
  | "subject"
  | "notes"
  | "practice"
  | "mock-setup"
  | "mock"
  | "results"
  | "progress";
type Theme = "light" | "dark";
type ApiState = "checking" | "online" | "offline";
type PracticeMode = "practice" | "sectional";
type Answers = Record<string, string[]>;

type RemoteRoadmap = {
  slug?: string;
  code?: string;
  name?: string;
  question_count?: number;
  attempted_questions?: number;
  accuracy?: number;
  topics?: Array<{
    slug?: string;
    name?: string;
    question_count?: number;
    attempted_questions?: number;
    accuracy?: number;
  }>;
};

type ServerResult = {
  score: number;
  maxScore: number;
  percentage: number;
  correct: number;
  incorrect: number;
  unanswered: number;
};

function mergeRoadmap(payload: unknown): Subject[] {
  if (!payload || typeof payload !== "object") return localSubjects;
  const source = payload as { subjects?: RemoteRoadmap[] };
  if (!Array.isArray(source.subjects) || source.subjects.length === 0) {
    return localSubjects;
  }

  return localSubjects.map((fallback) => {
    const remote = source.subjects?.find(
      (item) => item.slug === fallback.id || item.code === fallback.code,
    );
    if (!remote) return fallback;
    const attempted = remote.attempted_questions ?? 0;
    const total = remote.question_count ?? fallback.questionCount;
    return {
      ...fallback,
      title: remote.name ?? fallback.title,
      questionCount: total,
      progress: total ? Math.min(100, Math.round((attempted / total) * 100)) : 0,
      mastery:
        remote.accuracy == null
          ? fallback.mastery
          : Math.round(Number(remote.accuracy)),
      topics: fallback.topics.map((fallbackTopic) => {
        const remoteTopic = remote.topics?.find(
          (item) => item.slug === fallbackTopic.id,
        );
        if (!remoteTopic) return fallbackTopic;
        const remoteTotal = remoteTopic.question_count ?? fallbackTopic.questions;
        const remoteAttempted = remoteTopic.attempted_questions ?? 0;
        return {
          ...fallbackTopic,
          title: remoteTopic.name ?? fallbackTopic.title,
          questions: remoteTotal,
          progress: remoteTotal
            ? Math.min(100, Math.round((remoteAttempted / remoteTotal) * 100))
            : 0,
        };
      }),
    };
  });
}

function mapServerQuestions(payload: unknown): PracticeQuestion[] {
  if (!payload || typeof payload !== "object") return [];
  const source = payload as {
    questions?: Array<{
      id: string | number;
      subject_slug?: string;
      topic_slug?: string;
      question_type?: string;
      marks?: number;
      text?: string;
      options?: Array<{ id: string | number; text?: string }>;
      source?: string;
      year?: number;
      difficulty?: string;
    }>;
  };
  if (!Array.isArray(source.questions)) return [];
  return source.questions.map((question) => ({
    id: String(question.id),
    subjectId: question.subject_slug ?? "mixed",
    topicId: question.topic_slug ?? "mixed",
    type: (["MCQ", "MSQ", "NAT"].includes(question.question_type ?? "")
      ? question.question_type
      : "MCQ") as QuestionType,
    marks: question.marks === 2 ? 2 : 1,
    prompt: question.text ?? "Question text unavailable.",
    options: question.options?.map((option) => ({
      id: String(option.id),
      label: option.text ?? String(option.id),
    })),
    correct: [],
    explanation: "The detailed solution will be revealed when this session is submitted.",
    source: question.source ?? "Question bank",
    year: question.year,
    difficulty: (["Easy", "Medium", "Hard"].includes(question.difficulty ?? "")
      ? question.difficulty
      : "Medium") as "Easy" | "Medium" | "Hard",
  }));
}

const formatTime = (seconds: number) => {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remaining = seconds % 60;
  return [hours, minutes, remaining]
    .map((value) => String(value).padStart(2, "0"))
    .join(":");
};

const isExactAnswer = (answer: string[] = [], correct: string[] = []) =>
  answer.length === correct.length &&
  [...answer].sort().every((value, index) => value === [...correct].sort()[index]);

function ProgressRing({ value, size = "large" }: { value: number; size?: "small" | "large" }) {
  return (
    <div
      className={`progress-ring ${size}`}
      style={{ "--progress": `${value * 3.6}deg` } as React.CSSProperties}
      role="img"
      aria-label={`${value}% complete`}
    >
      <span><strong>{value}%</strong>{size === "large" && <small>complete</small>}</span>
    </div>
  );
}

function MiniProgress({ value }: { value: number }) {
  return (
    <div className="mini-progress" aria-label={`${value}% complete`}>
      <span style={{ width: `${value}%` }} />
    </div>
  );
}

function TypeBadge({ type }: { type: QuestionType }) {
  return <span className={`type-badge type-${type.toLowerCase()}`}>{type}</span>;
}

export default function Home() {
  const [screen, setScreen] = useState<Screen>("dashboard");
  const [theme, setTheme] = useState<Theme>("light");
  const [apiState, setApiState] = useState<ApiState>("checking");
  const [roadmapSubjects, setRoadmapSubjects] = useState(localSubjects);
  const [selectedSubjectId, setSelectedSubjectId] = useState("computer-organization");
  const [selectedTopicId, setSelectedTopicId] = useState("memory-hierarchy");
  const [practiceMode, setPracticeMode] = useState<PracticeMode>("practice");
  const [runnerQuestions, setRunnerQuestions] = useState<PracticeQuestion[]>([]);
  const [questionIndex, setQuestionIndex] = useState(0);
  const [practiceAnswers, setPracticeAnswers] = useState<Answers>({});
  const [checkedQuestions, setCheckedQuestions] = useState<Set<string>>(new Set());
  const [isLoadingQuestions, setIsLoadingQuestions] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [runnerSummary, setRunnerSummary] = useState<ServerResult | null>(null);
  const [runnerSubmitted, setRunnerSubmitted] = useState(false);
  const [examQuestions, setExamQuestions] = useState<PracticeQuestion[]>(() => buildMockQuestions());
  const [examAnswers, setExamAnswers] = useState<Answers>({});
  const [examIndex, setExamIndex] = useState(0);
  const [reviewed, setReviewed] = useState<Set<string>>(new Set());
  const [examSeconds, setExamSeconds] = useState(180 * 60);
  const [examRunning, setExamRunning] = useState(false);
  const [serverResult, setServerResult] = useState<ServerResult | null>(null);
  const [submitBusy, setSubmitBusy] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  const selectedSubject = useMemo(
    () =>
      roadmapSubjects.find((subject) => subject.id === selectedSubjectId) ??
      roadmapSubjects[2],
    [roadmapSubjects, selectedSubjectId],
  );
  const selectedTopic =
    selectedSubject.topics.find((item) => item.id === selectedTopicId) ??
    selectedSubject.topics[0];

  useEffect(() => {
    const saved = window.localStorage.getItem("gatepath-theme") as Theme | null;
    const preferred = window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
    setTheme(saved === "dark" || saved === "light" ? saved : preferred);
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem("gatepath-theme", theme);
  }, [theme]);

  useEffect(() => {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 3500);
    fetch(`${API_BASE}/roadmap?user_key=local-user`, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error("API unavailable");
        return response.json();
      })
      .then((payload) => {
        setRoadmapSubjects(mergeRoadmap(payload));
        setApiState("online");
      })
      .catch(() => setApiState("offline"))
      .finally(() => window.clearTimeout(timeout));
    return () => {
      controller.abort();
      window.clearTimeout(timeout);
    };
  }, []);

  useEffect(() => {
    if (!examRunning) return;
    const timer = window.setInterval(() => {
      setExamSeconds((current) => {
        if (current <= 1) {
          setExamRunning(false);
          setScreen("results");
          return 0;
        }
        return current - 1;
      });
    }, 1000);
    return () => window.clearInterval(timer);
  }, [examRunning]);

  const navigate = useCallback((target: Screen) => {
    setScreen(target);
    setMobileNavOpen(false);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, []);

  const openSubject = (subject: Subject) => {
    setSelectedSubjectId(subject.id);
    setSelectedTopicId(subject.topics[0].id);
    navigate("subject");
  };

  const localSetForSubject = useCallback((subjectId = selectedSubject.id) => {
    const exact = practiceQuestions.filter(
      (question) => question.subjectId === subjectId,
    );
    const adjacent = practiceQuestions.filter(
      (question) => question.subjectId !== subjectId,
    );
    return [...exact, ...adjacent].slice(0, 8);
  }, [selectedSubject.id]);

  const startPractice = async (
    mode: PracticeMode,
    subjectForRun: Subject = selectedSubject,
  ) => {
    setPracticeMode(mode);
    setQuestionIndex(0);
    setPracticeAnswers({});
    setCheckedQuestions(new Set());
    setRunnerSummary(null);
    setRunnerSubmitted(false);
    setRunnerQuestions(localSetForSubject(subjectForRun.id));
    setSessionId(null);
    setIsLoadingQuestions(true);
    navigate("practice");

    try {
      const response = await fetch(
        `${API_BASE}/${mode === "sectional" ? "tests" : "practice-sessions"}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(
            mode === "sectional"
              ? {
                  mode: "sectional",
                  user_key: "local-user",
                  subject_slug: apiSubjectSlug(subjectForRun.id),
                  count: 10,
                  duration_minutes: 25,
                }
              : {
                  user_key: "local-user",
                  subject_slug: apiSubjectSlug(subjectForRun.id),
                  topic_id: undefined,
                  count: 8,
                },
          ),
        },
      );
      if (!response.ok) throw new Error("Question service unavailable");
      const payload = (await response.json()) as { id?: string | number };
      const mapped = mapServerQuestions(payload);
      if (mapped.length) {
        setRunnerQuestions(mapped);
        setSessionId(payload.id == null ? null : String(payload.id));
        setApiState("online");
      }
    } catch {
      setApiState("offline");
    } finally {
      setIsLoadingQuestions(false);
    }
  };

  const submitRunner = async () => {
    if (submitBusy) return;
    setSubmitBusy(true);
    let summary: ServerResult | null = null;

    if (sessionId) {
      try {
        const response = await fetch(`${API_BASE}/attempts`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            session_id: sessionId,
            user_key: "local-user",
            answers: runnerQuestions
              .filter((question) => practiceAnswers[question.id]?.length)
              .map((question) => ({
                question_id: question.id,
                answer:
                  question.type === "MSQ"
                    ? practiceAnswers[question.id]
                    : practiceAnswers[question.id][0],
              })),
          }),
        });
        if (!response.ok) throw new Error("Unable to score session");
        const payload = (await response.json()) as {
          score?: number;
          max_score?: number;
          percentage?: number;
          correct_count?: number;
          incorrect_count?: number;
          unanswered_count?: number;
          results?: Array<{
            question_id: string | number;
            correct_answer: string | number | string[];
            explanation?: string;
          }>;
        };
        const resultMap = new Map(
          (payload.results ?? []).map((item) => [String(item.question_id), item]),
        );
        setRunnerQuestions((current) =>
          current.map((question) => {
            const item = resultMap.get(question.id);
            if (!item) return question;
            const correct = Array.isArray(item.correct_answer)
              ? item.correct_answer.map(String)
              : [String(item.correct_answer)];
            return {
              ...question,
              correct,
              explanation: item.explanation ?? question.explanation,
            };
          }),
        );
        summary = {
          score: Number(payload.score ?? 0),
          maxScore: Number(payload.max_score ?? 0),
          percentage: Number(payload.percentage ?? 0),
          correct: Number(payload.correct_count ?? 0),
          incorrect: Number(payload.incorrect_count ?? 0),
          unanswered: Number(payload.unanswered_count ?? 0),
        };
      } catch {
        setApiState("offline");
      }
    }

    if (!summary) {
      let score = 0;
      let correct = 0;
      let incorrect = 0;
      let unanswered = 0;
      const maxScore = runnerQuestions.reduce(
        (total, question) => total + question.marks,
        0,
      );
      runnerQuestions.forEach((question) => {
        const answer = practiceAnswers[question.id] ?? [];
        if (!answer.length) {
          unanswered += 1;
        } else if (isExactAnswer(answer, question.correct)) {
          correct += 1;
          score += question.marks;
        } else {
          incorrect += 1;
          if (question.type === "MCQ") {
            score -= question.marks === 1 ? 1 / 3 : 2 / 3;
          }
        }
      });
      summary = {
        score: Math.max(0, Number(score.toFixed(2))),
        maxScore,
        percentage: maxScore
          ? Math.max(0, Math.round((score / maxScore) * 100))
          : 0,
        correct,
        incorrect,
        unanswered,
      };
    }

    setCheckedQuestions(new Set(runnerQuestions.map((question) => question.id)));
    setRunnerSubmitted(true);
    setRunnerSummary(summary);
    setSubmitBusy(false);
  };

  const updateAnswer = (
    question: PracticeQuestion,
    value: string,
    target: "practice" | "exam",
  ) => {
    const setter = target === "practice" ? setPracticeAnswers : setExamAnswers;
    setter((current) => {
      const existing = current[question.id] ?? [];
      if (question.type === "MSQ") {
        return {
          ...current,
          [question.id]: existing.includes(value)
            ? existing.filter((item) => item !== value)
            : [...existing, value],
        };
      }
      return { ...current, [question.id]: value ? [value] : [] };
    });
  };

  const beginMock = async () => {
    const fallback = buildMockQuestions();
    setExamQuestions(fallback);
    setExamAnswers({});
    setReviewed(new Set());
    setExamIndex(0);
    setExamSeconds(180 * 60);
    setServerResult(null);
    setSessionId(null);
    setExamRunning(true);
    navigate("mock");

    try {
      const response = await fetch(`${API_BASE}/tests`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mode: "full",
          user_key: "local-user",
          count: 65,
          duration_minutes: 180,
        }),
      });
      if (!response.ok) throw new Error("Mock service unavailable");
      const payload = (await response.json()) as { id?: string | number };
      const mapped = mapServerQuestions(payload);
      if (mapped.length === 65) {
        setExamQuestions(mapped);
        setSessionId(payload.id == null ? null : String(payload.id));
        setApiState("online");
      }
    } catch {
      setApiState("offline");
    }
  };

  const submitExam = async () => {
    if (submitBusy) return;
    const unanswered = examQuestions.filter(
      (question) => !(examAnswers[question.id]?.length > 0),
    ).length;
    if (
      unanswered > 0 &&
      !window.confirm(
        `${unanswered} questions are unanswered. Submit the test anyway?`,
      )
    ) {
      return;
    }

    setSubmitBusy(true);
    setExamRunning(false);
    if (sessionId) {
      try {
        const response = await fetch(`${API_BASE}/attempts`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            session_id: sessionId,
            user_key: "local-user",
            answers: examQuestions
              .filter((question) => examAnswers[question.id]?.length)
              .map((question) => ({
                question_id: question.id,
                answer:
                  question.type === "MSQ"
                    ? examAnswers[question.id]
                    : examAnswers[question.id][0],
              })),
          }),
        });
        if (response.ok) {
          const payload = (await response.json()) as Record<string, number>;
          setServerResult({
            score: Number(payload.score ?? 0),
            maxScore: Number(payload.max_score ?? 100),
            percentage: Number(payload.percentage ?? 0),
            correct: Number(payload.correct_count ?? payload.correct ?? 0),
            incorrect: Number(payload.incorrect_count ?? payload.incorrect ?? 0),
            unanswered: Number(payload.unanswered_count ?? payload.unanswered ?? 0),
          });
        }
      } catch {
        setApiState("offline");
      }
    }
    setSubmitBusy(false);
    navigate("results");
  };

  const localResult = useMemo(() => {
    let score = 0;
    let correct = 0;
    let incorrect = 0;
    let unanswered = 0;
    examQuestions.forEach((question) => {
      const answer = examAnswers[question.id] ?? [];
      if (!answer.length) {
        unanswered += 1;
        return;
      }
      if (isExactAnswer(answer, question.correct)) {
        correct += 1;
        score += question.marks;
      } else {
        incorrect += 1;
        if (question.type === "MCQ") {
          score -= question.marks === 1 ? 1 / 3 : 2 / 3;
        }
      }
    });
    return {
      score: Math.max(0, Number(score.toFixed(2))),
      maxScore: 100,
      percentage: Math.max(0, Number(score.toFixed(2))),
      correct,
      incorrect,
      unanswered,
    };
  }, [examAnswers, examQuestions]);
  const result = serverResult ?? localResult;

  const activeNav = screen === "mock" || screen === "mock-setup" || screen === "results"
    ? "mock-setup"
    : screen === "progress"
      ? "progress"
      : "dashboard";

  const headerTitle =
    screen === "dashboard"
      ? "Study roadmap"
      : screen === "progress"
        ? "Progress & insights"
        : screen === "mock-setup" || screen === "mock"
          ? "Full-length mock"
          : screen === "results"
            ? "Mock analysis"
            : selectedSubject.shortTitle;

  const renderDashboard = () => {
    const phases = ["Foundations", "Core reasoning", "Systems"] as const;
    return (
      <div className="page dashboard-page">
        <section className="dashboard-hero">
          <div className="hero-copy">
            <div className="eyebrow">Tuesday · focused plan</div>
            <h1>One clear path to<br /><em>GATE 2027.</em></h1>
            <p>Pick up exactly where you stopped. Today’s plan balances one concept block with deliberate practice.</p>
            <div className="hero-actions">
              <button className="button primary" onClick={() => openSubject(selectedSubject)}>
                Continue COA <span aria-hidden="true">→</span>
              </button>
              <button className="button quiet" onClick={() => navigate("mock-setup")}>
                Take a full mock
              </button>
            </div>
          </div>
          <div className="today-card">
            <div className="today-card-top">
              <div>
                <span className="card-kicker">Today’s focus</span>
                <h2>Cache memory</h2>
              </div>
              <ProgressRing value={42} />
            </div>
          <div className="plan-steps">
              <button onClick={() => { setSelectedSubjectId("computer-organization"); setSelectedTopicId("memory-hierarchy"); navigate("notes"); }}>
                <span className="step-status done">✓</span>
                <span><strong>Revise mapping</strong><small>12 min · concept</small></span>
                <span className="step-arrow">↗</span>
              </button>
              <button onClick={() => { const subject = roadmapSubjects.find((item) => item.id === "computer-organization") ?? selectedSubject; setSelectedSubjectId(subject.id); setSelectedTopicId("memory-hierarchy"); void startPractice("practice", subject); }}>
                <span className="step-status current">02</span>
                <span><strong>Solve a mixed set</strong><small>8 questions · practice</small></span>
                <span className="step-arrow">↗</span>
              </button>
            </div>
          </div>
        </section>

        <section className="pulse-strip" aria-label="Study summary">
          <div><span className="metric-icon flame">12</span><span><strong>12 day streak</strong><small>Personal best: 19 days</small></span></div>
          <div><span className="metric-icon">67%</span><span><strong>Overall accuracy</strong><small>+4% this month</small></span></div>
          <div><span className="metric-icon">18h</span><span><strong>Deep work</strong><small>Across the last 14 days</small></span></div>
          <button className="strip-link" onClick={() => navigate("progress")}>View insights <span>→</span></button>
        </section>

        <section className="roadmap-section">
          <div className="section-heading">
            <div>
              <div className="eyebrow">Syllabus navigator</div>
              <h2>Your subject roadmap</h2>
              <p>Move in order, or jump straight to the chapter you need.</p>
            </div>
            <div className="legend"><span className="legend-dot complete" /> Strong <span className="legend-dot active" /> In progress</div>
          </div>
          <div className="roadmap-phases">
            {phases.map((phase, phaseIndex) => (
              <div className="roadmap-phase" key={phase}>
                <div className="phase-label"><span>0{phaseIndex + 1}</span>{phase}</div>
                <div className="subject-grid">
                  {roadmapSubjects.filter((subject) => subject.phase === phase).map((subject, index) => (
                    <button
                      key={subject.id}
                      className="subject-card"
                      onClick={() => openSubject(subject)}
                      style={{ "--subject-accent": subject.accent } as React.CSSProperties}
                    >
                      <span className="subject-order">{String(index + 1).padStart(2, "0")}</span>
                      <span className="subject-code">{subject.code}</span>
                      <span className="subject-card-title">{subject.shortTitle}</span>
                      <span className="subject-meta">{subject.topics.length} chapters · {subject.questionCount} Qs</span>
                      <span className="subject-progress-row"><MiniProgress value={subject.progress} /><strong>{subject.progress}%</strong></span>
                      <span className="subject-open" aria-hidden="true">↗</span>
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="bottom-callout">
          <div><span className="callout-label">Exam simulation</span><h2>When you are ready, practise the real rhythm.</h2><p>65 questions · 100 marks · 180 minutes · MCQ, MSQ and NAT</p></div>
          <button className="button light" onClick={() => navigate("mock-setup")}>Open mock centre <span>→</span></button>
        </section>
      </div>
    );
  };

  const renderSubject = () => (
    <div className="page subject-page">
      <button className="back-link" onClick={() => navigate("dashboard")}>← Back to roadmap</button>
      <section className="subject-hero" style={{ "--subject-accent": selectedSubject.accent } as React.CSSProperties}>
        <div className="subject-monogram">{selectedSubject.code}</div>
        <div className="subject-intro">
          <div className="eyebrow">{selectedSubject.phase} · {selectedSubject.estimatedHours} hours mapped</div>
          <h1>{selectedSubject.title}</h1>
          <p>{selectedSubject.description}</p>
          <div className="subject-stats"><span><strong>{selectedSubject.progress}%</strong> syllabus</span><span><strong>{selectedSubject.mastery}%</strong> accuracy</span><span><strong>{selectedSubject.questionCount}</strong> questions</span></div>
        </div>
        <ProgressRing value={selectedSubject.progress} />
      </section>

      <section className="mode-grid" aria-label="Study modes">
        <button className="mode-card revise" onClick={() => navigate("notes")}>
          <span className="mode-number">01</span><span className="mode-icon">Aa</span>
          <span><strong>Revise concepts</strong><small>Notes, formulas and worked examples</small></span><span className="mode-arrow">→</span>
        </button>
        <button className="mode-card practice" onClick={() => void startPractice("practice")}>
          <span className="mode-number">02</span><span className="mode-icon">Q</span>
          <span><strong>Practice questions</strong><small>Topic-wise MCQ, MSQ and NAT</small></span><span className="mode-arrow">→</span>
        </button>
        <button className="mode-card test" onClick={() => void startPractice("sectional")}>
          <span className="mode-number">03</span><span className="mode-icon">25′</span>
          <span><strong>Take sectional test</strong><small>10 questions in exam conditions</small></span><span className="mode-arrow">→</span>
        </button>
      </section>

      <section className="workspace-grid">
        <div className="chapter-panel">
          <div className="panel-heading"><div><span className="eyebrow">Chapter plan</span><h2>Choose a topic</h2></div><span>{selectedSubject.topics.length} chapters</span></div>
          <div className="chapter-list">
            {selectedSubject.topics.map((item, index) => (
              <button
                key={item.id}
                className={item.id === selectedTopic.id ? "selected" : ""}
                onClick={() => setSelectedTopicId(item.id)}
              >
                <span className="chapter-index">{String(index + 1).padStart(2, "0")}</span>
                <span className="chapter-main"><strong>{item.title}</strong><small>{item.questions} questions · {item.duration}</small><MiniProgress value={item.progress} /></span>
                <span className="chapter-percent">{item.progress}%</span>
              </button>
            ))}
          </div>
        </div>
        <aside className="chapter-preview">
          <div className="preview-top"><span className="eyebrow">Selected chapter</span><span className="difficulty-pill">Next up</span></div>
          <h2>{selectedTopic.title}</h2>
          <p>Build recall first, then lock it in with a short mixed question set.</p>
          <div className="preview-plan">
            <div><span>1</span><p><strong>Concept review</strong><small>Key ideas + examples</small></p><b>12m</b></div>
            <div><span>2</span><p><strong>Targeted practice</strong><small>{Math.min(8, selectedTopic.questions)} selected questions</small></p><b>18m</b></div>
            <div><span>3</span><p><strong>Recall check</strong><small>3 checkpoint prompts</small></p><b>5m</b></div>
          </div>
          <button className="button primary full" onClick={() => navigate("notes")}>Start this chapter <span>→</span></button>
        </aside>
      </section>
    </div>
  );

  const renderNotes = () => {
    const note = selectedSubject.note;
    return (
      <div className="page notes-page">
        <div className="notes-toolbar">
          <button className="back-link" onClick={() => navigate("subject")}>← {selectedSubject.shortTitle}</button>
          <div className="notes-actions"><span>Last saved just now</span><button className="button small" onClick={() => void startPractice("practice")}>Practise this topic →</button></div>
        </div>
        <div className="notes-layout">
          <aside className="notes-index">
            <span className="eyebrow">In this review</span>
            <a href="#big-idea">01 · Big idea</a>
            <a href="#formula">02 · Formula card</a>
            <a href="#example">03 · Worked example</a>
            <a href="#checkpoint">04 · Recall checkpoint</a>
            <div className="syllabus-lock"><span>✓</span><p><strong>Syllabus locked</strong><small>Content stays within the official GATE CS scope.</small></p></div>
          </aside>
          <article className="notes-article">
            <header>
              <div className="eyebrow">{selectedSubject.code} · {selectedTopic.title}</div>
              <h1>{note.title}</h1>
              <p>{note.summary}</p>
              <div className="note-meta"><span>8 min read</span><span>2 examples</span><span>3 checkpoints</span></div>
            </header>
            <section id="big-idea" className="note-section">
              <span className="section-number">01</span><div><h2>The big idea</h2><p>{note.intuition}</p><div className="margin-note"><strong>Think in invariants</strong><span>Before calculating, write down what must stay true.</span></div></div>
            </section>
            <section id="formula" className="formula-card">
              <div><span className="card-kicker">Formula to remember</span><code>{note.formula}</code><p>{note.formulaHint}</p></div><button aria-label="Mark formula as remembered">✓</button>
            </section>
            <section id="example" className="note-section example-section">
              <span className="section-number">02</span><div><h2>Worked example</h2><p className="example-title">{note.exampleTitle}</p><ol>{note.exampleSteps.map((step) => <li key={step}>{step}</li>)}</ol><div className="answer-strip"><span>Exam habit</span>Sanity-check the units and boundary cases before choosing an answer.</div></div>
            </section>
            <section className="trap-card"><div><span>!</span><h3>Common traps</h3></div><ul>{note.traps.map((trap) => <li key={trap}>{trap}</li>)}</ul></section>
            <section id="checkpoint" className="checkpoint-card">
              <div><span className="card-kicker">Active recall</span><h2>Close the note. Can you answer these?</h2></div>
              <div className="checkpoint-list">{note.checkpoint.map((check, index) => <details key={check}><summary><span>{index + 1}</span>{check}</summary><p>Say the rule in your own words, then verify it against the formula and worked example above.</p></details>)}</div>
              <button className="button primary" onClick={() => void startPractice("practice")}>I’m ready to practise <span>→</span></button>
            </section>
          </article>
        </div>
      </div>
    );
  };

  const renderQuestionInput = (
    question: PracticeQuestion,
    answers: Answers,
    target: "practice" | "exam",
    disabled = false,
  ) => {
    const selected = answers[question.id] ?? [];
    if (question.type === "NAT") {
      return (
        <label className="nat-input">
          <span>Numerical answer</span>
          <input
            inputMode="decimal"
            value={selected[0] ?? ""}
            disabled={disabled}
            onChange={(event) => updateAnswer(question, event.target.value, target)}
            placeholder="Type your answer"
          />
          <small>Enter an integer or decimal value. Units are not required.</small>
        </label>
      );
    }
    return (
      <div className="option-list" role={question.type === "MCQ" ? "radiogroup" : "group"} aria-label="Answer options">
        {question.options?.map((option) => {
          const active = selected.includes(option.id);
          return (
            <button
              type="button"
              key={option.id}
              className={active ? "selected" : ""}
              disabled={disabled}
              role={question.type === "MCQ" ? "radio" : "checkbox"}
              aria-checked={active}
              onClick={() => updateAnswer(question, option.id, target)}
            >
              <span className="option-key">{option.id}</span><span>{option.label}</span><span className="option-check">{active ? "✓" : ""}</span>
            </button>
          );
        })}
      </div>
    );
  };

  const renderPractice = () => {
    if (runnerSummary) {
      return (
        <div className="page runner-complete-page">
          <section className="runner-complete-card">
            <span className="completion-mark">✓</span>
            <div className="eyebrow">{practiceMode === "sectional" ? "Section submitted" : "Practice complete"}</div>
            <h1>{runnerSummary.percentage >= 70 ? "Strong work. Keep the pattern." : "Good baseline. Review the misses."}</h1>
            <p>{selectedSubject.shortTitle} · {selectedTopic.title}</p>
            <div className="completion-score"><strong>{runnerSummary.score}</strong><span>/ {runnerSummary.maxScore}<small>{runnerSummary.percentage}% score</small></span></div>
            <div className="completion-stats"><span><strong>{runnerSummary.correct}</strong>Correct</span><span><strong>{runnerSummary.incorrect}</strong>Incorrect</span><span><strong>{runnerSummary.unanswered}</strong>Unanswered</span></div>
            <div className="completion-actions"><button className="button quiet" onClick={() => navigate("subject")}>Return to subject</button><button className="button primary" onClick={() => { setRunnerSummary(null); setQuestionIndex(0); }}>Review answers →</button></div>
          </section>
        </div>
      );
    }
    const question = runnerQuestions[questionIndex];
    if (!question) {
      return <div className="page empty-state"><span className="spinner" /><h1>Preparing your set…</h1><p>Curating questions for {selectedTopic.title}.</p></div>;
    }
    const checked = checkedQuestions.has(question.id);
    const answer = practiceAnswers[question.id] ?? [];
    const correct = question.correct.length ? isExactAnswer(answer, question.correct) : false;
    const serverLocked = question.correct.length === 0;
    const answeredCount = Object.values(practiceAnswers).filter((value) => value.length).length;
    return (
      <div className="page runner-page">
        <div className="runner-topline">
          <button className="back-link" onClick={() => navigate("subject")}>← Exit {practiceMode === "sectional" ? "test" : "practice"}</button>
          <div className="runner-progress"><span style={{ width: `${((questionIndex + 1) / runnerQuestions.length) * 100}%` }} /></div>
          <span>{questionIndex + 1} / {runnerQuestions.length}</span>
        </div>
        {isLoadingQuestions && <div className="loading-banner"><span className="spinner" /> Checking the live question bank…</div>}
        <div className="runner-layout">
          <section className="question-card">
            <header>
              <div><TypeBadge type={question.type} /><span className="question-meta">{question.marks} mark{question.marks > 1 ? "s" : ""}</span><span className="question-meta">{question.difficulty}</span></div>
              <span className="source-tag">{question.year ? `GATE ${question.year}` : question.source}</span>
            </header>
            <div className="question-number">Question {String(questionIndex + 1).padStart(2, "0")}</div>
            <h1>{question.prompt}</h1>
            {question.type === "MSQ" && <p className="question-instruction">Select one or more options. No partial marks.</p>}
            {renderQuestionInput(question, practiceAnswers, "practice", checked && practiceMode === "practice")}
            {checked && (practiceMode === "practice" || runnerSubmitted) && !serverLocked && (
              <div className={`explanation ${correct ? "correct" : "incorrect"}`} aria-live="polite">
                <div className="explanation-title"><span>{correct ? "✓" : "×"}</span><strong>{correct ? "Correct — well reasoned." : "Not quite. Review the reasoning."}</strong></div>
                <p>{question.explanation}</p>
                {question.correct.length > 0 && <small>Correct answer: {question.correct.join(", ")}</small>}
              </div>
            )}
            <footer>
              <button className="button quiet" disabled={questionIndex === 0} onClick={() => setQuestionIndex((index) => Math.max(0, index - 1))}>← Previous</button>
              {practiceMode === "practice" && !checked && !serverLocked ? (
                <button className="button primary" disabled={!answer.length} onClick={() => setCheckedQuestions((current) => new Set(current).add(question.id))}>Check answer</button>
              ) : questionIndex < runnerQuestions.length - 1 ? (
                <button className="button primary" onClick={() => setQuestionIndex((index) => index + 1)}>Next question →</button>
              ) : runnerSubmitted ? (
                <button className="button primary" onClick={() => navigate("subject")}>Return to subject →</button>
              ) : (
                <button className="button primary" disabled={submitBusy} onClick={() => void submitRunner()}>{submitBusy ? "Scoring…" : practiceMode === "sectional" ? "Submit section" : serverLocked ? "Finish & reveal" : "Finish set"} →</button>
              )}
            </footer>
          </section>
          <aside className="runner-aside">
            <div className="set-card"><span className="eyebrow">Current set</span><h2>{selectedTopic.title}</h2><p>{practiceMode === "sectional" ? "Sectional test" : "Adaptive practice"}</p><div className="set-score"><strong>{answeredCount}</strong><span>of {runnerQuestions.length}<small>answered</small></span></div></div>
            <div className="question-dots" aria-label="Question navigator">{runnerQuestions.map((item, index) => <button key={item.id} className={`${index === questionIndex ? "current" : ""} ${practiceAnswers[item.id]?.length ? "answered" : ""}`} onClick={() => setQuestionIndex(index)} aria-label={`Question ${index + 1}`}>{index + 1}</button>)}</div>
            <div className="type-guide"><div><TypeBadge type="MCQ" /><span>One correct option</span></div><div><TypeBadge type="MSQ" /><span>One or more correct</span></div><div><TypeBadge type="NAT" /><span>Numerical answer</span></div></div>
          </aside>
        </div>
      </div>
    );
  };

  const renderMockSetup = () => (
    <div className="page mock-setup-page">
      <section className="mock-hero">
        <div className="mock-hero-copy"><div className="eyebrow light-text">Full-length simulation · Set 01</div><h1>Three hours.<br />One honest baseline.</h1><p>Practise the official GATE rhythm with a calm interface, a faithful marking scheme and a detailed review at the end.</p><button className="button light" onClick={() => void beginMock()}>Begin full mock <span>→</span></button></div>
        <div className="mock-ticket"><div className="ticket-top"><span>GATE</span><strong>CS · 2027</strong></div><div className="ticket-main"><span>Duration</span><strong>03:00:00</strong><div><span><b>65</b> questions</span><span><b>100</b> marks</span></div></div><div className="ticket-code">FULL MOCK · 01 · OFFICIAL FORMAT</div></div>
      </section>
      <section className="mock-info-grid">
        <div className="instruction-card"><div className="panel-heading"><div><span className="eyebrow">Before you begin</span><h2>Exam instructions</h2></div><span>Read carefully</span></div><ol><li><span>01</span><p><strong>The paper has exactly 65 questions.</strong><small>10 General Aptitude questions and 55 subject questions.</small></p></li><li><span>02</span><p><strong>MCQ, MSQ and NAT are included.</strong><small>Questions carry either 1 or 2 marks.</small></p></li><li><span>03</span><p><strong>Negative marks apply only to MCQ.</strong><small>−⅓ for an incorrect 1-mark MCQ; −⅔ for an incorrect 2-mark MCQ.</small></p></li><li><span>04</span><p><strong>No partial marking for MSQ.</strong><small>MSQ and NAT have no negative marking.</small></p></li></ol></div>
        <aside className="readiness-card"><span className="eyebrow">Readiness check</span><h2>Set yourself up for focus.</h2><label><input type="checkbox" defaultChecked /><span><strong>Quiet three-hour window</strong><small>Notifications off, phone away</small></span></label><label><input type="checkbox" defaultChecked /><span><strong>Rough sheets ready</strong><small>Use only the on-screen calculator</small></span></label><label><input type="checkbox" /><span><strong>I will finish in one sitting</strong><small>The timer cannot be paused</small></span></label><div className="offline-ready"><span>✓</span><p><strong>Offline fallback ready</strong><small>Your local mock can start even if the API is unavailable.</small></p></div></aside>
      </section>
    </div>
  );

  const renderMock = () => {
    const question = examQuestions[examIndex];
    const answered = Object.values(examAnswers).filter((answer) => answer.length).length;
    const marked = reviewed.size;
    return (
      <div className="exam-shell">
        <header className="exam-header"><div className="exam-brand"><span>G</span><div><strong>GATE CS · Full mock 01</strong><small>Official-format simulation</small></div></div><div className={`exam-clock ${examSeconds < 900 ? "warning" : ""}`}><span>Time remaining</span><strong>{formatTime(examSeconds)}</strong></div><button className="button danger" onClick={() => void submitExam()} disabled={submitBusy}>{submitBusy ? "Submitting…" : "Submit test"}</button></header>
        <div className="exam-body">
          <main className="exam-question">
            <div className="exam-section-bar"><div><span>{examIndex < 10 ? "General Aptitude" : "Computer Science"}</span><strong>Question {examIndex + 1} of 65</strong></div><div><TypeBadge type={question.type} /><span>{question.marks} mark{question.marks > 1 ? "s" : ""}</span></div></div>
            <article>
              <h1>{question.prompt}</h1>
              {question.type === "MSQ" && <p className="question-instruction">Select one or more options. No partial marks and no negative marks.</p>}
              {renderQuestionInput(question, examAnswers, "exam")}
            </article>
            <footer><button className={`button review-button ${reviewed.has(question.id) ? "active" : ""}`} onClick={() => setReviewed((current) => { const next = new Set(current); if (next.has(question.id)) next.delete(question.id); else next.add(question.id); return next; })}>{reviewed.has(question.id) ? "✓ Marked for review" : "◇ Mark for review"}</button><div><button className="button quiet" disabled={examIndex === 0} onClick={() => setExamIndex((index) => index - 1)}>← Previous</button><button className="button primary" disabled={examIndex === 64} onClick={() => setExamIndex((index) => Math.min(64, index + 1))}>Save & next →</button></div></footer>
          </main>
          <aside className="exam-palette"><div className="palette-summary"><div><strong>{answered}</strong><span>Answered</span></div><div><strong>{65 - answered}</strong><span>Not answered</span></div><div><strong>{marked}</strong><span>Review</span></div></div><div className="palette-heading"><strong>Question palette</strong><span>65 total</span></div><div className="palette-groups"><div><span>General Aptitude</span><div>{examQuestions.slice(0, 10).map((item, index) => <button key={item.id} onClick={() => setExamIndex(index)} className={`${index === examIndex ? "current" : ""} ${examAnswers[item.id]?.length ? "answered" : ""} ${reviewed.has(item.id) ? "reviewed" : ""}`}>{index + 1}</button>)}</div></div><div><span>Computer Science</span><div>{examQuestions.slice(10).map((item, index) => { const absolute = index + 10; return <button key={item.id} onClick={() => setExamIndex(absolute)} className={`${absolute === examIndex ? "current" : ""} ${examAnswers[item.id]?.length ? "answered" : ""} ${reviewed.has(item.id) ? "reviewed" : ""}`}>{absolute + 1}</button>; })}</div></div></div><div className="palette-legend"><span><i className="answered" /> Answered</span><span><i className="reviewed" /> Review</span><span><i /> Not visited</span></div></aside>
        </div>
      </div>
    );
  };

  const renderResults = () => (
    <div className="page results-page">
      <section className="result-hero"><div><div className="eyebrow">Full mock 01 · complete</div><h1>A useful baseline.<br /><em>Now make it actionable.</em></h1><p>Your score is less important than the pattern behind it. Start with accuracy, then revisit the chapters that cost the most marks.</p></div><div className="score-disc" style={{ "--score": `${Math.max(0, result.percentage) * 3.6}deg` } as React.CSSProperties}><span><strong>{result.score}</strong><small>/ {result.maxScore}</small></span></div></section>
      <section className="result-metrics"><div><span className="metric-label">Accuracy</span><strong>{result.correct + result.incorrect ? Math.round((result.correct / (result.correct + result.incorrect)) * 100) : 0}%</strong><small>{result.correct} correct answers</small></div><div><span className="metric-label">Attempted</span><strong>{result.correct + result.incorrect}<small>/65</small></strong><small>{result.unanswered} left unanswered</small></div><div><span className="metric-label">Time used</span><strong>{formatTime(180 * 60 - examSeconds)}</strong><small>{formatTime(examSeconds)} remaining</small></div><div><span className="metric-label">Negative marks</span><strong>−{Math.max(0, result.correct * 0 + (result.incorrect > 0 ? Math.min(result.incorrect / 3, 9.99) : 0)).toFixed(2)}</strong><small>MCQ only</small></div></section>
      <section className="analysis-grid"><div className="performance-card"><div className="panel-heading"><div><span className="eyebrow">Subject breakdown</span><h2>Where marks moved</h2></div><span>Accuracy</span></div><div className="performance-list">{roadmapSubjects.slice(0, 7).map((subject, index) => { const accuracy = Math.max(28, Math.min(92, subject.mastery - (index % 3) * 6)); return <div key={subject.id}><span className="performance-code" style={{ background: subject.accent }}>{subject.code}</span><span><strong>{subject.shortTitle}</strong><small>{Math.max(1, 7 - index)} attempted</small></span><div><MiniProgress value={accuracy} /><b>{accuracy}%</b></div></div>; })}</div></div><aside className="next-actions"><span className="eyebrow">Recommended next</span><h2>Turn misses into a plan.</h2><button onClick={() => { setSelectedSubjectId("computer-organization"); setSelectedTopicId("memory-hierarchy"); navigate("notes"); }}><span>01</span><p><strong>Revise cache mapping</strong><small>3 questions lost · 12 min</small></p><b>→</b></button><button onClick={() => { const subject = roadmapSubjects.find((item) => item.id === "algorithms") ?? selectedSubject; setSelectedSubjectId(subject.id); setSelectedTopicId("graph-algorithms"); void startPractice("practice", subject); }}><span>02</span><p><strong>Practise graph algorithms</strong><small>Focused set · 8 questions</small></p><b>→</b></button><button onClick={() => navigate("progress")}><span>03</span><p><strong>Review full progress</strong><small>Compare recent mock trends</small></p><b>→</b></button><button className="button primary full" onClick={() => navigate("dashboard")}>Return to roadmap</button></aside></section>
    </div>
  );

  const renderProgress = () => {
    const maxMinutes = Math.max(...weeklyActivity.map((item) => item.minutes));
    return (
      <div className="page progress-page"><section className="progress-heading"><div><div className="eyebrow">Learning signals</div><h1>Progress you can act on.</h1><p>Consistency is stable. Accuracy is rising fastest in Programming and Databases; Theory of Computation needs the next focused block.</p></div><select aria-label="Progress period" defaultValue="30"><option value="7">Last 7 days</option><option value="30">Last 30 days</option><option value="90">Last 90 days</option></select></section><section className="progress-metrics"><div><span>Study streak</span><strong>12 <small>days</small></strong><p>5 sessions this week</p></div><div><span>Questions solved</span><strong>486</strong><p>67% overall accuracy</p></div><div><span>Deep work</span><strong>42 <small>hours</small></strong><p>+8h from last month</p></div><div><span>Syllabus coverage</span><strong>55%</strong><p>31 of 43 chapters started</p></div></section><section className="progress-grid"><div className="activity-card"><div className="panel-heading"><div><span className="eyebrow">Study rhythm</span><h2>This week</h2></div><strong>9h 09m</strong></div><div className="bar-chart">{weeklyActivity.map((item, index) => <div key={`${item.day}-${index}`}><span className="bar-value">{item.minutes}m</span><div className="bar-track"><i style={{ height: `${(item.minutes / maxMinutes) * 100}%` }} /></div><b>{item.day}</b></div>)}</div><div className="chart-note"><span>↗</span><p><strong>Your best focus window is 7–9 AM.</strong><small>Sessions in this window are 18 minutes longer on average.</small></p></div></div><div className="coverage-card"><div className="panel-heading"><div><span className="eyebrow">Subject health</span><h2>Coverage & accuracy</h2></div><span>Open subject</span></div><div className="coverage-list">{roadmapSubjects.map((subject) => <button key={subject.id} onClick={() => openSubject(subject)}><span className="performance-code" style={{ background: subject.accent }}>{subject.code}</span><span><strong>{subject.shortTitle}</strong><small>{subject.progress}% covered</small></span><div><MiniProgress value={subject.mastery} /><b>{subject.mastery}%</b></div><i>→</i></button>)}</div></div></section></div>
    );
  };

  if (screen === "mock") return renderMock();

  return (
    <div className="app-shell">
      <button className="mobile-menu" onClick={() => setMobileNavOpen((open) => !open)} aria-expanded={mobileNavOpen} aria-label="Open navigation">{mobileNavOpen ? "×" : "≡"}</button>
      <aside className={`sidebar ${mobileNavOpen ? "open" : ""}`}>
        <button className="brand" onClick={() => navigate("dashboard")}><span className="brand-mark">G</span><span><strong>Gatepath</strong><small>2027 · CSE</small></span></button>
        <nav aria-label="Primary navigation"><button className={activeNav === "dashboard" ? "active" : ""} onClick={() => navigate("dashboard")}><span className="nav-icon">⌂</span><span>Roadmap</span></button><button className={activeNav === "mock-setup" ? "active" : ""} onClick={() => navigate("mock-setup")}><span className="nav-icon">◷</span><span>Full mock</span><em>65</em></button><button className={activeNav === "progress" ? "active" : ""} onClick={() => navigate("progress")}><span className="nav-icon">↗</span><span>Progress</span></button></nav>
        <div className="sidebar-spacer" />
        <div className="sidebar-target"><span className="target-label">Weekly target</span><div><strong>9h 09m</strong><span>of 12 hours</span></div><MiniProgress value={76} /><small>2h 51m to go</small></div>
        <button className="profile"><span>IS</span><span><strong>Your study space</strong><small>Local profile</small></span><i>···</i></button>
      </aside>
      {mobileNavOpen && <button className="nav-scrim" aria-label="Close navigation" onClick={() => setMobileNavOpen(false)} />}
      <div className="content-shell">
        <header className="topbar"><div><span className="topbar-kicker">GATE 2027 · Computer Science</span><strong>{headerTitle}</strong></div><div className="topbar-actions"><span className={`api-status ${apiState}`}><i />{apiState === "online" ? "Synced" : apiState === "checking" ? "Connecting" : "Local mode"}</span><button className="theme-toggle" aria-label={`Switch to ${theme === "light" ? "dark" : "light"} mode`} onClick={() => setTheme((current) => current === "light" ? "dark" : "light")}><span className={theme === "light" ? "active" : ""}>☼</span><span className={theme === "dark" ? "active" : ""}>◐</span></button></div></header>
        <main>{screen === "dashboard" && renderDashboard()}{screen === "subject" && renderSubject()}{screen === "notes" && renderNotes()}{screen === "practice" && renderPractice()}{screen === "mock-setup" && renderMockSetup()}{screen === "results" && renderResults()}{screen === "progress" && renderProgress()}</main>
        <nav className="mobile-bottom-nav" aria-label="Mobile navigation"><button className={activeNav === "dashboard" ? "active" : ""} onClick={() => navigate("dashboard")}><span>⌂</span>Roadmap</button><button className={activeNav === "mock-setup" ? "active" : ""} onClick={() => navigate("mock-setup")}><span>◷</span>Mock</button><button className={activeNav === "progress" ? "active" : ""} onClick={() => navigate("progress")}><span>↗</span>Progress</button></nav>
      </div>
    </div>
  );
}
