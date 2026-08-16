"""Add immutable per-execution audit events for PYQ archive applies.

Revision ID: 0005_pyq_archive_execution_audit
Revises: 0004_pyq_archive
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0005_pyq_archive_execution_audit"
down_revision = "0004_pyq_archive"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if "pyq_archive_executions" in _tables():
        return

    op.create_table(
        "pyq_archive_executions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("archive_import_id", sa.Integer(), nullable=False),
        sa.Column("artifact_version", sa.String(length=96), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("execution_mode", sa.String(length=32), nullable=False),
        sa.Column("inserted_count", sa.Integer(), nullable=False),
        sa.Column("updated_count", sa.Integer(), nullable=False),
        sa.Column("unchanged_count", sa.Integer(), nullable=False),
        sa.Column("materialized_inserted_count", sa.Integer(), nullable=False),
        sa.Column("materialized_adopted_count", sa.Integer(), nullable=False),
        sa.Column("materialized_updated_count", sa.Integer(), nullable=False),
        sa.Column("retired_count", sa.Integer(), nullable=False),
        sa.Column("original_active_before", sa.Integer(), nullable=False),
        sa.Column("original_active_after", sa.Integer(), nullable=False),
        sa.Column("pyq_active_before", sa.Integer(), nullable=False),
        sa.Column("pyq_active_after", sa.Integer(), nullable=False),
        sa.Column("expected_original_count", sa.Integer(), nullable=True),
        sa.Column("original_guard_bypassed", sa.Boolean(), nullable=False),
        sa.Column("retirement_allowed", sa.Boolean(), nullable=False),
        sa.Column("expected_retirement_count", sa.Integer(), nullable=True),
        sa.Column("expected_active_pyqs_before", sa.Integer(), nullable=True),
        sa.Column("expected_active_pyqs_after", sa.Integer(), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["archive_import_id"],
            ["pyq_archive_imports.id"],
            name="fk_pyq_archive_executions_archive_import_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_pyq_archive_executions_archive_import_id",
        "pyq_archive_executions",
        ["archive_import_id"],
        unique=False,
    )
    op.create_index(
        "ix_pyq_archive_executions_artifact_version",
        "pyq_archive_executions",
        ["artifact_version"],
        unique=False,
    )
    op.create_index(
        "ix_pyq_archive_executions_checksum",
        "pyq_archive_executions",
        ["checksum"],
        unique=False,
    )
    op.create_index(
        "ix_pyq_archive_executions_execution_mode",
        "pyq_archive_executions",
        ["execution_mode"],
        unique=False,
    )
    op.create_index(
        "ix_pyq_archive_executions_artifact",
        "pyq_archive_executions",
        ["artifact_version", "checksum"],
        unique=False,
    )


def downgrade() -> None:
    if "pyq_archive_executions" in _tables():
        op.drop_table("pyq_archive_executions")
