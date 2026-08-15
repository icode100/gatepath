import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { loadTypeScriptModule } from "./load-typescript-module.mjs";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const CSS = readFileSync(resolve(ROOT, "app", "globals.css"), "utf8");
const LAYOUT = readFileSync(resolve(ROOT, "app", "layout.tsx"), "utf8");
const OFFLINE = readFileSync(resolve(ROOT, "public", "offline.html"), "utf8");
const manifest = loadTypeScriptModule("app/manifest.ts").default();

function selectorBody(pattern, label) {
  const match = CSS.match(pattern);
  assert.ok(match, `missing ${label} theme block`);
  return match[1];
}

function variablesFrom(body) {
  return Object.fromEntries(
    [...body.matchAll(/--([\w-]+)\s*:\s*(#[\da-f]{6})\s*;/gi)].map((match) => [
      match[1],
      match[2].toLowerCase(),
    ]),
  );
}

const light = variablesFrom(selectorBody(/:root\s*\{([\s\S]*?)\}/, "light"));
const dark = variablesFrom(
  selectorBody(/:root\[data-theme=["']dark["']\]\s*\{([\s\S]*?)\}/, "dark"),
);

function rgb(hex) {
  return [1, 3, 5].map((offset) => Number.parseInt(hex.slice(offset, offset + 2), 16));
}

function channelSpread(hex) {
  const channels = rgb(hex);
  return Math.max(...channels) - Math.min(...channels);
}

function relativeLuminance(hex) {
  const linear = rgb(hex).map((channel) => {
    const normalized = channel / 255;
    return normalized <= 0.04045
      ? normalized / 12.92
      : ((normalized + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
}

function contrast(first, second) {
  const lighter = Math.max(relativeLuminance(first), relativeLuminance(second));
  const darker = Math.min(relativeLuminance(first), relativeLuminance(second));
  return (lighter + 0.05) / (darker + 0.05);
}

const neutralTokens = [
  "canvas",
  "canvas-raised",
  "surface",
  "surface-soft",
  "surface-strong",
  "ink",
  "ink-soft",
  "muted",
  "muted-2",
  "line",
  "line-strong",
  "primary",
  "primary-strong",
  "primary-pale",
  "on-primary",
];
const surfaceTokens = ["canvas", "canvas-raised", "surface", "surface-soft", "surface-strong"];

test("light and dark foundation tokens use neutral grayscale values", () => {
  for (const [themeName, theme] of [["light", light], ["dark", dark]]) {
    for (const token of neutralTokens) {
      assert.ok(theme[token], `${themeName} theme is missing --${token}`);
      assert.ok(
        channelSpread(theme[token]) <= 4,
        `${themeName} --${token} (${theme[token]}) is visibly color-tinted`,
      );
    }
  }

  for (const token of surfaceTokens) {
    assert.ok(relativeLuminance(light[token]) >= 0.84, `light --${token} is not a shade of white`);
    assert.ok(relativeLuminance(dark[token]) <= 0.02, `dark --${token} is not a shade of black`);
  }
});

test("core text tokens retain readable contrast on their surfaces", () => {
  for (const [themeName, theme] of [["light", light], ["dark", dark]]) {
    for (const textToken of ["ink", "ink-soft", "muted"]) {
      assert.ok(
        contrast(theme[textToken], theme.surface) >= 4.5,
        `${themeName} --${textToken} lacks 4.5:1 contrast on --surface`,
      );
    }
  }
});

test("large focus and mock panels inherit neutral theme surfaces", () => {
  const todayCard = selectorBody(/\.today-card\s*\{([\s\S]*?)\}/, ".today-card");
  const mockHero = selectorBody(/\.mock-hero\s*\{([\s\S]*?)\}/, ".mock-hero");
  for (const [selector, body] of [[".today-card", todayCard], [".mock-hero", mockHero]]) {
    assert.match(body, /var\(--surface\)/, `${selector} must use the neutral surface token`);
    assert.match(body, /var\(--surface-soft\)/, `${selector} must use the neutral soft surface token`);
    assert.doesNotMatch(
      body,
      /#(?:253777|4056d6|3349ba|1b2860|374db7)\b/i,
      `${selector} reintroduced a deep-blue background`,
    );
  }
});

test("manifest, prepaint shell and offline shell use the neutral theme foundations", () => {
  assert.equal(manifest.background_color.toLowerCase(), light.canvas);
  assert.ok(channelSpread(manifest.theme_color) <= 4, "manifest theme color must remain neutral");

  const shellColors = [...LAYOUT.matchAll(/["'](#[\da-f]{6})["']/gi)]
    .map((match) => match[1].toLowerCase());
  assert.ok(shellColors.includes(light.canvas), "prepaint shell is missing the light canvas color");
  assert.ok(shellColors.includes(dark.canvas), "prepaint shell is missing the dark canvas color");
  assert.match(LAYOUT, /data-gatepath-theme-color/);
  assert.match(OFFLINE, /localStorage\.getItem\(["']gatepath-theme["']\)/);
  assert.match(OFFLINE, /prefers-color-scheme:\s*dark/);
  assert.match(OFFLINE, /dataset\.theme\s*=\s*resolved/);
  assert.match(OFFLINE, /dataset\.themePreference\s*=\s*preference/);
  assert.match(OFFLINE, /:root\[data-theme=["']dark["']\]/);
  assert.match(
    OFFLINE.toLowerCase(),
    new RegExp(`--canvas\\s*:\\s*${dark.canvas.replace("#", "\\#")}`),
  );
});
