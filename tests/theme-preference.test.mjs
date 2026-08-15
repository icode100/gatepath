import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { loadTypeScriptModule } from "./load-typescript-module.mjs";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const THEME = readFileSync(
  resolve(ROOT, "components", "theme", "theme.ts"),
  "utf8",
);
const PROVIDER = readFileSync(
  resolve(ROOT, "components", "theme", "ThemeProvider.tsx"),
  "utf8",
);
const SELECTOR = readFileSync(
  resolve(ROOT, "components", "theme", "ThemeSelector.tsx"),
  "utf8",
);
const LAYOUT = readFileSync(resolve(ROOT, "app", "layout.tsx"), "utf8");
const OFFLINE = readFileSync(resolve(ROOT, "public", "offline.html"), "utf8");
const CSS = readFileSync(resolve(ROOT, "app", "globals.css"), "utf8");

function cssRule(source, selectorPattern, label) {
  const match = source.match(new RegExp(`${selectorPattern}\\s*\\{([^}]*)\\}`, "s"));
  assert.ok(match, `missing ${label} CSS rule`);
  return match[1];
}

test("theme preference recognizes and resolves light, dark, and system", () => {
  const { isThemePreference, resolveThemePreference } = loadTypeScriptModule(
    "components/theme/theme.ts",
  );

  assert.equal(typeof isThemePreference, "function");
  assert.equal(typeof resolveThemePreference, "function");

  for (const preference of ["light", "dark", "system"]) {
    assert.equal(isThemePreference(preference), true, `${preference} must be accepted`);
  }
  for (const invalid of [undefined, null, "", "auto", "sepia", 1]) {
    assert.equal(isThemePreference(invalid), false, `${String(invalid)} must be rejected`);
  }

  assert.equal(resolveThemePreference("light", true), "light");
  assert.equal(resolveThemePreference("light", false), "light");
  assert.equal(resolveThemePreference("dark", true), "dark");
  assert.equal(resolveThemePreference("dark", false), "dark");
  assert.equal(resolveThemePreference("system", true), "dark");
  assert.equal(resolveThemePreference("system", false), "light");
});

