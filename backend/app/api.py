from __future__ import annotations

import random
import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.csrf import require_csrf
from app.identity import current_user_key
from app.models import (
    Attempt,
    AttemptResponse,
    Difficulty,
    PracticeSession,
    Question,
    QuestionBankImport,
    QuestionSource,
    QuestionType,
    ResponseStatus,
    SessionMode,
    Subject,
    TestForm,
    Topic,
    utc_now,
)
from app.schemas import (
    AttemptResult,
    AttemptSubmit,
    AnalyticsDashboard,
    AnalyticsOverall,
    CatalogSessionCreate,
    PracticeSessionCreate,
    ProgressDashboard,
    ProgressResetRequest,
    ProgressResetResult,
    QuestionListResponse,
    QuestionBankImportSummary,
    QuestionBankStatus,
    QuestionPublic,
    QuestionResult,
    RecentAttempt,
    RevisionNoteRead,
    RoadmapResponse,
    RoadmapSubject,
    RoadmapTopic,
    SessionRead,
    SubjectDetail,
    SubjectProgress,
    SubjectSummary,
    TestCatalogItem,
    TestCatalogResponse,
    TestCreate,
    TopicAnalytics,
    TopicSummary,
)
from app.config import settings
from app.question_bank import resolve_question_bank_path
from app.question_assets import validate_public_asset_payload
from app.scoring import score_question
from app.user_state import (
    ProgressProjection,
    StudyAttempt,
    StudyResponse,
    StudySession,
    UserStateAlreadySubmitted,
    UserStateNotFound,
    UserStatePayloadTooLarge,
    UserStateRepository,
    UserStateUnavailable,
    rebuild_progress_projection,
)
from app.user_state.dependencies import get_user_state_repository


router = APIRouter()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _question_public(question: Question) -> QuestionPublic:
    return QuestionPublic(
        id=question.id,
        subject_id=question.subject_id,
        subject_slug=question.subject.slug,
        subject_name=question.subject.name,
        topic_id=question.topic_id,
        topic_slug=question.topic.slug,
        topic_name=question.topic.name,
        source=question.source,
        year=question.year,
        exam_session=question.exam_session,
        source_kind=question.source_kind,
        source_year=question.source_year,
        source_paper=question.source_paper,
        source_question_number=question.source_question_number,
        source_paper_id=question.source_paper_id,
        source_item_label=question.source_item_label,
        source_page=question.source_page,
        source_url=question.source_url,
        answer_key_url=question.answer_key_url,
        extraction_method=question.extraction_method,
        extraction_confidence=question.extraction_confidence,
        question_type=question.question_type,
        difficulty=question.difficulty,
        text=question.text,
        options=question.options,
        numerical_tolerance=(
            question.numerical_tolerance
            if question.question_type == QuestionType.NAT
            else None
        ),
        marks=question.marks,
        tags=question.tags,
        assets=validate_public_asset_payload(question.assets),
    )


def _question_snapshot(question: Question) -> dict[str, Any]:
    snapshot = _question_public(question).model_dump(mode="json")
    snapshot["correct_answer"] = question.correct_answer
    snapshot["explanation"] = question.explanation
    return snapshot


