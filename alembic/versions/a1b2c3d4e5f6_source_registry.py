"""source_registry: add sources table and source_id FK on media_items

Revision ID: a1b2c3d4e5f6
Revises: 7a8b9c0d1e2f
Create Date: 2026-04-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '7a8b9c0d1e2f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create sources table and add source_id FK to media_items."""
    op.create_table(
        'sources',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('source_type', sa.String(length=50), nullable=False, server_default='manual'),
        sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_sources_user_id', 'sources', ['user_id'])

    op.add_column(
        'media_items',
        sa.Column('source_id', sa.String(length=36), nullable=True),
    )
    with op.batch_alter_table('media_items') as batch_op:
        batch_op.create_foreign_key(
            'fk_media_items_source_id',
            'sources',
            ['source_id'], ['id'],
        )


def downgrade() -> None:
    """Remove source_id FK from media_items and drop sources table."""
    with op.batch_alter_table('media_items') as batch_op:
        batch_op.drop_constraint('fk_media_items_source_id', type_='foreignkey')
        batch_op.drop_column('source_id')
    op.drop_index('ix_sources_user_id', table_name='sources')
    op.drop_table('sources')
