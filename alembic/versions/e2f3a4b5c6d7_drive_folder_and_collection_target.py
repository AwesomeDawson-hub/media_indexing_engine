"""drive_folder_and_collection_target: add target_folder_id and
target_collection_id to source_connectors for folder-scoped Drive sync.

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-04-05

Changes:
  - Add source_connectors.target_folder_id   (VARCHAR 255, nullable — Drive folder ID, NULL means root)
  - Add source_connectors.target_folder_label (VARCHAR 255, nullable — display name of the folder)
  - Add source_connectors.target_collection_id (VARCHAR 36, nullable — FK to collections.id)
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = 'e2f3a4b5c6d7'
down_revision = 'd1e2f3a4b5c6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "source_connectors",
        sa.Column("target_folder_id", sa.String(255), nullable=True),
    )
    op.add_column(
        "source_connectors",
        sa.Column("target_folder_label", sa.String(255), nullable=True),
    )
    op.add_column(
        "source_connectors",
        sa.Column("target_collection_id", sa.String(36), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("source_connectors", "target_collection_id")
    op.drop_column("source_connectors", "target_folder_label")
    op.drop_column("source_connectors", "target_folder_id")
