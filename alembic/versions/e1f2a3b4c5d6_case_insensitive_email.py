"""Enforce case-insensitive email uniqueness: normalize existing emails to lowercase,
handle any duplicates, replace case-sensitive unique constraint with a functional
UNIQUE index on LOWER(email).

Revision ID: e1f2a3b4c5d6
Revises: d5e6f7a8b9c0
Create Date: 2026-04-02

"""
from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = 'e1f2a3b4c5d6'
down_revision = 'd5e6f7a8b9c0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Step 1: For any rows that would collide after lowercasing (pre-existing duplicates
    # with different capitalisation), rename the *newer* duplicate(s) so they don't
    # block the normalization.  Admins can identify and clean these up via the admin
    # console — their email will end with '+dupXXXXXXXX'.
    op.execute("""
        UPDATE users
        SET email = LOWER(email) || '+dup' || LEFT(id, 8)
        WHERE id IN (
            SELECT id FROM (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY LOWER(email)
                           ORDER BY created_at ASC
                       ) AS rn
                FROM users
            ) ranked
            WHERE rn > 1
        )
    """)

    # Step 2: Lowercase all remaining emails.
    op.execute("UPDATE users SET email = LOWER(email)")

    # Step 3: Drop the existing case-sensitive unique constraint.
    # SQLAlchemy names it 'users_email_key' by default; guard with a DO block in case
    # the name differs on this instance.
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'users_email_key' AND conrelid = 'users'::regclass
            ) THEN
                ALTER TABLE users DROP CONSTRAINT users_email_key;
            END IF;
        END$$
    """)

    # Step 4: Add a functional unique index on LOWER(email) — enforces
    # case-insensitive uniqueness at the database level.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email_lower ON users (LOWER(email))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_users_email_lower")
    op.execute("ALTER TABLE users ADD CONSTRAINT users_email_key UNIQUE (email)")
