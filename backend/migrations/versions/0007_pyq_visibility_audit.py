"""Audit fingerprint-bound PYQ visibility transitions.

Revision ID: 0007_pyq_visibility_audit
Revises: 0006_question_assets
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0007_pyq_visibility_audit"
down_revision = "0006_question_assets"
branch_labels = None
depends_on = None


def _execution_columns() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if "pyq_archive_executions" not in inspector.get_table_names():
        return set()
    return {
        column["name"]
        for column in inspector.get_columns("pyq_archive_executions")
    }


def upgrade() -> None:
    columns = _execution_columns()
    if "reactivated_count" not in columns:
        op.add_column(
            "pyq_archive_executions",
            sa.Column(
                "reactivated_count",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )
    if "visibility_plan_sha256" not in columns:
        op.add_column(
            "pyq_archive_executions",
            sa.Column("visibility_plan_sha256", sa.String(length=64), nullable=True),
        )
    if "expected_reactivation_count" not in columns:
        op.add_column(
            "pyq_archive_executions",
            sa.Column("expected_reactivation_count", sa.Integer(), nullable=True),
        )


def downgrade() -> None:
    columns = _execution_columns()
    if "expected_reactivation_count" in columns:
        op.drop_column("pyq_archive_executions", "expected_reactivation_count")
    if "visibility_plan_sha256" in columns:
        op.drop_column("pyq_archive_executions", "visibility_plan_sha256")
    if "reactivated_count" in columns:
        op.drop_column("pyq_archive_executions", "reactivated_count")
