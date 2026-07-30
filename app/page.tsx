"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
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

const clientSlugify = (value: string) =>
  value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");

const COA_SYLLABUS_TOPICS = [
  "instruction-set-addressing",
  "alu-design",
  "control-unit",
  "memory-hierarchy",
  "io-interface",
  "pipelining",
] as const;

type Screen =
  | "dashboard"
  | "library"
  | "subject"
  | "notes"
  | "practice"
  | "mock-setup"
  | "mock"
  | "results"
  | "progress";
type Theme = "light" | "dark";
type ApiState = "checking" | "online" | "offline";
type PracticeMode = "practice" | "sectional" | "syllabus";
type Answers = Record<string, string[]>;
type LibraryTab = "full" | "course" | "bank";
type TopicStatus = "strong" | "developing" | "needs_practice" | "unattempted";

const LIBRARY_TABS: LibraryTab[] = ["full", "course", "bank"];
const CONNECT_BANK_REASON =
  "Connect the FastAPI question bank to launch this validated test form.";

type CatalogTest = {
  id: string;
  title: string;
  description: string;
  kind: "full" | "course";
  sequence: number;
  subjectId?: string;
  subjectCode?: string;
  subjectName?: string;
  questionCount: number;
  durationSeconds: number;
  totalMarks: number;
  topicCount: number;
  questionTypeCounts: Record<Lowercase<QuestionType>, number>;
  isAvailable: boolean;
  unavailableReason?: string;
};

type TopicAnalytics = {
  topicId: string;
  topicName: string;
  subjectId: string;
  subjectCode: string;
  subjectName: string;
  availableQuestions: number;
  attempts: number;
  uniqueAttempted: number;
  correct: number;
  accuracy: number;
  coverage: number;
  mastery: number;
  status: TopicStatus;
  lastAttemptedAt?: string;
};

type AnalyticsSnapshot = {
  attemptedResponses: number;
  uniqueQuestionsAttempted: number;
  availableQuestions: number;
  accuracy: number;
  coverage: number;
  mastery: number;
  testsCompleted: number;
  topics: TopicAnalytics[];
  generatedAt?: string;
};

type RemoteRoadmap = {
  slug?: string;
  code?: string;
  name?: string;
  question_count?: number;
  attempted_questions?: number;
  accuracy?: number;
  topics?: Array<{
    id?: number;
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

type RemoteRevisionNote = {
  id: number;
  topic_id: number;
  title: string;
  summary: string;
  content_md: string;
  key_points: string[];
  worked_examples: Array<{
    question: string;
    solution: string;
  }>;
};

const clampPercent = (value: number) =>
  Math.max(0, Math.min(100, Math.round(value)));

const toFiniteNumber = (value: unknown, fallback = 0) => {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : fallback;
};

const localSubjectFromSlug = (slug?: string, code?: string) =>
  localSubjects.find(
    (subject) =>
      subject.id === slug ||
      apiSubjectSlug(subject.id) === slug ||
      subject.code.toLowerCase() === code?.toLowerCase(),
  );

const LOCAL_FULL_TESTS: CatalogTest[] = Array.from(
  { length: 25 },
  (_, index) => ({
    id: `full-${String(index + 1).padStart(2, "0")}`,
    title: `Full-length mock ${String(index + 1).padStart(2, "0")}`,
    description: "Official-format, three-hour GATE CS simulation.",
    kind: "full",
    sequence: index + 1,
    questionCount: 65,
    durationSeconds: 180 * 60,
    totalMarks: 100,
    topicCount: localSubjects.reduce(
      (total, subject) => total + subject.topics.length,
      0,
    ),
    questionTypeCounts: { mcq: 30, msq: 18, nat: 17 },
    isAvailable: false,
    unavailableReason: CONNECT_BANK_REASON,
  }),
);

const LOCAL_COURSE_TESTS: CatalogTest[] = localSubjects.flatMap((subject) =>
  Array.from({ length: 10 }, (_, index) => ({
    id: `${subject.id}-test-${String(index + 1).padStart(2, "0")}`,
    title: `${subject.shortTitle} test ${String(index + 1).padStart(2, "0")}`,
    description: `A balanced ${subject.code} test spanning ${subject.topics.length} syllabus topics.`,
    kind: "course" as const,
    sequence: index + 1,
    subjectId: subject.id,
    subjectCode: subject.code,
    subjectName: subject.shortTitle,
    questionCount: 30,
    durationSeconds: 90 * 60,
    totalMarks: 45,
    topicCount: subject.topics.length,
    questionTypeCounts: { mcq: 12, msq: 9, nat: 9 },
    isAvailable: false,
    unavailableReason: CONNECT_BANK_REASON,
  })),
);

const LOCAL_TEST_CATALOG = [...LOCAL_FULL_TESTS, ...LOCAL_COURSE_TESTS];

function catalogIdentity(test: CatalogTest) {
  return test.kind === "full"
    ? `full-${test.sequence}`
    : `${test.subjectId ?? test.subjectCode ?? "course"}-${test.sequence}`;
}

function mapCatalog(payload: unknown): CatalogTest[] {
  if (!payload || typeof payload !== "object") return LOCAL_TEST_CATALOG;
  const source = payload as {
    items?: Array<Record<string, unknown>>;
    tests?: Array<Record<string, unknown>>;
  };
  const items = source.items ?? source.tests ?? [];
  if (!Array.isArray(items) || items.length === 0) return LOCAL_TEST_CATALOG;

  const remote = items.map((item, index): CatalogTest => {
    const mode = String(item.mode ?? item.kind ?? item.test_type ?? "sectional");
    const kind = mode === "full" ? "full" : "course";
    const subject = localSubjectFromSlug(
      String(item.subject_slug ?? ""),
      String(item.subject_code ?? ""),
    );
    const sequence = Math.max(
      1,
      Math.round(
        toFiniteNumber(item.form_number ?? item.sequence ?? item.number, index + 1),
      ),
    );
    const rawCounts =
      item.question_type_counts && typeof item.question_type_counts === "object"
        ? (item.question_type_counts as Record<string, unknown>)
        : {};
    return {
      id: String(item.id ?? item.test_id ?? `${kind}-${sequence}`),
      title: String(
        item.title ??
          item.name ??
          (kind === "full"
            ? `Full-length mock ${String(sequence).padStart(2, "0")}`
            : `${subject?.shortTitle ?? item.subject_name ?? "Course"} test ${String(sequence).padStart(2, "0")}`),
      ),
      description: String(
        item.description ??
          (kind === "full"
            ? "Official-format, three-hour GATE CS simulation."
            : "A balanced course test across the official syllabus."),
      ),
      kind,
      sequence,
      subjectId: subject?.id ?? String(item.subject_slug ?? ""),
      subjectCode: subject?.code ?? String(item.subject_code ?? ""),
      subjectName:
        subject?.shortTitle ?? String(item.subject_name ?? item.subject_code ?? ""),
      questionCount: Math.max(
        1,
        Math.round(toFiniteNumber(item.question_count, kind === "full" ? 65 : 30)),
      ),
      durationSeconds: Math.max(
        60,
        Math.round(
          toFiniteNumber(
            item.duration_seconds,
            kind === "full" ? 180 * 60 : 60 * 60,
          ),
        ),
      ),
      totalMarks: Math.max(
        1,
        Math.round(toFiniteNumber(item.total_marks, kind === "full" ? 100 : 45)),
      ),
      topicCount: Math.max(
        1,
        Math.round(
          toFiniteNumber(item.topic_count, subject?.topics.length ?? 1),
        ),
      ),
      questionTypeCounts: {
        mcq: Math.max(0, Math.round(toFiniteNumber(rawCounts.mcq))),
        msq: Math.max(0, Math.round(toFiniteNumber(rawCounts.msq))),
        nat: Math.max(0, Math.round(toFiniteNumber(rawCounts.nat))),
      },
      isAvailable: item.is_available !== false,
      unavailableReason:
        item.unavailable_reason == null
          ? undefined
          : String(item.unavailable_reason),
    };
  });

  const remoteByIdentity = new Map(
    remote.map((test) => [catalogIdentity(test), test]),
  );
  const merged = LOCAL_TEST_CATALOG.map((fallback) => {
    const server = remoteByIdentity.get(catalogIdentity(fallback));
    return server ? { ...fallback, ...server } : fallback;
  });
  const knownIds = new Set(merged.map((test) => test.id));
  return [...merged, ...remote.filter((test) => !knownIds.has(test.id))];
}

function buildLocalAnalytics(subjects: Subject[]): AnalyticsSnapshot {
  const topics = subjects.flatMap((subject, subjectIndex) =>
    subject.topics.map((topic, topicIndex): TopicAnalytics => {
      const attempts = Math.max(
        topic.progress > 0 ? 1 : 0,
        Math.round((topic.questions * topic.progress) / 100),
      );
      const accuracy = clampPercent(
        subject.mastery + ((subjectIndex + topicIndex) % 5 - 2) * 6,
      );
      const mastery = clampPercent(accuracy * 0.7 + topic.progress * 0.3);
      const status: TopicStatus =
        attempts === 0
          ? "unattempted"
          : accuracy >= 72 && topic.progress >= 55
            ? "strong"
            : accuracy < 55 || topic.progress < 32
              ? "needs_practice"
              : "developing";
      return {
        topicId: topic.id,
        topicName: topic.title,
        subjectId: subject.id,
        subjectCode: subject.code,
        subjectName: subject.shortTitle,
        availableQuestions: topic.questions,
        attempts,
        uniqueAttempted: attempts,
        correct: Math.round((attempts * accuracy) / 100),
        accuracy,
        coverage: topic.progress,
        mastery,
        status,
      };
    }),
  );
  const attemptedResponses = topics.reduce(
    (total, topic) => total + topic.attempts,
    0,
  );
  const correct = topics.reduce((total, topic) => total + topic.correct, 0);
  const availableQuestions = topics.reduce(
    (total, topic) => total + topic.availableQuestions,
    0,
  );
  return {
    attemptedResponses,
    uniqueQuestionsAttempted: topics.reduce(
      (total, topic) => total + topic.uniqueAttempted,
      0,
    ),
    availableQuestions,
    accuracy: attemptedResponses
      ? clampPercent((correct / attemptedResponses) * 100)
      : 0,
    coverage: availableQuestions
      ? clampPercent(
          (topics.reduce((total, topic) => total + topic.uniqueAttempted, 0) /
            availableQuestions) *
            100,
        )
      : 0,
    mastery: topics.length
      ? clampPercent(
          topics.reduce((total, topic) => total + topic.mastery, 0) /
            topics.length,
        )
      : 0,
    testsCompleted: 0,
    topics,
  };
}

function mergeAnalytics(
  payload: unknown,
  subjects: Subject[],
): AnalyticsSnapshot {
  const fallback = buildLocalAnalytics(subjects);
  if (!payload || typeof payload !== "object") return fallback;
  const source = payload as Record<string, unknown>;
  const overall =
    source.overall && typeof source.overall === "object"
      ? (source.overall as Record<string, unknown>)
      : {};
  const rawTopics = Array.isArray(source.topics)
    ? (source.topics as Array<Record<string, unknown>>)
    : [];
  if (!rawTopics.length) return fallback;

  const fallbackByKey = new Map(
    fallback.topics.map((topic) => [
      `${topic.subjectId}:${topic.topicId}`,
      topic,
    ]),
  );
  const mapped = rawTopics.map((item): TopicAnalytics => {
    const subject = localSubjectFromSlug(
      String(item.subject_slug ?? ""),
      String(item.subject_code ?? ""),
    );
    const topicSlug = String(item.topic_slug ?? item.topic_id ?? "");
    const localTopic = subject?.topics.find(
      (topic) =>
        topic.id === topicSlug || topic.apiId === toFiniteNumber(item.topic_id, -1),
    );
    const local = fallbackByKey.get(
      `${subject?.id ?? item.subject_slug}:${localTopic?.id ?? topicSlug}`,
    );
    const attempts = Math.max(
      0,
      Math.round(
        toFiniteNumber(
          item.attempt_count ?? item.attempts ?? item.answered_count,
          local?.attempts,
        ),
      ),
    );
    const accuracy = clampPercent(
      toFiniteNumber(item.accuracy_percent ?? item.accuracy, local?.accuracy),
    );
    const coverage = clampPercent(
      toFiniteNumber(item.coverage_percent ?? item.coverage, local?.coverage),
    );
    const rawStatus = String(item.status ?? local?.status ?? "developing");
    const status: TopicStatus = (
      ["strong", "developing", "needs_practice", "unattempted"].includes(
        rawStatus,
      )
        ? rawStatus
        : "developing"
    ) as TopicStatus;
    return {
      topicId: localTopic?.id ?? topicSlug,
      topicName: String(item.topic_name ?? localTopic?.title ?? "Topic"),
      subjectId: subject?.id ?? String(item.subject_slug ?? "unknown"),
      subjectCode: subject?.code ?? String(item.subject_code ?? "CS"),
      subjectName:
        subject?.shortTitle ??
        String(item.subject_name ?? item.subject_code ?? "Computer Science"),
      availableQuestions: Math.max(
        0,
        Math.round(
          toFiniteNumber(item.available_questions, local?.availableQuestions),
        ),
      ),
      attempts,
      uniqueAttempted: Math.max(
        0,
        Math.round(
          toFiniteNumber(
            item.unique_questions_attempted,
            local?.uniqueAttempted ?? attempts,
          ),
        ),
      ),
      correct: Math.max(
        0,
        Math.round(
          toFiniteNumber(
            item.correct_count,
            Math.round((attempts * accuracy) / 100),
          ),
        ),
      ),
      accuracy,
      coverage,
      mastery: clampPercent(
        toFiniteNumber(item.mastery_score, accuracy * 0.7 + coverage * 0.3),
      ),
      status,
      lastAttemptedAt:
        item.last_attempted_at == null
          ? undefined
          : String(item.last_attempted_at),
    };
  });

  const mappedKeys = new Set(
    mapped.map((topic) => `${topic.subjectId}:${topic.topicId}`),
  );
  const topics = [
    ...mapped,
    ...fallback.topics.filter(
      (topic) => !mappedKeys.has(`${topic.subjectId}:${topic.topicId}`),
    ),
  ];
  return {
    attemptedResponses: Math.max(
      0,
      Math.round(
        toFiniteNumber(
          overall.attempted_responses,
          fallback.attemptedResponses,
        ),
      ),
    ),
    uniqueQuestionsAttempted: Math.max(
      0,
      Math.round(
        toFiniteNumber(
          overall.unique_questions_attempted,
          fallback.uniqueQuestionsAttempted,
        ),
      ),
    ),
    availableQuestions: Math.max(
      0,
      Math.round(
        toFiniteNumber(
          overall.available_questions,
          fallback.availableQuestions,
        ),
      ),
    ),
    accuracy: clampPercent(
      toFiniteNumber(overall.accuracy_percent, fallback.accuracy),
    ),
    coverage: clampPercent(
      toFiniteNumber(overall.coverage_percent, fallback.coverage),
    ),
    mastery: clampPercent(
      toFiniteNumber(overall.mastery_score, fallback.mastery),
    ),
    testsCompleted: Math.max(
      0,
      Math.round(
        toFiniteNumber(
          overall.tests_completed ?? source.tests_completed,
          fallback.testsCompleted,
        ),
      ),
    ),
    topics,
    generatedAt:
      source.generated_at == null ? undefined : String(source.generated_at),
  };
}

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
    const topics =
      remote.topics && remote.topics.length > 0
        ? remote.topics.map((remoteTopic) => {
            const remoteSlug =
              remoteTopic.slug ??
              clientSlugify(remoteTopic.name ?? "syllabus-topic");
            const fallbackTopic = fallback.topics.find(
              (topic) => topic.id === remoteSlug,
            );
            const remoteTotal =
              remoteTopic.question_count ?? fallbackTopic?.questions ?? 0;
            const remoteAttempted = remoteTopic.attempted_questions ?? 0;
            return {
              id: remoteSlug,
              apiId: remoteTopic.id,
              title:
                remoteTopic.name ?? fallbackTopic?.title ?? "Syllabus topic",
              questions: remoteTotal,
              progress: remoteTotal
                ? Math.min(
                    100,
                    Math.round((remoteAttempted / remoteTotal) * 100),
                  )
                : 0,
              duration:
                fallbackTopic?.duration ??
                `${Math.max(1, Math.round(remoteTotal / 18))}h`,
            };
          })
        : fallback.topics;
    return {
      ...fallback,
      title: remote.name ?? fallback.title,
      questionCount: total,
      progress: total ? Math.min(100, Math.round((attempted / total) * 100)) : 0,
      mastery:
        remote.accuracy == null
          ? fallback.mastery
          : Math.round(Number(remote.accuracy)),
      topics,
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
    items?: Array<{
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
  const questions = source.questions ?? source.items;
  if (!Array.isArray(questions)) return [];
  return questions.map((question) => {
    const rawType = String(question.question_type ?? "").toUpperCase();
    const rawDifficulty = String(question.difficulty ?? "").toLowerCase();
    const difficulty =
      rawDifficulty === "easy"
        ? "Easy"
        : rawDifficulty === "hard"
          ? "Hard"
          : "Medium";
    return {
      id: String(question.id),
      subjectId: question.subject_slug ?? "mixed",
      topicId: question.topic_slug ?? "mixed",
      type: (["MCQ", "MSQ", "NAT"].includes(rawType)
        ? rawType
        : "MCQ") as QuestionType,
      marks: question.marks === 2 ? 2 : 1,
      prompt: question.text ?? "Question text unavailable.",
      options: question.options?.map((option) => ({
        id: String(option.id),
        label: option.text ?? String(option.id),
      })),
      correct: [],
      explanation:
        "The detailed solution will be revealed when this session is submitted.",
      source: question.source ?? "Question bank",
      year: question.year,
      difficulty: difficulty as "Easy" | "Medium" | "Hard",
    };
  });
}

async function requestCatalogSession(test: CatalogTest) {
  const selectedResponse = await fetch(
    `${API_BASE}/tests/${encodeURIComponent(test.id)}/sessions`,
    {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_key: "local-user" }),
    },
  );
  if (selectedResponse.ok) return selectedResponse.json();

  const legacyResponse = await fetch(`${API_BASE}/tests`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      mode: test.kind === "full" ? "full" : "sectional",
      user_key: "local-user",
      subject_slug:
        test.kind === "course" && test.subjectId
          ? apiSubjectSlug(test.subjectId)
          : undefined,
      count: test.questionCount,
      duration_minutes: Math.round(test.durationSeconds / 60),
      seed: 2027 + test.sequence,
    }),
  });
  if (!legacyResponse.ok) {
    throw new Error("Test service unavailable");
  }
  return legacyResponse.json();
}

