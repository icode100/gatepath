"""Build a page cache and locator index for the GateOverflow reference books.

This utility is deliberately separate from the production PYQ importer.  It
does not assert that a GateOverflow transcription is authoritative; instead it
turns the three topic-organized reference PDFs into an auditable lookup layer
that can be used while transcribing the original question papers.

Generated artifacts live below ``tmp/pyq/reference/extracted`` (an ignored
directory):

* one UTF-8 text file per PDF page,
* one JSONL page index per volume,
* one JSONL question-locator index,
* a small representative prototype JSON, and
* JSON and Markdown coverage reports for 1996-2025.

Question metadata is joined by the stable book-local identifier printed before
each heading (for example ``3.19.9``).  The same identifier is printed in the
chapter's ``Answer Keys`` section.  An answer is emitted only when that exact
identifier has one unambiguous value in the relevant chapter answer-key span.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from pypdf import PdfReader


REPO_DIR = Path(__file__).resolve().parents[2]
DEFAULT_REFERENCE_DIR = REPO_DIR / "tmp" / "pyq" / "reference"
DEFAULT_OUTPUT_DIR = DEFAULT_REFERENCE_DIR / "extracted"
YEAR_MIN = 1996
YEAR_MAX = 2025

QUESTION_HEADING_RE = re.compile(
    r"(?m)^(?:(?P<topic>[^\r\n]{1,180}?):[ \t]*)?"
    r"GATE[ \t]+CSE[ \t]+(?P<year>19\d{2}|20\d{2})"
    r"(?:[ \t]*\|[ \t]*Set[ \t]*(?P<set>\d+))?"
    r"(?:[ \t]*\|[ \t]*(?P<section>GA|General Aptitude))?"
    r"[ \t]*\|[ \t]*Question:[ \t]*(?P<label>[^\r\n]+?)[ \t]*$"
)
GENERIC_GATE_HEADING_RE = re.compile(
    r"(?m)^(?:[^\r\n]{1,180}?:[ \t]*)?GATE"
    r"(?:(?:[ \t]+[A-Z]{2,4}[ \t]+(?:19\d{2}|20\d{2}))|"
    r"(?:(?:19\d{2}|20\d{2})[ \t]+[A-Z]{2,4}:))"
    r"[^\r\n]*$"
)
INTERNAL_ID_RE = re.compile(r"(?m)^(?P<id>\d+\.\d+\.\d+)\s*$")
CHAPTER_TOC_RE = re.compile(
    r"(?m)^(?P<chapter>\d{1,2})\s+"
    r"(?P<title>[A-Z][^\r\n]{2,140}?)\s+\((?P<count>\d+)\)\s*$"
)
SOURCE_TAG_RE = re.compile(r"(?m)^gate(?:cse)?-(?:19\d{2}|20\d{2})(?:-set\d+)?\s*$")
SLUG_LINE_RE = re.compile(r"^[a-z][a-z0-9-]{1,80}$")
ANSWER_PAIR_RE = re.compile(
    r"(?m)^(?P<id>\d+\.\d+\.\d+)\s*\n"
    r"(?P<answer>"
    r"(?:[A-E](?:\s*[;,]\s*[A-E])*)|"
    r"True|False|N/A|X|"
    r"[-+]?\d+(?:\.\d+)?(?:\s*:\s*[-+]?\d+(?:\.\d+)?)?"
    r")\s*$"
)

COURSE_TAG_TO_CODE = {
    "algorithms": "ALG",
    "compiler-design": "CD",
    "computer-networks": "CN",
    "computer-organization": "COA",
    "computer-organization-and-architecture": "COA",
    "data-structures": "PDS",
    "databases": "DBMS",
    "database-management-system": "DBMS",
    "digital-logic": "DL",
    "discrete-mathematics": "EM",
    "engineering-mathematics": "EM",
    "general-aptitude": "GA",
    "operating-system": "OS",
    "operating-systems": "OS",
    "programming": "PDS",
    "programming-and-data-structures": "PDS",
    "theory-of-computation": "TOC",
}

CHAPTER_TITLE_RULES: tuple[tuple[str, str], ...] = (
    ("general aptitude", "GA"),
    ("compiler", "CD"),
    ("theory of computation", "TOC"),
    ("algorithm", "ALG"),
    ("programming", "PDS"),
    ("data structure", "PDS"),
    ("co & architecture", "COA"),
    ("computer organization", "COA"),
    ("computer network", "CN"),
    ("database", "DBMS"),
    ("digital logic", "DL"),
    ("operating system", "OS"),
    ("discrete mathematics", "EM"),
    ("engineering mathematics", "EM"),
)

# Counts are asserted only where the 65-question format/session inventory is
# known.  Older formats are intentionally left unasserted in the report.
EXPECTED_65_QUESTION_SESSIONS: dict[int, tuple[str, ...]] = {
    2010: ("main",),
    2011: ("main",),
    2012: ("main",),
    2013: ("main",),
    2014: ("set1", "set2", "set3"),
    2015: ("set1", "set2", "set3"),
    2016: ("set1", "set2"),
    2017: ("set1", "set2"),
    2018: ("main",),
    2019: ("main",),
    2020: ("main",),
    2021: ("set1", "set2"),
    2022: ("main",),
    2023: ("main",),
    2024: ("set1", "set2"),
    2025: ("set1", "set2"),
}


@dataclass(frozen=True)
class PageSpan:
    page: int
    start: int
    end: int
    text: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _clean_text(text: str) -> str:
    return text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")


def _slugify(value: str) -> str:
    value = value.casefold().replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def extract_volume(
    pdf_path: Path,
    output_dir: Path,
    *,
    force: bool = False,
    progress_every: int = 25,
) -> tuple[list[str], dict[str, Any]]:
    """Extract one PDF to independently reusable page text files."""

    volume_dir = output_dir / "pages" / pdf_path.stem
    volume_dir.mkdir(parents=True, exist_ok=True)
    source_sha256 = _sha256(pdf_path)
    manifest_path = volume_dir / "manifest.json"
    prior_manifest: dict[str, Any] = {}
    if manifest_path.exists():
        prior_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_unchanged = prior_manifest.get("source_pdf_sha256") == source_sha256

    reader = PdfReader(pdf_path)
    page_texts: list[str] = []
    page_records: list[dict[str, Any]] = []
    cache_hits = 0
    low_text_pages: list[int] = []

    for page_number, page in enumerate(reader.pages, start=1):
        page_path = volume_dir / f"page-{page_number:04d}.txt"
        if source_unchanged and page_path.exists() and not force:
            text = page_path.read_text(encoding="utf-8")
            cache_hits += 1
        else:
            text = _clean_text(page.extract_text() or "")
            page_path.write_text(text, encoding="utf-8", newline="\n")
        page_texts.append(text)
        if len(re.sub(r"\s+", "", text)) < 80:
            low_text_pages.append(page_number)
        page_records.append(
            {
                "volume": pdf_path.stem,
                "page": page_number,
                "text_path": page_path.relative_to(output_dir).as_posix(),
                "character_count": len(text),
                "text_sha256": _text_sha256(text),
                "text": text,
            }
        )
        if progress_every and page_number % progress_every == 0:
            print(
                f"{pdf_path.name}: {page_number}/{len(reader.pages)} pages "
                f"({cache_hits} cache hits)",
                file=sys.stderr,
            )

    metadata = {
        "volume": pdf_path.stem,
        "source_pdf": pdf_path.name,
        "source_pdf_sha256": source_sha256,
        "source_pdf_bytes": pdf_path.stat().st_size,
        "page_count": len(reader.pages),
        "cache_hits": cache_hits,
        "low_text_page_count": len(low_text_pages),
        "low_text_pages": low_text_pages,
        "pdf_metadata": {
            str(key): str(value) for key, value in (reader.metadata or {}).items()
        },
    }
    _write_json(manifest_path, metadata)
    _write_jsonl(output_dir / f"{pdf_path.stem}.pages.jsonl", page_records)
    return page_texts, metadata


def _join_pages(page_texts: list[str]) -> tuple[str, list[PageSpan]]:
    chunks: list[str] = []
    spans: list[PageSpan] = []
    offset = 0
    for page_number, text in enumerate(page_texts, start=1):
        chunk = text + "\n"
        chunks.append(chunk)
        spans.append(PageSpan(page_number, offset, offset + len(chunk), text))
        offset += len(chunk)
    return "".join(chunks), spans


def _page_for_offset(spans: list[PageSpan], offset: int) -> int:
    starts = [span.start for span in spans]
    index = max(0, bisect_right(starts, offset) - 1)
    return spans[index].page


def _chapter_toc(text: str) -> dict[str, dict[str, Any]]:
    chapters: dict[str, dict[str, Any]] = {}
    # The generated books place the complete TOC at the front.  Restricting to
    # the first 12% avoids re-reading chapter headings from the content body.
    toc_text = text[: max(10_000, len(text) // 8)]
    for match in CHAPTER_TOC_RE.finditer(toc_text):
        chapter = match.group("chapter")
        chapters.setdefault(
            chapter,
            {
                "title": match.group("title").strip(),
                "declared_question_count": int(match.group("count")),
            },
        )
    return chapters


def _course_from_chapter(title: str | None) -> str | None:
    if not title:
        return None
    folded = title.casefold()
    return next((code for needle, code in CHAPTER_TITLE_RULES if needle in folded), None)


def _page_book_id_alignment(
    spans: list[PageSpan],
) -> tuple[dict[int, str], dict[str, Any]]:
    """Align book IDs to headings only on pages with a one-to-one layout.

    The HTML-to-PDF renderer emits all visible ``chapter.topic.ordinal`` IDs
    near the top of each page, followed by the corresponding question cards in
    the same order.  Proximity is therefore unsafe (it maps the last ID to the
    first card).  Page-order alignment is deterministic on almost every page;
    pages containing a topic boundary or an unsupported exam heading can have
    unequal counts and are withheld for manual review.
    """

    aligned: dict[int, str] = {}
    exact_pages = 0
    mismatch_pages: list[dict[str, Any]] = []
    heading_pages = 0
    for span in spans:
        headings = list(GENERIC_GATE_HEADING_RE.finditer(span.text))
        if not headings:
            continue
        heading_pages += 1
        ids = [
            match.group("id")
            for match in INTERNAL_ID_RE.finditer(span.text[: headings[0].start()])
        ]
        if len(ids) != len(headings):
            mismatch_pages.append(
                {
                    "page": span.page,
                    "book_id_count": len(ids),
                    "gate_heading_count": len(headings),
                }
            )
            continue
        exact_pages += 1
        for heading, book_id in zip(headings, ids, strict=True):
            aligned[span.start + heading.start()] = book_id
    return aligned, {
        "heading_page_count": heading_pages,
        "exact_alignment_page_count": exact_pages,
        "mismatch_page_count": len(mismatch_pages),
        "mismatch_pages": mismatch_pages,
    }


def _tag_lines(block: str) -> list[str]:
    marker = SOURCE_TAG_RE.search(block)
    if not marker:
        return []
    tail = block[marker.start() :]
    answer_key = tail.find("Answer key")
    if answer_key >= 0:
        tail = tail[:answer_key]
    result: list[str] = []
    for raw_line in tail.splitlines():
        line = raw_line.strip()
        if SLUG_LINE_RE.fullmatch(line):
            result.append(line)
    return result


def _course_from_tags(tags: list[str]) -> str | None:
    return next((COURSE_TAG_TO_CODE[tag] for tag in tags if tag in COURSE_TAG_TO_CODE), None)


def _question_body(block: str) -> str:
    marker = SOURCE_TAG_RE.search(block)
    body = block[: marker.start()] if marker else block
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return body


def _answer_maps(
    text: str,
    questions: list[dict[str, Any]],
) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Return unambiguous book-id answers and any conflicting candidates."""

    chapter_starts: dict[str, int] = {}
    for question in questions:
        chapter = question.get("chapter_number")
        if chapter:
            chapter_starts[chapter] = min(
                chapter_starts.get(chapter, question["heading_offset"]),
                question["heading_offset"],
            )
    ordered = sorted(chapter_starts.items(), key=lambda item: item[1])
    candidates: dict[str, set[str]] = defaultdict(set)

    for index, (chapter, start) in enumerate(ordered):
        end = ordered[index + 1][1] if index + 1 < len(ordered) else len(text)
        span = text[start:end]
        markers = [match.end() for match in re.finditer(r"(?m)^Answer Keys\s*$", span)]
        if not markers:
            continue
        # The last marker is the content answer key; earlier occurrences can be
        # generated navigation/TOC text in the HTML-to-PDF output.
        answer_text = span[markers[-1] :]
        for match in ANSWER_PAIR_RE.finditer(answer_text):
            book_id = match.group("id")
            if book_id.split(".", 1)[0] != chapter:
                continue
            answer = re.sub(r"\s+", "", match.group("answer")).replace(",", ";")
            candidates[book_id].add(answer)

    answers = {
        book_id: next(iter(values))
        for book_id, values in candidates.items()
        if len(values) == 1
    }
    conflicts = {
        book_id: sorted(values)
        for book_id, values in candidates.items()
        if len(values) > 1
    }
    return answers, conflicts


