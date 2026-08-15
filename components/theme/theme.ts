export type ThemePreference = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

export const THEME_STORAGE_KEY = "gatepath-theme";
export const LIGHT_THEME_COLOR = "#F7F7F7";
export const DARK_THEME_COLOR = "#080808";
export const SYSTEM_THEME_QUERY = "(prefers-color-scheme: dark)";

export const isThemePreference = (value: unknown): value is ThemePreference =>
  value === "light" || value === "dark" || value === "system";

export const parseThemePreference = (value: unknown): ThemePreference =>
  isThemePreference(value) ? value : "system";

export const resolveThemePreference = (
  preference: ThemePreference,
  systemPrefersDark: boolean,
): ResolvedTheme =>
  preference === "system"
    ? systemPrefersDark
      ? "dark"
      : "light"
    : preference;

export const themeColorFor = (theme: ResolvedTheme) =>
  theme === "dark" ? DARK_THEME_COLOR : LIGHT_THEME_COLOR;