def _snapshot_question(snapshot: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(
        id=int(snapshot["id"]),
        question_type=QuestionType(snapshot["question_type"]),
        correct_answer=snapshot["correct_answer"],
        numerical_tolerance=float(snapshot.get("numerical_tolerance") or 0.01),
        marks=int(snapshot["marks"]),
    )


def _snapshots_by_id(
    session: PracticeSession | StudySession,
) -> dict[int, dict[str, Any]]:
    return {
        int(snapshot["id"]): snapshot
        for snapshot in (session.question_snapshots or [])
    }


async def _resolve_subject(
    db: AsyncSession,
    *,
    subject_id: int | None = None,
    subject_slug: str | None = None,
) -> Subject:
    if subject_id is not None:
        statement = select(Subject).where(Subject.id == subject_id)
    elif subject_slug is not None:
        statement = select(Subject).where(Subject.slug == subject_slug)
    else:
        raise HTTPException(status_code=422, detail="A subject is required")
    subject = await db.scalar(statement)
    if subject is None:
        raise HTTPException(status_code=404, detail="Subject not found")
    return subject


async def _load_questions(db: AsyncSession, question_ids: list[int]) -> list[Question]:
    if not question_ids:
        return []
    questions = (
        await db.scalars(
            select(Question)
            .where(Question.id.in_(question_ids))
            .options(selectinload(Question.subject), selectinload(Question.topic))
        )
    ).all()
    by_id = {question.id: question for question in questions}
    return [by_id[item] for item in question_ids if item in by_id]


async def _correctly_solved_question_ids(
    db: AsyncSession,
    user_state: UserStateRepository | None,
    *,
    user_key: str,
    candidate_ids: set[int],
) -> set[int]:
    """Return candidate questions the learner has answered correctly at least once.

    Correctly solved evidence is monotonic: a later miss does not make a mastered
    question unsolved. Firestore already maintains this projection, while the
    legacy Postgres path can answer the same question with a small distinct query.
    """

    if not candidate_ids:
        return set()
    if user_state is not None:
        try:
            progress = await user_state.get_progress(user_key)
        except (
            UserStateNotFound,
            UserStateAlreadySubmitted,
            UserStatePayloadTooLarge,
            UserStateUnavailable,
        ) as exc:
            _raise_user_state_http(exc)
        return {
            question_id
            for question_id in candidate_ids
            if (
                (evidence := progress.evidence.get(question_id)) is not None
                and evidence.correct_count > 0
            )
        }

    solved_ids = (
        await db.scalars(
            select(AttemptResponse.question_id)
            .join(Attempt, Attempt.id == AttemptResponse.attempt_id)
            .where(
                Attempt.user_key == user_key,
                AttemptResponse.question_id.in_(candidate_ids),
                AttemptResponse.status == ResponseStatus.CORRECT,
            )
            .distinct()
        )
    ).all()
    return set(solved_ids)


def _select_practice_batch(
    questions: list[Question],
    *,
    count: int,
    seed: int,
    solved_ids: set[int],
) -> list[Question]:
    """Select the learner's first not-yet-mastered stable practice batch.

    The seeded order partitions every filtered subject/topic pool into stable
    batches. A partially mastered batch is therefore returned unchanged on the
    next launch. Only after every question in it has been answered correctly at
    least once does selection advance to the next batch. Once the complete pool
    is mastered, the first batch becomes a deterministic revision set.
    """

    ordered = list(questions)
    random.Random(seed).shuffle(ordered)
    for offset in range(0, len(ordered), count):
        batch = ordered[offset : offset + count]
        if any(question.id not in solved_ids for question in batch):
            return batch
    return ordered[:count]


async def _session_read(
    db: AsyncSession,
    session: PracticeSession | StudySession,
) -> SessionRead:
    if session.question_snapshots:
        public_questions = [
            QuestionPublic.model_validate(snapshot)
            for snapshot in session.question_snapshots
        ]
    else:
        questions = await _load_questions(db, session.question_ids)
        public_questions = [_question_public(question) for question in questions]
    return SessionRead(
        id=session.id,
        user_key=session.user_key,
        catalog_id=session.catalog_id,
        mode=session.mode,
        subject_id=session.subject_id,
        topic_id=session.topic_id,
        question_count=session.question_count,
        duration_seconds=session.duration_seconds,
        total_marks=session.total_marks,
        seed=session.seed,
        started_at=session.started_at,
        expires_at=session.expires_at,
        is_submitted=session.is_submitted,
        questions=public_questions,
    )


def _raise_user_state_http(exc: Exception) -> None:
    if isinstance(exc, UserStateNotFound):
        raise HTTPException(status_code=404, detail="Session or attempt not found") from exc
    if isinstance(exc, UserStateAlreadySubmitted):
        raise HTTPException(status_code=409, detail="Session has already been submitted") from exc
    if isinstance(exc, UserStatePayloadTooLarge):
        raise HTTPException(
            status_code=413,
            detail="The study record is too large to store safely",
        ) from exc
    raise HTTPException(
        status_code=503,
        detail="User progress storage is temporarily unavailable",
    ) from exc


async def _persist_session(
    db: AsyncSession,
    user_state: UserStateRepository | None,
    *,
    user_key: str,
    catalog_id: str | None,
    mode: SessionMode,
    subject_id: int | None,
    topic_id: int | None,
    questions: list[Question],
    duration_seconds: int | None,
    total_marks: int,
    seed: int,
    started_at: datetime,
    expires_at: datetime | None,
) -> PracticeSession | StudySession:
    question_ids = [question.id for question in questions]
    snapshots = [_question_snapshot(question) for question in questions]
    if user_state is not None:
        session = StudySession(
            id=str(uuid.uuid4()),
            user_key=user_key,
            catalog_id=catalog_id,
            mode=mode.value,
            subject_id=subject_id,
            topic_id=topic_id,
            question_ids=tuple(question_ids),
            question_snapshots=tuple(snapshots),
            question_count=len(questions),
            duration_seconds=duration_seconds,
            total_marks=total_marks,
            seed=seed,
            started_at=started_at,
            expires_at=expires_at,
        )
        try:
            return await user_state.create_session(session)
        except (
            UserStateNotFound,
            UserStateAlreadySubmitted,
            UserStatePayloadTooLarge,
            UserStateUnavailable,
        ) as exc:
            _raise_user_state_http(exc)

    session = PracticeSession(
        user_key=user_key,
        catalog_id=catalog_id,
        mode=mode,
        subject_id=subject_id,
        topic_id=topic_id,
        question_ids=question_ids,
        question_snapshots=snapshots,
        question_count=len(questions),
        duration_seconds=duration_seconds,
        total_marks=total_marks,
        seed=seed,
        started_at=started_at,
        expires_at=expires_at,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


@router.get("/subjects", response_model=list[SubjectSummary], tags=["Curriculum"])
async def list_subjects(db: AsyncSession = Depends(get_db)) -> list[SubjectSummary]:
    topic_count = (
        select(func.count(Topic.id))
        .where(Topic.subject_id == Subject.id)
        .correlate(Subject)
        .scalar_subquery()
    )
    question_count = (
        select(func.count(Question.id))
        .where(Question.subject_id == Subject.id, Question.is_active.is_(True))
        .correlate(Subject)
        .scalar_subquery()
    )
    rows = (
        await db.execute(
            select(Subject, topic_count, question_count).order_by(Subject.order_index)
        )
    ).all()
    return [
        SubjectSummary(
            id=subject.id,
            slug=subject.slug,
            code=subject.code,
            name=subject.name,
            description=subject.description,
            order_index=subject.order_index,
            topic_count=topics,
            question_count=questions,
        )
        for subject, topics, questions in rows
    ]


@router.get("/subjects/{subject_ref}", response_model=SubjectDetail, tags=["Curriculum"])
async def get_subject(
    subject_ref: str, db: AsyncSession = Depends(get_db)
) -> SubjectDetail:
    statement = select(Subject).options(
        selectinload(Subject.topics).selectinload(Topic.questions),
        selectinload(Subject.topics).selectinload(Topic.note),
    )
    if subject_ref.isdigit():
        statement = statement.where(Subject.id == int(subject_ref))
    else:
        statement = statement.where(Subject.slug == subject_ref)
    subject = await db.scalar(statement)
    if subject is None:
        raise HTTPException(status_code=404, detail="Subject not found")
    topics = [
        TopicSummary(
            id=topic.id,
            subject_id=topic.subject_id,
            slug=topic.slug,
            name=topic.name,
            description=topic.description,
            order_index=topic.order_index,
            question_count=sum(question.is_active for question in topic.questions),
            note_available=topic.note is not None,
        )
        for topic in subject.topics
    ]
    return SubjectDetail(
        id=subject.id,
        slug=subject.slug,
        code=subject.code,
        name=subject.name,
        description=subject.description,
        order_index=subject.order_index,
        topic_count=len(subject.topics),
        question_count=sum(item.question_count for item in topics),
        topics=topics,
    )


@router.get("/topics/{topic_id}", response_model=TopicSummary, tags=["Curriculum"])
async def get_topic(topic_id: int, db: AsyncSession = Depends(get_db)) -> TopicSummary:
    topic = await db.scalar(
        select(Topic)
        .where(Topic.id == topic_id)
        .options(selectinload(Topic.questions), selectinload(Topic.note))
    )
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    return TopicSummary(
        id=topic.id,
        subject_id=topic.subject_id,
        slug=topic.slug,
        name=topic.name,
        description=topic.description,
        order_index=topic.order_index,
        question_count=sum(question.is_active for question in topic.questions),
        note_available=topic.note is not None,
    )


@router.get(
    "/topics/{topic_id}/notes", response_model=RevisionNoteRead, tags=["Revision Notes"]
)
async def get_topic_notes(
    topic_id: int, db: AsyncSession = Depends(get_db)
) -> RevisionNoteRead:
    topic = await db.scalar(
        select(Topic).where(Topic.id == topic_id).options(selectinload(Topic.note))
    )
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    if topic.note is None:
        raise HTTPException(status_code=404, detail="Revision notes not found")
    return RevisionNoteRead.model_validate(topic.note)


@router.get("/notes/{note_id}", response_model=RevisionNoteRead, tags=["Revision Notes"])
async def get_note(note_id: int, db: AsyncSession = Depends(get_db)) -> RevisionNoteRead:
    from app.models import RevisionNote

    note = await db.get(RevisionNote, note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="Revision note not found")
    return RevisionNoteRead.model_validate(note)


@router.get("/questions", response_model=QuestionListResponse, tags=["Question Bank"])
async def list_questions(
    subject_id: int | None = None,
    subject_slug: str | None = None,
    topic_id: int | None = None,
    source: QuestionSource | None = None,
    source_kind: QuestionSource | None = None,
    year: int | None = Query(default=None, ge=1987, le=2100),
    question_type: QuestionType | None = None,
    difficulty: Difficulty | None = None,
    search: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> QuestionListResponse:
    conditions: list[Any] = [Question.is_active.is_(True)]
    if subject_id is not None:
        conditions.append(Question.subject_id == subject_id)
    if subject_slug is not None:
        subject = await _resolve_subject(db, subject_slug=subject_slug)
        conditions.append(Question.subject_id == subject.id)
    if topic_id is not None:
        conditions.append(Question.topic_id == topic_id)
    if source is not None:
        conditions.append(Question.source == source)
    if source_kind is not None:
        conditions.append(Question.source_kind == source_kind)
    if year is not None:
        conditions.append(Question.year == year)
    if question_type is not None:
        conditions.append(Question.question_type == question_type)
    if difficulty is not None:
        conditions.append(Question.difficulty == difficulty)
    if search is not None and (search_term := search.strip()):
        # Treat user-entered LIKE metacharacters literally.  ``ilike`` compiles
        # to a portable case-insensitive predicate for both SQLite (tests/local)
        # and PostgreSQL (production).
        escaped_search = (
            search_term.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        search_pattern = f"%{escaped_search}%"
        conditions.append(
            or_(
                Question.text.ilike(search_pattern, escape="\\"),
                Question.source_paper.ilike(search_pattern, escape="\\"),
                Question.exam_session.ilike(search_pattern, escape="\\"),
                Question.external_id.ilike(search_pattern, escape="\\"),
                Question.source_url.ilike(search_pattern, escape="\\"),
            )
        )

    total = await db.scalar(select(func.count(Question.id)).where(*conditions)) or 0
    questions = (
        await db.scalars(
            select(Question)
            .where(*conditions)
            .options(selectinload(Question.subject), selectinload(Question.topic))
            .order_by(Question.id)
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return QuestionListResponse(
        items=[_question_public(question) for question in questions],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/question-bank/status",
    response_model=QuestionBankStatus,
    tags=["Question Bank"],
)
async def question_bank_status(
    db: AsyncSession = Depends(get_db),
) -> QuestionBankStatus:
    latest = await db.scalar(
        select(QuestionBankImport)
        .order_by(QuestionBankImport.imported_at.desc(), QuestionBankImport.id.desc())
        .limit(1)
    )
    total_questions = (
        await db.scalar(
            select(func.count(Question.id)).where(Question.is_active.is_(True))
        )
        or 0
    )
    return QuestionBankStatus(
        configured_path=str(resolve_question_bank_path(settings.question_bank_path)),
        total_questions=total_questions,
        latest_import=(
            QuestionBankImportSummary.model_validate(latest) if latest else None
        ),
    )


@router.get("/questions/{question_id}", response_model=QuestionPublic, tags=["Question Bank"])
async def get_question(
    question_id: int, db: AsyncSession = Depends(get_db)
) -> QuestionPublic:
    question = await db.scalar(
        select(Question)
        .where(Question.id == question_id, Question.is_active.is_(True))
        .options(selectinload(Question.subject), selectinload(Question.topic))
    )
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")
    return _question_public(question)


@router.post(
    "/practice-sessions",
    response_model=SessionRead,
    status_code=status.HTTP_201_CREATED,
    tags=["Practice and Tests"],
)
async def create_practice_session(
    payload: PracticeSessionCreate,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(current_user_key),
    user_state: UserStateRepository | None = Depends(get_user_state_repository),
) -> SessionRead:
    conditions: list[Any] = [Question.is_active.is_(True)]
    subject: Subject | None = None
    if payload.subject_id is not None or payload.subject_slug is not None:
        subject = await _resolve_subject(
            db,
            subject_id=payload.subject_id,
            subject_slug=payload.subject_slug,
        )
        conditions.append(Question.subject_id == subject.id)
    if payload.topic_id is not None:
        topic = await db.get(Topic, payload.topic_id)
        if topic is None:
            raise HTTPException(status_code=404, detail="Topic not found")
        if subject is not None and topic.subject_id != subject.id:
            raise HTTPException(status_code=422, detail="Topic does not belong to subject")
        conditions.append(Question.topic_id == topic.id)
        if subject is None:
            subject = await db.get(Subject, topic.subject_id)
    if payload.question_types:
        conditions.append(Question.question_type.in_(payload.question_types))
    if payload.difficulties:
        conditions.append(Question.difficulty.in_(payload.difficulties))
    if payload.source:
        conditions.append(Question.source == payload.source)

    questions = (
        await db.scalars(
            select(Question)
            .where(*conditions)
            .options(selectinload(Question.subject), selectinload(Question.topic))
            .order_by(Question.id)
        )
    ).all()
    if not questions:
        raise HTTPException(status_code=404, detail="No questions match these filters")
    solved_ids = await _correctly_solved_question_ids(
        db,
        user_state,
        user_key=user_key,
        candidate_ids={question.id for question in questions},
    )
    selected = _select_practice_batch(
        list(questions),
        count=payload.count,
        seed=payload.seed,
        solved_ids=solved_ids,
    )

    session = await _persist_session(
        db,
        user_state,
        user_key=user_key,
        catalog_id=None,
        mode=SessionMode.PRACTICE,
        subject_id=subject.id if subject else None,
        topic_id=payload.topic_id,
        questions=selected,
        duration_seconds=None,
        total_marks=sum(question.marks for question in selected),
        seed=payload.seed,
        started_at=utc_now(),
        expires_at=None,
    )
    return await _session_read(db, session)


def _catalog_item(form: TestForm) -> TestCatalogItem:
    return TestCatalogItem(
        id=form.id,
        title=form.title,
        description=form.description,
        mode=form.mode,
        subject_id=form.subject_id,
        subject_slug=form.subject.slug if form.subject else None,
        subject_code=form.subject.code if form.subject else None,
        form_number=form.form_number,
        question_count=form.question_count,
        duration_seconds=form.duration_seconds,
        total_marks=form.total_marks,
        question_type_counts=form.question_type_counts,
        topic_count=form.topic_count,
        is_available=form.is_available,
        unavailable_reason=form.unavailable_reason,
    )


@router.get(
    "/tests/catalog",
    response_model=TestCatalogResponse,
    tags=["Practice and Tests"],
)
async def list_test_catalog(
    mode: Literal["full", "sectional"] | None = None,
    subject_slug: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> TestCatalogResponse:
    conditions: list[Any] = []
    if mode:
        conditions.append(TestForm.mode == SessionMode(mode))
    if subject_slug:
        subject = await _resolve_subject(db, subject_slug=subject_slug)
        conditions.append(TestForm.subject_id == subject.id)
    forms = list(
        (
            await db.scalars(
                select(TestForm)
                .where(*conditions)
                .options(selectinload(TestForm.subject))
            )
        ).all()
    )
    forms.sort(
        key=lambda form: (
            0 if form.mode == SessionMode.FULL else 1,
            form.subject.order_index if form.subject else 0,
            form.form_number,
        )
    )
    items = [_catalog_item(form) for form in forms]
    return TestCatalogResponse(
        items=items,
        total=len(items),
        full_test_count=sum(item.mode == SessionMode.FULL for item in items),
        course_test_count=sum(item.mode == SessionMode.SECTIONAL for item in items),
        bank_version=forms[0].bank_version if forms else None,
    )


@router.post(
    "/tests/{catalog_id}/sessions",
    response_model=SessionRead,
    status_code=status.HTTP_201_CREATED,
    tags=["Practice and Tests"],
)
async def create_catalog_test_session(
    catalog_id: str,
    payload: CatalogSessionCreate,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(current_user_key),
    user_state: UserStateRepository | None = Depends(get_user_state_repository),
) -> SessionRead:
    form = await db.get(TestForm, catalog_id)
    if form is None:
        raise HTTPException(status_code=404, detail="Catalog test not found")
    if not form.is_available:
        raise HTTPException(
            status_code=409,
            detail=form.unavailable_reason or "Catalog test is not available",
        )
    questions = await _load_questions(db, form.question_ids)
    latest_bank_version = await db.scalar(
        select(QuestionBankImport.bank_version)
        .order_by(QuestionBankImport.imported_at.desc(), QuestionBankImport.id.desc())
        .limit(1)
    )
    if (
        len(questions) != form.question_count
        or any(not question.is_active for question in questions)
        or (
            latest_bank_version is not None
            and form.bank_version != latest_bank_version
        )
    ):
        raise HTTPException(
            status_code=409,
            detail="Catalog test is stale; rebuild the catalog from the current bank",
        )
    started_at = utc_now()
    session = await _persist_session(
        db,
        user_state,
        user_key=user_key,
        catalog_id=form.id,
        mode=form.mode,
        subject_id=form.subject_id,
        topic_id=None,
        questions=questions,
        duration_seconds=form.duration_seconds,
        total_marks=form.total_marks,
        seed=form.seed,
        started_at=started_at,
        expires_at=started_at + timedelta(seconds=form.duration_seconds),
    )
    return await _session_read(db, session)


@router.post(
    "/tests",
    response_model=SessionRead,
    status_code=status.HTTP_201_CREATED,
    tags=["Practice and Tests"],
)
async def create_test(
    payload: TestCreate,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(current_user_key),
    user_state: UserStateRepository | None = Depends(get_user_state_repository),
) -> SessionRead:
    rng = random.Random(payload.seed)
    subject: Subject | None = None

    if payload.mode == "full":
        all_questions = (
            await db.scalars(
                select(Question)
                .where(Question.is_active.is_(True))
                .options(selectinload(Question.subject))
                .options(selectinload(Question.topic))
                .order_by(Question.id)
            )
        ).all()
        ga_one = [
            question
            for question in all_questions
            if question.subject.slug == "general-aptitude" and question.marks == 1
        ]
        ga_two = [
            question
            for question in all_questions
            if question.subject.slug == "general-aptitude" and question.marks == 2
        ]
        em_one = [
            question
            for question in all_questions
            if question.subject.code == "EM" and question.marks == 1
        ]
        em_two = [
            question
            for question in all_questions
            if question.subject.code == "EM" and question.marks == 2
        ]
        core_one = [
            question
            for question in all_questions
            if question.subject.code not in {"GA", "EM"} and question.marks == 1
        ]
        core_two = [
            question
            for question in all_questions
            if question.subject.code not in {"GA", "EM"} and question.marks == 2
        ]
        if (
            len(ga_one) < 5
            or len(ga_two) < 5
            or len(em_one) < 5
            or len(em_two) < 4
            or len(core_one) < 20
            or len(core_two) < 26
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "A full mock requires 5 one-mark and 5 two-mark GA questions, "
                    "5 one-mark and 4 two-mark Engineering Mathematics questions, "
                    "plus 20 one-mark and 26 two-mark core CS questions"
                ),
            )
        for group in (ga_one, ga_two, em_one, em_two, core_one, core_two):
            rng.shuffle(group)
        selected = (
            ga_one[:5]
            + ga_two[:5]
            + em_one[:5]
            + em_two[:4]
            + core_one[:20]
            + core_two[:26]
        )
        duration_minutes = 180
        mode = SessionMode.FULL
    else:
        subject = await _resolve_subject(
            db,
            subject_id=payload.subject_id,
            subject_slug=payload.subject_slug,
        )
        available = (
            await db.scalars(
                select(Question)
                .where(
                    Question.subject_id == subject.id,
                    Question.is_active.is_(True),
                )
                .options(
                    selectinload(Question.subject),
                    selectinload(Question.topic),
                )
                .order_by(Question.id)
            )
        ).all()
        if len(available) < payload.count:
            raise HTTPException(
                status_code=409,
                detail=f"Only {len(available)} questions are available for this section",
            )
        rng.shuffle(available)
        selected = list(available[: payload.count])
        duration_minutes = payload.duration_minutes or min(180, max(15, payload.count * 3))
        mode = SessionMode.SECTIONAL

    started_at = utc_now()
    session = await _persist_session(
        db,
        user_state,
        user_key=user_key,
        catalog_id=None,
        mode=mode,
        subject_id=subject.id if subject else None,
        topic_id=None,
        questions=selected,
        duration_seconds=duration_minutes * 60,
        total_marks=sum(question.marks for question in selected),
        seed=payload.seed,
        started_at=started_at,
        expires_at=started_at + timedelta(minutes=duration_minutes),
    )
    return await _session_read(db, session)


@router.get("/sessions/{session_id}", response_model=SessionRead, tags=["Practice and Tests"])
async def get_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(current_user_key),
    user_state: UserStateRepository | None = Depends(get_user_state_repository),
) -> SessionRead:
    if user_state is not None:
        try:
            session = await user_state.get_session(user_key, session_id)
        except (
            UserStateNotFound,
            UserStateAlreadySubmitted,
            UserStatePayloadTooLarge,
            UserStateUnavailable,
        ) as exc:
            _raise_user_state_http(exc)
        return await _session_read(db, session)

    session = await db.get(PracticeSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_key != user_key:
        raise HTTPException(status_code=404, detail="Session not found")
    return await _session_read(db, session)


def _attempt_result(
    attempt: Attempt | StudyAttempt,
    questions: dict[int, Question] | None = None,
) -> AttemptResult:
    questions = questions or {}
    results = [
        QuestionResult(
            question_id=response.question_id,
            answer=response.answer,
            correct_answer=(
                response.correct_answer_snapshot
                if response.correct_answer_snapshot is not None
                else questions[response.question_id].correct_answer
            ),
            status=(
                response.status
                if isinstance(response.status, ResponseStatus)
                else ResponseStatus(response.status)
            ),
            awarded_marks=response.awarded_marks,
            max_marks=response.max_marks,
            negative_marks=response.negative_marks,
            explanation=(
                response.explanation_snapshot
                if response.explanation_snapshot is not None
                else questions[response.question_id].explanation
            ),
        )
        for response in attempt.responses
    ]
    percentage = round((attempt.score / attempt.max_score * 100), 2) if attempt.max_score else 0
    return AttemptResult(
        id=attempt.id,
        session_id=attempt.session_id,
        user_key=attempt.user_key,
        submitted_at=attempt.submitted_at,
        timed_out=attempt.timed_out,
        score=round(attempt.score, 4),
        max_score=attempt.max_score,
        percentage=percentage,
        correct_count=attempt.correct_count,
        incorrect_count=attempt.incorrect_count,
        unanswered_count=attempt.unanswered_count,
        results=results,
    )


@router.post(
    "/attempts",
    response_model=AttemptResult,
    status_code=status.HTTP_201_CREATED,
    tags=["Attempts and Progress"],
)
async def submit_attempt(
    payload: AttemptSubmit,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(current_user_key),
    user_state: UserStateRepository | None = Depends(get_user_state_repository),
) -> AttemptResult:
    if user_state is not None:
        try:
            session: PracticeSession | StudySession = await user_state.get_session(
                user_key,
                payload.session_id,
            )
        except (
            UserStateNotFound,
            UserStateAlreadySubmitted,
            UserStatePayloadTooLarge,
            UserStateUnavailable,
        ) as exc:
            _raise_user_state_http(exc)
        if session.is_submitted and session.attempt_id:
            try:
                existing = await user_state.get_attempt(user_key, session.attempt_id)
            except (
                UserStateNotFound,
                UserStateAlreadySubmitted,
                UserStatePayloadTooLarge,
                UserStateUnavailable,
            ) as exc:
                _raise_user_state_http(exc)
            return _attempt_result(existing)
    else:
        session = await db.get(PracticeSession, payload.session_id)
        if session is None or session.user_key != user_key:
            raise HTTPException(status_code=404, detail="Session not found")
        if session.is_submitted:
            raise HTTPException(status_code=409, detail="Session has already been submitted")

    submitted_ids = {answer.question_id for answer in payload.answers}
    unknown_ids = submitted_ids.difference(session.question_ids)
    if unknown_ids:
        raise HTTPException(
            status_code=422,
            detail=f"Answers include questions outside this session: {sorted(unknown_ids)}",
        )
    answer_by_id = {answer.question_id: answer.answer for answer in payload.answers}
    now = _aware(utc_now())
    timed_out = bool(session.expires_at and now >= _aware(session.expires_at))
    snapshots = _snapshots_by_id(session)
    missing_snapshot_ids = [
        question_id
        for question_id in session.question_ids
        if question_id not in snapshots
    ]
    questions = {
        question.id: question
        for question in await _load_questions(db, missing_snapshot_ids)
    }
    if any(
        question_id not in snapshots and question_id not in questions
        for question_id in session.question_ids
    ):
        raise HTTPException(
            status_code=409,
            detail="One or more immutable session questions are unavailable",
        )

    response_models: list[AttemptResponse] = []
    stored_responses: list[StudyResponse] = []
    correct = incorrect = unanswered = 0

    for question_id in session.question_ids:
        question = questions.get(question_id)
        snapshot = snapshots.get(question_id)
        if snapshot is None and question is not None:
            snapshot = _question_snapshot(question)
        if snapshot is None:  # Defensive: the completeness check above must hold.
            raise HTTPException(
                status_code=409,
                detail="An immutable session question is unavailable",
            )
        grading_question = _snapshot_question(snapshot)
        # Answers arriving at or after the deadline are deliberately discarded:
        # a late network request cannot turn an expired session into a score.
        answer = None if timed_out else answer_by_id.get(question_id)
        result = score_question(grading_question, answer)
        if result.status == ResponseStatus.CORRECT:
            correct += 1
        elif result.status == ResponseStatus.INCORRECT:
            incorrect += 1
        else:
            unanswered += 1
        stored_response = StudyResponse(
            question_id=question_id,
            subject_id=int(snapshot["subject_id"]),
            topic_id=int(snapshot["topic_id"]),
            answer=answer,
            correct_answer_snapshot=snapshot["correct_answer"],
            explanation_snapshot=str(snapshot.get("explanation") or ""),
            status=result.status.value,
            awarded_marks=result.awarded_marks,
            max_marks=float(grading_question.marks),
            negative_marks=result.negative_marks,
        )
        stored_responses.append(stored_response)
        if user_state is None:
            response_models.append(
                AttemptResponse(
                    question_id=question_id,
                    answer=answer,
                    correct_answer_snapshot=stored_response.correct_answer_snapshot,
                    explanation_snapshot=stored_response.explanation_snapshot,
                    status=result.status,
                    awarded_marks=result.awarded_marks,
                    max_marks=stored_response.max_marks,
                    negative_marks=result.negative_marks,
                )
            )

    score = round(sum(item.awarded_marks for item in stored_responses), 6)
    if user_state is not None:
        candidate = StudyAttempt(
            id=session.id,
            session_id=session.id,
            user_key=user_key,
            submitted_at=now,
            timed_out=timed_out,
            score=score,
            max_score=float(session.total_marks),
            correct_count=correct,
            incorrect_count=incorrect,
            unanswered_count=unanswered,
            mode=(
                session.mode.value
                if isinstance(session.mode, SessionMode)
                else session.mode
            ),
            subject_id=session.subject_id,
            topic_id=session.topic_id,
            catalog_id=session.catalog_id,
            responses=tuple(stored_responses),
        )
        try:
            stored_attempt = await user_state.submit_attempt(
                user_key,
                session.id,
                candidate,
            )
        except (
            UserStateNotFound,
            UserStateAlreadySubmitted,
            UserStatePayloadTooLarge,
            UserStateUnavailable,
        ) as exc:
            _raise_user_state_http(exc)
        return _attempt_result(stored_attempt)

    attempt = Attempt(
        session=session,
        user_key=user_key,
        submitted_at=now,
        timed_out=timed_out,
        score=score,
        max_score=float(session.total_marks),
        correct_count=correct,
        incorrect_count=incorrect,
        unanswered_count=unanswered,
        responses=response_models,
    )
    session.is_submitted = True
    db.add(attempt)
    await db.commit()
    attempt = await db.scalar(
        select(Attempt)
        .where(Attempt.id == attempt.id)
        .options(selectinload(Attempt.responses))
    )
    if attempt is None:  # Defensive: the committed attempt must be retrievable.
        raise HTTPException(status_code=500, detail="Submitted attempt could not be loaded")
    return _attempt_result(attempt, questions)


@router.get("/attempts/{attempt_id}", response_model=AttemptResult, tags=["Attempts and Progress"])
async def get_attempt(
    attempt_id: str,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(current_user_key),
    user_state: UserStateRepository | None = Depends(get_user_state_repository),
) -> AttemptResult:
    if user_state is not None:
        try:
            attempt = await user_state.get_attempt(user_key, attempt_id)
        except (
            UserStateNotFound,
            UserStateAlreadySubmitted,
            UserStatePayloadTooLarge,
            UserStateUnavailable,
        ) as exc:
            _raise_user_state_http(exc)
        return _attempt_result(attempt)

    attempt = await db.scalar(
        select(Attempt)
        .where(Attempt.id == attempt_id)
        .options(
            selectinload(Attempt.responses)
            .selectinload(AttemptResponse.question)
            .selectinload(Question.subject),
            selectinload(Attempt.responses)
            .selectinload(AttemptResponse.question)
            .selectinload(Question.topic),
        )
    )
    if attempt is None:
        raise HTTPException(status_code=404, detail="Attempt not found")
    if attempt.user_key != user_key:
        raise HTTPException(status_code=404, detail="Attempt not found")
    questions = {response.question_id: response.question for response in attempt.responses}
    return _attempt_result(attempt, questions)


async def _attempts_for_user(db: AsyncSession, user_key: str) -> list[Attempt]:
    return list(
        (
            await db.scalars(
                select(Attempt)
                .where(Attempt.user_key == user_key)
                .options(
                    selectinload(Attempt.responses)
                    .selectinload(AttemptResponse.question)
                    .selectinload(Question.subject),
                    selectinload(Attempt.responses)
                    .selectinload(AttemptResponse.question)
                    .selectinload(Question.topic),
                    selectinload(Attempt.session),
                )
                .order_by(Attempt.submitted_at.desc())
            )
        ).all()
    )


def _study_attempt_from_orm(attempt: Attempt) -> StudyAttempt:
    return StudyAttempt(
        id=attempt.id,
        session_id=attempt.session_id,
        user_key=attempt.user_key,
        submitted_at=_aware(attempt.submitted_at),
        timed_out=attempt.timed_out,
        score=attempt.score,
        max_score=attempt.max_score,
        correct_count=attempt.correct_count,
        incorrect_count=attempt.incorrect_count,
        unanswered_count=attempt.unanswered_count,
        mode=attempt.session.mode.value,
        subject_id=attempt.session.subject_id,
        topic_id=attempt.session.topic_id,
        catalog_id=attempt.session.catalog_id,
        responses=tuple(
            StudyResponse(
                question_id=response.question_id,
                subject_id=response.question.subject_id,
                topic_id=response.question.topic_id,
                answer=response.answer,
                correct_answer_snapshot=(
                    response.correct_answer_snapshot
                    if response.correct_answer_snapshot is not None
                    else response.question.correct_answer
                ),
                explanation_snapshot=(
                    response.explanation_snapshot
                    if response.explanation_snapshot is not None
                    else response.question.explanation
                ),
                status=response.status.value,
                awarded_marks=response.awarded_marks,
                max_marks=response.max_marks,
                negative_marks=response.negative_marks,
            )
            for response in attempt.responses
        ),
    )


async def _progress_for_user(
    db: AsyncSession,
    user_state: UserStateRepository | None,
    user_key: str,
) -> ProgressProjection:
    if user_state is not None:
        try:
            return await user_state.get_progress(user_key)
        except (
            UserStateNotFound,
            UserStateAlreadySubmitted,
            UserStatePayloadTooLarge,
            UserStateUnavailable,
        ) as exc:
            _raise_user_state_http(exc)
    attempts = await _attempts_for_user(db, user_key)
    return rebuild_progress_projection(
        user_key,
        tuple(_study_attempt_from_orm(attempt) for attempt in attempts),
    )


@router.get("/progress/dashboard", response_model=ProgressDashboard, tags=["Attempts and Progress"])
async def progress_dashboard(
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(current_user_key),
    user_state: UserStateRepository | None = Depends(get_user_state_repository),
) -> ProgressDashboard:
    subjects = list((await db.scalars(select(Subject).order_by(Subject.order_index))).all())
    progress = await _progress_for_user(db, user_state, user_key)

    subject_progress: list[SubjectProgress] = []
    for subject in subjects:
        bucket = progress.subjects.get(subject.id)
        correct = bucket.correct_count if bucket else 0
        incorrect = bucket.incorrect_count if bucket else 0
        unanswered = bucket.unanswered_count if bucket else 0
        answered = correct + incorrect
        accuracy = round(correct / answered * 100, 2) if answered else 0.0
        subject_progress.append(
            SubjectProgress(
                subject_id=subject.id,
                subject_slug=subject.slug,
                subject_name=subject.name,
                attempted_questions=bucket.attempted_questions if bucket else 0,
                unique_questions_attempted=(
                    bucket.unique_questions_attempted if bucket else 0
                ),
                correct=correct,
                incorrect=incorrect,
                unanswered=unanswered,
                accuracy=accuracy,
                marks_earned=round(bucket.marks_earned, 4) if bucket else 0.0,
                marks_available=bucket.marks_available if bucket else 0.0,
            )
        )

    total_correct = progress.correct_count
    total_incorrect = progress.incorrect_count
    total_unanswered = progress.unanswered_count
    answered_total = total_correct + total_incorrect
    recent = [
        RecentAttempt(
            attempt_id=attempt.attempt_id,
            session_id=attempt.session_id,
            mode=SessionMode(attempt.mode),
            submitted_at=attempt.submitted_at,
            score=round(attempt.score, 4),
            max_score=attempt.max_score,
            percentage=round(attempt.score / attempt.max_score * 100, 2)
            if attempt.max_score
            else 0.0,
        )
        for attempt in progress.recent_attempts
    ]
    return ProgressDashboard(
        user_key=user_key,
        total_attempts=progress.total_attempts,
        total_responses=total_correct + total_incorrect + total_unanswered,
        correct=total_correct,
        incorrect=total_incorrect,
        unanswered=total_unanswered,
        accuracy=round(total_correct / answered_total * 100, 2) if answered_total else 0.0,
        total_score=round(progress.total_score, 4),
        total_max_score=progress.total_max_score,
        average_test_percentage=round(
            progress.percentage_sum / progress.total_attempts,
            2,
        )
        if progress.total_attempts
        else 0.0,
        subjects=subject_progress,
        recent_attempts=recent,
    )


@router.post(
    "/progress/reset",
    response_model=ProgressResetResult,
    tags=["Attempts and Progress"],
)
async def reset_progress(
    payload: ProgressResetRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(current_user_key),
    user_state: UserStateRepository | None = Depends(get_user_state_repository),
) -> ProgressResetResult:
    """Irreversibly clear study state for the current cookie identity only."""

    response.headers["Cache-Control"] = "no-store"
    require_csrf(request, payload.csrf_token)
    if user_state is not None:
        try:
            summary = await user_state.reset_progress(user_key)
        except (
            UserStateNotFound,
            UserStateAlreadySubmitted,
            UserStatePayloadTooLarge,
            UserStateUnavailable,
        ) as exc:
            _raise_user_state_http(exc)
        return ProgressResetResult(
            user_key=user_key,
            sessions_deleted=summary.sessions_deleted,
            attempts_deleted=summary.attempts_deleted,
            progress_deleted=summary.progress_deleted,
        )

    try:
        attempt_result = await db.execute(
            delete(Attempt).where(Attempt.user_key == user_key)
        )
        session_result = await db.execute(
            delete(PracticeSession).where(PracticeSession.user_key == user_key)
        )
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Progress reset is temporarily unavailable",
        ) from exc

    return ProgressResetResult(
        user_key=user_key,
        sessions_deleted=max(0, int(session_result.rowcount or 0)),
        attempts_deleted=max(0, int(attempt_result.rowcount or 0)),
        progress_deleted=False,
    )


def _weighted_accuracy(
    responses: list[tuple[ResponseStatus, datetime]],
    *,
    now: datetime,
) -> float:
    answered = [
        (response_status, submitted_at)
        for response_status, submitted_at in responses
        if response_status != ResponseStatus.UNANSWERED
    ]
    if not answered:
        return 0.0
    weighted_correct = 0.0
    total_weight = 0.0
    for response_status, submitted_at in answered:
        age_days = max(0.0, (now - _aware(submitted_at)).total_seconds() / 86_400)
        weight = 0.5 ** (age_days / 30.0)
        total_weight += weight
        if response_status == ResponseStatus.CORRECT:
            weighted_correct += weight
    return weighted_correct / total_weight if total_weight else 0.0


def _mastery_score(
    *,
    accuracy: float,
    recency_accuracy: float,
    answered_count: int,
    coverage: float,
    volume_target: int,
) -> float:
    volume = min(answered_count / volume_target, 1.0)
    return 100 * (
        0.45 * accuracy
        + 0.20 * recency_accuracy
        + 0.20 * volume
        + 0.15 * coverage
    )


@router.get(
    "/progress/analytics",
    response_model=AnalyticsDashboard,
    tags=["Attempts and Progress"],
)
async def progress_analytics(
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(current_user_key),
    user_state: UserStateRepository | None = Depends(get_user_state_repository),
) -> AnalyticsDashboard:
    subjects = list(
        (
            await db.scalars(
                select(Subject)
                .options(selectinload(Subject.topics))
                .order_by(Subject.order_index)
            )
        ).all()
    )
    active_question_rows = (
        await db.execute(
            select(Question.id, Question.topic_id).where(
                Question.is_active.is_(True)
            )
        )
    ).all()
    active_question_ids = {question_id for question_id, _ in active_question_rows}
    topic_question_counts: dict[int, int] = defaultdict(int)
    for _, topic_id in active_question_rows:
        topic_question_counts[topic_id] += 1
    progress = await _progress_for_user(db, user_state, user_key)
    now = utc_now()
    topic_evidence: dict[int, list[Any]] = defaultdict(list)
    for evidence in progress.evidence.values():
        topic_evidence[evidence.topic_id].append(evidence)

    topics: list[TopicAnalytics] = []
    for subject in subjects:
        for topic in subject.topics:
            evidence_rows = [
                evidence
                for evidence in topic_evidence[topic.id]
                if evidence.question_id in active_question_ids
            ]
            answered_rows = [
                evidence
                for evidence in evidence_rows
                if evidence.latest_answered_status is not None
                and evidence.latest_answered_at is not None
            ]
            solved_rows = [
                evidence for evidence in evidence_rows if evidence.correct_count > 0
            ]
            correct_count = sum(
                evidence.latest_answered_status == ResponseStatus.CORRECT.value
                for evidence in answered_rows
            )
            incorrect_count = sum(
                evidence.latest_answered_status == ResponseStatus.INCORRECT.value
                for evidence in answered_rows
            )
            unanswered_count = sum(
                evidence.unanswered_count for evidence in evidence_rows
            )
            answered_count = len(answered_rows)
            available_questions = topic_question_counts.get(topic.id, 0)
            unique_questions = answered_count
            unique_questions_solved = len(solved_rows)
            accuracy = (
                correct_count / answered_count if answered_count else 0.0
            )
            attempted_coverage = (
                unique_questions / available_questions
                if available_questions
                else 0.0
            )
            solved_coverage = (
                unique_questions_solved / available_questions
                if available_questions
                else 0.0
            )
            recency_accuracy = _weighted_accuracy(
                [
                    (
                        ResponseStatus(evidence.latest_answered_status),
                        evidence.latest_answered_at,
                    )
                    for evidence in answered_rows
                ],
                now=now,
            )
            mastery = _mastery_score(
                accuracy=accuracy,
                recency_accuracy=recency_accuracy,
                answered_count=answered_count,
                coverage=attempted_coverage,
                volume_target=10,
            )
            if not answered_rows:
                classification = "unattempted"
            elif (
                answered_count >= 5
                and accuracy >= 0.75
                and recency_accuracy >= 0.70
                and mastery >= 65
            ):
                classification = "strong"
            elif (
                answered_count == 0
                or accuracy < 0.60
                or recency_accuracy < 0.55
                or mastery < 50
            ):
                classification = "needs_practice"
            else:
                classification = "developing"
            topics.append(
                TopicAnalytics(
                    topic_id=topic.id,
                    topic_slug=topic.slug,
                    topic_name=topic.name,
                    subject_id=subject.id,
                    subject_slug=subject.slug,
                    subject_code=subject.code,
                    subject_name=subject.name,
                    available_questions=available_questions,
                    attempt_count=sum(
                        evidence.attempt_count for evidence in evidence_rows
                    ),
                    answered_count=answered_count,
                    unique_questions_attempted=unique_questions,
                    unique_questions_solved=unique_questions_solved,
                    correct_count=correct_count,
                    incorrect_count=incorrect_count,
                    unanswered_count=unanswered_count,
                    accuracy_percent=round(accuracy * 100, 2),
                    attempted_coverage_percent=round(
                        attempted_coverage * 100,
                        2,
                    ),
                    solved_coverage_percent=round(solved_coverage * 100, 2),
                    coverage_percent=round(attempted_coverage * 100, 2),
                    recency_weighted_accuracy_percent=round(
                        recency_accuracy * 100, 2
                    ),
                    mastery_score=round(mastery, 2),
                    status=classification,
                    last_attempted_at=(
                        max(
                            _aware(evidence.latest_answered_at)
                            for evidence in answered_rows
                            if evidence.latest_answered_at is not None
                        )
                        if answered_rows
                        else None
                    ),
                )
            )

    answered_responses = [
        evidence
        for evidence in progress.evidence.values()
        if evidence.question_id in active_question_ids
        and evidence.latest_answered_status is not None
        and evidence.latest_answered_at is not None
    ]
    correct_responses = sum(
        evidence.latest_answered_status == ResponseStatus.CORRECT.value
        for evidence in answered_responses
    )
    solved_responses = sum(
        evidence.correct_count > 0 for evidence in answered_responses
    )
    available_questions = sum(topic_question_counts.values())
    unique_questions = len(answered_responses)
    overall_accuracy = (
        correct_responses / len(answered_responses) if answered_responses else 0.0
    )
    overall_attempted_coverage = (
        unique_questions / available_questions if available_questions else 0.0
    )
    overall_solved_coverage = (
        solved_responses / available_questions if available_questions else 0.0
    )
    overall_recency = _weighted_accuracy(
        [
            (
                ResponseStatus(evidence.latest_answered_status),
                evidence.latest_answered_at,
            )
            for evidence in answered_responses
        ],
        now=now,
    )
    overall = AnalyticsOverall(
        attempted_responses=progress.total_responses,
        answered_responses=len(answered_responses),
        unique_questions_attempted=unique_questions,
        unique_questions_solved=solved_responses,
        available_questions=available_questions,
        accuracy_percent=round(overall_accuracy * 100, 2),
        attempted_coverage_percent=round(overall_attempted_coverage * 100, 2),
        solved_coverage_percent=round(overall_solved_coverage * 100, 2),
        coverage_percent=round(overall_attempted_coverage * 100, 2),
        recency_weighted_accuracy_percent=round(overall_recency * 100, 2),
        mastery_score=round(
            _mastery_score(
                accuracy=overall_accuracy,
                recency_accuracy=overall_recency,
                answered_count=len(answered_responses),
                coverage=overall_attempted_coverage,
                volume_target=50,
            ),
            2,
        ),
    )
    strong_topics = sorted(
        (topic for topic in topics if topic.status == "strong"),
        key=lambda topic: (-topic.mastery_score, topic.topic_name),
    )
    needs_practice_topics = sorted(
        (topic for topic in topics if topic.status == "needs_practice"),
        key=lambda topic: (topic.mastery_score, -topic.attempt_count, topic.topic_name),
    )
    unattempted_topics = [
        topic for topic in topics if topic.status == "unattempted"
    ]
    return AnalyticsDashboard(
        user_key=user_key,
        generated_at=now,
        overall=overall,
        topics=topics,
        strong_topics=strong_topics,
        needs_practice_topics=needs_practice_topics,
        unattempted_topics=unattempted_topics,
    )


@router.get("/roadmap", response_model=RoadmapResponse, tags=["Curriculum"])
async def roadmap(
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(current_user_key),
    user_state: UserStateRepository | None = Depends(get_user_state_repository),
) -> RoadmapResponse:
    subjects = list(
        (
            await db.scalars(
                select(Subject)
                .options(
                    selectinload(Subject.topics).selectinload(Topic.questions),
                    selectinload(Subject.topics).selectinload(Topic.note),
                )
                .order_by(Subject.order_index)
            )
        ).all()
    )
    progress = await _progress_for_user(db, user_state, user_key)
    active_question_topic_ids = {
        question.id: topic.id
        for subject in subjects
        for topic in subject.topics
        for question in topic.questions
        if question.is_active
    }
    topic_stats: dict[int, dict[str, int]] = defaultdict(
        lambda: {
            "attempted": 0,
            "solved": 0,
            "correct": 0,
            "incorrect": 0,
        }
    )
    for evidence in progress.evidence.values():
        current_topic_id = active_question_topic_ids.get(evidence.question_id)
        if current_topic_id is None:
            continue
        bucket = topic_stats[current_topic_id]
        bucket["attempted"] += evidence.attempt_count
        bucket["solved"] += int(evidence.correct_count > 0)
        bucket["correct"] += int(
            evidence.latest_answered_status == ResponseStatus.CORRECT.value
        )
        bucket["incorrect"] += int(
            evidence.latest_answered_status == ResponseStatus.INCORRECT.value
        )

    def accuracy(correct: int, incorrect: int) -> float | None:
        answered = correct + incorrect
        if not answered:
            return None
        return round(correct / answered * 100, 2)

    roadmap_subjects: list[RoadmapSubject] = []
    for subject in subjects:
        topics = [
            RoadmapTopic(
                id=topic.id,
                slug=topic.slug,
                name=topic.name,
                question_count=sum(question.is_active for question in topic.questions),
                note_available=topic.note is not None,
                attempted_questions=topic_stats[topic.id]["attempted"],
                solved_questions=topic_stats[topic.id]["solved"],
                accuracy=accuracy(
                    topic_stats[topic.id]["correct"],
                    topic_stats[topic.id]["incorrect"],
                ),
            )
            for topic in subject.topics
        ]
        subject_attempted = sum(
            topic_stats[topic.id]["attempted"] for topic in subject.topics
        )
        subject_solved = sum(
            topic_stats[topic.id]["solved"] for topic in subject.topics
        )
        subject_correct = sum(
            topic_stats[topic.id]["correct"] for topic in subject.topics
        )
        subject_incorrect = sum(
            topic_stats[topic.id]["incorrect"] for topic in subject.topics
        )
        roadmap_subjects.append(
            RoadmapSubject(
                id=subject.id,
                slug=subject.slug,
                code=subject.code,
                name=subject.name,
                order_index=subject.order_index,
                topic_count=len(subject.topics),
                question_count=sum(item.question_count for item in topics),
                attempted_questions=subject_attempted,
                solved_questions=subject_solved,
                accuracy=accuracy(subject_correct, subject_incorrect),
                topics=topics,
            )
        )
    return RoadmapResponse(user_key=user_key, subjects=roadmap_subjects)
