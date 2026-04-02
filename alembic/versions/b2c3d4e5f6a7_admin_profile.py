"""admin_profile: add role/profile fields to users, admin_audit_log, pending_tokens

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-04-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add role/profile columns to users; create admin_audit_log and pending_tokens tables."""
    # Extend users table
    op.add_column('users', sa.Column('role', sa.String(length=20), nullable=False, server_default='user'))
    op.add_column('users', sa.Column('phone', sa.String(length=50), nullable=True))
    op.add_column('users', sa.Column('company', sa.String(length=200), nullable=True))
    op.add_column('users', sa.Column('icon_url', sa.String(length=500), nullable=True))
    op.add_column('users', sa.Column('disabled_at', sa.DateTime(timezone=True), nullable=True))

    # Admin audit log
    op.create_table(
        'admin_audit_log',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('acting_admin_id', sa.String(length=36), nullable=False),
        sa.Column('target_user_id', sa.String(length=36), nullable=True),
        sa.Column('action', sa.String(length=100), nullable=False),
        sa.Column('detail', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['acting_admin_id'], ['users.id']),
        sa.ForeignKeyConstraint(['target_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_audit_log_acting_admin_id', 'admin_audit_log', ['acting_admin_id'])

    # Pending tokens (email-change + password-reset)
    op.create_table(
        'pending_tokens',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('token_type', sa.String(length=30), nullable=False),
        sa.Column('token_hash', sa.String(length=255), nullable=False),
        sa.Column('new_value', sa.String(length=500), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_pending_tokens_user_id', 'pending_tokens', ['user_id'])


def downgrade() -> None:
    """Reverse admin_profile migration."""
    op.drop_index('ix_pending_tokens_user_id', table_name='pending_tokens')
    op.drop_table('pending_tokens')

    op.drop_index('ix_audit_log_acting_admin_id', table_name='admin_audit_log')
    op.drop_table('admin_audit_log')

    op.drop_column('users', 'disabled_at')
    op.drop_column('users', 'icon_url')
    op.drop_column('users', 'company')
    op.drop_column('users', 'phone')
    op.drop_column('users', 'role')
