"""Add perceptual_hash columns to media_items for near-duplicate detection.

Revision ID: f1e2d3c4b5a6
Revises: e1f2a3b4c5d6
Create Date: 2026-04-03

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'f1e2d3c4b5a6'
down_revision = 'e1f2a3b4c5d6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'media_items',
        sa.Column('perceptual_hash', sa.String(16), nullable=True),
    )
    op.add_column(
        'media_items',
        sa.Column('phash_version', sa.String(20), nullable=True),
    )
    op.add_column(
        'media_items',
        sa.Column(
            'phash_computed_at',
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        'ix_media_items_perceptual_hash',
        'media_items',
        ['perceptual_hash'],
    )


def downgrade() -> None:
    op.drop_index('ix_media_items_perceptual_hash', table_name='media_items')
    op.drop_column('media_items', 'phash_computed_at')
    op.drop_column('media_items', 'phash_version')
    op.drop_column('media_items', 'perceptual_hash')
