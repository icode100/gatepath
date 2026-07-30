from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Subject, Topic
from app.question_bank import import_question_bank
from app.seed import seed_database


BACKEND_DIR = Path(__file__).resolve().parents[1]
BANK_PATH = BACKEND_DIR / "data" / "question_bank.json"
SCRIPTS_DIR = BACKEND_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from generate_question_bank import TOPICS  # noqa: E402


TECHNICAL_CODES = {
    "EM",
    "DL",
    "COA",
    "PDS",
    "ALG",
    "TOC",
    "CD",
    "OS",
    "DBMS",
    "CN",
}


def _section(markdown: str, heading: str) -> str:
    match = re.search(
        rf"(?:^|\n)##\s+{re.escape(heading)}\s*\n"
        rf"([\s\S]*?)(?=\n##\s+|$)",
        markdown,
        re.IGNORECASE,
    )
    return match.group(1).strip() if match else ""


def _list_section(markdown: str, heading: str) -> list[str]:
    return [
        re.sub(r"^\s*(?:[-*]|\d+[.)])\s+", "", line).strip()
        for line in _section(markdown, heading).splitlines()
        if re.match(r"^\s*(?:[-*]|\d+[.)])\s+", line)
    ]


def test_release_artifact_has_audited_note_metadata_for_every_canonical_topic() -> None:
    payload = json.loads(BANK_PATH.read_text(encoding="utf-8"))
    notes = payload["revision_notes"]
    by_topic = {
        (note["course"], note["topic"]): note
        for note in notes
    }
    expected_topics = {
        (topic.course, topic.name): topic
        for topic in TOPICS
    }

    assert len(by_topic) == len(expected_topics) == 64
    assert sum(course in TECHNICAL_CODES for course, _ in by_topic) == 60
    assert set(by_topic) == set(expected_topics)
    for key, topic in expected_topics.items():
        note = by_topic[key]
        assert note["key_points"] == list(topic.truths)
        assert len(set(note["key_points"])) >= 3
        assert len(set(note["common_traps"])) >= 3
        assert all(
            falsehood.lower() in trap.lower()
            for falsehood, trap in zip(
                topic.falsehoods,
                note["common_traps"],
                strict=True,
            )
        )
        assert note["summary"].strip()
        assert note["reasoning_pattern"].strip()


@pytest.mark.asyncio
async def test_import_builds_complete_topic_specific_revision_notes() -> None:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        await seed_database(session)
        await import_question_bank(session, BANK_PATH)
        subjects = list(
            (
                await session.scalars(
                    select(Subject).options(
                        selectinload(Subject.topics).selectinload(Topic.note)
                    )
                )
            ).all()
        )

        canonical_topics = [
            topic
            for subject in subjects
            for topic in subject.topics
        ]
        assert len(canonical_topics) == 64
        for topic in canonical_topics:
            assert topic.note is not None
            assert len(set(topic.note.key_points)) >= 3
            assert _section(topic.note.content_md, "Syllabus scope") == topic.description
            assert _section(topic.note.content_md, "Standard reasoning pattern")
            assert len(set(_list_section(topic.note.content_md, "Common traps"))) >= 3
            assert len(topic.note.worked_examples) >= 3
            assert all(
                example["question"].strip() and example["solution"].strip()
                for example in topic.note.worked_examples[:3]
            )

    await engine.dispose()
