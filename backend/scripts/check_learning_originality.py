"""Detect suspicious long phrase overlap between learning copy and a reference PDF.

This is a maintenance check, not part of the deployed application. It reports
locations and counts without printing source passages, which keeps copyrighted
reference text out of logs.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

try:
    from pypdf import PdfReader
except ImportError as exc:  # pragma: no cover - developer environment helper
    raise SystemExit(
        "pypdf is required for this audit. Run it with the workspace Python "
        "runtime or install pypdf in a temporary developer environment."
    ) from exc


WORD_PATTERN = re.compile(r"[a-z0-9]+")
STRING_PATTERN = re.compile(
    r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`',
    re.DOTALL,
)


def normalized_words(value: str) -> list[str]:
    return WORD_PATTERN.findall(value.lower())


def ngrams(words: list[str], size: int):
    for index in range(len(words) - size + 1):
        yield tuple(words[index : index + size])


def pdf_words(path: Path) -> list[str]:
    reader = PdfReader(str(path))
    return normalized_words("\n".join(page.extract_text() or "" for page in reader.pages))


def source_literals(path: Path):
    source = path.read_text(encoding="utf-8")
    for match in STRING_PATTERN.finditer(source):
        literal = match.group(0)[1:-1].replace("\\n", " ").replace("\\\"", '"')
        line = source.count("\n", 0, match.start()) + 1
        yield line, literal


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit learning content for long verbatim overlap with a PDF.",
    )
    parser.add_argument("reference_pdf", type=Path)
    parser.add_argument(
        "--content-dir",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "app" / "learning" / "content",
    )
    parser.add_argument("--ngram-size", type=int, default=12)
    parser.add_argument("--max-shared-ngrams", type=int, default=0)
    args = parser.parse_args()

    if args.ngram_size < 8:
        parser.error("--ngram-size must be at least 8 to avoid generic phrase matches")
    if not args.reference_pdf.is_file():
        parser.error(f"reference PDF not found: {args.reference_pdf}")
    if not args.content_dir.is_dir():
        parser.error(f"content directory not found: {args.content_dir}")

    reference_ngrams = set(ngrams(pdf_words(args.reference_pdf), args.ngram_size))
    matches: list[tuple[Path, int, str]] = []
    for path in sorted(args.content_dir.glob("*.ts")):
        for line, literal in source_literals(path):
            for phrase in ngrams(normalized_words(literal), args.ngram_size):
                if phrase in reference_ngrams:
                    digest = hashlib.sha256(" ".join(phrase).encode()).hexdigest()[:12]
                    matches.append((path, line, digest))

    print(
        f"Originality audit: {len(matches)} shared {args.ngram_size}-word sequence(s) "
        f"across {len(list(args.content_dir.glob('*.ts')))} content file(s)."
    )
    for path, line, digest in matches[:25]:
        print(f"  {path}:{line} phrase-sha256={digest}")
    if len(matches) > 25:
        print(f"  ...and {len(matches) - 25} more")

    if len(matches) > args.max_shared_ngrams:
        print(
            "Audit failed: rewrite the flagged passage(s) and rerun. "
            "No reference text has been printed.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

