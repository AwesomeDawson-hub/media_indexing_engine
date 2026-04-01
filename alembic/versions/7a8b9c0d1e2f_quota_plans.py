"""quota_plans: add plan_name/monthly_limit to users and create quota_events table

Revision ID: 7a8b9c0d1e2f
Revises: cce0c99946e6
Create Date: 2026-04-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7a8b9c0d1e2f'
down_revision: Union[str, Sequence[str], None] = 'cce0c99946e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add quota plan columns to users and create quota_events table."""
    # Add plan_name and monthly_limit to users; server_default fills existing rows.
    op.add_column('users', sa.Column('plan_name', sa.String(length=50), nullable=False, server_default='basic'))
    op.add_column('users', sa.Column('monthly_limit', sa.Integer(), nullable=False, server_default='500'))

    op.create_table(
        'quota_events',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('event_type', sa.String(length=20), nullable=False),
        sa.Column('media_item_id', sa.String(length=36), nullable=True),
        sa.Column('period_month', sa.Date(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['media_item_id'], ['media_items.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_quota_events_user_period', 'quota_events', ['user_id', 'period_month'])
    op.create_index('ix_quota_events_user_period_type', 'quota_events', ['user_id', 'period_month', 'event_type'])


def downgrade() -> None:
    """Remove quota_events table and plan columns from users."""
    op.drop_index('ix_quota_events_user_period_type', table_name='quota_events')
    op.drop_index('ix_quota_events_user_period', table_name='quota_events')
    op.drop_table('quota_events')
    op.drop_column('users', 'monthly_limit')
    op.drop_column('users', 'plan_name')
