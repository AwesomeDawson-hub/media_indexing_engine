"""google_drive_connector: evolve source_connectors to provider-neutral
remote container semantics and add authorized-account snapshot columns.

Revision ID: d1e2f3a4b5c6
Revises: b6c7d8e9f0a1
Create Date: 2026-04-05

Changes:
  - Rename source_connectors.bucket_name → remote_container_id
  - Add source_connectors.remote_container_label (VARCHAR 255, nullable)
  - Add source_connectors.authorized_account_provider_id (VARCHAR 255, nullable)
  - Add source_connectors.authorized_account_email (VARCHAR 255, nullable)
  - Add source_connectors.authorized_account_display_name (VARCHAR 255, nullable)

Existing S3-compatible rows are preserved:
  - remote_container_id retains the bucket name value
  - remote_container_label is backfilled to the bucket name value (since
    remote_container_label == bucket name for S3)
  - authorized_account_* columns are left NULL for existing S3 rows
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = 'd1e2f3a4b5c6'
down_revision = 'b6c7d8e9f0a1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Rename bucket_name → remote_container_id
    op.alter_column(
        'source_connectors',
        'bucket_name',
        new_column_name='remote_container_id',
        existing_type=sa.String(255),
        existing_nullable=False,
    )

    # Add provider-neutral label column (backfill to remote_container_id value for S3)
    op.add_column(
        'source_connectors',
        sa.Column('remote_container_label', sa.String(255), nullable=True),
    )
    op.execute(
        "UPDATE source_connectors SET remote_container_label = remote_container_id"
    )

    # Add authorized-account snapshot columns (non-secret, informational)
    op.add_column(
        'source_connectors',
        sa.Column('authorized_account_provider_id', sa.String(255), nullable=True),
    )
    op.add_column(
        'source_connectors',
        sa.Column('authorized_account_email', sa.String(255), nullable=True),
    )
    op.add_column(
        'source_connectors',
        sa.Column('authorized_account_display_name', sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('source_connectors', 'authorized_account_display_name')
    op.drop_column('source_connectors', 'authorized_account_email')
    op.drop_column('source_connectors', 'authorized_account_provider_id')
    op.drop_column('source_connectors', 'remote_container_label')
    op.alter_column(
        'source_connectors',
        'remote_container_id',
        new_column_name='bucket_name',
        existing_type=sa.String(255),
        existing_nullable=False,
    )
