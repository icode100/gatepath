"""Audit and stage original-paper figure assets for the GATE CS PYQ archive.

The output is deliberately review-first and deployment-neutral.  Every one of
the 2,712 canonical parent slots and 272 audited legacy child records receives
an explicit visual-dependence status.  Only crops listed in the visually
reviewed override file are extracted, and every crop is rendered from a local
question-paper PDF whose SHA-256 matches the reviewed source manifest.

Secondary HTML is consumed only through the existing sanitized transcription
match artifact as a boolean locator hint.  This script never downloads or
copies remote images, never reads explanations, never opens a database, and
never marks a question practice-eligible.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from PIL import Image
from pypdf import PdfReader


REPO_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_DIR / "backend"
BUILD_DIR = REPO_DIR / "tmp" / "pyq" / "build"
DEFAULT_MANIFEST = BACKEND_DIR / "data" / "pyq_source_manifest.json"
DEFAULT_CANONICAL = BUILD_DIR / "canonical_pyq_archive.json"
DEFAULT_PROVENANCE = BUILD_DIR / "original_pdf_provenance.json"
DEFAULT_OVERLAY = BUILD_DIR / "original_question_transcription_overlay.json"
DEFAULT_LEGACY = BACKEND_DIR / "data" / "legacy_pyq_subparts_1996_2002.json"
DEFAULT_MATCHES = BUILD_DIR / "pyq_transcription_matches.json"
DEFAULT_CROPS = BACKEND_DIR / "data" / "pyq_figure_crop_overrides.json"
DEFAULT_OUTPUT = BUILD_DIR / "pyq_figure_assets.json"
DEFAULT_ASSET_DIR = BUILD_DIR / "figure-assets"

SCHEMA_VERSION = "1.0-staging-original-pdf-figure-assets"
EXPECTED_PAPERS = 39
EXPECTED_PARENTS = 2712
EXPECTED_CHILDREN = 272
EXPECTED_AUDITED_RECORDS = EXPECTED_PARENTS + EXPECTED_CHILDREN
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
SAFE_NAME_RE = re.compile(r"[^a-z0-9]+")

VISUAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "explicit_image_placeholder",
        re.compile(r"\[(?:image|figure|diagram)\s*:", re.IGNORECASE),
    ),
    (
        "named_visual_shown",
        re.compile(
            r"\b(?:figure|diagram|flow\s*chart|circuit|waveform|plot|"
            r"state\s+(?:transition\s+)?diagram|network\s+diagram|tree\s+diagram|"
            r"table)\b.{0,72}\b(?:shown|given|depicted|illustrated|below|above|"
            r"following|presents?)\b",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "shown_named_visual",
        re.compile(
            r"\b(?:shown|given|depicted|illustrated|presented)\b.{0,72}\b(?:in|by|"
            r"as)?\s*(?:the\s+)?(?:following\s+)?(?:figure|diagram|flow\s*chart|"
            r"circuit|waveform|plot|table)\b",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "deictic_visual_reference",
        re.compile(
            r"\b(?:the|this|following|above|below)\s+(?:figure|diagram|flow\s*chart|"
            r"circuit|waveform|plot|table)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "visual_option_reference",
        re.compile(
            r"\b(?:which|one)\s+of\s+the\s+(?:following\s+)?(?:figures|diagrams|"
            r"circuits|waveforms|plots|trees|graphs)\b",
            re.IGNORECASE,
        ),
    ),
)

VISUAL_FLAG_RE = re.compile(r"image|visual|diagram|figure|asset|layout", re.IGNORECASE)
FORBIDDEN_OUTPUT_KEYS = {
    "answer",
    "accepted_answers",
    "correct_answer",
    "explanation",
    "explanation_html",
    "solution",
    "solution_md",
}


class FigureAssetError(ValueError):
    """Raised when a source identity or staging invariant is unsafe."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json_sha256(value: Any) -> str:
    return _sha256_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FigureAssetError(f"Cannot read JSON input {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise FigureAssetError(f"{path}: expected a JSON object")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _input_binding(path: Path) -> dict[str, Any]:
    try:
        label = str(path.relative_to(REPO_DIR)).replace("\\", "/")
    except ValueError:
        label = str(path)
    return {"path": label, "sha256": _sha256_file(path), "bytes": path.stat().st_size}


def _validate_embedded_hash(value: Mapping[str, Any], *, label: str) -> None:
    expected = value.get("artifact_sha256")
    if expected is None:
        return
    if not isinstance(expected, str) or HASH_RE.fullmatch(expected) is None:
        raise FigureAssetError(f"{label}: malformed artifact_sha256")
    core = {key: child for key, child in value.items() if key != "artifact_sha256"}
    if _canonical_json_sha256(core) != expected:
        raise FigureAssetError(f"{label}: embedded artifact hash mismatch")


def _safe_output(value: Any, path: str = "root") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_OUTPUT_KEYS:
                raise FigureAssetError(f"Forbidden output field {path}.{key}")
            _safe_output(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _safe_output(child, f"{path}[{index}]")


def _slot_key(
    row: Mapping[str, Any], *, ordinal_field: str, child_label: str | None = None
) -> tuple[str, int, str | None]:
    paper = str(row.get("source_paper_id") or row.get("paper_id") or "").strip()
    ordinal = row.get(ordinal_field)
    if not paper or not isinstance(ordinal, int) or ordinal < 1:
        raise FigureAssetError(f"Invalid slot identity {paper!r}/{ordinal!r}")
    return paper, ordinal, child_label


def _unique_parent_rows(
    rows: Any, *, ordinal_field: str, label: str
) -> dict[tuple[str, int], dict[str, Any]]:
    if not isinstance(rows, list):
        raise FigureAssetError(f"{label}: missing item list")
    result: dict[tuple[str, int], dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise FigureAssetError(f"{label}: row is not an object")
        paper = str(row.get("source_paper_id") or row.get("paper_id") or "").strip()
        ordinal = row.get(ordinal_field)
        key = (paper, ordinal) if paper and isinstance(ordinal, int) else None
        if key is None or ordinal < 1 or key in result:
            raise FigureAssetError(f"{label}: invalid or duplicate slot {key}")
        result[key] = row
    return result


def _normalize_prompt(value: str) -> str:
    folded = unicodedata.normalize("NFKC", value or "")
    return " ".join(folded.replace("\u00ad", "").split())


def _prompt_hashes(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        normalized = _normalize_prompt(value)
        if normalized:
            digest = _sha256_text(normalized)
            if digest not in result:
                result.append(digest)
    return result


def detect_visual_signals(
    prompt_values: Sequence[str],
    *,
    overlay_status_reason: str | None = None,
    overlay_flags: Sequence[str] = (),
    remote_visual_hint: bool = False,
    objective_options_available: bool = True,
    parent_signals: Sequence[str] = (),
) -> list[str]:
    """Return conservative signal identifiers without serializing prompt text."""

    signals = set(parent_signals)
    normalized = "\n".join(_normalize_prompt(value) for value in prompt_values if value)
    for name, pattern in VISUAL_PATTERNS:
        if pattern.search(normalized):
            signals.add(name)
    if remote_visual_hint:
        signals.add("secondary_remote_visual_locator_hint")
    if overlay_status_reason == "source_text_contains_visual_or_layout_risk":
        signals.add("original_overlay_visual_or_layout_risk")
    if overlay_status_reason == "original_source_requires_rendered_page_review":
        signals.add("original_rendered_page_review_required")
    if any(VISUAL_FLAG_RE.search(str(flag)) for flag in overlay_flags):
        signals.add("original_overlay_visual_review_flag")
    if not normalized:
        signals.add("prompt_unavailable_for_visual_audit")
    if not objective_options_available:
        signals.add("objective_options_not_safely_transcribed")
    return sorted(signals)


CONFIRMED_SIGNAL_NAMES = {
    "explicit_image_placeholder",
    "named_visual_shown",
    "shown_named_visual",
    "deictic_visual_reference",
    "visual_option_reference",
    "secondary_remote_visual_locator_hint",
}


def decide_dependence_status(
    *,
    signals: Sequence[str],
    source_pages: Sequence[int],
    has_complete_reviewed_crop: bool,
    visually_reviewed_no_asset_required: bool = False,
) -> tuple[str, str]:
    if visually_reviewed_no_asset_required:
        if has_complete_reviewed_crop:
            raise FigureAssetError(
                "A row cannot have both a reviewed crop and a no-asset disposition"
            )
        return "not_required", "not_detected"
    confirmed = bool(CONFIRMED_SIGNAL_NAMES.intersection(signals))
    if has_complete_reviewed_crop:
        return "asset_ready", "confirmed"
    if confirmed and not source_pages:
        return "missing", "confirmed"
    if signals:
        return "review_required", "confirmed" if confirmed else "potential"
    return "not_required", "not_detected"


def _find_pdftoppm(explicit: str | None = None) -> str:
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise FigureAssetError(f"pdftoppm does not exist: {path}")
        return str(path)
    found = shutil.which("pdftoppm.exe") or shutil.which("pdftoppm") or shutil.which(
        "pdftoppm.cmd"
    )
    if not found:
        raise FigureAssetError("pdftoppm is required for original-paper crops")
    found_path = Path(found).resolve()
    if found_path.suffix.casefold() == ".cmd":
        for ancestor in found_path.parents:
            if ancestor.name.casefold() != "dependencies":
                continue
            bundled = ancestor / "native" / "poppler" / "Library" / "bin" / "pdftoppm.exe"
            if bundled.is_file():
                return str(bundled)
    return str(found_path)


def _render_page(
    source_pdf: Path,
    *,
    page: int,
    dpi: int,
    pdftoppm: str,
    output_prefix: Path,
) -> Path:
    command = [
        pdftoppm,
        "-f",
        str(page),
        "-l",
        str(page),
        "-r",
        str(dpi),
        "-png",
        "-singlefile",
        str(source_pdf),
        str(output_prefix),
    ]
    completed = subprocess.run(
        command, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise FigureAssetError(
            f"pdftoppm failed for {source_pdf} page {page}: {detail}"
        )
    rendered = output_prefix.with_suffix(".png")
    if not rendered.is_file():
        raise FigureAssetError(
            f"pdftoppm did not create a PNG for {source_pdf} page {page}"
        )
    return rendered


def _validate_crop_box(box: Any, page_size: Sequence[int]) -> tuple[int, int, int, int]:
    if (
        not isinstance(box, list)
        or len(box) != 4
        or any(not isinstance(value, int) for value in box)
    ):
        raise FigureAssetError(f"Invalid pixel crop box {box!r}")
    if len(page_size) != 2 or any(not isinstance(value, int) for value in page_size):
        raise FigureAssetError(f"Invalid source page pixel size {page_size!r}")
    left, top, right, bottom = box
    width, height = page_size
    if not (0 <= left < right <= width and 0 <= top < bottom <= height):
        raise FigureAssetError(f"Crop {box!r} falls outside {page_size!r}")
    if right - left < 32 or bottom - top < 32:
        raise FigureAssetError(f"Crop {box!r} is too small to be a reviewed figure")
    return left, top, right, bottom


def _slug(value: str) -> str:
    return SAFE_NAME_RE.sub("-", value.casefold()).strip("-") or "asset"


def _asset_identity(crop: Mapping[str, Any]) -> str:
    core = {
        "source_paper_id": crop["source_paper_id"],
        "canonical_ordinal": crop["canonical_ordinal"],
        "child_item_label": crop.get("child_item_label"),
        "source_pdf_sha256": crop["source_pdf_sha256"],
        "source_page": crop["source_page"],
        "crop_box_pixels": crop["crop_box_pixels"],
        "asset_role": crop["asset_role"],
        "visual_kind": crop["visual_kind"],
    }
    return f"pyq-figure-{_canonical_json_sha256(core)[:20]}"


def _extract_crop(
    crop: Mapping[str, Any],
    *,
    rendered_page: Path,
    asset_dir: Path,
    render_specification: Mapping[str, Any],
) -> dict[str, Any]:
    page_hash = _sha256_file(rendered_page)
    if page_hash != crop["visual_reviewed_source_page_render_sha256"]:
        raise FigureAssetError(
            f"{crop['source_paper_id']}/{crop['canonical_ordinal']}: "
            "visually reviewed page-render hash drifted"
        )
    with Image.open(rendered_page) as page_image:
        page_image.load()
        page_size = [page_image.width, page_image.height]
        if page_size != crop["source_page_pixel_size"]:
            raise FigureAssetError(
                f"{crop['source_paper_id']}/{crop['canonical_ordinal']}: "
                f"rendered page size {page_size} != reviewed {crop['source_page_pixel_size']}"
            )
        box = _validate_crop_box(crop["crop_box_pixels"], page_size)
        image = page_image.convert("RGB").crop(box)

    asset_id = _asset_identity(crop)
    paper_dir = asset_dir / _slug(str(crop["source_paper_id"]))
    paper_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{asset_id}--{_slug(str(crop['asset_role']))}.png"
    output = paper_dir / filename
    image.save(output, format="PNG", optimize=False, compress_level=9)
    try:
        relative = str(output.relative_to(REPO_DIR)).replace("\\", "/")
    except ValueError:
        # Pure-function tests may use an isolated temporary directory.  The
        # full builder additionally requires every emitted path to be repo-local.
        relative = str(output.resolve())
    dpi = int(render_specification["dpi"])
    points = [round(value * 72 / dpi, 3) for value in box]
    return {
        "asset_id": asset_id,
        "relative_path": relative,
        "media_type": "image/png",
        "sha256": _sha256_file(output),
        "bytes": output.stat().st_size,
        "pixel_width": image.width,
        "pixel_height": image.height,
        "source_page": crop["source_page"],
        "source_pdf_sha256": crop["source_pdf_sha256"],
        "source_page_render_sha256": page_hash,
        "crop_box_pixels": list(box),
        "crop_box_pdf_points": points,
        "render_dpi": dpi,
        "asset_role": crop["asset_role"],
        "visual_kind": crop["visual_kind"],
        "alt_text": crop["alt_text"],
        "caption": crop["caption"],
        "review_status": crop["review_status"],
        "origin": "checksum_bound_original_question_paper_pdf_crop",
    }


def _validate_no_asset_review_page(
    *,
    key: tuple[str, int, str | None],
    page_review: Mapping[str, Any],
    rendered_page: Path,
) -> None:
    page_hash = _sha256_file(rendered_page)
    if page_hash != page_review["visual_reviewed_source_page_render_sha256"]:
        raise FigureAssetError(
            f"{key}: visually reviewed no-asset page-render hash drifted"
        )
    with Image.open(rendered_page) as page_image:
        page_image.load()
        page_size = [page_image.width, page_image.height]
    if page_size != page_review["source_page_pixel_size"]:
        raise FigureAssetError(
            f"{key}: no-asset page size {page_size} != reviewed "
            f"{page_review['source_page_pixel_size']}"
        )


def _load_children(
    legacy: Mapping[str, Any],
) -> dict[tuple[str, int, str], dict[str, Any]]:
    result: dict[tuple[str, int, str], dict[str, Any]] = {}
    for paper in legacy.get("papers") or []:
        if not isinstance(paper, dict):
            raise FigureAssetError("Legacy subpart paper is not an object")
        paper_id = str(paper.get("paper_id") or "")
        for decision in paper.get("decisions") or []:
            if not isinstance(decision, dict):
                raise FigureAssetError(f"{paper_id}: invalid legacy decision")
            ordinal = decision.get("parent_canonical_ordinal")
            for child in decision.get("child_records") or []:
                if not isinstance(child, dict):
                    raise FigureAssetError(f"{paper_id}/{ordinal}: invalid child")
                child_label = str(child.get("child_item_label") or "").strip()
                key = (paper_id, ordinal, child_label)
                if (
                    not isinstance(ordinal, int)
                    or ordinal < 1
                    or not child_label
                    or key in result
                ):
                    raise FigureAssetError(f"Invalid or duplicate legacy child {key}")
                enriched = dict(child)
                enriched["parent_item_label"] = decision.get("parent_item_label")
                result[key] = enriched
    if len(result) != EXPECTED_CHILDREN:
        raise FigureAssetError(
            f"Legacy audit exposes {len(result)} children, expected {EXPECTED_CHILDREN}"
        )
    return result


def _remote_visual_keys(
    matches: Mapping[str, Any], parent_keys: set[tuple[str, int]]
) -> set[tuple[str, int]]:
    result: set[tuple[str, int]] = set()
    for row in matches.get("matches") or []:
        if not isinstance(row, dict):
            raise FigureAssetError("Transcription match is not an object")
        flags = [str(flag) for flag in row.get("review_flags") or []]
        if "remote_visual_asset_not_copied" not in flags:
            continue
        key = (str(row.get("source_paper_id") or ""), row.get("canonical_ordinal"))
        if key not in parent_keys:
            raise FigureAssetError(f"Remote visual hint references unknown slot {key}")
        result.add(key)
    return result


def _source_files(
    *,
    manifest: Mapping[str, Any],
    provenance_rows: Mapping[tuple[str, int], Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    papers = manifest.get("papers")
    if not isinstance(papers, list) or len(papers) != EXPECTED_PAPERS:
        raise FigureAssetError("Source manifest must contain exactly 39 papers")
    manifest_by_id = {str(paper.get("id") or ""): paper for paper in papers}
    if len(manifest_by_id) != EXPECTED_PAPERS or "" in manifest_by_id:
        raise FigureAssetError("Source manifest contains duplicate or empty paper ids")
    paths_by_paper: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for (paper_id, _), row in provenance_rows.items():
        paths_by_paper[paper_id].add(
            (str(row.get("source_path") or ""), str(row.get("source_pdf_sha256") or ""))
        )
    result: dict[str, dict[str, Any]] = {}
    verified_by_path: dict[Path, tuple[str, int]] = {}
    for paper_id, paper in sorted(manifest_by_id.items()):
        identities = paths_by_paper.get(paper_id, set())
        if len(identities) != 1:
            raise FigureAssetError(f"{paper_id}: provenance source identity is not unique")
        source_path_raw, source_hash = next(iter(identities))
        source = Path(source_path_raw)
        expected_hash = str(paper.get("local_sha256") or "").casefold()
        if not source.is_file() or HASH_RE.fullmatch(expected_hash) is None:
            raise FigureAssetError(f"{paper_id}: source PDF is unavailable or unbound")
        if source_hash.casefold() != expected_hash:
            raise FigureAssetError(f"{paper_id}: provenance/manifest PDF hash mismatch")
        resolved = source.resolve()
        if resolved not in verified_by_path:
            actual_hash = _sha256_file(resolved)
            page_count = len(PdfReader(resolved).pages)
            verified_by_path[resolved] = (actual_hash, page_count)
        actual_hash, page_count = verified_by_path[resolved]
        if actual_hash != expected_hash:
            raise FigureAssetError(f"{paper_id}: source PDF SHA-256 mismatch")
        declared_pages = paper.get("local_page_count")
        if declared_pages is not None and page_count != int(declared_pages):
            raise FigureAssetError(f"{paper_id}: source PDF page-count mismatch")
        result[paper_id] = {
            "path": resolved,
            "sha256": actual_hash,
            "page_count": page_count,
            "manifest_local_file": paper.get("local_file"),
        }
    return result


def _load_crop_overrides(
    crops: Mapping[str, Any],
    *,
    parent_keys: set[tuple[str, int]],
    child_keys: set[tuple[str, int, str]],
    provenance_rows: Mapping[tuple[str, int], Mapping[str, Any]],
    sources: Mapping[str, Mapping[str, Any]],
) -> tuple[
    dict[tuple[str, int, str | None], list[dict[str, Any]]],
    dict[str, Any],
    dict[tuple[str, int, str | None], dict[str, Any]],
]:
    if (
        crops.get("production_import_authorized") is not False
        or crops.get("practice_eligible_count") != 0
        or crops.get("review_required") is not True
    ):
        raise FigureAssetError("Crop override staging guards failed")
    render_spec = crops.get("render_specification")
    if not isinstance(render_spec, dict) or render_spec.get("format") != "png":
        raise FigureAssetError("Crop override render specification is invalid")
    if render_spec.get("dpi") != 216 or render_spec.get("color_mode") != "rgb":
        raise FigureAssetError("Crop overrides must use reviewed 216-DPI RGB renders")
    result: dict[tuple[str, int, str | None], list[dict[str, Any]]] = defaultdict(list)
    seen_roles: set[tuple[str, int, str | None, str]] = set()
    for crop in crops.get("crops") or []:
        if not isinstance(crop, dict):
            raise FigureAssetError("Crop override is not an object")
        paper = str(crop.get("source_paper_id") or "")
        ordinal = crop.get("canonical_ordinal")
        child = crop.get("child_item_label")
        child = str(child) if child is not None else None
        key = (paper, ordinal, child)
        if child is None:
            if (paper, ordinal) not in parent_keys:
                raise FigureAssetError(f"Crop references unknown parent {key}")
        elif key not in child_keys:
            raise FigureAssetError(f"Crop references unknown child {key}")
        role = str(crop.get("asset_role") or "").strip()
        role_key = (*key, role)
        if not role or role_key in seen_roles:
            raise FigureAssetError(f"Duplicate or empty crop role {role_key}")
        seen_roles.add(role_key)
        source = sources[paper]
        source_hash = str(crop.get("source_pdf_sha256") or "").casefold()
        if source_hash != source["sha256"]:
            raise FigureAssetError(f"{key}: crop/source PDF hash mismatch")
        page = crop.get("source_page")
        parent_pages = provenance_rows[(paper, ordinal)].get("source_pages") or []
        if not isinstance(page, int) or page not in parent_pages:
            raise FigureAssetError(f"{key}: crop page is outside parent provenance")
        page_size = crop.get("source_page_pixel_size")
        _validate_crop_box(crop.get("crop_box_pixels"), page_size)
        for hash_field in (
            "source_pdf_sha256",
            "visual_reviewed_source_page_render_sha256",
        ):
            if HASH_RE.fullmatch(str(crop.get(hash_field) or "")) is None:
                raise FigureAssetError(f"{key}: malformed {hash_field}")
        for text_field in ("alt_text", "caption"):
            text = str(crop.get(text_field) or "").strip()
            if len(text) < 20 or len(text) > 500 or "<" in text or "http" in text.casefold():
                raise FigureAssetError(f"{key}: unsafe or unhelpful {text_field}")
        if crop.get("review_status") != "visually_reviewed_exact_bounds":
            raise FigureAssetError(f"{key}: crop was not visually reviewed")
        result[key].append(dict(crop))
    for values in result.values():
        values.sort(key=lambda row: (str(row["asset_role"]), int(row["source_page"])))

    no_asset_reviews: dict[tuple[str, int, str | None], dict[str, Any]] = {}
    for review in crops.get("no_asset_reviews") or []:
        if not isinstance(review, dict):
            raise FigureAssetError("No-asset review is not an object")
        paper = str(review.get("source_paper_id") or "")
        ordinal = review.get("canonical_ordinal")
        child = review.get("child_item_label")
        child = str(child) if child is not None else None
        key = (paper, ordinal, child)
        if child is not None:
            raise FigureAssetError(
                f"{key}: no-asset review currently requires a canonical parent"
            )
        if (paper, ordinal) not in parent_keys:
            raise FigureAssetError(f"No-asset review references unknown parent {key}")
        if key in no_asset_reviews or key in result:
            raise FigureAssetError(
                f"{key}: duplicate review or overlap with a reviewed crop"
            )
        source_hash = str(review.get("source_pdf_sha256") or "").casefold()
        if source_hash != sources[paper]["sha256"]:
            raise FigureAssetError(f"{key}: no-asset review/source PDF hash mismatch")
        if review.get("disposition") != "no_external_asset_required":
            raise FigureAssetError(f"{key}: unsupported no-asset disposition")
        if review.get("review_status") != "visually_reviewed_original_pages":
            raise FigureAssetError(f"{key}: no-asset disposition was not reviewed")
        rationale = str(review.get("rationale") or "").strip()
        if (
            len(rationale) < 20
            or len(rationale) > 500
            or "<" in rationale
            or "http" in rationale.casefold()
        ):
            raise FigureAssetError(f"{key}: unsafe or unhelpful no-asset rationale")
        expected_pages = sorted(
            set(
                int(page)
                for page in provenance_rows[(paper, ordinal)].get("source_pages") or []
            )
        )
        reviewed_pages = review.get("reviewed_source_pages")
        if not isinstance(reviewed_pages, list) or not reviewed_pages:
            raise FigureAssetError(f"{key}: reviewed source pages are missing")
        observed_pages: list[int] = []
        for page_review in reviewed_pages:
            if not isinstance(page_review, dict):
                raise FigureAssetError(f"{key}: reviewed page is not an object")
            page = page_review.get("source_page")
            size = page_review.get("source_page_pixel_size")
            render_hash = str(
                page_review.get("visual_reviewed_source_page_render_sha256") or ""
            )
            if not isinstance(page, int) or page < 1:
                raise FigureAssetError(f"{key}: reviewed page number is invalid")
            if (
                not isinstance(size, list)
                or len(size) != 2
                or any(not isinstance(value, int) or value < 1 for value in size)
            ):
                raise FigureAssetError(f"{key}: reviewed page size is invalid")
            if HASH_RE.fullmatch(render_hash) is None:
                raise FigureAssetError(f"{key}: reviewed page hash is malformed")
            observed_pages.append(page)
        if sorted(observed_pages) != expected_pages or len(observed_pages) != len(
            set(observed_pages)
        ):
            raise FigureAssetError(
                f"{key}: no-asset review must cover every provenance page exactly"
            )
        no_asset_reviews[key] = dict(review)

    reviewed_papers: set[str] = set()
    for paper_review in crops.get("paper_no_asset_reviews") or []:
        if not isinstance(paper_review, dict):
            raise FigureAssetError("Paper no-asset review is not an object")
        paper = str(paper_review.get("source_paper_id") or "")
        if paper not in sources:
            raise FigureAssetError(
                f"Paper no-asset review references unknown source {paper!r}"
            )
        if paper in reviewed_papers:
            raise FigureAssetError(f"{paper}: duplicate paper no-asset review")
        reviewed_papers.add(paper)
        source_hash = str(
            paper_review.get("source_pdf_sha256") or ""
        ).casefold()
        if source_hash != sources[paper]["sha256"]:
            raise FigureAssetError(
                f"{paper}: paper no-asset review/source PDF hash mismatch"
            )
        if (
            paper_review.get("disposition")
            != "no_external_asset_required_for_listed_parents"
        ):
            raise FigureAssetError(
                f"{paper}: unsupported paper no-asset disposition"
            )
        if (
            paper_review.get("review_status")
            != "visually_reviewed_all_original_pages"
        ):
            raise FigureAssetError(
                f"{paper}: paper no-asset disposition was not fully reviewed"
            )
        rationale = str(paper_review.get("rationale") or "").strip()
        if (
            len(rationale) < 20
            or len(rationale) > 500
            or "<" in rationale
            or "http" in rationale.casefold()
        ):
            raise FigureAssetError(
                f"{paper}: unsafe or unhelpful paper no-asset rationale"
            )
        reviewed_pages = paper_review.get("reviewed_source_pages")
        if not isinstance(reviewed_pages, list) or not reviewed_pages:
            raise FigureAssetError(f"{paper}: reviewed source pages are missing")
        page_map: dict[int, dict[str, Any]] = {}
        for page_review in reviewed_pages:
            if not isinstance(page_review, dict):
                raise FigureAssetError(
                    f"{paper}: paper-reviewed page is not an object"
                )
            page = page_review.get("source_page")
            size = page_review.get("source_page_pixel_size")
            render_hash = str(
                page_review.get("visual_reviewed_source_page_render_sha256") or ""
            )
            if (
                not isinstance(page, int)
                or page < 1
                or page > int(sources[paper]["page_count"])
                or page in page_map
            ):
                raise FigureAssetError(
                    f"{paper}: paper-reviewed page number is invalid or duplicate"
                )
            if (
                not isinstance(size, list)
                or len(size) != 2
                or any(not isinstance(value, int) or value < 1 for value in size)
            ):
                raise FigureAssetError(
                    f"{paper}: paper-reviewed page size is invalid"
                )
            if HASH_RE.fullmatch(render_hash) is None:
                raise FigureAssetError(
                    f"{paper}: paper-reviewed page hash is malformed"
                )
            page_map[page] = dict(page_review)
        expected_paper_pages = set(range(1, int(sources[paper]["page_count"]) + 1))
        if set(page_map) != expected_paper_pages:
            raise FigureAssetError(
                f"{paper}: paper review must bind every source PDF page exactly"
            )
        ordinals = paper_review.get("canonical_parent_ordinals")
        if (
            not isinstance(ordinals, list)
            or not ordinals
            or any(not isinstance(ordinal, int) or ordinal < 1 for ordinal in ordinals)
            or len(ordinals) != len(set(ordinals))
        ):
            raise FigureAssetError(
                f"{paper}: paper no-asset parent ordinals are invalid"
            )
        for ordinal in ordinals:
            key = (paper, ordinal, None)
            if (paper, ordinal) not in parent_keys:
                raise FigureAssetError(
                    f"Paper no-asset review references unknown parent {key}"
                )
            if key in no_asset_reviews or key in result:
                raise FigureAssetError(
                    f"{key}: duplicate review or overlap with a reviewed crop"
                )
            expected_pages = sorted(
                set(
                    int(page)
                    for page in provenance_rows[(paper, ordinal)].get(
                        "source_pages"
                    )
                    or []
                )
            )
            if not expected_pages or any(page not in page_map for page in expected_pages):
                raise FigureAssetError(
                    f"{key}: parent provenance is outside the paper review"
                )
            no_asset_reviews[key] = {
                "source_paper_id": paper,
                "canonical_ordinal": ordinal,
                "child_item_label": None,
                "source_pdf_sha256": source_hash,
                "disposition": "no_external_asset_required",
                "review_status": "visually_reviewed_original_pages",
                "rationale": rationale,
                "reviewed_source_pages": [
                    dict(page_map[page]) for page in expected_pages
                ],
                "paper_review_status": paper_review["review_status"],
            }
    return dict(result), dict(render_spec), no_asset_reviews


def _parent_prompt_values(
    canonical: Mapping[str, Any], overlay: Mapping[str, Any]
) -> list[str]:
    values: list[str] = []
    for value in (
        canonical.get("question_md"),
        (overlay.get("proposed_overlay") or {}).get("question_text")
        if isinstance(overlay.get("proposed_overlay"), dict)
        else None,
    ):
        if isinstance(value, str) and value.strip():
            values.append(value)
    return values


def _child_prompt_values(child: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    shared = child.get("shared_context")
    if isinstance(shared, dict):
        for field in ("canonical_parent_question", "additional_shared_text"):
            value = shared.get(field)
            if isinstance(value, str) and value.strip():
                values.append(value)
    value = child.get("prompt_text")
    if isinstance(value, str) and value.strip():
        values.append(value)
    return values


def _objective_options_available(
    canonical: Mapping[str, Any], overlay: Mapping[str, Any]
) -> bool:
    item_type = str(canonical.get("item_type") or "").casefold()
    if item_type not in {"mcq", "msq", "mcqm"}:
        return True
    canonical_options = canonical.get("options")
    proposed = overlay.get("proposed_overlay")
    overlay_options = proposed.get("options") if isinstance(proposed, dict) else None
    return bool(canonical_options) or bool(overlay_options)


def _record(
    *,
    key: tuple[str, int, str | None],
    item_label: str,
    record_kind: str,
    prompt_values: Sequence[str],
    source_pages: Sequence[int],
    source_pdf_sha256: str,
    signals: Sequence[str],
    assets: Sequence[dict[str, Any]],
    shared_parent_asset: bool = False,
    no_asset_review: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    status, assessment = decide_dependence_status(
        signals=signals,
        source_pages=source_pages,
        has_complete_reviewed_crop=bool(assets),
        visually_reviewed_no_asset_required=no_asset_review is not None,
    )
    flags: list[str] = []
    if status == "review_required":
        flags.append("manual_original_page_figure_review_required")
    elif status == "missing":
        flags.append("confirmed_visual_dependency_without_source_locator")
    if shared_parent_asset:
        flags.append("asset_shared_from_parent_context")
    review_disposition = None
    if no_asset_review is not None:
        review_disposition = {
            "disposition": "no_external_asset_required",
            "review_status": "visually_reviewed_original_pages",
            "rationale": str(no_asset_review["rationale"]),
            "reviewed_source_pages": [
                {
                    "source_page": int(page["source_page"]),
                    "source_page_pixel_size": list(page["source_page_pixel_size"]),
                    "source_page_render_sha256": str(
                        page["visual_reviewed_source_page_render_sha256"]
                    ),
                }
                for page in no_asset_review["reviewed_source_pages"]
            ],
        }
    return {
        "source_paper_id": key[0],
        "canonical_ordinal": key[1],
        "child_item_label": key[2],
        "item_label": item_label,
        "record_kind": record_kind,
        "dependence_status": status,
        "dependence_assessment": assessment,
        "source_pdf_sha256": source_pdf_sha256,
        "source_pages": sorted(set(int(page) for page in source_pages)),
        "prompt_text_sha256": _prompt_hashes(prompt_values),
        "detection_signals": sorted(set(signals)),
        "assets": list(assets),
        "visual_review_disposition": review_disposition,
        "review_flags": flags,
        "production_import_authorized": False,
    }


def build_figure_asset_index(
    *,
    manifest_path: Path = DEFAULT_MANIFEST,
    canonical_path: Path = DEFAULT_CANONICAL,
    provenance_path: Path = DEFAULT_PROVENANCE,
    overlay_path: Path = DEFAULT_OVERLAY,
    legacy_path: Path = DEFAULT_LEGACY,
    matches_path: Path = DEFAULT_MATCHES,
    crop_overrides_path: Path = DEFAULT_CROPS,
    asset_dir: Path = DEFAULT_ASSET_DIR,
    pdftoppm: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = _read_json(manifest_path)
    canonical = _read_json(canonical_path)
    provenance = _read_json(provenance_path)
    overlay = _read_json(overlay_path)
    legacy = _read_json(legacy_path)
    matches = _read_json(matches_path)
    crops = _read_json(crop_overrides_path)
    for label, value in (
        ("provenance", provenance),
        ("overlay", overlay),
        ("legacy subparts", legacy),
        ("transcription matches", matches),
    ):
        _validate_embedded_hash(value, label=label)
    if manifest.get("production_import_authorized") is not False:
        raise FigureAssetError("Source manifest is not staging-only")
    if provenance.get("production_import_authorized") is not False:
        raise FigureAssetError("Provenance artifact is not staging-only")
    if overlay.get("production_import_authorized") is not False:
        raise FigureAssetError("Transcription overlay is not staging-only")
    if legacy.get("production_import_authorized") is not False:
        raise FigureAssetError("Legacy expansion audit is not staging-only")
    if matches.get("production_import_authorized") is not False:
        raise FigureAssetError("Transcription match artifact is not staging-only")

    parent_rows = _unique_parent_rows(
        canonical.get("questions"), ordinal_field="ordinal", label="canonical archive"
    )
    provenance_rows = _unique_parent_rows(
        provenance.get("items"),
        ordinal_field="canonical_ordinal",
        label="original PDF provenance",
    )
    overlay_rows = _unique_parent_rows(
        overlay.get("items"),
        ordinal_field="canonical_ordinal",
        label="original transcription overlay",
    )
    if not (
        len(parent_rows)
        == len(provenance_rows)
        == len(overlay_rows)
        == EXPECTED_PARENTS
    ):
        raise FigureAssetError("Parent inputs must expose exactly 2,712 matching slots")
    if set(parent_rows) != set(provenance_rows) or set(parent_rows) != set(overlay_rows):
        raise FigureAssetError("Parent input slot identities drifted")
    children = _load_children(legacy)
    remote_visual = _remote_visual_keys(matches, set(parent_rows))
    sources = _source_files(manifest=manifest, provenance_rows=provenance_rows)
    crop_rows, render_specification, no_asset_reviews = _load_crop_overrides(
        crops,
        parent_keys=set(parent_rows),
        child_keys=set(children),
        provenance_rows=provenance_rows,
        sources=sources,
    )

    renderer = _find_pdftoppm(pdftoppm)
    asset_dir.mkdir(parents=True, exist_ok=True)
    extracted_by_key: dict[tuple[str, int, str | None], list[dict[str, Any]]] = {}
    validated_no_asset_reviews: set[tuple[str, int, str | None]] = set()
    with tempfile.TemporaryDirectory(prefix="gate-pyq-figure-render-") as temp:
        temp_dir = Path(temp)
        rendered_cache: dict[tuple[str, int], Path] = {}
        for key, values in sorted(
            crop_rows.items(), key=lambda item: (item[0][0], item[0][1], item[0][2] or "")
        ):
            assets: list[dict[str, Any]] = []
            for crop in values:
                render_key = (key[0], int(crop["source_page"]))
                rendered = rendered_cache.get(render_key)
                if rendered is None:
                    prefix = temp_dir / f"{_slug(key[0])}-page-{render_key[1]}"
                    rendered = _render_page(
                        Path(sources[key[0]]["path"]),
                        page=render_key[1],
                        dpi=int(render_specification["dpi"]),
                        pdftoppm=renderer,
                        output_prefix=prefix,
                    )
                    rendered_cache[render_key] = rendered
                assets.append(
                    _extract_crop(
                        crop,
                        rendered_page=rendered,
                        asset_dir=asset_dir,
                        render_specification=render_specification,
                    )
                )
            extracted_by_key[key] = assets

        for key, review in sorted(
            no_asset_reviews.items(),
            key=lambda item: (item[0][0], item[0][1], item[0][2] or ""),
        ):
            for page_review in review["reviewed_source_pages"]:
                render_key = (key[0], int(page_review["source_page"]))
                rendered = rendered_cache.get(render_key)
                if rendered is None:
                    prefix = temp_dir / f"{_slug(key[0])}-page-{render_key[1]}"
                    rendered = _render_page(
                        Path(sources[key[0]]["path"]),
                        page=render_key[1],
                        dpi=int(render_specification["dpi"]),
                        pdftoppm=renderer,
                        output_prefix=prefix,
                    )
                    rendered_cache[render_key] = rendered
                _validate_no_asset_review_page(
                    key=key,
                    page_review=page_review,
                    rendered_page=rendered,
                )
            validated_no_asset_reviews.add(key)
    if validated_no_asset_reviews != set(no_asset_reviews):
        raise FigureAssetError("No-asset reviews were not all render-validated")

    records: list[dict[str, Any]] = []
    parent_signals_by_key: dict[tuple[str, int], list[str]] = {}
    parent_assets_by_key: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for key in sorted(parent_rows):
        canonical_row = parent_rows[key]
        provenance_row = provenance_rows[key]
        overlay_row = overlay_rows[key]
        prompt_values = _parent_prompt_values(canonical_row, overlay_row)
        signals = detect_visual_signals(
            prompt_values,
            overlay_status_reason=str(overlay_row.get("status_reason") or "") or None,
            overlay_flags=[str(value) for value in overlay_row.get("review_flags") or []],
            remote_visual_hint=key in remote_visual,
            objective_options_available=_objective_options_available(
                canonical_row, overlay_row
            ),
        )
        parent_signals_by_key[key] = signals
        assets = extracted_by_key.get((key[0], key[1], None), [])
        parent_assets_by_key[key] = assets
        records.append(
            _record(
                key=(key[0], key[1], None),
                item_label=str(canonical_row.get("item_label") or ""),
                record_kind="canonical_parent",
                prompt_values=prompt_values,
                source_pages=provenance_row.get("source_pages") or [],
                source_pdf_sha256=str(provenance_row["source_pdf_sha256"]),
                signals=signals,
                assets=assets,
                no_asset_review=no_asset_reviews.get((key[0], key[1], None)),
            )
        )

    for key in sorted(children):
        paper, ordinal, child_label = key
        child = children[key]
        parent_key = (paper, ordinal)
        prompt_values = _child_prompt_values(child)
        child_specific_assets = extracted_by_key.get(key, [])
        shared_assets = parent_assets_by_key.get(parent_key, []) if not child_specific_assets else []
        assets = child_specific_assets or shared_assets
        parent_signals = [
            f"parent:{signal}" for signal in parent_signals_by_key[parent_key]
        ]
        signals = detect_visual_signals(
            prompt_values,
            objective_options_available=True,
            parent_signals=parent_signals,
        )
        provenance_row = provenance_rows[parent_key]
        records.append(
            _record(
                key=key,
                item_label=child_label,
                record_kind="expanded_legacy_child",
                prompt_values=prompt_values,
                source_pages=child.get("source_pages") or provenance_row.get("source_pages") or [],
                source_pdf_sha256=str(provenance_row["source_pdf_sha256"]),
                signals=signals,
                assets=assets,
                shared_parent_asset=bool(shared_assets),
            )
        )

    records.sort(
        key=lambda row: (
            row["source_paper_id"],
            row["canonical_ordinal"],
            row["child_item_label"] is not None,
            row["child_item_label"] or "",
        )
    )
    if len(records) != EXPECTED_AUDITED_RECORDS:
        raise FigureAssetError(
            f"Audited {len(records)} records, expected {EXPECTED_AUDITED_RECORDS}"
        )
    unique_keys = {
        (row["source_paper_id"], row["canonical_ordinal"], row["child_item_label"])
        for row in records
    }
    if len(unique_keys) != EXPECTED_AUDITED_RECORDS:
        raise FigureAssetError("Figure audit output contains duplicate record keys")

    papers_report: list[dict[str, Any]] = []
    for paper_id in sorted(sources):
        paper_records = [row for row in records if row["source_paper_id"] == paper_id]
        status_counts = Counter(row["dependence_status"] for row in paper_records)
        paper_assets = {
            asset["asset_id"]
            for row in paper_records
            for asset in row["assets"]
        }
        papers_report.append(
            {
                "paper_id": paper_id,
                "source_pdf_sha256": sources[paper_id]["sha256"],
                "source_page_count": sources[paper_id]["page_count"],
                "parent_item_count": sum(
                    row["record_kind"] == "canonical_parent" for row in paper_records
                ),
                "expanded_child_count": sum(
                    row["record_kind"] == "expanded_legacy_child"
                    for row in paper_records
                ),
                "audited_record_count": len(paper_records),
                "not_required_count": status_counts["not_required"],
                "visually_reviewed_no_asset_count": sum(
                    row["visual_review_disposition"] is not None
                    for row in paper_records
                ),
                "asset_ready_count": status_counts["asset_ready"],
                "review_required_count": status_counts["review_required"],
                "missing_count": status_counts["missing"],
                "confirmed_visual_blocker_count": sum(
                    row["dependence_status"] in {"review_required", "missing"}
                    and row["dependence_assessment"] == "confirmed"
                    for row in paper_records
                ),
                "potential_visual_review_count": sum(
                    row["dependence_status"] == "review_required"
                    and row["dependence_assessment"] == "potential"
                    for row in paper_records
                ),
                "unique_asset_count": len(paper_assets),
                "asset_reference_count": sum(len(row["assets"]) for row in paper_records),
            }
        )

    status_counts = Counter(row["dependence_status"] for row in records)
    unique_assets = {
        asset["asset_id"]: asset for row in records for asset in row["assets"]
    }
    source_bindings = [
        {
            "paper_id": paper_id,
            "manifest_local_file": sources[paper_id]["manifest_local_file"],
            "source_pdf_sha256": sources[paper_id]["sha256"],
            "source_page_count": sources[paper_id]["page_count"],
        }
        for paper_id in sorted(sources)
    ]
    artifact_core = {
        "schema_version": SCHEMA_VERSION,
        "scope": "Original-paper visual-dependence audit and reviewed figure crops for GATE CS 1996-2025",
        "database_writes_performed": False,
        "production_import_authorized": False,
        "automatic_promotion_allowed": False,
        "practice_eligible_count": 0,
        "identity": {
            "paper_count": EXPECTED_PAPERS,
            "canonical_parent_count": EXPECTED_PARENTS,
            "expanded_legacy_child_count": EXPECTED_CHILDREN,
            "audited_record_count": EXPECTED_AUDITED_RECORDS,
        },
        "input_bindings": {
            "source_manifest": _input_binding(manifest_path),
            "canonical_archive": _input_binding(canonical_path),
            "original_pdf_provenance": _input_binding(provenance_path),
            "original_transcription_overlay": _input_binding(overlay_path),
            "legacy_subpart_audit": _input_binding(legacy_path),
            "secondary_match_locator_hints": _input_binding(matches_path),
            "visually_reviewed_crop_overrides": _input_binding(crop_overrides_path),
        },
        "source_files": source_bindings,
        "render_specification": render_specification,
        "status_vocabulary": {
            "not_required": "No visual dependency was detected, or checksum-bound original pages were visually reviewed and explicitly found not to require an external asset.",
            "asset_ready": "All currently identified visual dependencies are covered by visually reviewed original-PDF crops.",
            "review_required": "A visual/layout risk or insufficient transcription evidence remains; no crop is promoted automatically.",
            "missing": "A visual dependency is confirmed but no checksum-bound original-paper page locator is available.",
        },
        "items": records,
        "papers": papers_report,
    }
    _safe_output(artifact_core)
    artifact_sha256 = _canonical_json_sha256(artifact_core)
    artifact = {**artifact_core, "artifact_sha256": artifact_sha256}
    report = {
        "schema_version": SCHEMA_VERSION,
        "artifact_sha256": artifact_sha256,
        "paper_count": len(papers_report),
        "canonical_parent_count": sum(
            row["record_kind"] == "canonical_parent" for row in records
        ),
        "expanded_legacy_child_count": sum(
            row["record_kind"] == "expanded_legacy_child" for row in records
        ),
        "audited_record_count": len(records),
        "not_required_count": status_counts["not_required"],
        "visually_reviewed_no_asset_count": sum(
            row["visual_review_disposition"] is not None for row in records
        ),
        "asset_ready_count": status_counts["asset_ready"],
        "review_required_count": status_counts["review_required"],
        "missing_count": status_counts["missing"],
        "confirmed_visual_dependency_count": sum(
            row["dependence_assessment"] == "confirmed" for row in records
        ),
        "confirmed_visual_blocker_count": sum(
            row["dependence_status"] in {"review_required", "missing"}
            and row["dependence_assessment"] == "confirmed"
            for row in records
        ),
        "potential_visual_review_count": sum(
            row["dependence_status"] == "review_required"
            and row["dependence_assessment"] == "potential"
            for row in records
        ),
        "detection_signal_counts": dict(
            sorted(Counter(signal for row in records for signal in row["detection_signals"]).items())
        ),
        "unique_asset_count": len(unique_assets),
        "asset_reference_count": sum(len(row["assets"]) for row in records),
        "remote_visual_locator_hint_count": len(remote_visual),
        "reviewed_crop_override_count": sum(len(rows) for rows in crop_rows.values()),
        "reviewed_no_asset_override_count": len(no_asset_reviews),
        "invariants": {
            "paper_count_is_39": len(papers_report) == EXPECTED_PAPERS,
            "canonical_parent_count_is_2712": sum(
                row["record_kind"] == "canonical_parent" for row in records
            )
            == EXPECTED_PARENTS,
            "expanded_child_count_is_272": sum(
                row["record_kind"] == "expanded_legacy_child" for row in records
            )
            == EXPECTED_CHILDREN,
            "audited_record_count_is_2984": len(records) == EXPECTED_AUDITED_RECORDS,
            "status_counts_cover_all_records": sum(status_counts.values()) == len(records),
            "all_records_staging_only": all(
                row["production_import_authorized"] is False for row in records
            ),
            "all_assets_are_original_pdf_crops": all(
                asset["origin"]
                == "checksum_bound_original_question_paper_pdf_crop"
                for asset in unique_assets.values()
            ),
            "all_asset_hashes_well_formed": all(
                HASH_RE.fullmatch(asset["sha256"]) is not None
                for asset in unique_assets.values()
            ),
            "all_asset_files_exist_and_match": all(
                (REPO_DIR / asset["relative_path"]).is_file()
                and _sha256_file(REPO_DIR / asset["relative_path"]) == asset["sha256"]
                for asset in unique_assets.values()
            ),
            "all_asset_paths_are_repo_relative": all(
                not Path(asset["relative_path"]).is_absolute()
                for asset in unique_assets.values()
            ),
            "asset_ready_records_have_assets": all(
                row["dependence_status"] != "asset_ready" or row["assets"]
                for row in records
            ),
            "not_required_records_have_no_assets": all(
                row["dependence_status"] != "not_required" or not row["assets"]
                for row in records
            ),
            "reviewed_no_asset_rows_are_exact_and_unblocked": all(
                row["visual_review_disposition"] is None
                or (
                    row["dependence_status"] == "not_required"
                    and row["dependence_assessment"] == "not_detected"
                    and not row["assets"]
                    and not row["review_flags"]
                    and sorted(
                        page["source_page"]
                        for page in row["visual_review_disposition"][
                            "reviewed_source_pages"
                        ]
                    )
                    == row["source_pages"]
                )
                for row in records
            ),
            "reviewed_no_asset_count_matches_overrides": sum(
                row["visual_review_disposition"] is not None for row in records
            )
            == len(no_asset_reviews),
            "missing_records_have_confirmed_signals": all(
                row["dependence_status"] != "missing"
                or row["dependence_assessment"] == "confirmed"
                for row in records
            ),
        },
        "papers": papers_report,
    }
    if not all(report["invariants"].values()):
        raise FigureAssetError(f"Figure asset invariants failed: {report['invariants']}")
    return artifact, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--canonical", type=Path, default=DEFAULT_CANONICAL)
    parser.add_argument("--provenance", type=Path, default=DEFAULT_PROVENANCE)
    parser.add_argument("--overlay", type=Path, default=DEFAULT_OVERLAY)
    parser.add_argument("--legacy", type=Path, default=DEFAULT_LEGACY)
    parser.add_argument("--matches", type=Path, default=DEFAULT_MATCHES)
    parser.add_argument("--crop-overrides", type=Path, default=DEFAULT_CROPS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--asset-dir", type=Path, default=DEFAULT_ASSET_DIR)
    parser.add_argument("--pdftoppm")
    args = parser.parse_args()
    artifact, report = build_figure_asset_index(
        manifest_path=args.manifest.resolve(),
        canonical_path=args.canonical.resolve(),
        provenance_path=args.provenance.resolve(),
        overlay_path=args.overlay.resolve(),
        legacy_path=args.legacy.resolve(),
        matches_path=args.matches.resolve(),
        crop_overrides_path=args.crop_overrides.resolve(),
        asset_dir=args.asset_dir.resolve(),
        pdftoppm=args.pdftoppm,
    )
    _write_json(args.output, artifact)
    report_path = args.output.with_suffix(".report.json")
    _write_json(report_path, report)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "report": str(report_path),
                "asset_dir": str(args.asset_dir),
                "artifact_sha256": artifact["artifact_sha256"],
                "paper_count": report["paper_count"],
                "canonical_parent_count": report["canonical_parent_count"],
                "expanded_legacy_child_count": report[
                    "expanded_legacy_child_count"
                ],
                "audited_record_count": report["audited_record_count"],
                "not_required_count": report["not_required_count"],
                "visually_reviewed_no_asset_count": report[
                    "visually_reviewed_no_asset_count"
                ],
                "asset_ready_count": report["asset_ready_count"],
                "review_required_count": report["review_required_count"],
                "missing_count": report["missing_count"],
                "confirmed_visual_blocker_count": report[
                    "confirmed_visual_blocker_count"
                ],
                "potential_visual_review_count": report[
                    "potential_visual_review_count"
                ],
                "unique_asset_count": report["unique_asset_count"],
                "asset_reference_count": report["asset_reference_count"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
