"""Add versioned question-bank imports and deterministic test forms.

Revision ID: 0002_question_bank_catalog
Revises: 0001_initial
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0002_question_bank_catalog"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def _columns(table_name: str) -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns(table_name)
    }


def _indexes(table_name: str) -> set[str]:
    return {
        index["name"]
        for index in sa.inspect(op.get_bind()).get_indexes(table_name)
        if index.get("name")
    }


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "external_id" not in _columns("questions"):
        op.add_column(
            "questions", sa.Column("external_id", sa.String(length=180), nullable=True)
        )
    if "bank_version" not in _columns("questions"):
        op.add_column(
            "questions", sa.Column("bank_version", sa.String(length=80), nullable=True)
        )
    question_indexes = _indexes("questions")
    if "ix_questions_external_id" not in question_indexes:
        op.create_index(
            "ix_questions_external_id",
            "questions",
            ["external_id"],
            unique=True,
        )
    if "ix_questions_bank_version" not in question_indexes:
        op.create_index(
            "ix_questions_bank_version",
            "questions",
            ["bank_version"],
            unique=False,
        )

    if "question_bank_imports" not in tables:
        op.create_table(
            "question_bank_imports",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("schema_version", sa.String(length=32), nullable=False),
            sa.Column("bank_version", sa.String(length=80), nullable=False),
            sa.Column("source_path", sa.Text(), nullable=False),
            sa.Column("checksum", sa.String(length=64), nullable=False),
            sa.Column("question_count", sa.Integer(), nullable=False),
            sa.Column("inserted_count", sa.Integer(), nullable=False),
            sa.Column("updated_count", sa.Integer(), nullable=False),
            sa.Column("unchanged_count", sa.Integer(), nullable=False),
            sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "bank_version",
                "checksum",
                name="uq_question_bank_version_checksum",
            ),
        )
        op.create_index(
            "ix_question_bank_imports_bank_version",
            "question_bank_imports",
            ["bank_version"],
            unique=False,
        )
        op.create_index(
            "ix_question_bank_imports_checksum",
            "question_bank_imports",
            ["checksum"],
            unique=False,
        )

    if "test_forms" not in tables:
        op.create_table(
            "test_forms",
            sa.Column("id", sa.String(length=80), nullable=False),
            sa.Column("title", sa.String(length=180), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column(
                "mode",
                sa.Enum(
                    "PRACTICE",
                    "SECTIONAL",
                    "FULL",
                    name="sessionmode",
                    native_enum=False,
                ),
                nullable=False,
            ),
            sa.Column("subject_id", sa.Integer(), nullable=True),
            sa.Column("form_number", sa.Integer(), nullable=False),
            sa.Column("question_ids", sa.JSON(), nullable=False),
            sa.Column("question_count", sa.Integer(), nullable=False),
            sa.Column("duration_seconds", sa.Integer(), nullable=False),
            sa.Column("total_marks", sa.Integer(), nullable=False),
            sa.Column("seed", sa.Integer(), nullable=False),
            sa.Column("question_type_counts", sa.JSON(), nullable=False),
            sa.Column("topic_count", sa.Integer(), nullable=False),
            sa.Column("bank_version", sa.String(length=80), nullable=True),
            sa.Column("is_available", sa.Boolean(), nullable=False),
            sa.Column("unavailable_reason", sa.Text(), nullable=True),
            sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["subject_id"], ["subjects.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "mode",
                "subject_id",
                "form_number",
                name="uq_test_form_scope_number",
            ),
        )
        op.create_index(
            "ix_test_forms_mode_active",
            "test_forms",
            ["mode", "is_available"],
            unique=False,
        )
        op.create_index(
            "ix_test_forms_mode", "test_forms", ["mode"], unique=False
        )
        op.create_index(
            "ix_test_forms_subject_id",
            "test_forms",
            ["subject_id"],
            unique=False,
        )
        op.create_index(
            "ix_test_forms_is_available",
            "test_forms",
            ["is_available"],
            unique=False,
        )

    if "catalog_id" not in _columns("practice_sessions"):
        with op.batch_alter_table("practice_sessions") as batch_op:
            batch_op.add_column(
                sa.Column("catalog_id", sa.String(length=80), nullable=True)
            )
            batch_op.create_foreign_key(
                "fk_practice_sessions_catalog_id_test_forms",
                "test_forms",
                ["catalog_id"],
                ["id"],
                ondelete="SET NULL",
            )
            batch_op.create_index(
                "ix_practice_sessions_catalog_id",
                ["catalog_id"],
                unique=False,
            )


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "practice_sessions" in tables and "catalog_id" in _columns("practice_sessions"):
        with op.batch_alter_table("practice_sessions") as batch_op:
            if "ix_practice_sessions_catalog_id" in _indexes("practice_sessions"):
                batch_op.drop_index("ix_practice_sessions_catalog_id")
            batch_op.drop_constraint(
                "fk_practice_sessions_catalog_id_test_forms", type_="foreignkey"
            )
            batch_op.drop_column("catalog_id")
    if "test_forms" in tables:
        op.drop_table("test_forms")
    if "question_bank_imports" in tables:
        op.drop_table("question_bank_imports")
    if "questions" in tables:
        if "ix_questions_bank_version" in _indexes("questions"):
            op.drop_index("ix_questions_bank_version", table_name="questions")
        if "ix_questions_external_id" in _indexes("questions"):
            op.drop_index("ix_questions_external_id", table_name="questions")
        if "bank_version" in _columns("questions"):
            op.drop_column("questions", "bank_version")
        if "external_id" in _columns("questions"):
            op.drop_column("questions", "external_id")

