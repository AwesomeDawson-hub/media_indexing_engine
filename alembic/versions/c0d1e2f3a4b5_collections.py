"""collections

Revision ID: c0d1e2f3a4b5
Revises: a3b4c5d6e7f8
Create Date: 2026-04-05

Adds:
  - collections       — user-owned named groups of media items
  - collection_items  — join table linking media_items to collections
"""
from alembic import op
import sqlalchemy as sa

revision = 'c0d1e2f3a4b5'
down_revision = 'a3b4c5d6e7f8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'collections',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('description', sa.String(1000), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'name', name='uq_collection_user_name'),
    )
    op.create_index('ix_collections_user_id', 'collections', ['user_id'])

    op.create_table(
        'collection_items',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('collection_id', sa.String(36), sa.ForeignKey('collections.id', ondelete='CASCADE'), nullable=False),
        sa.Column('media_item_id', sa.String(36), sa.ForeignKey('media_items.id', ondelete='CASCADE'), nullable=False),
        sa.Column('added_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('collection_id', 'media_item_id', name='uq_collection_item'),
    )
    op.create_index('ix_collection_items_collection_id', 'collection_items', ['collection_id'])
    op.create_index('ix_collection_items_media_item_id', 'collection_items', ['media_item_id'])


def downgrade() -> None:
    op.drop_table('collection_items')
    op.drop_table('collections')
