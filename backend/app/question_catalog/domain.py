from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, Mapping

from app.models import Difficulty, QuestionSource, QuestionType, SessionMode


class QuestionCatalogError(RuntimeError):
    """Base class for catalog-provider failures safe to map at the API edge."""


class QuestionCatalogUnavailable(QuestionCatalogError):
    """The selected catalog provider cannot currently serve a consistent release."""


class QuestionCatalogInvalid(QuestionCatalogError):
    """The published catalog violates a runtime integrity invariant."""


class QuestionCatalogNotFound(QuestionCatalogError):
    """A requested catalog entity does not exist in the current release."""


def _utc_datetime(value: Any, *, field_name: str) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise QuestionCatalogInvalid(f"{field_name} is not an ISO datetime") from exc
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    raise QuestionCatalogInvalid(f"{field_name} is not a datetime")


def _required_string(document: Mapping[str, Any], field_name: str) -> str:
    value = document.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise QuestionCatalogInvalid(f"{field_name} must be a non-empty string")
    return value.strip()


def _optional_string(document: Mapping[str, Any], field_name: str) -> str | None:
    value = document.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise QuestionCatalogInvalid(f"{field_name} must be a string or null")
    normalized = value.strip()
    return normalized or None


def _required_int(document: Mapping[str, Any], field_name: str) -> int:
    value = document.get(field_name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise QuestionCatalogInvalid(f"{field_name} must be an integer")
    return value


def _optional_int(document: Mapping[str, Any], field_name: str) -> int | None:
    value = document.get(field_name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise QuestionCatalogInvalid(f"{field_name} must be an integer or null")
    return value


def _enum_value(enum_type: type, document: Mapping[str, Any], field_name: str):
    value = document.get(field_name)
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise QuestionCatalogInvalid(f"{field_name} has an unsupported value") from exc


@dataclass(frozen=True, slots=True)
class CatalogSubject:
    id: int
    slug: str
    code: str
    name: str
    description: str
    order_index: int

    @classmethod
    def from_document(cls, document: Mapping[str, Any]) -> CatalogSubject:
        return cls(
            id=_required_int(document, "id"),
            slug=_required_string(document, "slug"),
            code=_required_string(document, "code"),
            name=_required_string(document, "name"),
            description=str(document.get("description") or ""),
            order_index=_required_int(document, "order_index"),
        )


@dataclass(frozen=True, slots=True)
class CatalogTopic:
    id: int
    subject_id: int
    slug: str
    name: str
    description: str
    order_index: int

    @classmethod
    def from_document(cls, document: Mapping[str, Any]) -> CatalogTopic:
        return cls(
            id=_required_int(document, "id"),
            subject_id=_required_int(document, "subject_id"),
            slug=_required_string(document, "slug"),
            name=_required_string(document, "name"),
            description=str(document.get("description") or ""),
            order_index=_required_int(document, "order_index"),
        )


@dataclass(frozen=True, slots=True)
class CatalogRevisionNote:
    id: int
    topic_id: int
    title: str
    summary: str
    content_md: str
    key_points: tuple[str, ...]
    worked_examples: tuple[dict[str, str], ...]
    updated_at: datetime

    @classmethod
    def from_document(cls, document: Mapping[str, Any]) -> CatalogRevisionNote:
        key_points = document.get("key_points") or []
        worked_examples = document.get("worked_examples") or []
        if not isinstance(key_points, list) or not all(
            isinstance(item, str) for item in key_points
        ):
            raise QuestionCatalogInvalid("key_points must be a string array")
        if not isinstance(worked_examples, list) or not all(
            isinstance(item, dict) for item in worked_examples
        ):
            raise QuestionCatalogInvalid("worked_examples must be an object array")
        return cls(
            id=_required_int(document, "id"),
            topic_id=_required_int(document, "topic_id"),
            title=_required_string(document, "title"),
            summary=str(document.get("summary") or ""),
            content_md=str(document.get("content_md") or ""),
            key_points=tuple(key_points),
            worked_examples=tuple(dict(item) for item in worked_examples),
            updated_at=_utc_datetime(document.get("updated_at"), field_name="updated_at"),
        )


@dataclass(frozen=True, slots=True)
class CatalogQuestion:
    id: int
    external_id: str | None
    bank_version: str | None
    is_active: bool
    subject_id: int
    topic_id: int
    source: QuestionSource
    year: int | None
    exam_session: str | None
    source_kind: QuestionSource
    source_year: int | None
    source_paper: str | None
    source_question_number: int | None
    source_paper_id: str | None
    source_item_label: str | None
    source_page: int | None
    source_url: str | None
    answer_key_url: str | None
    extraction_method: str | None
    extraction_confidence: float | None
    question_type: QuestionType
    difficulty: Difficulty
    text: str
    options: tuple[dict[str, str], ...]
    correct_answer: Any
    numerical_tolerance: float
    marks: int
    explanation: str
    tags: tuple[str, ...]
    assets: tuple[dict[str, str], ...]
    created_at: datetime | None
    subject: CatalogSubject
    topic: CatalogTopic
    search_text: str = field(repr=False)

    @classmethod
    def from_document(
        cls,
        document: Mapping[str, Any],
        *,
        subject: CatalogSubject,
        topic: CatalogTopic,
    ) -> CatalogQuestion:
        question_id = _required_int(document, "id")
        if topic.subject_id != subject.id:
            raise QuestionCatalogInvalid(
                f"question {question_id} subject/topic relationship is inconsistent"
            )
        if _required_int(document, "subject_id") != subject.id:
            raise QuestionCatalogInvalid(f"question {question_id} has an unknown subject")
        if _required_int(document, "topic_id") != topic.id:
            raise QuestionCatalogInvalid(f"question {question_id} has an unknown topic")
        options = document.get("options") or []
        tags = document.get("tags") or []
        assets = document.get("assets") or []
        if not isinstance(options, list) or not all(isinstance(item, dict) for item in options):
            raise QuestionCatalogInvalid(f"question {question_id} options are invalid")
        if not isinstance(tags, list) or not all(isinstance(item, str) for item in tags):
            raise QuestionCatalogInvalid(f"question {question_id} tags are invalid")
        if not isinstance(assets, list) or not all(isinstance(item, dict) for item in assets):
            raise QuestionCatalogInvalid(f"question {question_id} assets are invalid")
        is_active = document.get("is_active")
        if not isinstance(is_active, bool):
            raise QuestionCatalogInvalid(f"question {question_id} is_active is invalid")
        extraction_confidence = document.get("extraction_confidence")
        if extraction_confidence is not None and not isinstance(
            extraction_confidence, (int, float)
        ):
            raise QuestionCatalogInvalid(
                f"question {question_id} extraction_confidence is invalid"
            )
        tolerance = document.get("numerical_tolerance", 0.01)
        if isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)):
            raise QuestionCatalogInvalid(
                f"question {question_id} numerical_tolerance is invalid"
            )
        created_value = document.get("created_at")
        text = _required_string(document, "text")
        searchable_values = (
            text,
            _optional_string(document, "source_paper") or "",
            _optional_string(document, "exam_session") or "",
            _optional_string(document, "external_id") or "",
            _optional_string(document, "source_url") or "",
        )
        return cls(
            id=question_id,
            external_id=_optional_string(document, "external_id"),
            bank_version=_optional_string(document, "bank_version"),
            is_active=is_active,
            subject_id=subject.id,
            topic_id=topic.id,
            source=_enum_value(QuestionSource, document, "source"),
            year=_optional_int(document, "year"),
            exam_session=_optional_string(document, "exam_session"),
            source_kind=_enum_value(QuestionSource, document, "source_kind"),
            source_year=_optional_int(document, "source_year"),
            source_paper=_optional_string(document, "source_paper"),
            source_question_number=_optional_int(document, "source_question_number"),
            source_paper_id=_optional_string(document, "source_paper_id"),
            source_item_label=_optional_string(document, "source_item_label"),
            source_page=_optional_int(document, "source_page"),
            source_url=_optional_string(document, "source_url"),
            answer_key_url=_optional_string(document, "answer_key_url"),
            extraction_method=_optional_string(document, "extraction_method"),
            extraction_confidence=(
                float(extraction_confidence)
                if extraction_confidence is not None
                else None
            ),
            question_type=_enum_value(QuestionType, document, "question_type"),
            difficulty=_enum_value(Difficulty, document, "difficulty"),
            text=text,
            options=tuple(dict(item) for item in options),
            correct_answer=document.get("correct_answer"),
            numerical_tolerance=float(tolerance),
            marks=_required_int(document, "marks"),
            explanation=str(document.get("explanation") or ""),
            tags=tuple(tags),
            assets=tuple(dict(item) for item in assets),
            created_at=(
                _utc_datetime(created_value, field_name="created_at")
                if created_value is not None
                else None
            ),
            subject=subject,
            topic=topic,
            search_text="\n".join(searchable_values).casefold(),
        )


