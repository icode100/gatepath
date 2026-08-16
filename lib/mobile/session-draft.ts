import {
  normalizeQuestionAssets,
  type QuestionAsset,
} from "../question-assets";

const DRAFT_VERSION = 1;
const DRAFT_PREFIX = "gatepath:session-draft:";
const ACTIVE_OWNER_KEY = "gatepath:session-draft-owner";
const GUEST_DEVICE_KEY = "gatepath:guest-device-id";

export type DraftQuestion = {
  id: string;
  subjectId: string;
  topicId: string;
  type: "MCQ" | "MSQ" | "NAT";
  marks: 1 | 2;
  prompt: string;
  options?: Array<{ id: string; label: string }>;
  source?: string;
  year?: number;
  difficulty: "Easy" | "Medium" | "Hard";
  assets?: QuestionAsset[];
};

export type DraftTest = {
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
  questionTypeCounts: Record<"mcq" | "msq" | "nat", number>;
  isAvailable: boolean;
  unavailableReason?: string;
};

export type SessionDraft = {
  version: typeof DRAFT_VERSION;
  ownerKey: string;
  savedAt: number;
  kind: "practice" | "mock";
  sessionId: string | null;
  questions: DraftQuestion[];
  answers: Record<string, string[]>;
  currentIndex: number;
  reviewedQuestionIds: string[];
  deadlineMs: number | null;
  selectedSubjectId: string;
  selectedTopicId: string;
  practiceMode?: "practice" | "sectional" | "syllabus";
  practiceTopicId?: string | null;
  test?: DraftTest;
};

const storage = () => {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
};

const draftKey = (ownerKey: string) =>
  `${DRAFT_PREFIX}${encodeURIComponent(ownerKey)}`;

function newGuestDeviceId() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

/** Returns a stable, non-secret storage namespace for the current identity. */
export function sessionDraftOwnerKey(firebaseUid?: string | null): string | null {
  const store = storage();
  if (!store) return null;
  if (firebaseUid?.trim()) return `user:${firebaseUid.trim()}`;

  let deviceId = store.getItem(GUEST_DEVICE_KEY);
  if (!deviceId) {
    deviceId = newGuestDeviceId();
    store.setItem(GUEST_DEVICE_KEY, deviceId);
  }
  return `guest:${deviceId}`;
}

export function activeSessionDraftOwnerKey(): string | null {
  try {
    return storage()?.getItem(ACTIVE_OWNER_KEY) ?? null;
  } catch {
    return null;
  }
}

/**
 * Marks an identity as active and deletes any other identity's unfinished
 * draft. This prevents account switches from exposing a previous learner's
 * answers on the same device.
 */
export function activateSessionDraftOwner(ownerKey: string): void {
  const store = storage();
  if (!store) return;
  try {
    const previousOwner = store.getItem(ACTIVE_OWNER_KEY);
    if (previousOwner && previousOwner !== ownerKey) {
      store.removeItem(draftKey(previousOwner));
    }
    store.setItem(ACTIVE_OWNER_KEY, ownerKey);
  } catch {
    // Recovery is optional and must never interrupt studying or sign-in.
  }
}

export function clearSessionDraft(ownerKey: string | null): void {
  if (!ownerKey) return;
  try {
    storage()?.removeItem(draftKey(ownerKey));
  } catch {
    // Best-effort cleanup only.
  }
}

function safeStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((item): item is string => typeof item === "string")
    .slice(0, 100);
}

function safeAnswers(value: unknown): Record<string, string[]> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  const result: Record<string, string[]> = {};
  for (const [questionId, answer] of Object.entries(value)) {
    if (
      !questionId ||
      questionId === "__proto__" ||
      questionId === "constructor" ||
      questionId === "prototype"
    ) {
      continue;
    }
    result[questionId] = safeStringArray(answer).slice(0, 20);
  }
  return result;
}

