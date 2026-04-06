"""source_mutation_completion_states: add P7-004 mutation state and history.

Revision ID: f8a9b0c1d2e3
Revises: e2f3a4b5c6d7
Create Date: 2026-04-10

Changes:
  - media_items: add mutation_state, first_seen_source_filename, prior_source_filename,
                 source_filename_applied_at, last_writeback_at, last_mutation_attempted_at,
                 last_mutation_error_code, last_mutation_error_message, source_file_fingerprint
  - source_connectors: add granted_scopes
  - Create source_mutation_history table
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = 'f8a9b0c1d2e3'
down_revision = 'e2f3a4b5c6d7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- media_items: mutation-state fields ---
    op.add_column("media_items", sa.Column("mutation_state", sa.String(30), nullable=True))
    op.add_column("media_items", sa.Column("first_seen_source_filename", sa.String(255), nullable=True))
    op.add_column("media_items", sa.Column("prior_source_filename", sa.String(255), nullable=True))
    op.add_column("media_items", sa.Column("source_filename_applied_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("media_items", sa.Column("last_writeback_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("media_items", sa.Column("last_mutation_attempted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("media_items", sa.Column("last_mutation_error_code", sa.String(50), nullable=True))
    op.add_column("media_items", sa.Column("last_mutation_error_message", sa.Text, nullable=True))
    op.add_column("media_items", sa.Column("source_file_fingerprint", sa.String(64), nullable=True))
    op.create_index("ix_media_items_mutation_state", "media_items", ["mutation_state"])

    # --- source_connectors: granted_scopes ---
    op.add_column("source_connectors", sa.Column("granted_scopes", sa.Text, nullable=True))

    # --- source_mutation_history table ---
    op.create_table(
        "source_mutation_history",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("media_item_id", sa.String(36), sa.ForeignKey("media_items.id"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("operation_type", sa.String(30), nullable=False),
        sa.Column("prior_filename", sa.String(255), nullable=True),
        sa.Column("new_filename", sa.String(255), nullable=True),
        sa.Column("source_locator_snapshot", sa.Text, nullable=True),
        sa.Column("metadata_payload_hash", sa.String(64), nullable=True),
        sa.Column("succeeded", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error_code", sa.String(50), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_mutation_history_media_item_id", "source_mutation_history", ["media_item_id"])
    op.create_index("ix_mutation_history_user_id", "source_mutation_history", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_mutation_history_user_id", "source_mutation_history")
    op.drop_index("ix_mutation_history_media_item_id", "source_mutation_history")
    op.drop_table("source_mutation_history")

    op.drop_column("source_connectors", "granted_scopes")

    op.drop_index("ix_media_items_mutation_state", "media_items")
    op.drop_column("media_items", "source_file_fingerprint")
    op.drop_column("media_items", "last_mutation_error_message")
    op.drop_column("media_items", "last_mutation_error_code")
    op.drop_column("media_items", "last_mutation_attempted_at")
    op.drop_column("media_items", "last_writeback_at")
    op.drop_column("media_items", "source_filename_applied_at")
    op.drop_column("media_items", "prior_source_filename")
    op.drop_column("media_items", "first_seen_source_filename")
    op.drop_column("media_items", "mutation_state")