const formatTime = (seconds: number) => {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remaining = seconds % 60;
  return [hours, minutes, remaining]
    .map((value) => String(value).padStart(2, "0"))
    .join(":");
};

const normalizeAnswerValue = (value: string) => {
  const trimmed = value.trim();
  if (/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(trimmed)) {
    const numeric = Number(trimmed);
    if (Number.isFinite(numeric)) return String(numeric);
  }
  return trimmed;
};

const isExactAnswer = (answer: string[] = [], correct: string[] = []) => {
  const normalizedAnswer = answer.map(normalizeAnswerValue).sort();
  const normalizedCorrect = correct.map(normalizeAnswerValue).sort();
  return (
    normalizedAnswer.length === normalizedCorrect.length &&
    normalizedAnswer.every(
      (value, index) => value === normalizedCorrect[index],
    )
  );
};

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
  const [testCatalog, setTestCatalog] =
    useState<CatalogTest[]>(LOCAL_TEST_CATALOG);
  const [catalogSource, setCatalogSource] = useState<"live" | "local">("local");
  const [analytics, setAnalytics] = useState<AnalyticsSnapshot>(() =>
    buildLocalAnalytics(localSubjects),
  );
  const [analyticsSource, setAnalyticsSource] =
    useState<"live" | "local">("local");
  const [analyticsRefreshKey, setAnalyticsRefreshKey] = useState(0);
  const [libraryTab, setLibraryTab] = useState<LibraryTab>("full");
  const [catalogSubjectId, setCatalogSubjectId] = useState(
    "computer-organization",
  );
  const [bankSubjectId, setBankSubjectId] = useState("all");
  const [bankTopicId, setBankTopicId] = useState("all");
  const [bankType, setBankType] = useState<"all" | QuestionType>("all");
  const [bankQuery, setBankQuery] = useState("");
  const [progressSubjectId, setProgressSubjectId] = useState("all");
  const [bankQuestions, setBankQuestions] =
    useState<PracticeQuestion[] | null>(null);
  const [bankTotal, setBankTotal] = useState(practiceQuestions.length);
  const [bankLoading, setBankLoading] = useState(false);
  const [revisionNote, setRevisionNote] =
    useState<RemoteRevisionNote | null>(null);
  const [noteLoading, setNoteLoading] = useState(false);
  const [selectedSubjectId, setSelectedSubjectId] = useState("computer-organization");
  const [selectedTopicId, setSelectedTopicId] = useState("memory-hierarchy");
  const [practiceMode, setPracticeMode] = useState<PracticeMode>("practice");
  const [practiceTopicId, setPracticeTopicId] = useState<string | null>(null);
  const [runnerQuestions, setRunnerQuestions] = useState<PracticeQuestion[]>([]);
  const [questionIndex, setQuestionIndex] = useState(0);
  const [practiceAnswers, setPracticeAnswers] = useState<Answers>({});
  const [checkedQuestions, setCheckedQuestions] = useState<Set<string>>(new Set());
  const [isLoadingQuestions, setIsLoadingQuestions] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [runnerSummary, setRunnerSummary] = useState<ServerResult | null>(null);
  const [runnerSubmitted, setRunnerSubmitted] = useState(false);
  const [launchError, setLaunchError] = useState<string | null>(null);
  const [examQuestions, setExamQuestions] = useState<PracticeQuestion[]>([]);
  const [examAnswers, setExamAnswers] = useState<Answers>({});
  const [examIndex, setExamIndex] = useState(0);
  const [reviewed, setReviewed] = useState<Set<string>>(new Set());
  const [examSeconds, setExamSeconds] = useState(180 * 60);
  const [examRunning, setExamRunning] = useState(false);
  const [serverResult, setServerResult] = useState<ServerResult | null>(null);
  const [submitBusy, setSubmitBusy] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [activeTest, setActiveTest] = useState<CatalogTest>(
    LOCAL_FULL_TESTS[0],
  );
  const [runnerCatalogTest, setRunnerCatalogTest] =
    useState<CatalogTest | null>(null);
  const practiceRequestId = useRef(0);
  const submitExamRef =
    useRef<((skipConfirmation?: boolean) => Promise<void>) | null>(null);

  const selectedSubject = useMemo(
    () =>
      roadmapSubjects.find((subject) => subject.id === selectedSubjectId) ??
      roadmapSubjects[2],
    [roadmapSubjects, selectedSubjectId],
  );
  const selectedTopic =
    selectedSubject.topics.find((item) => item.id === selectedTopicId) ??
    selectedSubject.topics[0];
  const fullTests = useMemo(
    () =>
      testCatalog
        .filter((test) => test.kind === "full")
        .sort((a, b) => a.sequence - b.sequence),
    [testCatalog],
  );
  const selectedCourseTests = useMemo(
    () =>
      testCatalog
        .filter(
          (test) =>
            test.kind === "course" &&
            test.subjectId === catalogSubjectId,
        )
        .sort((a, b) => a.sequence - b.sequence),
    [catalogSubjectId, testCatalog],
  );
  const bankSubject =
    roadmapSubjects.find((subject) => subject.id === bankSubjectId) ?? null;
  const bankTopics = useMemo(
    () => bankSubject?.topics ?? [],
    [bankSubject],
  );

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
    fetch(`${API_BASE}/roadmap?user_key=local-user`, {
      credentials: "include",
      signal: controller.signal,
    })
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
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 5000);
    fetch(`${API_BASE}/tests/catalog`, {
      credentials: "include",
      signal: controller.signal,
    })
      .then((response) => {
        if (!response.ok) throw new Error("Catalog unavailable");
        return response.json();
      })
      .then((payload) => {
        const catalog = mapCatalog(payload);
        setTestCatalog(catalog);
        const firstAvailableFullTest = catalog.find(
          (test) => test.kind === "full" && test.isAvailable,
        );
        if (firstAvailableFullTest) {
          setActiveTest((current) =>
            current.isAvailable ? current : firstAvailableFullTest,
          );
        }
        setCatalogSource("live");
        setApiState("online");
      })
      .catch(() => {
        setTestCatalog(LOCAL_TEST_CATALOG);
        setCatalogSource("local");
      })
      .finally(() => window.clearTimeout(timeout));
    return () => {
      controller.abort();
      window.clearTimeout(timeout);
    };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 5000);
    fetch(`${API_BASE}/progress/analytics?user_key=local-user`, {
      credentials: "include",
      signal: controller.signal,
    })
      .then((response) => {
        if (!response.ok) throw new Error("Analytics unavailable");
        return response.json();
      })
      .then((payload) => {
        setAnalytics(mergeAnalytics(payload, roadmapSubjects));
        setAnalyticsSource("live");
        setApiState("online");
      })
      .catch(() => {
        setAnalytics(buildLocalAnalytics(roadmapSubjects));
        setAnalyticsSource("local");
      })
      .finally(() => window.clearTimeout(timeout));
    return () => {
      controller.abort();
      window.clearTimeout(timeout);
    };
  }, [analyticsRefreshKey, roadmapSubjects]);

  useEffect(() => {
    if (screen !== "library" || libraryTab !== "bank") return;
    const controller = new AbortController();
    const selectedBankTopic = bankTopics.find(
      (topic) => topic.id === bankTopicId,
    );
    const params = new URLSearchParams({ limit: "100" });
    if (bankSubjectId !== "all") {
      params.set("subject_slug", apiSubjectSlug(bankSubjectId));
    }
    if (selectedBankTopic?.apiId != null) {
      params.set("topic_id", String(selectedBankTopic.apiId));
    }
    if (bankType !== "all") {
      params.set("question_type", bankType.toLowerCase());
    }
    setBankLoading(true);
    fetch(`${API_BASE}/questions?${params.toString()}`, {
      credentials: "include",
      signal: controller.signal,
    })
      .then((response) => {
        if (!response.ok) throw new Error("Question bank unavailable");
        return response.json();
      })
      .then((payload) => {
        setBankQuestions(mapServerQuestions(payload));
        setBankTotal(
          Math.max(
            0,
            Math.round(
              toFiniteNumber(
                (payload as { total?: unknown }).total,
                mapServerQuestions(payload).length,
              ),
            ),
          ),
        );
        setApiState("online");
      })
      .catch(() => {
        setBankQuestions(null);
        setBankTotal(practiceQuestions.length);
      })
      .finally(() => setBankLoading(false));
    return () => controller.abort();
  }, [
    bankSubjectId,
    bankTopicId,
    bankTopics,
    bankType,
    libraryTab,
    screen,
  ]);

  useEffect(() => {
    if (screen !== "notes" || selectedTopic.apiId == null) {
      setRevisionNote(null);
      setNoteLoading(false);
      return;
    }
    const controller = new AbortController();
    setNoteLoading(true);
    fetch(`${API_BASE}/topics/${selectedTopic.apiId}/notes`, {
      credentials: "include",
      signal: controller.signal,
    })
      .then((response) => {
        if (!response.ok) throw new Error("Revision note unavailable");
        return response.json();
      })
      .then((payload) => {
        setRevisionNote(payload as RemoteRevisionNote);
        setApiState("online");
      })
      .catch(() => setRevisionNote(null))
      .finally(() => setNoteLoading(false));
    return () => controller.abort();
  }, [screen, selectedTopic.apiId]);

  useEffect(() => {
    if (!examRunning) return;
    const timer = window.setInterval(() => {
      setExamSeconds((current) => Math.max(0, current - 1));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [examRunning]);

  useEffect(() => {
    if (examRunning && examSeconds === 0) {
      void submitExamRef.current?.(true);
    }
  }, [examRunning, examSeconds]);

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

  const localSetForSubject = useCallback(
    (subjectId: string, topicId: string | null, count: number) => {
      const subjectQuestions = practiceQuestions.filter(
        (question) => question.subjectId === subjectId,
      );
      if (
        subjectId === "computer-organization" &&
        topicId === null &&
        count === 12
      ) {
        return COA_SYLLABUS_TOPICS.flatMap((syllabusTopic) =>
          subjectQuestions
            .filter((question) => question.topicId === syllabusTopic)
            .slice(0, 2),
        );
      }
      const topicQuestions =
        topicId === null
          ? subjectQuestions
          : subjectQuestions.filter(
              (question) => question.topicId === topicId,
            );
      const fallbackQuestions = topicQuestions.length
        ? topicQuestions
        : subjectQuestions.length
          ? subjectQuestions
          : practiceQuestions;
      return fallbackQuestions.slice(0, count);
    },
    [],
  );

  const startPractice = async (
    mode: PracticeMode,
    subjectForRun: Subject = selectedSubject,
    topicForRun: string | null = null,
  ) => {
    const requestId = ++practiceRequestId.current;
    const questionCount = mode === "syllabus" ? 12 : mode === "sectional" ? 10 : 8;
    const apiTopicId = topicForRun
      ? subjectForRun.topics.find((topic) => topic.id === topicForRun)?.apiId
      : undefined;
    const fallbackQuestions = localSetForSubject(
      subjectForRun.id,
      topicForRun,
      questionCount,
    );
    const requiresLiveQuestions =
      mode !== "syllabus" && !(topicForRun !== null && apiTopicId == null);
    setPracticeMode(mode);
    setRunnerCatalogTest(null);
    setPracticeTopicId(topicForRun);
    setQuestionIndex(0);
    setPracticeAnswers({});
    setCheckedQuestions(new Set());
    setRunnerSummary(null);
    setRunnerSubmitted(false);
    setLaunchError(null);
    setRunnerQuestions(requiresLiveQuestions ? [] : fallbackQuestions);
    setSessionId(null);
    setIsLoadingQuestions(requiresLiveQuestions);
    navigate("practice");

    if (!requiresLiveQuestions) {
      setIsLoadingQuestions(false);
      return;
    }

    try {
      const response = await fetch(
        `${API_BASE}/${mode === "sectional" ? "tests" : "practice-sessions"}`,
        {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(
            mode === "sectional"
              ? {
                  mode: "sectional",
                  user_key: "local-user",
                  subject_slug: apiSubjectSlug(subjectForRun.id),
                  count: questionCount,
                  duration_minutes: 25,
                }
              : {
                  user_key: "local-user",
                  subject_slug: apiSubjectSlug(subjectForRun.id),
                  topic_id: apiTopicId,
                  count: questionCount,
                },
          ),
        },
      );
      if (!response.ok) throw new Error("Question service unavailable");
      const payload = (await response.json()) as { id?: string | number };
      const mapped = mapServerQuestions(payload);
      if (requestId === practiceRequestId.current && mapped.length) {
        setRunnerQuestions(mapped);
        setSessionId(payload.id == null ? null : String(payload.id));
        setApiState("online");
      }
    } catch {
      if (requestId === practiceRequestId.current) {
        setApiState("offline");
        setRunnerQuestions(fallbackQuestions);
        setLaunchError(
          "The live question bank is unavailable, so this guided set is using the small built-in sample.",
        );
      }
    } finally {
      if (requestId === practiceRequestId.current) {
        setIsLoadingQuestions(false);
      }
    }
  };

  const startCoaQuiz = () => {
    const subject =
      roadmapSubjects.find((item) => item.id === "computer-organization") ??
      localSubjects.find((item) => item.id === "computer-organization") ??
      selectedSubject;
    setSelectedSubjectId(subject.id);
    setSelectedTopicId("memory-hierarchy");
    void startPractice("syllabus", subject, null);
  };

  const submitRunner = async () => {
    if (submitBusy) return;
    setSubmitBusy(true);
    let summary: ServerResult | null = null;
    let recordedAttempt = false;

    if (sessionId) {
      try {
        const response = await fetch(`${API_BASE}/attempts`, {
          method: "POST",
          credentials: "include",
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
        recordedAttempt = true;
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
    if (recordedAttempt) {
      setAnalyticsRefreshKey((current) => current + 1);
    }
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

  const beginMock = async (
    test: CatalogTest =
      fullTests.find((item) => item.sequence === activeTest.sequence) ??
      fullTests[0] ??
      LOCAL_FULL_TESTS[0],
  ) => {
    if (!test.isAvailable) return;
    setActiveTest(test);
    setRunnerCatalogTest(null);
    setExamQuestions([]);
    setExamAnswers({});
    setReviewed(new Set());
    setExamIndex(0);
    setExamSeconds(test.durationSeconds);
    setServerResult(null);
    setSessionId(null);
    setExamRunning(false);
    setIsLoadingQuestions(true);
    setLaunchError(null);
    navigate("mock");

    try {
      const payload = (await requestCatalogSession(test)) as {
        id?: string | number;
      };
      const mapped = mapServerQuestions(payload);
      if (mapped.length !== test.questionCount) {
        throw new Error("Incomplete full-test form");
      }
      setExamQuestions(mapped);
      setSessionId(payload.id == null ? null : String(payload.id));
      setApiState("online");
      setExamRunning(true);
    } catch {
      setApiState("offline");
      setLaunchError(
        "This validated full-test form could not be loaded. Reconnect the FastAPI question bank and try again.",
      );
    } finally {
      setIsLoadingQuestions(false);
    }
  };

  const beginCourseTest = async (test: CatalogTest) => {
    if (!test.isAvailable || test.kind !== "course") return;
    const subject =
      roadmapSubjects.find((item) => item.id === test.subjectId) ??
      selectedSubject;
    const requestId = ++practiceRequestId.current;
    setActiveTest(test);
    setRunnerCatalogTest(test);
    setSelectedSubjectId(subject.id);
    setSelectedTopicId(subject.topics[0].id);
    setPracticeMode("sectional");
    setPracticeTopicId(null);
    setQuestionIndex(0);
    setPracticeAnswers({});
    setCheckedQuestions(new Set());
    setRunnerSummary(null);
    setRunnerSubmitted(false);
    setLaunchError(null);
    setRunnerQuestions([]);
    setSessionId(null);
    setIsLoadingQuestions(true);
    navigate("practice");

    try {
      const payload = (await requestCatalogSession(test)) as {
        id?: string | number;
      };
      const mapped = mapServerQuestions(payload);
      if (
        requestId === practiceRequestId.current &&
        mapped.length === test.questionCount
      ) {
        setRunnerQuestions(mapped);
        setSessionId(payload.id == null ? null : String(payload.id));
        setApiState("online");
      } else if (requestId === practiceRequestId.current) {
        throw new Error("Incomplete course-test form");
      }
    } catch {
      if (requestId === practiceRequestId.current) {
        setApiState("offline");
        setLaunchError(
          "This validated course-test form could not be loaded. Reconnect the FastAPI question bank and try again.",
        );
      }
    } finally {
      if (requestId === practiceRequestId.current) {
        setIsLoadingQuestions(false);
      }
    }
  };

  const startCatalogTest = (test: CatalogTest) => {
    if (test.kind === "full") {
      void beginMock(test);
      return;
    }
    void beginCourseTest(test);
  };

  const submitExam = async (skipConfirmation = false) => {
    if (submitBusy) return;
    const unanswered = examQuestions.filter(
      (question) => !(examAnswers[question.id]?.length > 0),
    ).length;
    if (
      !skipConfirmation &&
      unanswered > 0 &&
      !window.confirm(
        `${unanswered} questions are unanswered. Submit the test anyway?`,
      )
    ) {
      return;
    }

    setSubmitBusy(true);
    setLaunchError(null);
    setExamRunning(false);
    if (sessionId) {
      try {
        const response = await fetch(`${API_BASE}/attempts`, {
          method: "POST",
          credentials: "include",
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
        if (!response.ok) {
          throw new Error("Unable to score test");
        }
        const payload = (await response.json()) as Record<string, number>;
        setServerResult({
          score: Number(payload.score ?? 0),
          maxScore: Number(payload.max_score ?? 100),
          percentage: Number(payload.percentage ?? 0),
          correct: Number(payload.correct_count ?? payload.correct ?? 0),
          incorrect: Number(payload.incorrect_count ?? payload.incorrect ?? 0),
          unanswered: Number(payload.unanswered_count ?? payload.unanswered ?? 0),
        });
        setAnalyticsRefreshKey((current) => current + 1);
      } catch {
        setApiState("offline");
        setLaunchError(
          "Your answers are still here, but the scoring service did not accept the submission. Reconnect and submit again.",
        );
        setSubmitBusy(false);
        return;
      }
    }
    setSubmitBusy(false);
    navigate("results");
  };
  submitExamRef.current = submitExam;

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
  const visibleBankQuestions = useMemo(() => {
    const source = bankQuestions ?? practiceQuestions;
    const query = bankQuery.trim().toLowerCase();
    return source
      .filter((question) => {
        const matchesSubject =
          bankSubjectId === "all" ||
          question.subjectId === bankSubjectId ||
          question.subjectId === apiSubjectSlug(bankSubjectId);
        const matchesTopic =
          bankTopicId === "all" || question.topicId === bankTopicId;
        const matchesType = bankType === "all" || question.type === bankType;
        const matchesQuery =
          !query ||
          question.prompt.toLowerCase().includes(query) ||
          (question.source ?? "").toLowerCase().includes(query);
        return matchesSubject && matchesTopic && matchesType && matchesQuery;
      })
      .slice(0, 30);
  }, [
    bankQuestions,
    bankQuery,
    bankSubjectId,
    bankTopicId,
    bankType,
  ]);
  const strongTopics = useMemo(
    () =>
      analytics.topics
        .filter((topic) => topic.status === "strong" && topic.attempts >= 3)
        .sort(
          (a, b) =>
            b.mastery - a.mastery ||
            b.uniqueAttempted - a.uniqueAttempted,
        )
        .slice(0, 5),
    [analytics],
  );
  const needsPracticeTopics = useMemo(
    () =>
      analytics.topics
        .filter(
          (topic) =>
            topic.status === "needs_practice" ||
            topic.status === "unattempted",
        )
        .sort(
          (a, b) =>
            a.mastery - b.mastery ||
            a.uniqueAttempted - b.uniqueAttempted,
        )
        .slice(0, 5),
    [analytics],
  );
  const filteredAnalyticsTopics = useMemo(
    () =>
      analytics.topics
        .filter(
          (topic) =>
            progressSubjectId === "all" ||
            topic.subjectId === progressSubjectId,
        )
        .sort((a, b) => a.mastery - b.mastery),
    [analytics, progressSubjectId],
  );

  const activeNav =
    screen === "practice" && runnerCatalogTest
      ? "library"
      : screen === "practice" && practiceMode === "syllabus"
      ? "dashboard"
      : screen === "library"
        ? "library"
      : screen === "mock" || screen === "mock-setup" || screen === "results"
        ? "mock-setup"
        : screen === "progress"
          ? "progress"
          : "dashboard";

  const headerTitle =
    screen === "practice" && runnerCatalogTest
      ? runnerCatalogTest.title
      : screen === "practice" && practiceMode === "syllabus"
      ? "COA syllabus quiz"
      : screen === "library"
        ? "Test library"
      : screen === "dashboard"
      ? "Study roadmap"
      : screen === "progress"
        ? "Progress & insights"
        : screen === "mock-setup" || screen === "mock"
          ? "Full-length mock"
          : screen === "results"
            ? "Mock analysis"
            : selectedSubject.shortTitle;

  const openAnalyticsTopic = (
    topic: TopicAnalytics,
    action: "revise" | "practice",
  ) => {
    const subject =
      roadmapSubjects.find((item) => item.id === topic.subjectId) ??
      selectedSubject;
    const subjectTopic =
      subject.topics.find((item) => item.id === topic.topicId) ??
      subject.topics[0];
    setSelectedSubjectId(subject.id);
    setSelectedTopicId(subjectTopic.id);
    if (action === "practice") {
      void startPractice("practice", subject, subjectTopic.id);
      return;
    }
    navigate("notes");
  };

  const handleLibraryTabKeyDown = (
    event: React.KeyboardEvent<HTMLButtonElement>,
  ) => {
    const currentIndex = LIBRARY_TABS.indexOf(libraryTab);
    let nextIndex = currentIndex;
    if (event.key === "ArrowRight") {
      nextIndex = (currentIndex + 1) % LIBRARY_TABS.length;
    } else if (event.key === "ArrowLeft") {
      nextIndex =
        (currentIndex - 1 + LIBRARY_TABS.length) % LIBRARY_TABS.length;
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = LIBRARY_TABS.length - 1;
    } else {
      return;
    }
    event.preventDefault();
    const nextTab = LIBRARY_TABS[nextIndex];
    setLibraryTab(nextTab);
    window.requestAnimationFrame(() =>
      document.getElementById(`library-tab-${nextTab}`)?.focus(),
    );
  };

  const renderCatalogCard = (test: CatalogTest) => {
    const durationMinutes = Math.round(test.durationSeconds / 60);
    return (
      <article
        className={`catalog-card ${test.isAvailable ? "" : "unavailable"}`}
        key={test.id}
      >
        <header>
          <span className="catalog-number">
            {String(test.sequence).padStart(2, "0")}
          </span>
          <span className={`availability ${test.isAvailable ? "ready" : ""}`}>
            {test.isAvailable ? "Ready" : "Connect bank"}
          </span>
        </header>
        <div>
          <span className="catalog-kicker">
            {test.kind === "full"
              ? "Full syllabus"
              : `${test.subjectCode} · ${test.topicCount} topics`}
          </span>
          <h3>{test.title}</h3>
          <p>{test.description}</p>
        </div>
        <dl className="catalog-facts">
          <div>
            <dt>Questions</dt>
            <dd>{test.questionCount}</dd>
          </div>
          <div>
            <dt>Time</dt>
            <dd>{durationMinutes}m</dd>
          </div>
          <div>
            <dt>Marks</dt>
            <dd>{test.totalMarks}</dd>
          </div>
        </dl>
        <div className="type-mix" aria-label="Question type mix">
          <span>MCQ {test.questionTypeCounts.mcq}</span>
          <span>MSQ {test.questionTypeCounts.msq}</span>
          <span>NAT {test.questionTypeCounts.nat}</span>
        </div>
        <button
          className="button primary full"
          disabled={!test.isAvailable}
          onClick={() => startCatalogTest(test)}
          title={test.unavailableReason}
        >
          {test.isAvailable ? "Start test" : "Not yet available"}{" "}
          <span aria-hidden="true">→</span>
        </button>
      </article>
    );
  };

  const renderDashboard = () => {
    const phases = ["Foundations", "Core reasoning", "Systems"] as const;
    return (
      <div className="page dashboard-page">
        <section className="dashboard-hero">
          <div className="hero-copy">
            <div className="eyebrow">Tuesday · focused plan</div>
            <h1>One clear path to<br /><em>GATE 2027.</em></h1>
            <p>Test every official Computer Organization & Architecture area in one focused, GATE-style live quiz.</p>
            <div className="hero-actions">
              <button className="button primary" onClick={startCoaQuiz}>
                Start COA syllabus quiz <span aria-hidden="true">→</span>
              </button>
              <button
                className="button quiet"
                onClick={() => {
                  const subject =
                    roadmapSubjects.find(
                      (item) => item.id === "computer-organization",
                    ) ?? selectedSubject;
                  openSubject(subject);
                }}
              >
                Explore COA topics
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
              <button onClick={() => { const subject = roadmapSubjects.find((item) => item.id === "computer-organization") ?? selectedSubject; setSelectedSubjectId(subject.id); setSelectedTopicId("memory-hierarchy"); void startPractice("practice", subject, "memory-hierarchy"); }}>
                <span className="step-status current">02</span>
                <span><strong>Solve a cache set</strong><small>Targeted questions · practice</small></span>
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

  const renderLibrary = () => {
    const courseTotal = testCatalog.filter(
      (test) => test.kind === "course",
    ).length;
    return (
      <div className="page library-page">
        <section className="library-hero">
          <div>
            <div className="eyebrow">Structured test practice</div>
            <h1>
              A test for every stage.
              <br />
              <em>One quiet place to find it.</em>
            </h1>
            <p>
              Move from focused 30-question course tests to complete
              three-hour simulations, with MCQ, MSQ and NAT represented in
              every set.
            </p>
          </div>
          <div className="library-summary" aria-label="Test library summary">
            <div>
              <strong>{fullTests.length}</strong>
              <span>full tests</span>
            </div>
            <div>
              <strong>10</strong>
              <span>per course</span>
            </div>
            <div>
              <strong>{courseTotal}</strong>
              <span>course tests</span>
            </div>
            <small>
              {catalogSource === "live"
                ? "Synced with the local question bank"
                : "Connect the question bank to launch tests"}
            </small>
          </div>
        </section>

        <div className="library-tabs" role="tablist" aria-label="Test library">
          <button
            id="library-tab-full"
            role="tab"
            aria-selected={libraryTab === "full"}
            aria-controls="library-panel-full"
            tabIndex={libraryTab === "full" ? 0 : -1}
            className={libraryTab === "full" ? "active" : ""}
            onClick={() => setLibraryTab("full")}
            onKeyDown={handleLibraryTabKeyDown}
          >
            Full tests <span>{fullTests.length}</span>
          </button>
          <button
            id="library-tab-course"
            role="tab"
            aria-selected={libraryTab === "course"}
            aria-controls="library-panel-course"
            tabIndex={libraryTab === "course" ? 0 : -1}
            className={libraryTab === "course" ? "active" : ""}
            onClick={() => setLibraryTab("course")}
            onKeyDown={handleLibraryTabKeyDown}
          >
            Course tests <span>{courseTotal}</span>
          </button>
          <button
            id="library-tab-bank"
            role="tab"
            aria-selected={libraryTab === "bank"}
            aria-controls="library-panel-bank"
            tabIndex={libraryTab === "bank" ? 0 : -1}
            className={libraryTab === "bank" ? "active" : ""}
            onClick={() => setLibraryTab("bank")}
            onKeyDown={handleLibraryTabKeyDown}
          >
            Question bank
          </button>
        </div>

        {libraryTab === "full" && (
          <section
            id="library-panel-full"
            className="library-panel"
            role="tabpanel"
            aria-labelledby="library-tab-full"
          >
            <div className="library-panel-heading">
              <div>
                <span className="eyebrow">Full-length series</span>
                <h2>25 honest exam rehearsals</h2>
                <p>65 questions · 100 marks · 180 minutes</p>
              </div>
              <span className="series-note">Official GATE pattern</span>
            </div>
            <div className="catalog-grid full-series">
              {fullTests.map(renderCatalogCard)}
            </div>
          </section>
        )}

        {libraryTab === "course" && (
          <section
            id="library-panel-course"
            className="library-panel"
            role="tabpanel"
            aria-labelledby="library-tab-course"
          >
            <div className="library-panel-heading course-heading">
              <div>
                <span className="eyebrow">Course test series</span>
                <h2>Ten balanced sets for each course</h2>
                <p>30 questions per test · MCQ, MSQ and NAT · broad coverage</p>
              </div>
              <label className="catalog-select">
                <span>Choose course</span>
                <select
                  value={catalogSubjectId}
                  onChange={(event) =>
                    setCatalogSubjectId(event.target.value)
                  }
                >
                  {roadmapSubjects.map((subject) => (
                    <option value={subject.id} key={subject.id}>
                      {subject.code} · {subject.shortTitle}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="topic-coverage-line">
              <strong>
                {
                  roadmapSubjects.find(
                    (subject) => subject.id === catalogSubjectId,
                  )?.shortTitle
                }{" "}
                coverage
              </strong>
              <div>
                {roadmapSubjects
                  .find((subject) => subject.id === catalogSubjectId)
                  ?.topics.map((topic) => (
                    <span key={topic.id}>{topic.title}</span>
                  ))}
              </div>
            </div>
            <div className="catalog-grid">
              {selectedCourseTests.map(renderCatalogCard)}
            </div>
          </section>
        )}

        {libraryTab === "bank" && (
          <section
            id="library-panel-bank"
            className="library-panel bank-panel"
            role="tabpanel"
            aria-labelledby="library-tab-bank"
          >
            <div className="library-panel-heading">
              <div>
                <span className="eyebrow">Question bank</span>
                <h2>Find the exact practice you need</h2>
                <p>
                  Browse by course, syllabus topic and GATE question type.
                </p>
              </div>
              <span className="series-note">
                {bankLoading
                  ? "Loading…"
                  : `${bankTotal.toLocaleString()} matching questions`}
              </span>
            </div>
            <div className="bank-filters">
              <label>
                <span>Course</span>
                <select
                  value={bankSubjectId}
                  onChange={(event) => {
                    setBankSubjectId(event.target.value);
                    setBankTopicId("all");
                  }}
                >
                  <option value="all">All courses</option>
                  {roadmapSubjects.map((subject) => (
                    <option value={subject.id} key={subject.id}>
                      {subject.code} · {subject.shortTitle}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span>Topic</span>
                <select
                  value={bankTopicId}
                  disabled={bankSubjectId === "all"}
                  onChange={(event) => setBankTopicId(event.target.value)}
                >
                  <option value="all">All topics</option>
                  {bankTopics.map((topic) => (
                    <option value={topic.id} key={topic.id}>
                      {topic.title}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span>Question type</span>
                <select
                  value={bankType}
                  onChange={(event) =>
                    setBankType(event.target.value as "all" | QuestionType)
                  }
                >
                  <option value="all">MCQ, MSQ and NAT</option>
                  <option value="MCQ">MCQ</option>
                  <option value="MSQ">MSQ</option>
                  <option value="NAT">NAT</option>
                </select>
              </label>
              <label className="bank-search">
                <span>Search this page</span>
                <input
                  type="search"
                  value={bankQuery}
                  onChange={(event) => setBankQuery(event.target.value)}
                  placeholder="e.g. pipeline, cache, trees"
                />
              </label>
            </div>
            <div className="bank-list" aria-live="polite">
              {visibleBankQuestions.map((question, index) => {
                const subject =
                  localSubjectFromSlug(question.subjectId) ?? selectedSubject;
                const topic =
                  subject.topics.find(
                    (item) => item.id === question.topicId,
                  ) ?? null;
                return (
                  <article key={question.id}>
                    <span className="bank-index">
                      {String(index + 1).padStart(2, "0")}
                    </span>
                    <div className="bank-question-copy">
                      <div>
                        <TypeBadge type={question.type} />
                        <span>{subject.code}</span>
                        <span>{topic?.title ?? question.topicId}</span>
                        <span>
                          {question.year
                            ? `GATE ${question.year}`
                            : question.source}
                        </span>
                      </div>
                      <h3>{question.prompt}</h3>
                    </div>
                    <button
                      className="button quiet small"
                      onClick={() => {
                        setSelectedSubjectId(subject.id);
                        setSelectedTopicId(
                          topic?.id ?? subject.topics[0].id,
                        );
                        void startPractice(
                          "practice",
                          subject,
                          topic?.id ?? null,
                        );
                      }}
                    >
                      Practise <span aria-hidden="true">→</span>
                    </button>
                  </article>
                );
              })}
              {!bankLoading && visibleBankQuestions.length === 0 && (
                <div className="bank-empty">
                  <strong>No questions match these filters.</strong>
                  <span>Try a broader topic or clear the search.</span>
                </div>
              )}
            </div>
          </section>
        )}
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
        <button className="mode-card practice" onClick={() => void startPractice("practice", selectedSubject, selectedTopic.id)}>
          <span className="mode-number">02</span><span className="mode-icon">Q</span>
          <span><strong>Practice questions</strong><small>Topic-wise MCQ, MSQ and NAT</small></span><span className="mode-arrow">→</span>
        </button>
        <button
          className="mode-card test"
          onClick={() =>
            selectedSubject.id === "computer-organization"
              ? startCoaQuiz()
              : void startPractice("sectional", selectedSubject, null)
          }
        >
          <span className="mode-number">03</span><span className="mode-icon">{selectedSubject.id === "computer-organization" ? "12Q" : "25′"}</span>
          <span>
            <strong>{selectedSubject.id === "computer-organization" ? "Take COA syllabus quiz" : "Take sectional test"}</strong>
            <small>{selectedSubject.id === "computer-organization" ? "12 questions across all 6 official areas" : "10 questions in exam conditions"}</small>
          </span>
          <span className="mode-arrow">→</span>
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
    const fallbackNote = selectedSubject.note;
    const keyPoints =
      revisionNote?.key_points?.filter(Boolean) ?? [
        fallbackNote.intuition,
        fallbackNote.formulaHint,
      ];
    const workedExamples =
      revisionNote?.worked_examples?.length
        ? revisionNote.worked_examples
        : [
            {
              question: fallbackNote.exampleTitle,
              solution: fallbackNote.exampleSteps.join(" "),
            },
          ];
    const checkpoints = revisionNote
      ? keyPoints.slice(0, 4).map((point) => `Can you explain why this is true: ${point}`)
      : fallbackNote.checkpoint;
    const traps = revisionNote
      ? [
          "Applying a remembered rule without checking its assumptions.",
          "Skipping units, boundary cases, or the meaning of the requested quantity.",
          "Choosing a related method that answers a different question.",
        ]
      : fallbackNote.traps;
    return (
      <div className="page notes-page">
        <div className="notes-toolbar">
          <button className="back-link" onClick={() => navigate("subject")}>← {selectedSubject.shortTitle}</button>
          <div className="notes-actions"><span>{noteLoading ? "Loading topic notes…" : revisionNote ? "Synced to the question bank" : "Built-in syllabus note"}</span><button className="button small" onClick={() => void startPractice("practice", selectedSubject, selectedTopic.id)}>Practise this topic →</button></div>
        </div>
        <div className="notes-layout">
          <aside className="notes-index">
            <span className="eyebrow">In this review</span>
            <a href="#big-idea">01 · Big idea</a>
            <a href="#formula">02 · Key rules</a>
            <a href="#example">03 · Worked examples</a>
            <a href="#checkpoint">04 · Recall checkpoint</a>
            <div className="syllabus-lock"><span>✓</span><p><strong>Syllabus locked</strong><small>Content stays within the official GATE CS scope.</small></p></div>
          </aside>
          <article className="notes-article">
            <header>
              <div className="eyebrow">{selectedSubject.code} · {selectedTopic.title}</div>
              <h1>{revisionNote?.title ?? fallbackNote.title}</h1>
              <p>{revisionNote?.summary ?? fallbackNote.summary}</p>
              <div className="note-meta"><span>{Math.max(6, 4 + workedExamples.length * 2)} min read</span><span>{workedExamples.length} worked example{workedExamples.length === 1 ? "" : "s"}</span><span>{checkpoints.length} checkpoints</span></div>
            </header>
            <section id="big-idea" className="note-section">
              <span className="section-number">01</span><div><h2>The big idea</h2><p>{revisionNote ? keyPoints.join(" ") : fallbackNote.intuition}</p><div className="margin-note"><strong>Think in invariants</strong><span>Before calculating, write down what must stay true.</span></div></div>
            </section>
            <section id="formula" className="formula-card">
              <div>
                <span className="card-kicker">{revisionNote ? "Key rules to remember" : "Formula to remember"}</span>
                {revisionNote ? (
                  <ul className="note-key-points">
                    {keyPoints.map((point) => <li key={point}>{point}</li>)}
                  </ul>
                ) : (
                  <><code>{fallbackNote.formula}</code><p>{fallbackNote.formulaHint}</p></>
                )}
              </div>
              <button aria-label="Mark key rules as remembered">✓</button>
            </section>
            <section id="example" className="note-section example-section">
              <span className="section-number">02</span>
              <div>
                <h2>Worked examples</h2>
                <div className="worked-example-list">
                  {workedExamples.map((example, index) => (
                    <article key={`${example.question}-${index}`}>
                      <span>Example {String(index + 1).padStart(2, "0")}</span>
                      <p className="example-title">{example.question}</p>
                      <p>{example.solution}</p>
                    </article>
                  ))}
                </div>
                <div className="answer-strip"><span>Exam habit</span>Sanity-check the units and boundary cases before choosing an answer.</div>
              </div>
            </section>
            <section className="trap-card"><div><span>!</span><h3>Common traps</h3></div><ul>{traps.map((trap) => <li key={trap}>{trap}</li>)}</ul></section>
            <section id="checkpoint" className="checkpoint-card">
              <div><span className="card-kicker">Active recall</span><h2>Close the note. Can you answer these?</h2></div>
              <div className="checkpoint-list">{checkpoints.map((check, index) => <details key={check}><summary><span>{index + 1}</span>{check}</summary><p>Say the rule in your own words, then verify it against the key rules and worked examples above.</p></details>)}</div>
              <button className="button primary" onClick={() => void startPractice("practice", selectedSubject, selectedTopic.id)}>I’m ready to practise <span>→</span></button>
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
    const practiceTopic = practiceTopicId
      ? selectedSubject.topics.find((topic) => topic.id === practiceTopicId)
      : null;
    const scopeLabel =
      runnerCatalogTest?.title ??
      (practiceMode === "syllabus"
        ? "Full official COA syllabus"
        : practiceTopic?.title ?? `${selectedSubject.shortTitle} mixed set`);
    const modeLabel =
      runnerCatalogTest
        ? `Course test · ${Math.round(runnerCatalogTest.durationSeconds / 60)} min plan`
        : practiceMode === "syllabus"
        ? "Syllabus quiz"
        : practiceMode === "sectional"
          ? "Sectional test"
          : "Guided practice";
    const immediateFeedback = practiceMode !== "sectional";
    const returnScreen: Screen =
      practiceMode === "syllabus"
        ? "dashboard"
        : runnerCatalogTest
          ? "library"
          : "subject";
    const returnLabel =
      practiceMode === "syllabus"
        ? "Return to roadmap"
        : runnerCatalogTest
          ? "Return to tests"
          : "Return to subject";

    if (runnerSummary) {
      return (
        <div className="page runner-complete-page">
          <section className="runner-complete-card">
            <span className="completion-mark">✓</span>
            <div className="eyebrow">{practiceMode === "syllabus" ? "COA syllabus quiz complete" : practiceMode === "sectional" ? "Section submitted" : "Practice complete"}</div>
            <h1>{runnerSummary.percentage >= 70 ? "Strong work. Keep the pattern." : "Good baseline. Review the misses."}</h1>
            <p>{selectedSubject.shortTitle} · {scopeLabel}</p>
            <div className="completion-score"><strong>{runnerSummary.score}</strong><span>/ {runnerSummary.maxScore}<small>{runnerSummary.percentage}% score</small></span></div>
            <div className="completion-stats"><span><strong>{runnerSummary.correct}</strong>Correct</span><span><strong>{runnerSummary.incorrect}</strong>Incorrect</span><span><strong>{runnerSummary.unanswered}</strong>Unanswered</span></div>
            <div className="completion-actions"><button className="button quiet" onClick={() => navigate(returnScreen)}>{returnLabel}</button><button className="button primary" onClick={() => { setRunnerSummary(null); setQuestionIndex(0); }}>Review answers →</button></div>
          </section>
        </div>
      );
    }
    const question = runnerQuestions[questionIndex];
    if (!question) {
      return (
        <div className="page empty-state">
          {isLoadingQuestions ? (
            <>
              <span className="spinner" />
              <h1>Preparing your set…</h1>
              <p>Curating questions for {scopeLabel}.</p>
            </>
          ) : (
            <>
              <h1>We could not open this set.</h1>
              <p>{launchError ?? "The question bank did not return a usable form."}</p>
              <button className="button primary" onClick={() => navigate(returnScreen)}>
                {returnLabel}
              </button>
            </>
          )}
        </div>
      );
    }
    const checked = checkedQuestions.has(question.id);
    const answer = practiceAnswers[question.id] ?? [];
    const correct = question.correct.length ? isExactAnswer(answer, question.correct) : false;
    const serverLocked = question.correct.length === 0;
    const answeredCount = Object.values(practiceAnswers).filter((value) => value.length).length;
    const questionTopicLabel =
      selectedSubject.topics.find((topic) => topic.id === question.topicId)?.title ??
      practiceTopic?.title ??
      selectedSubject.shortTitle;
    return (
      <div className="page runner-page">
        <div className="runner-topline">
          <button className="back-link" onClick={() => navigate(returnScreen)}>← Exit {practiceMode === "syllabus" ? "quiz" : practiceMode === "sectional" ? "test" : "practice"}</button>
          <div
            className="runner-progress"
            role="progressbar"
            aria-label="Quiz progress"
            aria-valuemin={1}
            aria-valuemax={runnerQuestions.length}
            aria-valuenow={questionIndex + 1}
          >
            <span style={{ width: `${((questionIndex + 1) / runnerQuestions.length) * 100}%` }} />
          </div>
          <span>{questionIndex + 1} / {runnerQuestions.length} · {answeredCount} answered</span>
        </div>
        {isLoadingQuestions && <div className="loading-banner" role="status"><span className="spinner" /> Checking the live question bank…</div>}
        {!isLoadingQuestions && launchError && (
          <div className="loading-banner warning" role="status">{launchError}</div>
        )}
        <div className="runner-layout">
          <section className="question-card">
            <header>
              <div><TypeBadge type={question.type} /><span className="question-meta">{question.marks} mark{question.marks > 1 ? "s" : ""}</span><span className="question-meta">{question.difficulty}</span><span className="question-topic">{questionTopicLabel}</span></div>
              <span className="source-tag">{question.year ? `GATE ${question.year}` : question.source}</span>
            </header>
            <div className="question-number">Question {String(questionIndex + 1).padStart(2, "0")}</div>
            <h1>{question.prompt}</h1>
            {question.type === "MSQ" && <p className="question-instruction">Select one or more options. No partial marks.</p>}
            {renderQuestionInput(question, practiceAnswers, "practice", checked && immediateFeedback)}
            {checked && (immediateFeedback || runnerSubmitted) && !serverLocked && (
              <div className={`explanation ${correct ? "correct" : "incorrect"}`} aria-live="polite">
                <div className="explanation-title"><span>{correct ? "✓" : "×"}</span><strong>{correct ? "Correct — well reasoned." : "Not quite. Review the reasoning."}</strong></div>
                <p>{question.explanation}</p>
                {question.correct.length > 0 && <small>Correct answer: {question.correct.join(", ")}</small>}
              </div>
            )}
            <footer>
              <button className="button quiet" disabled={questionIndex === 0} onClick={() => setQuestionIndex((index) => Math.max(0, index - 1))}>← Previous</button>
              {immediateFeedback && !checked && !serverLocked ? (
                <button className="button primary" disabled={!answer.length} onClick={() => setCheckedQuestions((current) => new Set(current).add(question.id))}>Check answer</button>
              ) : questionIndex < runnerQuestions.length - 1 ? (
                <button className="button primary" onClick={() => setQuestionIndex((index) => index + 1)}>Next question →</button>
              ) : runnerSubmitted ? (
                <button className="button primary" onClick={() => navigate(returnScreen)}>{returnLabel} →</button>
              ) : (
                <button className="button primary" disabled={submitBusy} onClick={() => void submitRunner()}>{submitBusy ? "Scoring…" : practiceMode === "sectional" ? "Submit section" : practiceMode === "syllabus" ? "Finish quiz" : serverLocked ? "Finish & reveal" : "Finish set"} →</button>
              )}
            </footer>
          </section>
          <aside className="runner-aside">
            <div className="set-card"><span className="eyebrow">Current set</span><h2>{scopeLabel}</h2><p>{modeLabel}</p><div className="set-score"><strong>{answeredCount}</strong><span>of {runnerQuestions.length}<small>answered</small></span></div></div>
            <div className="question-dots" aria-label="Question navigator">{runnerQuestions.map((item, index) => <button key={item.id} className={`${index === questionIndex ? "current" : ""} ${practiceAnswers[item.id]?.length ? "answered" : ""}`} onClick={() => setQuestionIndex(index)} aria-current={index === questionIndex ? "step" : undefined} aria-label={`Question ${index + 1}${practiceAnswers[item.id]?.length ? ", answered" : ""}`}>{index + 1}</button>)}</div>
            <div className="type-guide"><div><TypeBadge type="MCQ" /><span>One correct option</span></div><div><TypeBadge type="MSQ" /><span>One or more correct</span></div><div><TypeBadge type="NAT" /><span>Numerical answer</span></div></div>
          </aside>
        </div>
      </div>
    );
  };

  const renderMockSetup = () => {
    const setupTest =
      activeTest.kind === "full" && activeTest.isAvailable
        ? activeTest
        : fullTests.find((test) => test.isAvailable) ??
          fullTests[0] ??
          LOCAL_FULL_TESTS[0];
    return (
      <div className="page mock-setup-page">
        <section className="mock-hero">
          <div className="mock-hero-copy">
            <div className="eyebrow light-text">
              Full-length simulation · Set{" "}
              {String(setupTest.sequence).padStart(2, "0")}
            </div>
            <h1>
              Three hours.
              <br />
              One honest baseline.
            </h1>
            <p>
              Practise the official GATE rhythm with a calm interface, a
              faithful marking scheme and a detailed review at the end.
            </p>
            <div className="mock-hero-actions">
              <button
                className="button light"
                onClick={() => void beginMock(setupTest)}
                disabled={!setupTest.isAvailable}
                title={setupTest.unavailableReason}
              >
                {setupTest.isAvailable
                  ? "Begin full mock"
                  : "Connect question bank"}{" "}
                <span>→</span>
              </button>
              <button
                className="button ghost-light"
                onClick={() => {
                  setLibraryTab("full");
                  navigate("library");
                }}
              >
                Choose from all 25
              </button>
            </div>
          </div>
          <div className="mock-ticket">
            <div className="ticket-top">
              <span>GATE</span>
              <strong>CS · 2027</strong>
            </div>
            <div className="ticket-main">
              <span>Duration</span>
              <strong>{formatTime(setupTest.durationSeconds)}</strong>
              <div>
                <span>
                  <b>{setupTest.questionCount}</b> questions
                </span>
                <span>
                  <b>{setupTest.totalMarks}</b> marks
                </span>
              </div>
            </div>
            <div className="ticket-code">
              FULL MOCK · {String(setupTest.sequence).padStart(2, "0")} ·
              OFFICIAL FORMAT
            </div>
          </div>
        </section>
        <section className="mock-info-grid">
          <div className="instruction-card">
            <div className="panel-heading">
              <div>
                <span className="eyebrow">Before you begin</span>
                <h2>Exam instructions</h2>
              </div>
              <span>Read carefully</span>
            </div>
            <ol>
              <li>
                <span>01</span>
                <p>
                  <strong>The paper has exactly 65 questions.</strong>
                  <small>
                    10 General Aptitude questions and 55 subject questions.
                  </small>
                </p>
              </li>
              <li>
                <span>02</span>
                <p>
                  <strong>MCQ, MSQ and NAT are included.</strong>
                  <small>Questions carry either 1 or 2 marks.</small>
                </p>
              </li>
              <li>
                <span>03</span>
                <p>
                  <strong>Negative marks apply only to MCQ.</strong>
                  <small>
                    −⅓ for an incorrect 1-mark MCQ; −⅔ for an incorrect 2-mark
                    MCQ.
                  </small>
                </p>
              </li>
              <li>
                <span>04</span>
                <p>
                  <strong>No partial marking for MSQ.</strong>
                  <small>MSQ and NAT have no negative marking.</small>
                </p>
              </li>
            </ol>
          </div>
          <aside className="readiness-card">
            <span className="eyebrow">Readiness check</span>
            <h2>Set yourself up for focus.</h2>
            <label>
              <input type="checkbox" defaultChecked />
              <span>
                <strong>Quiet three-hour window</strong>
                <small>Notifications off, phone away</small>
              </span>
            </label>
            <label>
              <input type="checkbox" defaultChecked />
              <span>
                <strong>Rough sheets ready</strong>
                <small>Use only the on-screen calculator</small>
              </span>
            </label>
            <label>
              <input type="checkbox" />
              <span>
                <strong>I will finish in one sitting</strong>
                <small>The timer cannot be paused</small>
              </span>
            </label>
            <div className="offline-ready">
              <span>{setupTest.isAvailable ? "✓" : "!"}</span>
              <p>
                <strong>
                  {setupTest.isAvailable
                    ? "Validated form ready"
                    : "Question bank required"}
                </strong>
                <small>
                  {setupTest.isAvailable
                    ? "The complete 65-question form is ready to launch."
                    : "Full tests launch only after all 65 questions are validated."}
                </small>
              </p>
            </div>
          </aside>
        </section>
      </div>
    );
  };

  const renderMock = () => {
    const question = examQuestions[examIndex];
    if (!question) {
      return (
        <div className="page empty-state">
          {isLoadingQuestions ? (
            <>
              <span className="spinner" />
              <h1>Preparing the full test…</h1>
              <p>Validating all {activeTest.questionCount} questions before the timer starts.</p>
            </>
          ) : (
            <>
              <h1>We could not open this test.</h1>
              <p>{launchError ?? "The question bank did not return a complete form."}</p>
              <button
                className="button primary"
                onClick={() => {
                  setLibraryTab("full");
                  navigate("library");
                }}
              >
                Return to full tests
              </button>
            </>
          )}
        </div>
      );
    }
    const answered = Object.values(examAnswers).filter((answer) => answer.length).length;
    const marked = reviewed.size;
    return (
      <div className="exam-shell">
        <header className="exam-header"><div className="exam-brand"><span>G</span><div><strong>GATE CS · Full mock {String(activeTest.sequence).padStart(2, "0")}</strong><small>Official-format simulation</small></div></div><div className={`exam-clock ${examSeconds < 900 ? "warning" : ""}`}><span>Time remaining</span><strong>{formatTime(examSeconds)}</strong></div><button className="button danger" onClick={() => void submitExam()} disabled={submitBusy}>{submitBusy ? "Submitting…" : "Submit test"}</button></header>
        {launchError && <div className="loading-banner warning" role="alert">{launchError}</div>}
        <div className="exam-body">
          <main className="exam-question">
            <div className="exam-section-bar"><div><span>{examIndex < 10 ? "General Aptitude" : "Computer Science"}</span><strong>Question {examIndex + 1} of {examQuestions.length}</strong></div><div><TypeBadge type={question.type} /><span>{question.marks} mark{question.marks > 1 ? "s" : ""}</span></div></div>
            <article>
              <h1>{question.prompt}</h1>
              {question.type === "MSQ" && <p className="question-instruction">Select one or more options. No partial marks and no negative marks.</p>}
              {renderQuestionInput(question, examAnswers, "exam")}
            </article>
            <footer><button className={`button review-button ${reviewed.has(question.id) ? "active" : ""}`} onClick={() => setReviewed((current) => { const next = new Set(current); if (next.has(question.id)) next.delete(question.id); else next.add(question.id); return next; })}>{reviewed.has(question.id) ? "✓ Marked for review" : "◇ Mark for review"}</button><div><button className="button quiet" disabled={examIndex === 0} onClick={() => setExamIndex((index) => index - 1)}>← Previous</button><button className="button primary" disabled={examIndex === examQuestions.length - 1} onClick={() => setExamIndex((index) => Math.min(examQuestions.length - 1, index + 1))}>Save & next →</button></div></footer>
          </main>
          <aside className="exam-palette"><div className="palette-summary"><div><strong>{answered}</strong><span>Answered</span></div><div><strong>{examQuestions.length - answered}</strong><span>Not answered</span></div><div><strong>{marked}</strong><span>Review</span></div></div><div className="palette-heading"><strong>Question palette</strong><span>{examQuestions.length} total</span></div><div className="palette-groups"><div><span>General Aptitude</span><div>{examQuestions.slice(0, 10).map((item, index) => <button key={item.id} onClick={() => setExamIndex(index)} className={`${index === examIndex ? "current" : ""} ${examAnswers[item.id]?.length ? "answered" : ""} ${reviewed.has(item.id) ? "reviewed" : ""}`}>{index + 1}</button>)}</div></div><div><span>Computer Science</span><div>{examQuestions.slice(10).map((item, index) => { const absolute = index + 10; return <button key={item.id} onClick={() => setExamIndex(absolute)} className={`${absolute === examIndex ? "current" : ""} ${examAnswers[item.id]?.length ? "answered" : ""} ${reviewed.has(item.id) ? "reviewed" : ""}`}>{absolute + 1}</button>; })}</div></div></div><div className="palette-legend"><span><i className="answered" /> Answered</span><span><i className="reviewed" /> Review</span><span><i /> Not visited</span></div></aside>
        </div>
      </div>
    );
  };

  const renderResults = () => (
    <div className="page results-page">
      <section className="result-hero"><div><div className="eyebrow">Full mock {String(activeTest.sequence).padStart(2, "0")} · complete</div><h1>A useful baseline.<br /><em>Now make it actionable.</em></h1><p>Your score is less important than the pattern behind it. Start with accuracy, then revisit the chapters that cost the most marks.</p></div><div className="score-disc" style={{ "--score": `${Math.max(0, result.percentage) * 3.6}deg` } as React.CSSProperties}><span><strong>{result.score}</strong><small>/ {result.maxScore}</small></span></div></section>
      <section className="result-metrics"><div><span className="metric-label">Accuracy</span><strong>{result.correct + result.incorrect ? Math.round((result.correct / (result.correct + result.incorrect)) * 100) : 0}%</strong><small>{result.correct} correct answers</small></div><div><span className="metric-label">Attempted</span><strong>{result.correct + result.incorrect}<small>/{examQuestions.length}</small></strong><small>{result.unanswered} left unanswered</small></div><div><span className="metric-label">Time used</span><strong>{formatTime(activeTest.durationSeconds - examSeconds)}</strong><small>{formatTime(examSeconds)} remaining</small></div><div><span className="metric-label">Negative marks</span><strong>−{Math.max(0, result.correct * 0 + (result.incorrect > 0 ? Math.min(result.incorrect / 3, 9.99) : 0)).toFixed(2)}</strong><small>MCQ only</small></div></section>
      <section className="analysis-grid"><div className="performance-card"><div className="panel-heading"><div><span className="eyebrow">Subject breakdown</span><h2>Where marks moved</h2></div><span>Accuracy</span></div><div className="performance-list">{roadmapSubjects.slice(0, 7).map((subject, index) => { const accuracy = Math.max(28, Math.min(92, subject.mastery - (index % 3) * 6)); return <div key={subject.id}><span className="performance-code" style={{ background: subject.accent }}>{subject.code}</span><span><strong>{subject.shortTitle}</strong><small>{Math.max(1, 7 - index)} attempted</small></span><div><MiniProgress value={accuracy} /><b>{accuracy}%</b></div></div>; })}</div></div><aside className="next-actions"><span className="eyebrow">Recommended next</span><h2>Turn misses into a plan.</h2><button onClick={() => { setSelectedSubjectId("computer-organization"); setSelectedTopicId("memory-hierarchy"); navigate("notes"); }}><span>01</span><p><strong>Revise cache mapping</strong><small>3 questions lost · 12 min</small></p><b>→</b></button><button onClick={() => { const subject = roadmapSubjects.find((item) => item.id === "algorithms") ?? selectedSubject; setSelectedSubjectId(subject.id); setSelectedTopicId("graph-algorithms"); void startPractice("practice", subject, "graph-algorithms"); }}><span>02</span><p><strong>Practise graph algorithms</strong><small>Focused set · 8 questions</small></p><b>→</b></button><button onClick={() => navigate("progress")}><span>03</span><p><strong>Review full progress</strong><small>Compare recent mock trends</small></p><b>→</b></button><button className="button primary full" onClick={() => navigate("dashboard")}>Return to roadmap</button></aside></section>
    </div>
  );

  const renderProgress = () => {
    const maxMinutes = Math.max(...weeklyActivity.map((item) => item.minutes));
    const strongest = strongTopics;
    const priorities =
      needsPracticeTopics.length > 0
        ? needsPracticeTopics
        : [...analytics.topics]
            .sort((a, b) => a.mastery - b.mastery)
            .slice(0, 5);
    return (
      <div className="page progress-page">
        <section className="progress-heading">
          <div>
            <div className="eyebrow">Learning signals</div>
            <h1>Know what is strong. Fix what is not.</h1>
            <p>
              Every recommendation below is tied to three pieces of evidence:
              accuracy, attempts and syllabus coverage.
            </p>
          </div>
          <span className={`insight-source ${analyticsSource}`}>
            <i />
            {analyticsSource === "live"
              ? "Updated from your attempts"
              : "Local profile preview"}
          </span>
        </section>

        <section className="progress-metrics">
          <div>
            <span>Questions attempted</span>
            <strong>{analytics.uniqueQuestionsAttempted.toLocaleString()}</strong>
            <p>{analytics.attemptedResponses.toLocaleString()} total responses</p>
          </div>
          <div>
            <span>Overall accuracy</span>
            <strong>{analytics.accuracy}%</strong>
            <p>Across answered questions</p>
          </div>
          <div>
            <span>Syllabus coverage</span>
            <strong>{analytics.coverage}%</strong>
            <p>{analytics.topics.length} topics measured</p>
          </div>
          <div>
            <span>Question bank</span>
            <strong>{analytics.availableQuestions.toLocaleString()}</strong>
            <p>{analytics.mastery}% current mastery score</p>
          </div>
        </section>

        <section className="strength-grid" aria-label="Topic recommendations">
          <div className="strength-card strong">
            <div className="strength-heading">
              <div>
                <span className="eyebrow">Strong topics</span>
                <h2>Protect these gains</h2>
              </div>
              <span>{strongest.length} signals</span>
            </div>
            <div className="insight-topic-list">
              {strongest.length === 0 && (
                <div className="insight-empty">
                  <strong>No strong topic yet</strong>
                  <span>
                    Complete at least three distinct questions in a topic to
                    build a reliable strength signal.
                  </span>
                </div>
              )}
              {strongest.map((topic) => (
                <article key={`${topic.subjectId}-${topic.topicId}`}>
                  <span className="insight-code">{topic.subjectCode}</span>
                  <div className="insight-copy">
                    <span>{topic.subjectName}</span>
                    <h3>{topic.topicName}</h3>
                    <div className="evidence-row">
                      <span>
                        <strong>{topic.accuracy}%</strong> accuracy
                      </span>
                      <span>
                        <strong>{topic.uniqueAttempted}</strong> attempted
                      </span>
                      <span>
                        <strong>{topic.coverage}%</strong> coverage
                      </span>
                    </div>
                  </div>
                  <button
                    aria-label={`Practise ${topic.topicName}`}
                    onClick={() => openAnalyticsTopic(topic, "practice")}
                  >
                    Maintain <span>→</span>
                  </button>
                </article>
              ))}
            </div>
          </div>

          <div className="strength-card needs">
            <div className="strength-heading">
              <div>
                <span className="eyebrow">Needs practice</span>
                <h2>Best next moves</h2>
              </div>
              <span>{priorities.length} priorities</span>
            </div>
            <div className="insight-topic-list">
              {priorities.map((topic) => (
                <article key={`${topic.subjectId}-${topic.topicId}`}>
                  <span className="insight-code">{topic.subjectCode}</span>
                  <div className="insight-copy">
                    <span>{topic.subjectName}</span>
                    <h3>{topic.topicName}</h3>
                    <div className="evidence-row">
                      <span>
                        <strong>{topic.accuracy}%</strong> accuracy
                      </span>
                      <span>
                        <strong>{topic.uniqueAttempted}</strong> attempted
                      </span>
                      <span>
                        <strong>{topic.coverage}%</strong> coverage
                      </span>
                    </div>
                  </div>
                  <div className="insight-actions">
                    <button
                      onClick={() => openAnalyticsTopic(topic, "revise")}
                    >
                      Revise
                    </button>
                    <button
                      onClick={() => openAnalyticsTopic(topic, "practice")}
                    >
                      Practise <span>→</span>
                    </button>
                  </div>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section className="analytics-detail-grid">
          <div className="topic-evidence-card">
            <div className="panel-heading evidence-heading">
              <div>
                <span className="eyebrow">Topic evidence</span>
                <h2>Lowest mastery first</h2>
              </div>
              <label>
                <span className="sr-only">Filter analytics by course</span>
                <select
                  value={progressSubjectId}
                  onChange={(event) =>
                    setProgressSubjectId(event.target.value)
                  }
                >
                  <option value="all">All courses</option>
                  {roadmapSubjects.map((subject) => (
                    <option value={subject.id} key={subject.id}>
                      {subject.code} · {subject.shortTitle}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="evidence-table">
              <div className="evidence-table-head" aria-hidden="true">
                <span>Topic</span>
                <span>Accuracy</span>
                <span>Attempts</span>
                <span>Coverage</span>
                <span>Status</span>
              </div>
              {filteredAnalyticsTopics.slice(0, 12).map((topic) => (
                <button
                  key={`${topic.subjectId}-${topic.topicId}`}
                  aria-label={`${topic.subjectCode} ${topic.topicName}: ${topic.accuracy}% accuracy, ${topic.uniqueAttempted} unique questions attempted, ${topic.coverage}% coverage, status ${topic.status.replace("_", " ")}. Start practice.`}
                  onClick={() => openAnalyticsTopic(topic, "practice")}
                >
                  <span>
                    <i>{topic.subjectCode}</i>
                    <strong>{topic.topicName}</strong>
                  </span>
                  <b>{topic.accuracy}%</b>
                  <b>{topic.uniqueAttempted}</b>
                  <b>{topic.coverage}%</b>
                  <em className={`status-${topic.status}`}>
                    {topic.status === "needs_practice"
                      ? "Needs practice"
                      : topic.status === "unattempted"
                        ? "Not started"
                        : topic.status}
                  </em>
                </button>
              ))}
            </div>
          </div>

          <div className="activity-card compact-activity">
            <div className="panel-heading">
              <div>
                <span className="eyebrow">Study rhythm</span>
                <h2>This week</h2>
              </div>
              <strong>9h 09m</strong>
            </div>
            <div className="bar-chart">
              {weeklyActivity.map((item, index) => (
                <div key={`${item.day}-${index}`}>
                  <span className="bar-value">{item.minutes}m</span>
                  <div className="bar-track">
                    <i
                      style={{
                        height: `${(item.minutes / maxMinutes) * 100}%`,
                      }}
                    />
                  </div>
                  <b>{item.day}</b>
                </div>
              ))}
            </div>
            <div className="chart-note">
              <span>→</span>
              <p>
                <strong>Start with the first priority above.</strong>
                <small>
                  One revision block, then a focused question set.
                </small>
              </p>
            </div>
          </div>
        </section>
      </div>
    );
  };

  if (screen === "mock") return renderMock();

  return (
    <div className="app-shell">
      <button className="mobile-menu" onClick={() => setMobileNavOpen((open) => !open)} aria-expanded={mobileNavOpen} aria-controls="primary-sidebar" aria-label={`${mobileNavOpen ? "Close" : "Open"} navigation`}>{mobileNavOpen ? "×" : "≡"}</button>
      <aside id="primary-sidebar" className={`sidebar ${mobileNavOpen ? "open" : ""}`}>
        <button className="brand" onClick={() => navigate("dashboard")}><span className="brand-mark">G</span><span><strong>Gatepath</strong><small>2027 · CSE</small></span></button>
        <nav aria-label="Primary navigation">
          <button className={activeNav === "dashboard" ? "active" : ""} onClick={() => navigate("dashboard")}><span className="nav-icon">⌂</span><span>Roadmap</span></button>
          <button className={activeNav === "library" ? "active" : ""} onClick={() => navigate("library")}><span className="nav-icon">▦</span><span>Test library</span><em>125</em></button>
          <button className={activeNav === "mock-setup" ? "active" : ""} onClick={() => navigate("mock-setup")}><span className="nav-icon">◷</span><span>Full mock</span><em>65</em></button>
          <button className={activeNav === "progress" ? "active" : ""} onClick={() => navigate("progress")}><span className="nav-icon">↗</span><span>Progress</span></button>
        </nav>
        <div className="sidebar-spacer" />
        <div className="sidebar-target"><span className="target-label">Weekly target</span><div><strong>9h 09m</strong><span>of 12 hours</span></div><MiniProgress value={76} /><small>2h 51m to go</small></div>
        <button className="profile"><span>IS</span><span><strong>Your study space</strong><small>Local profile</small></span><i>···</i></button>
      </aside>
      {mobileNavOpen && <button className="nav-scrim" aria-label="Close navigation" onClick={() => setMobileNavOpen(false)} />}
      <div className="content-shell">
        <header className="topbar"><div><span className="topbar-kicker">GATE 2027 · Computer Science</span><strong>{headerTitle}</strong></div><div className="topbar-actions"><span className={`api-status ${apiState}`}><i />{apiState === "online" ? "Synced" : apiState === "checking" ? "Connecting" : "Local mode"}</span><button className="theme-toggle" aria-label={`Switch to ${theme === "light" ? "dark" : "light"} mode`} onClick={() => setTheme((current) => current === "light" ? "dark" : "light")}><span className={theme === "light" ? "active" : ""}>☼</span><span className={theme === "dark" ? "active" : ""}>◐</span></button></div></header>
        <main>{screen === "dashboard" && renderDashboard()}{screen === "library" && renderLibrary()}{screen === "subject" && renderSubject()}{screen === "notes" && renderNotes()}{screen === "practice" && renderPractice()}{screen === "mock-setup" && renderMockSetup()}{screen === "results" && renderResults()}{screen === "progress" && renderProgress()}</main>
        <nav className="mobile-bottom-nav" aria-label="Mobile navigation">
          <button className={activeNav === "dashboard" ? "active" : ""} onClick={() => navigate("dashboard")}><span>⌂</span>Roadmap</button>
          <button className={activeNav === "library" ? "active" : ""} onClick={() => navigate("library")}><span>▦</span>Tests</button>
          <button className={activeNav === "mock-setup" ? "active" : ""} onClick={() => navigate("mock-setup")}><span>◷</span>Mock</button>
          <button className={activeNav === "progress" ? "active" : ""} onClick={() => navigate("progress")}><span>↗</span>Progress</button>
        </nav>
      </div>
    </div>
  );
}
