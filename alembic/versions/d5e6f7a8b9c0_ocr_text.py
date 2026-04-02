"""Add ocr_text column to media_metadata.

Revision ID: d5e6f7a8b9c0
Revises: c3d4e5f6a7b8
Create Date: 2026-04-01

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'd5e6f7a8b9c0'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'media_metadata',
        sa.Column('ocr_text', sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('media_metadata', 'ocr_text')
