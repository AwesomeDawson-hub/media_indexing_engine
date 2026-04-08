"""auto_sync_scheduler: add auto-sync fields to source_connectors (P7-006).

Revision ID: a0b1c2d3e4f5
Revises: f8a9b0c1d2e3
Create Date: 2026-04-07

Changes:
  - source_connectors: add auto_sync_enabled (BOOLEAN, NOT NULL, DEFAULT FALSE)
  - source_connectors: add auto_sync_interval_minutes (INTEGER, NOT NULL, DEFAULT 60)
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = 'a0b1c2d3e4f5'
down_revision = 'f8a9b0c1d2e3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "source_connectors",
        sa.Column("auto_sync_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "source_connectors",
        sa.Column("auto_sync_interval_minutes", sa.Integer(), nullable=False, server_default="60"),
    )


def downgrade() -> None:
    op.drop_column("source_connectors", "auto_sync_interval_minutes")
    op.drop_column("source_connectors", "auto_sync_enabled")
