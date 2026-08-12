const IST_OFFSET_MS = 5.5 * 60 * 60 * 1000;
const DAY_MS = 24 * 60 * 60 * 1000;

export type DailyFocusCandidate = {
  key: string;
};

const positiveModulo = (value: number, modulus: number) =>
  ((value % modulus) + modulus) % modulus;

const timestampOf = (value: Date | number) =>
  value instanceof Date ? value.getTime() : value;

/** A stable calendar-day number whose boundary is midnight in India. */
export function istDayNumber(value: Date | number = Date.now()): number {
  return Math.floor((timestampOf(value) + IST_OFFSET_MS) / DAY_MS);
}

/** Milliseconds until the next 00:00:00 IST boundary. */
export function millisecondsUntilNextIstMidnight(
  value: Date | number = Date.now(),
): number {
  const shifted = timestampOf(value) + IST_OFFSET_MS;
  const elapsedToday = positiveModulo(shifted, DAY_MS);
  return elapsedToday === 0 ? DAY_MS : DAY_MS - elapsedToday;
}

function hashSeed(value: string): number {
  let hash = 0x811c9dc5;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return hash >>> 0;
}

function seededRandom(seed: number) {
  let state = seed >>> 0;
  return () => {
    state += 0x6d2b79f5;
    let value = state;
    value = Math.imul(value ^ (value >>> 15), value | 1);
    value ^= value + Math.imul(value ^ (value >>> 7), value | 61);
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
  };
}

function shuffledCycle<T extends DailyFocusCandidate>(
  candidates: readonly T[],
  cycle: number,
): T[] {
  const ordered = [...candidates].sort((left, right) =>
    left.key < right.key ? -1 : left.key > right.key ? 1 : 0,
  );
  let previousLastKey: string | null = null;
  let shuffled = ordered;

  // Today is only a few hundred cycles from the Unix epoch for the current
  // syllabus size. Walking the cycles keeps the sequence pure while ensuring
  // midnight always produces a visibly different topic at a cycle boundary.
  for (let cycleIndex = 0; cycleIndex <= cycle; cycleIndex += 1) {
    shuffled = [...ordered];
    const random = seededRandom(
      hashSeed(`gatepath-daily-focus:${cycleIndex}`),
    );
    for (let index = shuffled.length - 1; index > 0; index -= 1) {
      const swapIndex = Math.floor(random() * (index + 1));
      [shuffled[index], shuffled[swapIndex]] = [
        shuffled[swapIndex],
        shuffled[index],
      ];
    }
    if (
      previousLastKey != null &&
      shuffled.length > 1 &&
      shuffled[0]?.key === previousLastKey
    ) {
      [shuffled[0], shuffled[1]] = [shuffled[1], shuffled[0]];
    }
    previousLastKey = shuffled[shuffled.length - 1]?.key ?? null;
  }
  return shuffled;
}

/**
 * Selects one topic per IST day from a deterministic probability shuffle.
 * Each topic appears exactly once before the next shuffled cycle begins.
 */
export function selectDailyFocus<T extends DailyFocusCandidate>(
  candidates: readonly T[],
  dayNumber: number,
): T | null {
  if (!candidates.length) return null;
  const cycle = Math.floor(dayNumber / candidates.length);
  const slot = positiveModulo(dayNumber, candidates.length);
  return shuffledCycle(candidates, cycle)[slot] ?? null;
}
