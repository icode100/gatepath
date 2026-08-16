"""Fail-closed delivery contract for materialized question images.

Staging archives point at checksum-reviewed crops under ``tmp/``.  Published
archives instead use immutable, same-origin ``question-assets/`` paths.  This
module accepts either exact representation, but a published path is trusted
only after its paper segment, SHA-named file, public-root containment, regular
file status, PNG header/dimensions, and bytes are all verified locally.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path, PurePosixPath
from typing import Any, Protocol


PUBLIC_ASSET_PREFIX = "/question-assets/pyq"
ARCHIVE_ASSET_PREFIX = ("tmp", "pyq", "build", "figure-assets")
PUBLISHED_ASSET_PREFIX = ("question-assets", "pyq")
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PUBLIC_ROOT = REPOSITORY_ROOT / "public"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
APPROVED_ASSET_ROLES = frozenset(
    {
        "answer_option_diagrams",
        "answer_option_table",
        "stem_and_answer_option_diagrams",
        "stem_and_answer_option_tables",
        "stem_chart",
        "stem_diagram",
        "stem_graph",
        "stem_table",
    }
)

_PAPER_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class QuestionAssetLike(Protocol):
    kind: str
    path: str
    alt: str
    sha256: str


class QuestionAssetValidationError(ValueError):
    """Raised when an archive asset is not safe to materialize publicly."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise QuestionAssetValidationError(
            f"published question asset cannot be read: {path}"
        ) from exc
    return digest.hexdigest()


def _validate_png(path: Path) -> None:
    try:
        with path.open("rb") as stream:
            header = stream.read(24)
    except OSError as exc:
        raise QuestionAssetValidationError(
            f"published question asset cannot be read: {path}"
        ) from exc
    if (
        len(header) < 24
        or header[:8] != PNG_SIGNATURE
        or header[12:16] != b"IHDR"
    ):
        raise QuestionAssetValidationError(
            "published question asset is not a dimensioned PNG"
        )
    width = int.from_bytes(header[16:20], "big")
    height = int.from_bytes(header[20:24], "big")
    if not 0 < width <= 100_000 or not 0 < height <= 100_000:
        raise QuestionAssetValidationError(
            "published question asset has invalid PNG dimensions"
        )


def _validated_published_file(source: PurePosixPath, *, sha256: str) -> Path:
    if PUBLIC_ROOT.is_symlink():
        raise QuestionAssetValidationError("public question asset root cannot be a symlink")
    try:
        root = PUBLIC_ROOT.resolve(strict=True)
    except OSError as exc:
        raise QuestionAssetValidationError(
            "public question asset root is missing"
        ) from exc
    candidate = PUBLIC_ROOT
    for part in source.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise QuestionAssetValidationError(
                "published question asset path cannot contain a symlink"
            )
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise QuestionAssetValidationError(
            "published question asset is missing or escapes the public root"
        ) from exc
    if not resolved.is_file():
        raise QuestionAssetValidationError(
            "published question asset must be a regular file"
        )
    _validate_png(resolved)
    if _sha256(resolved) != sha256:
        raise QuestionAssetValidationError(
            "published question asset checksum does not match its SHA filename"
        )
    return resolved


def _normalized_source_path(
    path: str, *, paper_id: str, sha256: str
) -> tuple[PurePosixPath, bool]:
    if not _PAPER_ID_RE.fullmatch(paper_id):
        raise QuestionAssetValidationError(f"unsafe source paper id {paper_id!r}")
    if "\\" in path:
        raise QuestionAssetValidationError("asset paths must use POSIX separators")
    source = PurePosixPath(path)
    if source.is_absolute() or ".." in source.parts or not source.name:
        raise QuestionAssetValidationError("asset path is absolute or contains traversal")
    archive_parent = (*ARCHIVE_ASSET_PREFIX, paper_id)
    if source.parts[:-1] == archive_parent and source.suffix.lower() == ".png":
        return source, False
    published_parent = (*PUBLISHED_ASSET_PREFIX, paper_id)
    if (
        source.parts[:-1] != published_parent
        or source.name != f"{sha256}.png"
    ):
        raise QuestionAssetValidationError(
            "asset path must be a direct staging PNG or the exact immutable "
            f"published route {'/'.join(published_parent)}/{sha256}.png"
        )
    _validated_published_file(source, sha256=sha256)
    return source, True


