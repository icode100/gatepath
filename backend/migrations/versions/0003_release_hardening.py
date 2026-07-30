"""Add immutable sessions, active bank membership and extraction metadata.

Revision ID: 0003_release_hardening
Revises: 0002_question_bank_catalog
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0003_release_hardening"
down_revision = "0002_question_bank_catalog"
branch_labels = None
depends_on = None


def _columns(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table_name not in inspector.get_table_names():
        return set()
    return {
        column["name"]
        for column in inspector.get_columns(table_name)
    }


def _indexes(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table_name not in inspector.get_table_names():
        return set()
    return {
        index["name"]
        for index in inspector.get_indexes(table_name)
        if index.get("name")
    }


def upgrade() -> None:
    question_columns = _columns("questions")
    with op.batch_alter_table("questions") as batch_op:
        if "is_active" not in question_columns:
            batch_op.add_column(
                sa.Column(
                    "is_active",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.true(),
                )
            )
        if "source_page" not in question_columns:
            batch_op.add_column(sa.Column("source_page", sa.Integer(), nullable=True))
        if "extraction_method" not in question_columns:
            batch_op.add_column(
                sa.Column("extraction_method", sa.String(length=80), nullable=True)
            )
        if "extraction_confidence" not in question_columns:
            batch_op.add_column(
                sa.Column("extraction_confidence", sa.Float(), nullable=True)
            )
    if "ix_questions_is_active" not in _indexes("questions"):
        op.create_index(
            "ix_questions_is_active",
            "questions",
            ["is_active"],
            unique=False,
        )

    session_columns = _columns("practice_sessions")
    if "question_snapshots" not in session_columns:
        with op.batch_alter_table("practice_sessions") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "question_snapshots",
                    sa.JSON(),
                    nullable=False,
                    server_default=sa.text("'[]'"),
                )
            )

    response_columns = _columns("attempt_responses")
    with op.batch_alter_table("attempt_responses") as batch_op:
        if "correct_answer_snapshot" not in response_columns:
            batch_op.add_column(
                sa.Column("correct_answer_snapshot", sa.JSON(), nullable=True)
            )
        if "explanation_snapshot" not in response_columns:
            batch_op.add_column(
                sa.Column("explanation_snapshot", sa.Text(), nullable=True)
            )

    import_columns = _columns("question_bank_imports")
    if "retired_count" not in import_columns:
        with op.batch_alter_table("question_bank_imports") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "retired_count",
                    sa.Integer(),
                    nullable=False,
                    server_default=sa.text("0"),
                )
            )


def downgrade() -> None:
    if "retired_count" in _columns("question_bank_imports"):
        with op.batch_alter_table("question_bank_imports") as batch_op:
            batch_op.drop_column("retired_count")

    response_columns = _columns("attempt_responses")
    with op.batch_alter_table("attempt_responses") as batch_op:
        if "explanation_snapshot" in response_columns:
            batch_op.drop_column("explanation_snapshot")
        if "correct_answer_snapshot" in response_columns:
            batch_op.drop_column("correct_answer_snapshot")

    if "question_snapshots" in _columns("practice_sessions"):
        with op.batch_alter_table("practice_sessions") as batch_op:
            batch_op.drop_column("question_snapshots")

    if "ix_questions_is_active" in _indexes("questions"):
        op.drop_index("ix_questions_is_active", table_name="questions")
    question_columns = _columns("questions")
    with op.batch_alter_table("questions") as batch_op:
        if "extraction_confidence" in question_columns:
            batch_op.drop_column("extraction_confidence")
        if "extraction_method" in question_columns:
            batch_op.drop_column("extraction_method")
        if "source_page" in question_columns:
            batch_op.drop_column("source_page")
        if "is_active" in question_columns:
            batch_op.drop_column("is_active")
