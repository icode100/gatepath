"""Validate the complete tracked PYQ publication without staging lineage files.

This clean-checkout gate consumes only the six tracked publication JSON files
and the promoted PNGs under ``public/question-assets/pyq``.  The publication
proof binds those outputs to the exact frozen staging checkpoint while making
it explicit that the large extraction lineage is checksum-only and is not part
of the deployable package.  No database is opened or written.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

import publish_pyq_release as publisher


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=publisher.DEFAULT_PUBLISHED_STAGING)
    parser.add_argument(
        "--archive-report",
        type=Path,
        default=publisher.DEFAULT_PUBLISHED_STAGING_REPORT,
    )
    parser.add_argument(
        "--practice", type=Path, default=publisher.DEFAULT_PUBLISHED_PROMOTION
    )
    parser.add_argument(
        "--allowlist", type=Path, default=publisher.DEFAULT_PUBLISHED_ALLOWLIST
    )
    parser.add_argument(
        "--practice-report",
        type=Path,
        default=publisher.DEFAULT_PUBLISHED_PROMOTION_REPORT,
    )
    parser.add_argument("--proof", type=Path, default=publisher.DEFAULT_PUBLISHED_PROOF)
    parser.add_argument("--public-root", type=Path, default=publisher.PUBLIC_DIR)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    summary = publisher.validate_published_package(
        staging_path=args.archive,
        staging_report_path=args.archive_report,
        promotion_path=args.practice,
        allowlist_path=args.allowlist,
        promotion_report_path=args.practice_report,
        proof_path=args.proof,
        public_root=args.public_root,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
