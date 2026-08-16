"""Add immutable public asset projections to materialized questions.

Revision ID: 0006_question_assets
Revises: 0005_pyq_archive_execution_audit
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0006_question_assets"
down_revision = "0005_pyq_archive_execution_audit"
branch_labels = None
depends_on = None


def _question_columns() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if "questions" not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns("questions")}


def upgrade() -> None:
    if "assets" in _question_columns():
        return
    op.add_column(
        "questions",
        sa.Column(
            "assets",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )


def downgrade() -> None:
    if "assets" in _question_columns():
        op.drop_column("questions", "assets")
