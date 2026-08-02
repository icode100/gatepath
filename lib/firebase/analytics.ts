import type { Analytics } from "firebase/analytics";
import {
  firebaseAnalyticsConfigured,
  getFirebaseApp,
} from "./client";

type AnalyticsValue = string | number | boolean;
type AnalyticsParams = Record<string, AnalyticsValue | undefined>;

let analyticsPromise: Promise<Analytics | null> | null = null;

async function loadAnalytics(): Promise<Analytics | null> {
  if (
    typeof window === "undefined" ||
    !firebaseAnalyticsConfigured ||
    !getFirebaseApp()
  ) {
    return null;
  }

  analyticsPromise ??= import("firebase/analytics")
    .then(async ({ getAnalytics, isSupported }) => {
      if (!(await isSupported())) return null;
      const app = getFirebaseApp();
      return app ? getAnalytics(app) : null;
    })
    .catch(() => null);

  return analyticsPromise;
}

export async function trackEvent(
  eventName: string,
  params: AnalyticsParams = {},
): Promise<void> {
  try {
    const analytics = await loadAnalytics();
    if (!analytics) return;
    const { logEvent } = await import("firebase/analytics");
    const safeParams = Object.fromEntries(
      Object.entries(params).filter((entry): entry is [string, AnalyticsValue] =>
        entry[1] !== undefined,
      ),
    );
    logEvent(analytics, eventName, safeParams);
  } catch {
    // Measurement is optional and must never interrupt studying or sign-in.
  }
}
