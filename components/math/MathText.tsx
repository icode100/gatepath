"use client";

import { Fragment, memo } from "react";
import katex from "katex";

type MathSegment =
  | { kind: "text"; value: string }
  | { kind: "math"; value: string; raw: string; display: boolean };

type MathTextProps = {
  children: string;
  className?: string;
};

type MathFormulaProps = {
  expression: string;
  className?: string;
  display?: boolean;
};

const renderCache = new Map<string, string | null>();
const MAX_CACHE_ENTRIES = 800;

const isEscaped = (value: string, index: number) => {
  let backslashes = 0;
  for (let cursor = index - 1; cursor >= 0 && value[cursor] === "\\"; cursor -= 1) {
    backslashes += 1;
  }
  return backslashes % 2 === 1;
};

const findClosingDollar = (value: string, start: number) => {
  for (let cursor = start; cursor < value.length; cursor += 1) {
    if (value[cursor] === "$" && !isEscaped(value, cursor)) return cursor;
  }
  return -1;
};

const isLikelyDollarMath = (value: string) => {
  const candidate = value.trim();
  if (!candidate) return false;
  if (/^[A-Za-z0-9]+(?:[_^][A-Za-z0-9{}]+)?$/.test(candidate)) return true;
  return /\\[A-Za-z]+|[=+\-*/^_{}()[\]<>≤≥≠≈∈∉⊆⊂∪∩∞ΘΩθλεπΔΣΠ√∑∫]/u.test(candidate);
};

export function parseMathSegments(value: string): MathSegment[] {
  const segments: MathSegment[] = [];
  let textStart = 0;
  let cursor = 0;

  while (cursor < value.length) {
    let open = "";
    let close = "";
    let display = false;

    if (value.startsWith("$$", cursor) && !isEscaped(value, cursor)) {
      open = "$$";
      close = "$$";
      display = true;
    } else if (value.startsWith("\\[", cursor)) {
      open = "\\[";
      close = "\\]";
      display = true;
    } else if (value.startsWith("\\(", cursor)) {
      open = "\\(";
      close = "\\)";
    } else if (
      value[cursor] === "$" &&
      value[cursor + 1] !== "$" &&
      !isEscaped(value, cursor)
    ) {
      open = "$";
      close = "$";
    }

    if (!open) {
      cursor += 1;
      continue;
    }

    const contentStart = cursor + open.length;
    const closeIndex =
      close === "$"
        ? findClosingDollar(value, contentStart)
        : value.indexOf(close, contentStart);
    if (closeIndex < 0 || closeIndex === contentStart) {
      cursor += open.length;
      continue;
    }

    if (open === "$" && !isLikelyDollarMath(value.slice(contentStart, closeIndex))) {
      cursor += 1;
      continue;
    }

    if (cursor > textStart) {
      segments.push({ kind: "text", value: value.slice(textStart, cursor) });
    }
    const end = closeIndex + close.length;
    segments.push({
      kind: "math",
      value: value.slice(contentStart, closeIndex),
      raw: value.slice(cursor, end),
      display,
    });
    cursor = end;
    textStart = end;
  }

  if (textStart < value.length) {
    segments.push({ kind: "text", value: value.slice(textStart) });
  }
  return segments.length ? segments : [{ kind: "text", value }];
}

const superscripts: Record<string, string> = {
  "⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4",
  "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9",
  "⁺": "+", "⁻": "-", "ⁿ": "n",
};

const subscripts: Record<string, string> = {
  "₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4",
  "₅": "5", "₆": "6", "₇": "7", "₈": "8", "₉": "9",
  "₊": "+", "₋": "-", "ₙ": "n",
};

const unicodeMath: Array<[RegExp, string]> = [
  [/−/g, "-"],
  [/×/g, "\\times "],
  [/÷/g, "\\div "],
  [/≤/g, "\\le "],
  [/≥/g, "\\ge "],
  [/≠/g, "\\ne "],
  [/≈/g, "\\approx "],
  [/→/g, "\\to "],
  [/←/g, "\\leftarrow "],
  [/↔/g, "\\leftrightarrow "],
  [/∈/g, "\\in "],
  [/∉/g, "\\notin "],
  [/⊆/g, "\\subseteq "],
  [/⊂/g, "\\subset "],
  [/∪/g, "\\cup "],
  [/∩/g, "\\cap "],
  [/∅/g, "\\varnothing "],
  [/∞/g, "\\infty "],
  [/√\(([^)]+)\)/g, "\\sqrt{$1}"],
  [/√\s*([A-Za-z0-9])/g, "\\sqrt{$1}"],
  [/√/g, "\\sqrt{}"],
  [/∑/g, "\\sum "],
  [/∫/g, "\\int "],
  [/Θ/g, "\\Theta "],
  [/Ω/g, "\\Omega "],
  [/θ/g, "\\theta "],
  [/λ/g, "\\lambda "],
  [/ε/g, "\\varepsilon "],
  [/π/g, "\\pi "],
  [/Δ/g, "\\Delta "],
  [/Σ/g, "\\Sigma "],
  [/Π/g, "\\Pi "],
  [/α/g, "\\alpha "],
  [/β/g, "\\beta "],
  [/γ/g, "\\gamma "],
];

