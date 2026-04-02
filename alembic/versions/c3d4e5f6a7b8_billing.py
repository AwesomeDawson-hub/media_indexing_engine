"""billing: stripe columns on users + stripe_events table

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-04-01
"""
from alembic import op
import sqlalchemy as sa

revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add Stripe billing columns to users
    op.add_column('users', sa.Column('stripe_customer_id', sa.String(100), nullable=True))
    op.add_column('users', sa.Column('stripe_subscription_id', sa.String(100), nullable=True))
    op.add_column('users', sa.Column('billing_status', sa.String(30), nullable=False, server_default='none'))

    # Unique index on stripe_customer_id (preferred over constraint for SQLite compat)
    op.create_index('ix_users_stripe_customer_id', 'users', ['stripe_customer_id'], unique=True)

    # Create stripe_events idempotency table
    op.create_table(
        'stripe_events',
        sa.Column('id', sa.String(36), primary_key=True, nullable=False),
        sa.Column('stripe_event_id', sa.String(100), nullable=False),
        sa.Column('event_type', sa.String(100), nullable=False),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_stripe_events_stripe_event_id', 'stripe_events', ['stripe_event_id'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_stripe_events_stripe_event_id', table_name='stripe_events')
    op.drop_table('stripe_events')
    op.drop_index('ix_users_stripe_customer_id', table_name='users')
    op.drop_column('users', 'billing_status')
    op.drop_column('users', 'stripe_subscription_id')
    op.drop_column('users', 'stripe_customer_id')
