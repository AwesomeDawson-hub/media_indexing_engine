"""p11_002_export_jobs: add export_jobs table for async bulk export.

Revision ID: a1b2c3d4e5f7
Revises: f8a9b0c1d2e3
Create Date: 2026-04-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "a1b2c3d4e5f7"
down_revision = "f8a9b0c1d2e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "export_jobs",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("request_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("accepted_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("blocked_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rejected_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("submission_outcomes", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("item_results", sa.Text(), nullable=True),
        sa.Column("artifact_path", sa.String(512), nullable=True),
        sa.Column("artifact_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("artifact_downloaded", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_export_jobs_user_id", "export_jobs", ["user_id"])
    op.create_index("ix_export_jobs_status", "export_jobs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_export_jobs_status", table_name="export_jobs")
    op.drop_index("ix_export_jobs_user_id", table_name="export_jobs")
    op.drop_table("export_jobs")
