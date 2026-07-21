from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.models import Question, QuestionType, ResponseStatus


@dataclass(frozen=True, slots=True)
class ScoreResult:
    status: ResponseStatus
    awarded_marks: float
    negative_marks: float


def is_unanswered(answer: Any) -> bool:
    if answer is None:
        return True
    if isinstance(answer, str) and not answer.strip():
        return True
    return isinstance(answer, (list, tuple, set, dict)) and len(answer) == 0


def _normalize_option(answer: Any) -> str:
    return str(answer).strip().upper()


def _normalize_options(answer: Any) -> set[str]:
    if not isinstance(answer, (list, tuple, set)):
        return {_normalize_option(answer)}
    return {_normalize_option(item) for item in answer}


def _nat_is_correct(answer: Any, expected: Any, tolerance: float) -> bool:
    try:
        submitted = float(answer)
    except (TypeError, ValueError):
        return False

    if isinstance(expected, dict):
        if "min" in expected and "max" in expected:
            return float(expected["min"]) <= submitted <= float(expected["max"])
        expected_value = float(expected["value"])
        tolerance = float(expected.get("tolerance", tolerance))
    else:
        try:
            expected_value = float(expected)
        except (TypeError, ValueError):
            return False
    return abs(submitted - expected_value) <= tolerance


def is_correct(question: Question, answer: Any) -> bool:
    if question.question_type == QuestionType.MCQ:
        return _normalize_option(answer) == _normalize_option(question.correct_answer)
    if question.question_type == QuestionType.MSQ:
        return _normalize_options(answer) == _normalize_options(question.correct_answer)
    return _nat_is_correct(
        answer,
        question.correct_answer,
        question.numerical_tolerance,
    )


def score_question(question: Question, answer: Any) -> ScoreResult:
    """Apply official GATE marking rules.

    Correct answers receive full marks. Incorrect MCQs lose one third of their
    marks (1/3 for a 1-mark MCQ, 2/3 for a 2-mark MCQ). MSQ and NAT questions
    have no negative marking. Unanswered questions always score zero.
    """
    if is_unanswered(answer):
        return ScoreResult(ResponseStatus.UNANSWERED, 0.0, 0.0)
    if is_correct(question, answer):
        return ScoreResult(ResponseStatus.CORRECT, float(question.marks), 0.0)

    penalty = float(question.marks) / 3 if question.question_type == QuestionType.MCQ else 0.0
    return ScoreResult(
        ResponseStatus.INCORRECT,
        round(-penalty, 6),
        round(penalty, 6),
    )
