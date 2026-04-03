"""Add curation_scores table for AI best-photo quality scoring.

Revision ID: c7d8e9f0a1b2
Revises: f1e2d3c4b5a6
Create Date: 2026-04-02

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'c7d8e9f0a1b2'
down_revision = 'f1e2d3c4b5a6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'curation_scores',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column(
            'media_item_id',
            sa.String(36),
            sa.ForeignKey('media_items.id'),
            nullable=False,
        ),
        sa.Column(
            'user_id',
            sa.String(36),
            sa.ForeignKey('users.id'),
            nullable=False,
        ),
        sa.Column('quality_score', sa.Float, nullable=False),
        sa.Column('rationale', sa.Text, nullable=False),
        sa.Column('scoring_model', sa.String(100), nullable=False),
        sa.Column('scored_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        'ix_curation_scores_media_item_id',
        'curation_scores',
        ['media_item_id'],
        unique=True,
    )
    op.create_index(
        'ix_curation_scores_user_id',
        'curation_scores',
        ['user_id'],
    )


def downgrade() -> None:
    op.drop_index('ix_curation_scores_user_id', table_name='curation_scores')
    op.drop_index('ix_curation_scores_media_item_id', table_name='curation_scores')
    op.drop_table('curation_scores')
