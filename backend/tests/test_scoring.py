from __future__ import annotations

import pytest

from app.models import Question, QuestionType, ResponseStatus
from app.scoring import score_question


def make_question(
    question_type: QuestionType,
    answer: object,
    *,
    marks: int = 1,
    tolerance: float = 0.01,
) -> Question:
    return Question(
        subject_id=1,
        topic_id=1,
        question_type=question_type,
        text="Test question",
        options=[],
        correct_answer=answer,
        numerical_tolerance=tolerance,
        marks=marks,
        explanation="Test explanation",
        tags=[],
    )


@pytest.mark.parametrize(
    ("marks", "expected"),
    [(1, -1 / 3), (2, -2 / 3)],
)
def test_incorrect_mcq_has_official_negative_marking(marks: int, expected: float) -> None:
    result = score_question(make_question(QuestionType.MCQ, "A", marks=marks), "B")
    assert result.status == ResponseStatus.INCORRECT
    assert result.awarded_marks == pytest.approx(expected, abs=1e-6)


def test_msq_requires_exact_set_and_has_no_negative_marking() -> None:
    question = make_question(QuestionType.MSQ, ["A", "C"], marks=2)
    assert score_question(question, ["C", "A"]).status == ResponseStatus.CORRECT
    wrong = score_question(question, ["A"])
    assert wrong.status == ResponseStatus.INCORRECT
    assert wrong.awarded_marks == 0
    assert wrong.negative_marks == 0


def test_nat_uses_tolerance_and_has_no_negative_marking() -> None:
    question = make_question(QuestionType.NAT, 3.14, marks=2, tolerance=0.01)
    assert score_question(question, "3.145").status == ResponseStatus.CORRECT
    wrong = score_question(question, 3.2)
    assert wrong.status == ResponseStatus.INCORRECT
    assert wrong.awarded_marks == 0


def test_blank_answer_is_unanswered() -> None:
    question = make_question(QuestionType.MCQ, "A")
    result = score_question(question, "")
    assert result.status == ResponseStatus.UNANSWERED
    assert result.awarded_marks == 0
