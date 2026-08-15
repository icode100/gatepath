"use client";

import { useTheme } from "./ThemeProvider";
import type { ThemePreference } from "./theme";

const OPTIONS: Array<{
  value: ThemePreference;
  label: string;
  icon: string;
}> = [
  { value: "light", label: "Light", icon: "☼" },
  { value: "system", label: "System", icon: "▣" },
  { value: "dark", label: "Dark", icon: "◐" },
];

export function ThemeSelector({
  variant = "compact",
}: {
  variant?: "compact" | "settings";
}) {
  const { preference, resolvedTheme, setPreference } = useTheme();

  return (
    <div
      className={`theme-selector theme-selector-${variant}`}
      role="group"
      aria-label="Appearance"
    >
      {OPTIONS.map((option) => {
        const systemContext =
          option.value === "system" ? ` (currently ${resolvedTheme})` : "";
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={preference === option.value}
            aria-label={`Use ${option.label.toLowerCase()} theme${systemContext}`}
            title={`${option.label}${systemContext}`}
            onClick={() => setPreference(option.value)}
          >
            <span aria-hidden="true">{option.icon}</span>
            {variant === "settings" && <strong>{option.label}</strong>}
          </button>
        );
      })}
    </div>
  );
}