@dataclass(frozen=True, slots=True)
class CatalogTestForm:
    id: str
    title: str
    description: str
    mode: SessionMode
    subject_id: int | None
    form_number: int
    question_ids: tuple[int, ...]
    question_count: int
    duration_seconds: int
    total_marks: int
    seed: int
    question_type_counts: Mapping[str, int]
    topic_count: int
    bank_version: str | None
    is_available: bool
    unavailable_reason: str | None
    generated_at: datetime
    subject: CatalogSubject | None

    @classmethod
    def from_document(
        cls,
        document: Mapping[str, Any],
        *,
        subject: CatalogSubject | None,
    ) -> CatalogTestForm:
        question_ids = document.get("question_ids") or []
        counts = document.get("question_type_counts") or {}
        if not isinstance(question_ids, list) or not all(
            isinstance(item, int) and not isinstance(item, bool) for item in question_ids
        ):
            raise QuestionCatalogInvalid("test form question_ids are invalid")
        if len(question_ids) != len(set(question_ids)):
            raise QuestionCatalogInvalid("test form contains duplicate question_ids")
        if not isinstance(counts, dict) or any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in counts.values()
        ):
            raise QuestionCatalogInvalid("test form question_type_counts are invalid")
        subject_id = _optional_int(document, "subject_id")
        if subject_id is not None and (subject is None or subject.id != subject_id):
            raise QuestionCatalogInvalid("test form has an unknown subject")
        is_available = document.get("is_available")
        if not isinstance(is_available, bool):
            raise QuestionCatalogInvalid("test form is_available is invalid")
        return cls(
            id=_required_string(document, "id"),
            title=_required_string(document, "title"),
            description=str(document.get("description") or ""),
            mode=_enum_value(SessionMode, document, "mode"),
            subject_id=subject_id,
            form_number=_required_int(document, "form_number"),
            question_ids=tuple(question_ids),
            question_count=_required_int(document, "question_count"),
            duration_seconds=_required_int(document, "duration_seconds"),
            total_marks=_required_int(document, "total_marks"),
            seed=_required_int(document, "seed"),
            question_type_counts=MappingProxyType(dict(counts)),
            topic_count=_required_int(document, "topic_count"),
            bank_version=_optional_string(document, "bank_version"),
            is_available=is_available,
            unavailable_reason=_optional_string(document, "unavailable_reason"),
            generated_at=_utc_datetime(
                document.get("generated_at"), field_name="generated_at"
            ),
            subject=subject,
        )


