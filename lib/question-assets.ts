export const QUESTION_ASSET_ROLES = [
  "answer_option_diagrams",
  "answer_option_table",
  "stem_and_answer_option_diagrams",
  "stem_and_answer_option_tables",
  "stem_chart",
  "stem_diagram",
  "stem_graph",
  "stem_table",
] as const;

export type QuestionAssetRole = (typeof QUESTION_ASSET_ROLES)[number];

export type QuestionAsset = {
  role: QuestionAssetRole;
  url: string;
  altText: string;
  sha256: string;
};

export type QuestionAssetPlacement = "stem" | "options";

const ROLE_SET = new Set<string>(QUESTION_ASSET_ROLES);
const SHA256 = /^[0-9a-f]{64}$/;
const LOCAL_PNG =
  /^\/question-assets\/pyq\/[a-z0-9]+(?:-[a-z0-9]+)*\/[0-9a-f]{64}\.png$/;

export function questionAssetPlacement(
  role: QuestionAssetRole,
): QuestionAssetPlacement {
  return role.startsWith("answer_option_") ? "options" : "stem";
}

export function normalizeQuestionAssets(value: unknown): QuestionAsset[] {
  if (!Array.isArray(value)) return [];
  const result: QuestionAsset[] = [];
  const seen = new Set<string>();
  for (const raw of value.slice(0, 12)) {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) continue;
    const item = raw as Record<string, unknown>;
    const role = item.role;
    const url = item.url;
    const altText = item.alt_text ?? item.altText;
    const sha256 = item.sha256;
    if (
      typeof role !== "string" ||
      !ROLE_SET.has(role) ||
      typeof url !== "string" ||
      !LOCAL_PNG.test(url) ||
      typeof altText !== "string" ||
      !altText.trim() ||
      altText.length > 1_000 ||
      typeof sha256 !== "string" ||
      !SHA256.test(sha256) ||
      !url.endsWith(`/${sha256}.png`)
    ) {
      continue;
    }
    const identity = `${role}:${sha256}`;
    if (seen.has(identity)) continue;
    seen.add(identity);
    result.push({
      role: role as QuestionAssetRole,
      url,
      altText: altText.replace(/\s+/g, " ").trim(),
      sha256,
    });
  }
  return result;
}
