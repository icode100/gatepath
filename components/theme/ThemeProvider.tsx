"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  parseThemePreference,
  resolveThemePreference,
  SYSTEM_THEME_QUERY,
  THEME_STORAGE_KEY,
  themeColorFor,
  type ResolvedTheme,
  type ThemePreference,
} from "./theme";

type ThemeContextValue = {
  preference: ThemePreference;
  resolvedTheme: ResolvedTheme;
  setPreference: (preference: ThemePreference) => void;
};

const ThemeContext = createContext<ThemeContextValue | null>(null);

const systemPrefersDark = () => {
  try {
    return window.matchMedia(SYSTEM_THEME_QUERY).matches;
  } catch {
    return false;
  }
};

const applyResolvedTheme = (
  preference: ThemePreference,
  prefersDark: boolean,
): ResolvedTheme => {
  const resolved = resolveThemePreference(preference, prefersDark);
  const root = document.documentElement;
  root.dataset.theme = resolved;
  root.dataset.themePreference = preference;
  root.style.colorScheme = resolved;
  const meta = document.querySelector<HTMLMetaElement>(
    'meta[name="theme-color"][data-gatepath-theme-color]',
  );
  if (meta) meta.content = themeColorFor(resolved);
  return resolved;
};

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPreferenceState] =
    useState<ThemePreference>("system");
  const [resolvedTheme, setResolvedTheme] =
    useState<ResolvedTheme>("light");
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    let stored: string | null = null;
    try {
      stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    } catch {
      // Storage may be unavailable in hardened/private browser contexts.
    }
    const bootstrapped = document.documentElement.dataset.themePreference;
    const initial = parseThemePreference(stored ?? bootstrapped);
    setPreferenceState(initial);
    setResolvedTheme(applyResolvedTheme(initial, systemPrefersDark()));
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!hydrated) return;

    let media: MediaQueryList | null = null;
    try {
      media = window.matchMedia(SYSTEM_THEME_QUERY);
    } catch {
      setResolvedTheme(applyResolvedTheme(preference, false));
      return;
    }

    const sync = () => {
      setResolvedTheme(applyResolvedTheme(preference, media?.matches ?? false));
    };
    sync();
    if (preference !== "system") return;

    media.addEventListener?.("change", sync);
    if (!media.addEventListener) media.addListener(sync);
    return () => {
      media?.removeEventListener?.("change", sync);
      if (media && !media.removeEventListener) media.removeListener(sync);
    };
  }, [hydrated, preference]);

  useEffect(() => {
    const syncAcrossTabs = (event: StorageEvent) => {
      if (event.key !== THEME_STORAGE_KEY && event.key !== null) return;
      setPreferenceState(parseThemePreference(event.newValue));
    };
    window.addEventListener("storage", syncAcrossTabs);
    return () => window.removeEventListener("storage", syncAcrossTabs);
  }, []);

  const setPreference = useCallback((next: ThemePreference) => {
    setResolvedTheme(applyResolvedTheme(next, systemPrefersDark()));
    setPreferenceState(next);
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      // The in-memory choice still works when storage is unavailable.
    }
  }, []);

  const value = useMemo(
    () => ({ preference, resolvedTheme, setPreference }),
    [preference, resolvedTheme, setPreference],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) throw new Error("useTheme must be used within ThemeProvider");
  return context;
}
