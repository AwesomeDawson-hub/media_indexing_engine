"""google_sso

Revision ID: a3b4c5d6e7f8
Revises: f6a7b8c9d0e1
Create Date: 2026-04-05

Adds:
  - oauth_accounts   — provider-neutral external identity links
  - google_completion_records — short-lived one-time SSO handoff records
"""
from alembic import op
import sqlalchemy as sa

revision = 'a3b4c5d6e7f8'
down_revision = 'f6a7b8c9d0e1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'oauth_accounts',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('provider', sa.String(50), nullable=False),
        sa.Column('provider_user_id', sa.String(255), nullable=False),
        sa.Column('provider_email', sa.String(255), nullable=True),
        sa.Column('provider_email_verified', sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('provider', 'provider_user_id', name='uq_oauth_provider_user'),
        sa.UniqueConstraint('user_id', 'provider', name='uq_oauth_user_provider'),
    )
    op.create_index('ix_oauth_accounts_user_id', 'oauth_accounts', ['user_id'])
    op.create_index('ix_oauth_accounts_provider_email', 'oauth_accounts',
                    ['provider', 'provider_email'])

    op.create_table(
        'google_completion_records',
        sa.Column('flow_id', sa.String(64), nullable=False),
        sa.Column('completion_id_hash', sa.String(64), nullable=False),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('flow_id'),
    )
    op.create_index('ix_completion_expires', 'google_completion_records', ['expires_at'])
    op.create_index('ix_completion_user_id', 'google_completion_records', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_completion_user_id', table_name='google_completion_records')
    op.drop_index('ix_completion_expires', table_name='google_completion_records')
    op.drop_table('google_completion_records')
    op.drop_index('ix_oauth_accounts_provider_email', table_name='oauth_accounts')
    op.drop_index('ix_oauth_accounts_user_id', table_name='oauth_accounts')
    op.drop_table('oauth_accounts')
