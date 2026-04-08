"""storage_pivot_p8_001: add thumbnail_path, storage_mode; make storage_path nullable.

Revision ID: a1b2c3d4e5f7
Revises: f8a9b0c1d2e3
Create Date: 2026-04-15

Changes:
  - media_items: add thumbnail_path (String 500, nullable)
  - media_items: add storage_mode (String 20, not-null, server_default='full')
  - media_items: alter storage_path to nullable
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = 'a1b2c3d4e5f7'
down_revision = 'f8a9b0c1d2e3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("media_items", sa.Column("thumbnail_path", sa.String(500), nullable=True))
    op.add_column(
        "media_items",
        sa.Column("storage_mode", sa.String(20), nullable=False, server_default="full"),
    )
    # Make storage_path nullable — existing rows keep their current value,
    # new preview_only rows will have storage_path = NULL.
    with op.batch_alter_table("media_items") as batch_op:
        batch_op.alter_column("storage_path", existing_type=sa.String(500), nullable=True)


def downgrade() -> None:
    # Restore storage_path to not-null (set any NULLs to empty string first)
    op.execute("UPDATE media_items SET storage_path = '' WHERE storage_path IS NULL")
    with op.batch_alter_table("media_items") as batch_op:
        batch_op.alter_column("storage_path", existing_type=sa.String(500), nullable=False)
    op.drop_column("media_items", "storage_mode")
    op.drop_column("media_items", "thumbnail_path")
