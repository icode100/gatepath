export type NumericalAnswerRange = {
  min: number;
  max: number;
};

export type NumericalAnswerWithTolerance = {
  value: number;
  tolerance?: number;
};

export type AcceptedAnswer =
  | string
  | number
  | string[]
  | NumericalAnswerRange
  | NumericalAnswerWithTolerance;

export type QuestionReviewStatus = "correct" | "incorrect" | "unanswered";

export type QuestionReview = {
  status: QuestionReviewStatus;
  acceptedAnswer?: AcceptedAnswer;
  explanation?: string;
};

type AttemptReviewRow = {
  question_id?: unknown;
  correct_answer?: unknown;
  explanation?: unknown;
  status?: unknown;
};

type ReviewableQuestion = {
  id: string;
  type: string;
  correct: string[];
  explanation: string;
  acceptedAnswer?: AcceptedAnswer;
  reviewStatus?: QuestionReviewStatus;
};

const finiteNumber = (value: unknown): number | undefined =>
  typeof value === "number" && Number.isFinite(value) ? value : undefined;

export function normalizeReviewStatus(
  value: unknown,
): QuestionReviewStatus | undefined {
  return value === "correct" || value === "incorrect" || value === "unanswered"
    ? value
    : undefined;
}

export function normalizeAcceptedAnswer(
  value: unknown,
): AcceptedAnswer | undefined {
  if (typeof value === "string") {
    const trimmed = value.trim();
    return trimmed || undefined;
  }
  const numeric = finiteNumber(value);
  if (numeric !== undefined) return numeric;
  if (Array.isArray(value)) {
    const options = value
      .filter(
        (item): item is string | number =>
          typeof item === "string" ||
          (typeof item === "number" && Number.isFinite(item)),
      )
      .map((item) => String(item).trim())
      .filter(Boolean);
    return options.length === value.length && options.length > 0
      ? options
      : undefined;
  }
  if (!value || typeof value !== "object") return undefined;
  const record = value as Record<string, unknown>;
  const min = finiteNumber(record.min);
  const max = finiteNumber(record.max);
  if (min !== undefined || max !== undefined) {
    return min !== undefined && max !== undefined && min <= max
      ? { min, max }
      : undefined;
  }
  const expected = finiteNumber(record.value);
  if (expected === undefined) return undefined;
  if (record.tolerance === undefined) return { value: expected };
  const tolerance = finiteNumber(record.tolerance);
  return tolerance !== undefined && tolerance >= 0
    ? { value: expected, tolerance }
    : undefined;
}

const displayNumber = (value: number) =>
  Object.is(value, -0) ? "0" : String(value);

export function formatAcceptedAnswer(value: unknown): string {
  const answer = normalizeAcceptedAnswer(value);
  if (answer === undefined) return "Unavailable";
  if (typeof answer === "string") return answer;
  if (typeof answer === "number") return displayNumber(answer);
  if (Array.isArray(answer)) return answer.join(", ");
  if ("min" in answer) {
    return answer.min === answer.max
      ? displayNumber(answer.min)
      : `${displayNumber(answer.min)} to ${displayNumber(answer.max)} (inclusive)`;
  }
  if (!answer.tolerance) return displayNumber(answer.value);
  return `${displayNumber(answer.value)} ± ${displayNumber(answer.tolerance)}`;
}

export function questionReviewsFromAttemptRows(
  rows: readonly AttemptReviewRow[] | undefined,
): Record<string, QuestionReview> {
  const reviews: Record<string, QuestionReview> = {};
  for (const row of rows ?? []) {
    if (
      (typeof row.question_id !== "string" &&
        typeof row.question_id !== "number") ||
      String(row.question_id).trim() === ""
    ) {
      continue;
    }
    const status = normalizeReviewStatus(row.status);
    if (!status) continue;
    const acceptedAnswer = normalizeAcceptedAnswer(row.correct_answer);
    reviews[String(row.question_id)] = {
      status,
      ...(acceptedAnswer === undefined ? {} : { acceptedAnswer }),
      ...(typeof row.explanation === "string" && row.explanation.trim()
        ? { explanation: row.explanation }
        : {}),
    };
  }
  return reviews;
}

export function applyQuestionReviews<T extends ReviewableQuestion>(
  questions: readonly T[],
  reviews: Readonly<Record<string, QuestionReview>>,
): T[] {
  return questions.map((question) => {
    const review = reviews[question.id];
    if (!review) return question;
    const acceptedOptions =
      question.type === "NAT"
        ? undefined
        : Array.isArray(review.acceptedAnswer)
          ? review.acceptedAnswer
          : typeof review.acceptedAnswer === "string"
            ? [review.acceptedAnswer]
            : undefined;
    return {
      ...question,
      correct: acceptedOptions ?? question.correct,
      acceptedAnswer: review.acceptedAnswer,
      reviewStatus: review.status,
      explanation: review.explanation ?? question.explanation,
    };
  });
}

export function resolveReviewCorrectness(
  status: QuestionReviewStatus | undefined,
  clientExactMatch: boolean,
): boolean {
  if (status === "correct") return true;
  if (status === "incorrect" || status === "unanswered") return false;
  return clientExactMatch;
}