function safeQuestions(value: unknown): DraftQuestion[] {
  if (!Array.isArray(value)) return [];
  const result: DraftQuestion[] = [];
  for (const item of value.slice(0, 100)) {
    if (!item || typeof item !== "object" || Array.isArray(item)) continue;
    const question = item as Partial<DraftQuestion>;
    if (
      typeof question.id !== "string" ||
      !question.id ||
      typeof question.subjectId !== "string" ||
      typeof question.topicId !== "string" ||
      typeof question.prompt !== "string" ||
      !["MCQ", "MSQ", "NAT"].includes(String(question.type)) ||
      (question.marks !== 1 && question.marks !== 2) ||
      !["Easy", "Medium", "Hard"].includes(String(question.difficulty))
    ) {
      continue;
    }
    const options = Array.isArray(question.options)
      ? question.options
          .filter(
            (option): option is { id: string; label: string } =>
              Boolean(option) &&
              typeof option === "object" &&
              typeof option.id === "string" &&
              typeof option.label === "string",
          )
          .slice(0, 20)
          .map((option) => ({ id: option.id, label: option.label }))
      : undefined;
    const assets = normalizeQuestionAssets(question.assets);
    result.push({
      id: question.id,
      subjectId: question.subjectId,
      topicId: question.topicId,
      type: question.type as DraftQuestion["type"],
      marks: question.marks,
      prompt: question.prompt,
      options,
      source: typeof question.source === "string" ? question.source : undefined,
      year:
        typeof question.year === "number" && Number.isFinite(question.year)
          ? question.year
          : undefined,
      difficulty: question.difficulty as DraftQuestion["difficulty"],
      assets: assets.length ? assets : undefined,
    });
  }
  return result;
}

function isDraft(value: unknown, ownerKey: string): value is SessionDraft {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const draft = value as Partial<SessionDraft>;
  return (
    draft.version === DRAFT_VERSION &&
    draft.ownerKey === ownerKey &&
    (draft.kind === "practice" || draft.kind === "mock") &&
    (draft.sessionId === null ||
      (typeof draft.sessionId === "string" && Boolean(draft.sessionId))) &&
    safeQuestions(draft.questions).length > 0 &&
    typeof draft.selectedSubjectId === "string" &&
    typeof draft.selectedTopicId === "string"
  );
}

export function readSessionDraft(ownerKey: string): SessionDraft | null {
  const store = storage();
  if (!store) return null;
  try {
    const raw = store.getItem(draftKey(ownerKey));
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (!isDraft(parsed, ownerKey)) {
      store.removeItem(draftKey(ownerKey));
      return null;
    }
    return {
      ...parsed,
      questions: safeQuestions(parsed.questions),
      answers: safeAnswers(parsed.answers),
      reviewedQuestionIds: safeStringArray(parsed.reviewedQuestionIds),
      currentIndex: Number.isFinite(parsed.currentIndex)
        ? Math.max(0, Math.floor(parsed.currentIndex))
        : 0,
      deadlineMs:
        typeof parsed.deadlineMs === "number" && Number.isFinite(parsed.deadlineMs)
          ? parsed.deadlineMs
          : null,
    };
  } catch {
    try {
      store.removeItem(draftKey(ownerKey));
    } catch {
      // Ignore storage cleanup failures.
    }
    return null;
  }
}

export function writeSessionDraft(draft: SessionDraft): void {
  const store = storage();
  if (!store || !draft.questions.length) return;
  try {
    // The schema intentionally has no token, correct-answer, explanation or
    // result fields. Keep this explicit projection when the schema evolves.
    const safeDraft: SessionDraft = {
      version: DRAFT_VERSION,
      ownerKey: draft.ownerKey,
      savedAt: Date.now(),
      kind: draft.kind,
      sessionId: draft.sessionId,
      questions: draft.questions.slice(0, 100),
      answers: safeAnswers(draft.answers),
      currentIndex: Math.max(0, Math.floor(draft.currentIndex)),
      reviewedQuestionIds: safeStringArray(draft.reviewedQuestionIds),
      deadlineMs: draft.deadlineMs,
      selectedSubjectId: draft.selectedSubjectId,
      selectedTopicId: draft.selectedTopicId,
      practiceMode: draft.practiceMode,
      practiceTopicId: draft.practiceTopicId,
      test: draft.test,
    };
    store.setItem(draftKey(draft.ownerKey), JSON.stringify(safeDraft));
  } catch {
    // Quota and privacy-mode failures leave the online experience unchanged.
  }
}