@dataclass(frozen=True, slots=True)
class CatalogSnapshot:
    release_id: str
    metadata: Mapping[str, Any]
    subjects: tuple[CatalogSubject, ...]
    topics: tuple[CatalogTopic, ...]
    notes: tuple[CatalogRevisionNote, ...]
    questions: tuple[CatalogQuestion, ...]
    test_forms: tuple[CatalogTestForm, ...]
    subjects_by_id: Mapping[int, CatalogSubject]
    subjects_by_slug: Mapping[str, CatalogSubject]
    topics_by_id: Mapping[int, CatalogTopic]
    topics_by_subject: Mapping[int, tuple[CatalogTopic, ...]]
    notes_by_id: Mapping[int, CatalogRevisionNote]
    notes_by_topic: Mapping[int, CatalogRevisionNote]
    questions_by_id: Mapping[int, CatalogQuestion]
    question_index: Mapping[int, bool]
    question_aliases: Mapping[int, int]
    alias_questions_by_id: Mapping[int, CatalogQuestion]
    active_questions: tuple[CatalogQuestion, ...]
    active_question_ids: frozenset[int]
    active_question_topic_ids: Mapping[int, int]
    active_topic_question_counts: Mapping[int, int]
    active_subject_question_counts: Mapping[int, int]
    test_forms_by_id: Mapping[str, CatalogTestForm]

    def resolve_question_id(self, question_id: int) -> int:
        return self.question_aliases.get(question_id, question_id)

    def question_for_runtime_id(
        self,
        question_id: int,
        *,
        preserve_alias: bool = False,
    ) -> CatalogQuestion | None:
        canonical_id = self.resolve_question_id(question_id)
        question = self.questions_by_id.get(canonical_id)
        if preserve_alias and canonical_id != question_id:
            return self.alias_questions_by_id.get(question_id)
        return question

    @property
    def bank_version(self) -> str | None:
        value = self.metadata.get("bank_version") or self.metadata.get("catalog_version")
        if isinstance(value, str) and value.strip():
            return value.strip()
        return self.test_forms[0].bank_version if self.test_forms else None

    @classmethod
    def build(
        cls,
        *,
        release_id: str,
        metadata: Mapping[str, Any],
        subject_documents: list[Mapping[str, Any]],
        topic_documents: list[Mapping[str, Any]],
        note_documents: list[Mapping[str, Any]],
        question_documents: list[Mapping[str, Any]],
        question_index_documents: list[Mapping[str, Any]],
        question_alias_documents: list[Mapping[str, Any]],
        test_form_documents: list[Mapping[str, Any]],
    ) -> CatalogSnapshot:
        subjects = tuple(
            sorted(
                (CatalogSubject.from_document(item) for item in subject_documents),
                key=lambda item: (item.order_index, item.id),
            )
        )
        subjects_by_id = {item.id: item for item in subjects}
        subjects_by_slug = {item.slug: item for item in subjects}
        if len(subjects_by_id) != len(subjects) or len(subjects_by_slug) != len(subjects):
            raise QuestionCatalogInvalid("catalog contains duplicate subject identities")

        topics = tuple(
            sorted(
                (CatalogTopic.from_document(item) for item in topic_documents),
                key=lambda item: (item.subject_id, item.order_index, item.id),
            )
        )
        topics_by_id = {item.id: item for item in topics}
        if len(topics_by_id) != len(topics):
            raise QuestionCatalogInvalid("catalog contains duplicate topic identities")
        topics_by_subject_mutable: dict[int, list[CatalogTopic]] = {
            subject.id: [] for subject in subjects
        }
        for topic in topics:
            if topic.subject_id not in subjects_by_id:
                raise QuestionCatalogInvalid(f"topic {topic.id} has an unknown subject")
            topics_by_subject_mutable[topic.subject_id].append(topic)

        notes = tuple(CatalogRevisionNote.from_document(item) for item in note_documents)
        notes_by_id = {item.id: item for item in notes}
        notes_by_topic = {item.topic_id: item for item in notes}
        if len(notes_by_id) != len(notes) or len(notes_by_topic) != len(notes):
            raise QuestionCatalogInvalid("catalog contains duplicate revision notes")
        if any(topic_id not in topics_by_id for topic_id in notes_by_topic):
            raise QuestionCatalogInvalid("revision note references an unknown topic")

        questions_list: list[CatalogQuestion] = []
        archive_subject = CatalogSubject(
            id=0,
            slug="archive-unclassified",
            code="ARCHIVE",
            name="Archive (unclassified)",
            description="Non-navigable archive-only records outside the active syllabus.",
            order_index=2**31 - 1,
        )
        archive_topic = CatalogTopic(
            id=0,
            subject_id=0,
            slug="archive-unclassified",
            name="Archive (unclassified)",
            description="Non-navigable archive-only records outside the active syllabus.",
            order_index=2**31 - 1,
        )
        for document in question_documents:
            subject_id = _required_int(document, "subject_id")
            topic_id = _required_int(document, "topic_id")
            is_active = document.get("is_active") is True
            if subject_id == 0 and topic_id == 0 and not is_active:
                subject = archive_subject
                topic = archive_topic
            else:
                subject = subjects_by_id.get(subject_id)
                topic = topics_by_id.get(topic_id)
            if subject is None or topic is None:
                raise QuestionCatalogInvalid("question references unknown curriculum data")
            questions_list.append(
                CatalogQuestion.from_document(document, subject=subject, topic=topic)
            )
        questions = tuple(sorted(questions_list, key=lambda item: item.id))
        questions_by_id = {item.id: item for item in questions}
        if len(questions_by_id) != len(questions):
            raise QuestionCatalogInvalid("catalog contains duplicate question identities")
        question_index: dict[int, bool] = {}
        for document in question_index_documents:
            runtime_id = _required_int(document, "runtime_id")
            is_active = document.get("is_active")
            if runtime_id <= 0 or runtime_id > 9_007_199_254_740_991:
                raise QuestionCatalogInvalid("question index contains an invalid runtime id")
            if not isinstance(is_active, bool):
                raise QuestionCatalogInvalid("question index is_active is invalid")
            if runtime_id in question_index:
                raise QuestionCatalogInvalid("question index contains duplicate runtime ids")
            question_index[runtime_id] = is_active
        active_index_ids = {
            runtime_id for runtime_id, is_active in question_index.items() if is_active
        }
        if active_index_ids != set(questions_by_id):
            raise QuestionCatalogInvalid(
                "active question shards do not match the canonical question index"
            )
        question_aliases: dict[int, int] = {}
        alias_questions: dict[int, CatalogQuestion] = {}
        for document in question_alias_documents:
            legacy_id = _required_int(document, "id")
            canonical_id = _required_int(document, "canonical_question_id")
            if legacy_id == canonical_id:
                raise QuestionCatalogInvalid(
                    f"question alias {legacy_id} is a forbidden self-alias"
                )
            if legacy_id in question_index:
                raise QuestionCatalogInvalid(
                    f"question alias {legacy_id} shadows a canonical question"
                )
            if canonical_id not in question_index:
                raise QuestionCatalogInvalid(
                    f"question alias {legacy_id} has an unknown canonical target"
                )
            if legacy_id in question_aliases:
                raise QuestionCatalogInvalid(
                    f"question alias {legacy_id} is duplicated"
                )
            question_aliases[legacy_id] = canonical_id
            legacy_snapshot = document.get("legacy_snapshot")
            if not isinstance(legacy_snapshot, dict):
                raise QuestionCatalogInvalid(
                    f"question alias {legacy_id} has no lossless legacy snapshot"
                )
            snapshot_document = dict(legacy_snapshot)
            snapshot_document.setdefault("id", legacy_id)
            if snapshot_document.get("id") != legacy_id:
                raise QuestionCatalogInvalid(
                    f"question alias {legacy_id} snapshot identity is inconsistent"
                )
            snapshot_subject_id = _required_int(snapshot_document, "subject_id")
            snapshot_topic_id = _required_int(snapshot_document, "topic_id")
            snapshot_subject = subjects_by_id.get(snapshot_subject_id)
            snapshot_topic = topics_by_id.get(snapshot_topic_id)
            if snapshot_subject is None or snapshot_topic is None:
                raise QuestionCatalogInvalid(
                    f"question alias {legacy_id} snapshot references unknown curriculum"
                )
            alias_questions[legacy_id] = CatalogQuestion.from_document(
                snapshot_document,
                subject=snapshot_subject,
                topic=snapshot_topic,
            )
        active_questions = tuple(item for item in questions if item.is_active)
        active_topic_counts: dict[int, int] = {item.id: 0 for item in topics}
        active_subject_counts: dict[int, int] = {item.id: 0 for item in subjects}
        for question in active_questions:
            active_topic_counts[question.topic_id] += 1
            active_subject_counts[question.subject_id] += 1

        forms_list: list[CatalogTestForm] = []
        for document in test_form_documents:
            subject_id = _optional_int(document, "subject_id")
            subject = subjects_by_id.get(subject_id) if subject_id is not None else None
            form = CatalogTestForm.from_document(document, subject=subject)
            if form.is_available and any(
                question_id not in questions_by_id
                or not questions_by_id[question_id].is_active
                for question_id in form.question_ids
            ):
                raise QuestionCatalogInvalid(
                    f"available test form {form.id} references inactive questions"
                )
            forms_list.append(form)
        forms = tuple(forms_list)
        forms_by_id = {item.id: item for item in forms}
        if len(forms_by_id) != len(forms):
            raise QuestionCatalogInvalid("catalog contains duplicate test form identities")

        if any(not question.is_active for question in questions):
            raise QuestionCatalogInvalid(
                "runtime catalog shards must contain active questions only"
            )
        expected_counts = {
            "canonical_question_count": len(question_index),
            "active_question_count": len(active_questions),
            "subject_count": len(subjects),
            "topic_count": len(topics),
            "test_form_count": len(forms),
        }
        for field_name, actual in expected_counts.items():
            expected = metadata.get(field_name)
            if expected is not None and expected != actual:
                raise QuestionCatalogInvalid(
                    f"catalog metadata {field_name}={expected!r}, expected {actual}"
                )

        return cls(
            release_id=release_id,
            metadata=MappingProxyType(dict(metadata)),
            subjects=subjects,
            topics=topics,
            notes=notes,
            questions=questions,
            test_forms=forms,
            subjects_by_id=MappingProxyType(subjects_by_id),
            subjects_by_slug=MappingProxyType(subjects_by_slug),
            topics_by_id=MappingProxyType(topics_by_id),
            topics_by_subject=MappingProxyType(
                {
                    subject_id: tuple(items)
                    for subject_id, items in topics_by_subject_mutable.items()
                }
            ),
            notes_by_id=MappingProxyType(notes_by_id),
            notes_by_topic=MappingProxyType(notes_by_topic),
            questions_by_id=MappingProxyType(questions_by_id),
            question_index=MappingProxyType(question_index),
            question_aliases=MappingProxyType(question_aliases),
            alias_questions_by_id=MappingProxyType(alias_questions),
            active_questions=active_questions,
            active_question_ids=frozenset(item.id for item in active_questions),
            active_question_topic_ids=MappingProxyType(
                {item.id: item.topic_id for item in active_questions}
            ),
            active_topic_question_counts=MappingProxyType(active_topic_counts),
            active_subject_question_counts=MappingProxyType(active_subject_counts),
            test_forms_by_id=MappingProxyType(forms_by_id),
        )
