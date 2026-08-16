import {
  questionAssetPlacement,
  type QuestionAsset,
  type QuestionAssetPlacement,
} from "@/lib/question-assets";

type QuestionAssetsProps = {
  assets?: QuestionAsset[];
  placement?: QuestionAssetPlacement | "all";
  compact?: boolean;
  eager?: boolean;
};

const roleLabel = (role: QuestionAsset["role"]) => {
  if (role.startsWith("answer_option_")) return "Answer options";
  if (role === "stem_table") return "Question table";
  if (role === "stem_graph") return "Question graph";
  if (role === "stem_chart") return "Question chart";
  if (role.startsWith("stem_and_answer_option_")) return "Question figure and options";
  return "Question diagram";
};

export function QuestionAssets({
  assets = [],
  placement = "all",
  compact = false,
  eager = false,
}: QuestionAssetsProps) {
  const visible = assets.filter(
    (asset) =>
      placement === "all" || questionAssetPlacement(asset.role) === placement,
  );
  if (visible.length === 0) return null;

  return (
    <div className={`question-assets${compact ? " compact" : ""}`}>
      {visible.map((asset) => (
        <figure key={`${asset.role}:${asset.sha256}`}>
          <img
            src={asset.url}
            alt={asset.altText}
            loading={eager ? "eager" : "lazy"}
            decoding="async"
          />
          <figcaption>{roleLabel(asset.role)}</figcaption>
        </figure>
      ))}
    </div>
  );
}