test("theme provider persists the preference rather than only its resolved color", () => {
  assert.match(
    THEME,
    /export\s+type\s+ThemePreference\s*=\s*["']light["']\s*\|\s*["']dark["']\s*\|\s*["']system["']/,
  );
  assert.match(`${THEME}\n${PROVIDER}`, /gatepath-theme/);
  assert.match(PROVIDER, /localStorage\.getItem\(/);
  assert.match(PROVIDER, /localStorage\.setItem\([^,]+,\s*(?:next|(?:theme)?preference)\b/i);
  assert.doesNotMatch(
    PROVIDER,
    /localStorage\.setItem\([^,]+,\s*resolvedTheme\b/i,
    "the selected system preference must not be overwritten with a resolved color",
  );
});

test("system preference follows operating-system changes and removes its listener", () => {
  assert.match(THEME, /\(prefers-color-scheme:\s*dark\)/);
  assert.match(PROVIDER, /matchMedia\(\s*SYSTEM_THEME_QUERY\s*\)/);
  assert.match(PROVIDER, /addEventListener(?:\?\.)?\(\s*["']change["']/);
  assert.match(PROVIDER, /removeEventListener(?:\?\.)?\(\s*["']change["']/);
  assert.match(
    PROVIDER,
    /preference\s*!==?\s*["']system["']|preference\s*===\s*["']system["']|["']system["']\s*===\s*preference/i,
    "media-query changes must be gated by the system preference",
  );
});

test("clearing theme storage returns other tabs to the system preference", () => {
  const storageHandler = PROVIDER.slice(
    PROVIDER.indexOf("const syncAcrossTabs"),
    PROVIDER.indexOf('window.addEventListener("storage"'),
  );
  assert.match(storageHandler, /event\.key\s*!==\s*THEME_STORAGE_KEY/);
  assert.match(
    storageHandler,
    /event\.key\s*!==\s*null|event\.key\s*===\s*null/,
    "StorageEvent.key=null from localStorage.clear() must be handled",
  );
  assert.match(storageHandler, /parseThemePreference\(event\.newValue\)/);
  assert.equal(
    loadTypeScriptModule("components/theme/theme.ts").parseThemePreference(null),
    "system",
  );
});

test("selecting a theme applies it synchronously before persistence effects run", () => {
  const setter = PROVIDER.slice(
    PROVIDER.indexOf("const setPreference"),
    PROVIDER.indexOf("const value = useMemo"),
  );
  assert.match(setter, /setPreferenceState\(next\)/);
  assert.match(setter, /applyResolvedTheme\(next,\s*systemPrefersDark\(\)\)/);
  assert.match(setter, /setResolvedTheme\(/);
  assert.ok(
    setter.indexOf("applyResolvedTheme") < setter.indexOf("localStorage.setItem"),
    "the DOM theme must update before storage persistence",
  );
});

test("layout prepaints the saved or system-resolved theme before hydration", () => {
  assert.match(LAYOUT, /gatepath-theme/);
  assert.match(LAYOUT, /prefers-color-scheme:\s*dark/);
  assert.match(LAYOUT, /["']system["']/);
  assert.match(LAYOUT, /dataset\.theme\s*=/);
  assert.match(LAYOUT, /dataset\.themePreference\s*=/);
  assert.match(LAYOUT, /dangerouslySetInnerHTML/);
});

test("theme control exposes three accessible pressed-button choices", () => {
  assert.match(SELECTOR, /role=["']group["']/);
  assert.match(SELECTOR, /aria-(?:label|labelledby)=[^\n>]+/i);
  assert.match(SELECTOR, /aria-pressed=/);
  assert.doesNotMatch(SELECTOR, /role=["']radio(?:group)?["']/);
  assert.doesNotMatch(SELECTOR, /aria-checked=/);
  for (const preference of ["light", "dark", "system"]) {
    assert.match(SELECTOR, new RegExp(`["']${preference}["']`));
  }
});

test("offline system mode follows live operating-system theme changes", () => {
  assert.match(OFFLINE, /matchMedia\(["']\(prefers-color-scheme:\s*dark\)["']\)/);
  assert.match(OFFLINE, /addEventListener(?:\?\.)?\(\s*["']change["']/);
  assert.match(
    OFFLINE,
    /preference\s*===\s*["']system["'][\s\S]{0,240}addEventListener(?:\?\.)?\(\s*["']change["']/,
    "the offline listener must only be attached for the System preference",
  );
  assert.match(OFFLINE, /dataset\.theme\s*=/);
  assert.match(OFFLINE, /data-gatepath-theme-color/);
});

test("narrow headers preserve 44px theme targets while reducing status text", () => {
  const buttons = cssRule(CSS, "\\.theme-selector\\s+button", ".theme-selector button");
  const compactButtons = cssRule(
    CSS,
    "\\.theme-selector-compact\\s+button",
    ".theme-selector-compact button",
  );
  assert.match(buttons, /min-width:\s*44px/);
  assert.match(buttons, /min-height:\s*44px/);
  assert.match(compactButtons, /width:\s*44px/);

  const narrow = CSS.slice(CSS.indexOf("@media (max-width: 720px)"));
  const status = cssRule(narrow, "\\.api-status", "narrow .api-status");
  assert.match(
    status,
    /font-size:\s*(?:[0-9](?:\.\d+)?px|0\.[0-9]+rem)|max-width:|overflow:|display:\s*none/,
    "narrow headers must reduce or constrain the connection-status text",
  );
  assert.doesNotMatch(
    narrow,
    /\.theme-selector(?:-compact)?\s+button\s*\{[^}]*(?:width|min-width|min-height):\s*(?:[0-3]?\d|4[0-3])px/s,
    "narrow CSS must not shrink theme controls below 44px",
  );
});
