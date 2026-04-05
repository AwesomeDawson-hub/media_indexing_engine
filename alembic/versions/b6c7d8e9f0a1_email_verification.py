"""email_verification

Revision ID: b6c7d8e9f0a1
Revises: c0d1e2f3a4b5
Create Date: 2026-04-05

Adds:
  - users.email_verified (boolean, NOT NULL, default FALSE)
  - Backfills existing rows to TRUE so current users are not locked out.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'b6c7d8e9f0a1'
down_revision = 'c0d1e2f3a4b5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add column with server default FALSE so the NOT NULL constraint is satisfied
    op.add_column(
        'users',
        sa.Column(
            'email_verified',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('FALSE'),
        ),
    )
    # Backfill existing users: they are already active, treat them as verified
    op.execute("UPDATE users SET email_verified = TRUE")

    # Remove the server default so new rows must explicitly set the value
    op.alter_column('users', 'email_verified', server_default=None)


def downgrade() -> None:
    op.drop_column('users', 'email_verified')
