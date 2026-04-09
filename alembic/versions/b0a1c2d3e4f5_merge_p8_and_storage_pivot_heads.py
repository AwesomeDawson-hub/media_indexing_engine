"""merge_p8_and_storage_pivot_heads: merge a0b1c2d3e4f5 and a1b2c3d4e5f7 into a single head.

Revision ID: b0a1c2d3e4f5
Revises: a0b1c2d3e4f5, a1b2c3d4e5f7
Create Date: 2026-04-09

Merges the auto_sync_scheduler branch (a0b1c2d3e4f5) with the
storage_pivot_p8_001 branch (a1b2c3d4e5f7) — both descend from
f8a9b0c1d2e3 and touch different tables, so no conflicts exist.
"""
from __future__ import annotations

from alembic import op  # noqa: F401


revision = 'b0a1c2d3e4f5'
down_revision = ('a0b1c2d3e4f5', 'a1b2c3d4e5f7')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