def public_question_asset(
    asset: QuestionAssetLike,
    *,
    paper_id: str,
) -> dict[str, str]:
    """Validate one release reference and return its client-safe projection."""

    role = str(asset.kind).strip()
    if role not in APPROVED_ASSET_ROLES:
        raise QuestionAssetValidationError(f"unapproved question asset role {role!r}")
    sha256 = str(asset.sha256).strip().lower()
    if not _SHA256_RE.fullmatch(sha256):
        raise QuestionAssetValidationError("question asset requires a lowercase SHA-256")
    _normalized_source_path(str(asset.path), paper_id=paper_id, sha256=sha256)
    alt_text = " ".join(str(asset.alt).split())
    if not alt_text or len(alt_text) > 1_000:
        raise QuestionAssetValidationError(
            "question asset alt text must contain 1 to 1000 characters"
        )
    return {
        "role": role,
        "url": f"{PUBLIC_ASSET_PREFIX}/{paper_id}/{sha256}.png",
        "alt_text": alt_text,
        "sha256": sha256,
    }


def public_question_assets(
    assets: list[QuestionAssetLike],
    *,
    paper_id: str,
) -> list[dict[str, str]]:
    """Return a deterministic, duplicate-free client projection."""

    projected: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for asset in assets:
        current = public_question_asset(asset, paper_id=paper_id)
        identity = (current["role"], current["sha256"])
        if identity in seen:
            raise QuestionAssetValidationError(
                f"duplicate question asset role/hash for {paper_id}: {identity}"
            )
        seen.add(identity)
        projected.append(current)
    return projected


def source_asset_parts(asset: QuestionAssetLike, *, paper_id: str) -> tuple[str, ...]:
    """Expose the already-validated repository-relative source path to tooling."""

    sha256 = str(asset.sha256).strip().lower()
    if not _SHA256_RE.fullmatch(sha256):
        raise QuestionAssetValidationError("question asset requires a lowercase SHA-256")
    source, published = _normalized_source_path(
        str(asset.path), paper_id=paper_id, sha256=sha256
    )
    return (("public", *source.parts) if published else source.parts)


def validate_public_asset_payload(value: Any) -> list[dict[str, str]]:
    """Validate stored JSON before API serialization.

    Existing non-PYQ rows receive ``[]`` from the migration.  Any malformed or
    remotely hosted entry fails closed instead of being emitted as an image.
    """

    if value is None:
        return []
    if not isinstance(value, list):
        raise QuestionAssetValidationError("stored question assets must be a list")
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for raw in value:
        if not isinstance(raw, dict) or set(raw) != {
            "role",
            "url",
            "alt_text",
            "sha256",
        }:
            raise QuestionAssetValidationError("stored question asset has invalid fields")
        role = raw.get("role")
        url = raw.get("url")
        alt_text = raw.get("alt_text")
        sha256 = raw.get("sha256")
        if not all(isinstance(item, str) for item in (role, url, alt_text, sha256)):
            raise QuestionAssetValidationError("stored question asset fields must be strings")
        if role not in APPROVED_ASSET_ROLES:
            raise QuestionAssetValidationError(f"stored asset role {role!r} is not approved")
        if not _SHA256_RE.fullmatch(sha256):
            raise QuestionAssetValidationError("stored asset SHA-256 is invalid")
        expected_suffix = f"/{sha256}.png"
        if (
            not url.startswith(f"{PUBLIC_ASSET_PREFIX}/")
            or not url.endswith(expected_suffix)
            or ".." in PurePosixPath(url).parts
            or "?" in url
            or "#" in url
        ):
            raise QuestionAssetValidationError("stored asset URL is not an immutable local PNG")
        normalized_alt = " ".join(alt_text.split())
        if not normalized_alt or len(normalized_alt) > 1_000:
            raise QuestionAssetValidationError("stored asset alt text is invalid")
        identity = (role, sha256)
        if identity in seen:
            raise QuestionAssetValidationError("stored question assets contain a duplicate")
        seen.add(identity)
        result.append(
            {
                "role": role,
                "url": url,
                "alt_text": normalized_alt,
                "sha256": sha256,
            }
        )
    return result
