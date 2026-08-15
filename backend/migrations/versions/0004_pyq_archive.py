"""Add canonical paper-scoped PYQ archive and provenance.

Revision ID: 0004_pyq_archive
Revises: 0003_release_hardening
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0004_pyq_archive"
down_revision = "0003_release_hardening"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table_name not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def _indexes(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table_name not in inspector.get_table_names():
        return set()
    return {
        str(index["name"])
        for index in inspector.get_indexes(table_name)
        if index.get("name")
    }


def upgrade() -> None:
    tables = _tables()

    if "pyq_source_papers" not in tables:
        op.create_table(
            "pyq_source_papers",
            sa.Column("id", sa.String(length=96), nullable=False),
            sa.Column("exam_code", sa.String(length=24), nullable=False),
            sa.Column("paper_code", sa.String(length=24), nullable=False),
            sa.Column("year", sa.Integer(), nullable=False),
            sa.Column("session_label", sa.String(length=80), nullable=False),
            sa.Column("display_name", sa.String(length=180), nullable=False),
            sa.Column("expected_item_count", sa.Integer(), nullable=False),
            sa.Column("source_url", sa.Text(), nullable=True),
            sa.Column("answer_key_url", sa.Text(), nullable=True),
            sa.Column("source_pdf_sha256", sa.String(length=64), nullable=True),
            sa.Column("answer_key_sha256", sa.String(length=64), nullable=True),
            sa.Column("source_status", sa.String(length=32), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "exam_code",
                "paper_code",
                "year",
                "session_label",
                name="uq_pyq_source_paper_session",
            ),
        )
        op.create_index(
            "ix_pyq_source_papers_year",
            "pyq_source_papers",
            ["year"],
            unique=False,
        )
        op.create_index(
            "ix_pyq_source_papers_source_status",
            "pyq_source_papers",
            ["source_status"],
            unique=False,
        )
        op.create_index(
            "ix_pyq_source_papers_year_session",
            "pyq_source_papers",
            ["year", "session_label"],
            unique=False,
        )

    tables = _tables()
    if "pyq_source_questions" not in tables:
        op.create_table(
            "pyq_source_questions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("source_paper_id", sa.String(length=96), nullable=False),
            sa.Column("item_label", sa.String(length=48), nullable=False),
            sa.Column("ordinal", sa.Integer(), nullable=False),
            sa.Column("parent_item_label", sa.String(length=48), nullable=True),
            sa.Column("source_page", sa.Integer(), nullable=True),
            sa.Column("marks", sa.Float(), nullable=True),
            sa.Column("item_type", sa.String(length=24), nullable=False),
            sa.Column("question_md", sa.Text(), nullable=True),
            sa.Column("options", sa.JSON(), nullable=False),
            sa.Column("accepted_answers", sa.JSON(), nullable=True),
            sa.Column("solution_md", sa.Text(), nullable=True),
            sa.Column("subject_code", sa.String(length=16), nullable=True),
            sa.Column("topic_slug", sa.String(length=100), nullable=True),
            sa.Column("syllabus_status", sa.String(length=32), nullable=False),
            sa.Column("transcription_status", sa.String(length=32), nullable=False),
            sa.Column("answer_status", sa.String(length=32), nullable=False),
            sa.Column("classification_status", sa.String(length=32), nullable=False),
            sa.Column(
                "practice_eligible",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column("review_flags", sa.JSON(), nullable=False),
            sa.Column("assets", sa.JSON(), nullable=False),
            sa.Column("source_references", sa.JSON(), nullable=False),
            sa.Column("extraction_method", sa.String(length=80), nullable=True),
            sa.Column("extraction_confidence", sa.Float(), nullable=True),
            sa.Column("content_sha256", sa.String(length=64), nullable=True),
            sa.Column("materialized_question_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["source_paper_id"],
                ["pyq_source_papers.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["materialized_question_id"],
                ["questions.id"],
                ondelete="SET NULL",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "source_paper_id",
                "item_label",
                name="uq_pyq_source_question_label",
            ),
            sa.UniqueConstraint(
                "source_paper_id",
                "ordinal",
                name="uq_pyq_source_question_ordinal",
            ),
            sa.UniqueConstraint("materialized_question_id"),
        )
        for name, columns in (
            ("ix_pyq_source_questions_source_paper_id", ["source_paper_id"]),
            ("ix_pyq_source_questions_item_type", ["item_type"]),
            ("ix_pyq_source_questions_syllabus_status", ["syllabus_status"]),
            (
                "ix_pyq_source_questions_transcription_status",
                ["transcription_status"],
            ),
            ("ix_pyq_source_questions_answer_status", ["answer_status"]),
            (
                "ix_pyq_source_questions_classification_status",
                ["classification_status"],
            ),
            ("ix_pyq_source_questions_practice_eligible", ["practice_eligible"]),
            (
                "ix_pyq_source_questions_materialized_question_id",
                ["materialized_question_id"],
            ),
            (
                "ix_pyq_source_questions_verification",
                [
                    "transcription_status",
                    "answer_status",
                    "classification_status",
                ],
            ),
        ):
            op.create_index(name, "pyq_source_questions", columns, unique=False)

    tables = _tables()
    if "pyq_archive_imports" not in tables:
        op.create_table(
            "pyq_archive_imports",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("schema_version", sa.String(length=32), nullable=False),
            sa.Column("artifact_version", sa.String(length=96), nullable=False),
            sa.Column("checksum", sa.String(length=64), nullable=False),
            sa.Column("source_path", sa.Text(), nullable=False),
            sa.Column("paper_count", sa.Integer(), nullable=False),
            sa.Column("item_count", sa.Integer(), nullable=False),
            sa.Column("inserted_count", sa.Integer(), nullable=False),
            sa.Column("updated_count", sa.Integer(), nullable=False),
            sa.Column("unchanged_count", sa.Integer(), nullable=False),
            sa.Column("materialized_count", sa.Integer(), nullable=False),
            sa.Column("retired_count", sa.Integer(), nullable=False),
            sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "artifact_version",
                "checksum",
                name="uq_pyq_archive_version_checksum",
            ),
        )
        op.create_index(
            "ix_pyq_archive_imports_artifact_version",
            "pyq_archive_imports",
            ["artifact_version"],
            unique=False,
        )
        op.create_index(
            "ix_pyq_archive_imports_checksum",
            "pyq_archive_imports",
            ["checksum"],
            unique=False,
        )

    question_columns = _columns("questions")
    with op.batch_alter_table("questions") as batch_op:
        if "source_paper_id" not in question_columns:
            batch_op.add_column(
                sa.Column("source_paper_id", sa.String(length=96), nullable=True)
            )
            batch_op.create_foreign_key(
                "fk_questions_source_paper_id_pyq_source_papers",
                "pyq_source_papers",
                ["source_paper_id"],
                ["id"],
                ondelete="SET NULL",
            )
        if "source_item_label" not in question_columns:
            batch_op.add_column(
                sa.Column("source_item_label", sa.String(length=48), nullable=True)
            )
    if "ix_questions_source_paper_id" not in _indexes("questions"):
        op.create_index(
            "ix_questions_source_paper_id",
            "questions",
            ["source_paper_id"],
            unique=False,
        )


def downgrade() -> None:
    tables = _tables()
    if "questions" in tables:
        question_columns = _columns("questions")
        with op.batch_alter_table("questions") as batch_op:
            if "ix_questions_source_paper_id" in _indexes("questions"):
                batch_op.drop_index("ix_questions_source_paper_id")
            if "source_item_label" in question_columns:
                batch_op.drop_column("source_item_label")
            if "source_paper_id" in question_columns:
                batch_op.drop_column("source_paper_id")
    if "pyq_archive_imports" in tables:
        op.drop_table("pyq_archive_imports")
    if "pyq_source_questions" in tables:
        op.drop_table("pyq_source_questions")
    if "pyq_source_papers" in tables:
        op.drop_table("pyq_source_papers")