export function normalizeLegacyFormula(expression: string): string {
  let value = expression.trim();
  const wrappers: Array<[string, string]> = [["$$", "$$"], ["\\[", "\\]"], ["\\(", "\\)"], ["$", "$"]];
  const wrapper = wrappers.find(
    ([open, close]) => value.startsWith(open) && value.endsWith(close),
  );
  if (wrapper) value = value.slice(wrapper[0].length, -wrapper[1].length).trim();
  const authoredLatex = /\\[A-Za-z]+/.test(value);
  if (!authoredLatex) {
    value = value.replace(/\{/g, "\\{").replace(/\}/g, "\\}");
  }

  value = value.replace(/[⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻ⁿ]+/g, (run) =>
    `^{${Array.from(run).map((char) => superscripts[char] ?? char).join("")}}`,
  );
  value = value.replace(/[₀₁₂₃₄₅₆₇₈₉₊₋ₙ]+/g, (run) =>
    `_{${Array.from(run).map((char) => subscripts[char] ?? char).join("")}}`,
  );
  value = value.normalize("NFKC");
  unicodeMath.forEach(([pattern, replacement]) => {
    value = value.replace(pattern, replacement);
  });

  if (!authoredLatex) {
    value = value
      .replace(/\u2061/g, "")
      .replace(/\.\.\./g, "\\ldots ")
      .replace(/\bsuch\s+that\b/gi, "\\text{ such that }")
      .replace(/\b(for|if|where|and|or|not|no|of|to|in)\b/gi, (word) => `\\text{ ${word.toLowerCase()} }`)
      .replace(/\bmod\b/gi, "\\bmod")
      .replace(/\bunion\b/gi, "\\cup")
      .replace(/\bintersection\b/gi, "\\cap")
      .replace(/\bsubseteq\b/gi, "\\subseteq")
      .replace(/\bsubset\b/gi, "\\subset")
      .replace(/\biff\b/gi, "\\iff")
      .replace(/\bsum\s*\(/gi, "\\sum(")
      .replace(/\b(log|ln|max|min|rank|det|sin|cos|tan)\b/g, "\\$1")
      .replace(/((?:\\Theta|\\Omega|O)\s*\(\s*)([nmkx])([2-9])(?=\s|\\|[)])/g, "$1$2^{$3}")
      .replace(/\b(deg|color|id)\b/g, "\\operatorname{$1}")
      .replace(/\b([A-Z]{2,8})\b/g, "\\mathrm{$1}")
      .replace(/([A-Za-z])_\(([^)]+)\)/g, "$1_{$2}")
      .replace(/\b([A-Za-z])(\d+)\b/g, "$1_{$2}");
  }

  const piecewise = value.match(
    /^(.*?)\s*=\s*\\\{(.*?)\\text\{\s*for\s*\}(.*?),\s*(.*?)\\text\{\s*for\s*\}(.*)$/i,
  );
  if (piecewise) {
    const [, left, firstValue, firstCondition, secondValue, secondCondition] = piecewise;
    value = `${left.trim()} = \\begin{cases}${firstValue.trim()} & \\text{for } ${firstCondition.trim()} \\\\ ${secondValue.trim()} & \\text{for } ${secondCondition.trim()}\\end{cases}`;
  }
  return value;
}

const legacyKeyword = /^(?:for|if|where|and|or|not|no|such|that|in|mod|of|to|log|ln|max|min|rank|det|sin|cos|tan|sum|deg|color|id)$/i;
const legacyPunctuation = /^[\s\d()[\]{}|,+\-=*/^_.%:;<>]+$/u;

const hasLegacyMathAnchor = (token: string) =>
  Array.from(token).some((char) => {
    const codePoint = char.codePointAt(0) ?? 0;
    return (
      (codePoint >= 0x1d400 && codePoint <= 0x1d7ff) ||
      /[√∑∫≤≥≠≈∈∉⊆⊂∪∩∞ΘΩθλεπΔΣΠ←→↔⁰¹²³⁴⁵⁶⁷⁸⁹₀₁₂₃₄₅₆₇₈₉]/u.test(char)
    );
  });

function parseLegacyMathSegments(value: string): MathSegment[] {
  const asciiEquationSafe = !/(?:#include|printf\s*\(|scanf\s*\(|int\s+main|SELECT\s|INSERT\s|UPDATE\s|DELETE\s|while\s*\(|for\s*\(|if\s*\(|return\s+)/i.test(value);
  const hasAsciiEquation =
    asciiEquationSafe &&
    /[A-Za-z0-9_)}\]]\s*=\s*[A-Za-z0-9_{([]/.test(value);
  if (!hasLegacyMathAnchor(value) && !hasAsciiEquation) {
    return [{ kind: "text", value }];
  }
  const tokenPattern = /[\p{L}]+|\d+(?:\.\d+)?|\s+|./gu;
  const tokens = Array.from(value.matchAll(tokenPattern));
  const segments: MathSegment[] = [];
  let pendingStart: number | null = null;
  let anchored = false;
  let emittedUntil = 0;

  const flush = (end: number) => {
    if (pendingStart == null || !anchored) return;
    const raw = value.slice(pendingStart, end);
    const leading = raw.match(/^[\s:;,]*/)?.[0].length ?? 0;
    const trailing = raw.match(/[\s.,;:]*$/)?.[0].length ?? 0;
    const start = pendingStart + leading;
    const finish = end - trailing;
    if (finish <= start) return;
    const expression = value.slice(start, finish);
    const isUnicodeMath = hasLegacyMathAnchor(expression);
    const isAsciiMath =
      hasAsciiEquation &&
      /[A-Za-z0-9_)}\]]\s*=\s*[A-Za-z0-9_{([]/.test(expression);
    if (!isUnicodeMath && !isAsciiMath) return;
    if (start > emittedUntil) {
      segments.push({ kind: "text", value: value.slice(emittedUntil, start) });
    }
    const normalized = normalizeLegacyFormula(expression);
    const display = normalized.includes("\\begin{cases}");
    segments.push({
      kind: "math",
      value: normalized,
      raw: expression,
      display,
    });
    emittedUntil = display && value[finish] === "." ? finish + 1 : finish;
  };

  for (const match of tokens) {
    const token = match[0];
    const index = match.index ?? 0;
    const isAsciiWord = /^[A-Za-z]+$/.test(token);
    const isSingleVariable = isAsciiWord && token.length === 1;
    const isAllowed =
      hasLegacyMathAnchor(token) ||
      isSingleVariable ||
      legacyKeyword.test(token) ||
      legacyPunctuation.test(token) ||
      /^\d+(?:\.\d+)?$/.test(token) ||
      token === "\u2061";

    if (isAllowed) {
      if (pendingStart == null) pendingStart = index;
      if (hasLegacyMathAnchor(token) || (hasAsciiEquation && token === "=")) anchored = true;
      continue;
    }

    flush(index);
    pendingStart = null;
    anchored = false;
  }
  flush(value.length);
  if (emittedUntil < value.length) {
    segments.push({ kind: "text", value: value.slice(emittedUntil) });
  }
  return segments.length ? segments : [{ kind: "text", value }];
}

const renderLatex = (expression: string, display: boolean) => {
  const key = `${display ? "d" : "i"}:${expression}`;
  if (renderCache.has(key)) return renderCache.get(key) ?? null;
  let html: string | null = null;
  try {
    html = katex.renderToString(expression, {
      displayMode: display,
      maxExpand: 500,
      maxSize: 20,
      output: "htmlAndMathml",
      strict: "ignore",
      throwOnError: true,
      trust: false,
    });
  } catch {
    html = null;
  }
  if (renderCache.size >= MAX_CACHE_ENTRIES) {
    const oldest = renderCache.keys().next().value;
    if (oldest) renderCache.delete(oldest);
  }
  renderCache.set(key, html);
  return html;
};

export const MathText = memo(function MathText({ children, className }: MathTextProps) {
  const segments = parseMathSegments(children).flatMap((segment) =>
    segment.kind === "text" ? parseLegacyMathSegments(segment.value) : segment,
  );
  return (
    <span className={["math-text", className].filter(Boolean).join(" ")}>
      {segments.map((segment, index) => {
        if (segment.kind === "text") {
          return <Fragment key={`text-${index}`}>{segment.value}</Fragment>;
        }
        const html = renderLatex(segment.value, segment.display);
        return html ? (
          <span
            className={segment.display ? "math-display" : "math-inline"}
            dangerouslySetInnerHTML={{ __html: html }}
            key={`math-${index}`}
          />
        ) : (
          <Fragment key={`fallback-${index}`}>{segment.raw}</Fragment>
        );
      })}
    </span>
  );
});

export const MathFormula = memo(function MathFormula({
  expression,
  className,
  display = true,
}: MathFormulaProps) {
  const normalized = normalizeLegacyFormula(expression);
  const html = renderLatex(normalized, display);
  if (!html) {
    return <span className={["math-formula-fallback", className].filter(Boolean).join(" ")}>{expression}</span>;
  }
  return (
    <span
      className={["math-formula", display ? "math-display" : "math-inline", className]
        .filter(Boolean)
        .join(" ")}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
});