def parse_volume(
    volume: str,
    page_texts: list[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    text, spans = _join_pages(page_texts)
    chapters = _chapter_toc(text)
    book_ids_by_heading_offset, alignment_report = _page_book_id_alignment(spans)
    heading_matches = list(QUESTION_HEADING_RE.finditer(text))
    questions: list[dict[str, Any]] = []

    for index, match in enumerate(heading_matches):
        next_start = (
            heading_matches[index + 1].start()
            if index + 1 < len(heading_matches)
            else len(text)
        )
        book_id = book_ids_by_heading_offset.get(match.start())
        chapter_number = book_id.split(".", 1)[0] if book_id else None
        chapter = chapters.get(chapter_number or "", {})
        block = text[match.end() : next_start]
        tags = _tag_lines(block)
        course_from_chapter = _course_from_chapter(chapter.get("title"))
        course_from_tags = _course_from_tags(tags)
        course_code = course_from_chapter or course_from_tags
        year = int(match.group("year"))
        set_number = int(match.group("set")) if match.group("set") else None
        session = f"set{set_number}" if set_number else "main"
        topic_label = (match.group("topic") or "General Aptitude").strip()
        section_code = (
            "GA"
            if match.group("section") is not None or course_code == "GA"
            else "CS"
        )
        body = _question_body(block)
        questions.append(
            {
                "volume": volume,
                "source_page": _page_for_offset(spans, match.start()),
                "book_id": book_id,
                "chapter_number": chapter_number,
                "chapter_title": chapter.get("title"),
                "declared_chapter_question_count": chapter.get(
                    "declared_question_count"
                ),
                "year": year,
                "session": session,
                "set_number": set_number,
                "section_code": section_code,
                "item_label": match.group("label").strip(),
                "heading": match.group(0).strip(),
                "course_code": course_code,
                "course_from_chapter": course_from_chapter,
                "course_from_tags": course_from_tags,
                "course_mapping_agrees": (
                    course_from_chapter is None
                    or course_from_tags is None
                    or course_from_chapter == course_from_tags
                ),
                "topic_label": topic_label,
                "topic_slug": _slugify(topic_label),
                "tags": tags,
                "body_character_count": len(body),
                "body_preview": re.sub(r"\s+", " ", body)[:500].strip(),
                "heading_offset": match.start(),
            }
        )

    answers, answer_conflicts = _answer_maps(text, questions)
    for question in questions:
        book_id = question["book_id"]
        question["answer"] = answers.get(book_id) if book_id else None
        question["answer_join_status"] = (
            "joined"
            if book_id in answers
            else "conflict"
            if book_id in answer_conflicts
            else "missing"
        )
        question.pop("heading_offset")

    report = {
        "volume": volume,
        "chapter_toc": chapters,
        "heading_count_all_years": len(questions),
        "heading_count_1996_2025": sum(
            YEAR_MIN <= item["year"] <= YEAR_MAX for item in questions
        ),
        "book_id_count": sum(item["book_id"] is not None for item in questions),
        "answer_joined_count": sum(
            item["answer_join_status"] == "joined" for item in questions
        ),
        "answer_missing_count": sum(
            item["answer_join_status"] == "missing" for item in questions
        ),
        "answer_conflicts": answer_conflicts,
        "page_alignment": alignment_report,
    }
    return questions, report


def build_coverage(
    questions: list[dict[str, Any]],
    volume_reports: list[dict[str, Any]],
    extraction_manifests: list[dict[str, Any]],
) -> dict[str, Any]:
    in_scope = [
        item for item in questions if YEAR_MIN <= item["year"] <= YEAR_MAX
    ]
    key_counts = Counter(
        (
            item["year"],
            item["session"],
            item.get("section_code", "CS"),
            item["item_label"],
        )
        for item in in_scope
    )
    duplicates = [
        {
            "year": year,
            "session": session,
            "section_code": section_code,
            "item_label": label,
            "count": count,
        }
        for (year, session, section_code, label), count in sorted(key_counts.items())
        if count > 1
    ]

    years: list[dict[str, Any]] = []
    for year in range(YEAR_MIN, YEAR_MAX + 1):
        year_items = [item for item in in_scope if item["year"] == year]
        session_names = sorted({item["session"] for item in year_items})
        sessions: list[dict[str, Any]] = []
        expected_sessions = EXPECTED_65_QUESTION_SESSIONS.get(year)
        report_sessions = sorted(set(session_names) | set(expected_sessions or ()))
        for session in report_sessions:
            session_items = [
                item for item in year_items if item["session"] == session
            ]
            expected = 65 if expected_sessions and session in expected_sessions else None
            count = len(session_items)
            sessions.append(
                {
                    "session": session,
                    "question_heading_count": count,
                    "expected_question_count": expected,
                    "count_matches_expected": count == expected if expected else None,
                    "book_id_count": sum(item["book_id"] is not None for item in session_items),
                    "answer_joined_count": sum(
                        item["answer_join_status"] == "joined"
                        for item in session_items
                    ),
                    "course_mapped_count": sum(
                        item["course_code"] is not None for item in session_items
                    ),
                    "topic_mapped_count": sum(
                        bool(item["topic_slug"]) for item in session_items
                    ),
                }
            )
        years.append(
            {
                "year": year,
                "question_heading_count": len(year_items),
                "observed_sessions": session_names,
                "sessions": sessions,
            }
        )

    return {
        "schema_version": "1.0",
        "scope": {"year_min": YEAR_MIN, "year_max": YEAR_MAX},
        "source_role": (
            "GateOverflow reference locator only; original paper PDFs and "
            "official keys remain the transcription authority"
        ),
        "totals": {
            "question_heading_count": len(in_scope),
            "book_id_count": sum(item["book_id"] is not None for item in in_scope),
            "answer_joined_count": sum(
                item["answer_join_status"] == "joined" for item in in_scope
            ),
            "course_mapped_count": sum(item["course_code"] is not None for item in in_scope),
            "topic_mapped_count": sum(bool(item["topic_slug"]) for item in in_scope),
            "duplicate_year_session_section_label_count": len(duplicates),
        },
        "duplicates": duplicates,
        "years": years,
        "volumes": volume_reports,
        "extraction_manifests": extraction_manifests,
        "method": {
            "year_session_section_label": (
                "parsed from each 'GATE CSE YEAR | Set N | [GA |] Question: LABEL' heading; "
                "section is retained because GA and CS numbering can overlap"
            ),
            "topic": "topic label before the GATE CSE heading; normalized to a slug",
            "course": "book chapter number/title first, GateOverflow subject tag as fallback",
            "answer": (
                "exact join from the question's printed book_id to the last Answer Keys "
                "block within the same chapter; ambiguous joins are withheld"
            ),
            "source_page": "character offset mapped to the cached source PDF page",
        },
    }


def _prototype(questions: list[dict[str, Any]]) -> dict[str, Any]:
    samples: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    for question in questions:
        if not YEAR_MIN <= question["year"] <= YEAR_MAX:
            continue
        key = (question["year"], question["session"])
        if key in seen:
            continue
        seen.add(key)
        samples.append(question)
    return {
        "schema_version": "1.0-prototype",
        "description": "One locator sample per observed year/session.",
        "questions": samples,
    }


def _coverage_markdown(report: dict[str, Any]) -> str:
    totals = report["totals"]
    lines = [
        "# GateOverflow reference coverage (1996-2025)",
        "",
        "> Reference locator only. Original papers and official final answer keys remain authoritative.",
        "",
        f"- Question headings: {totals['question_heading_count']}",
        f"- Book IDs recovered: {totals['book_id_count']}",
        f"- Answers joined unambiguously: {totals['answer_joined_count']}",
        f"- Course mappings: {totals['course_mapped_count']}",
        f"- Topic mappings: {totals['topic_mapped_count']}",
        "- Duplicate year/session/section/label keys: "
        f"{totals['duplicate_year_session_section_label_count']}",
        "",
        "| Year | Session | Located | Expected | Match | Answer joins | Course mapped |",
        "|---:|:---|---:|---:|:---:|---:|---:|",
    ]
    for year in report["years"]:
        if not year["sessions"]:
            lines.append(f"| {year['year']} | - | 0 | - | - | 0 | 0 |")
            continue
        for session in year["sessions"]:
            expected = session["expected_question_count"]
            match = session["count_matches_expected"]
            lines.append(
                "| {year} | {session} | {count} | {expected} | {match} | "
                "{answers} | {courses} |".format(
                    year=year["year"],
                    session=session["session"],
                    count=session["question_heading_count"],
                    expected=expected if expected is not None else "-",
                    match="yes" if match is True else "no" if match is False else "-",
                    answers=session["answer_joined_count"],
                    courses=session["course_mapped_count"],
                )
            )
    lines.extend(
        [
            "",
            "## Mapping method",
            "",
            "1. Parse year, optional set, and item label from the printed question heading.",
            "2. Align page-local book IDs (`chapter.topic.ordinal`) to all GATE cards by page order.",
            "3. Map the chapter number through the volume TOC; use the subject tag only as a fallback.",
            "4. Normalize the printed topic title to the application-facing topic candidate slug.",
            "5. Join the book-local ID to the final `Answer Keys` block in that same chapter.",
            "6. Withhold missing or conflicting answer joins for manual review.",
            "",
        ]
    )
    return "\n".join(lines)


def build_reference_index(
    reference_dir: Path,
    output_dir: Path,
    *,
    force: bool = False,
    progress_every: int = 25,
) -> dict[str, Any]:
    pdf_paths = sorted(reference_dir.glob("filter1_volume*.pdf"))
    if len(pdf_paths) != 3:
        raise FileNotFoundError(
            f"Expected exactly 3 filter1_volume*.pdf files in {reference_dir}; "
            f"found {len(pdf_paths)}"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    all_questions: list[dict[str, Any]] = []
    volume_reports: list[dict[str, Any]] = []
    extraction_manifests: list[dict[str, Any]] = []

    for pdf_path in pdf_paths:
        page_texts, extraction_manifest = extract_volume(
            pdf_path,
            output_dir,
            force=force,
            progress_every=progress_every,
        )
        questions, volume_report = parse_volume(pdf_path.stem, page_texts)
        all_questions.extend(questions)
        volume_reports.append(volume_report)
        extraction_manifests.append(extraction_manifest)

    all_questions.sort(
        key=lambda item: (
            item["year"],
            item["session"],
            item["item_label"],
            item["volume"],
            item["source_page"],
        )
    )
    report = build_coverage(all_questions, volume_reports, extraction_manifests)
    _write_jsonl(output_dir / "question_locator_index.jsonl", all_questions)
    _write_json(output_dir / "prototype_index.json", _prototype(all_questions))
    _write_json(output_dir / "coverage_1996_2025.json", report)
    (output_dir / "coverage_1996_2025.md").write_text(
        _coverage_markdown(report),
        encoding="utf-8",
        newline="\n",
    )
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-dir", type=Path, default=DEFAULT_REFERENCE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--progress-every", type=int, default=25)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_reference_index(
        args.reference_dir.resolve(),
        args.output_dir.resolve(),
        force=args.force,
        progress_every=args.progress_every,
    )
    totals = report["totals"]
    print(
        "Indexed {question_heading_count} GATE CSE headings for 1996-2025; "
        "joined {answer_joined_count} answers and mapped {course_mapped_count} "
        "courses.".format(**totals)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
