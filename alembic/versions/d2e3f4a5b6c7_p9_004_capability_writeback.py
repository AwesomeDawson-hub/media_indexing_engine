"""p9_004_capability_writeback: add capability snapshot and durable write-back tables.

Revision ID: d2e3f4a5b6c7
Revises: c1b2d3e4f5a6
Create Date: 2026-04-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "d2e3f4a5b6c7"
down_revision = "c1b2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_capability_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_id", sa.String(36), sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("source_connector_id", sa.String(36), sa.ForeignKey("source_connectors.id"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("provider_type", sa.String(50), nullable=False),
        sa.Column("can_read", sa.Boolean(), nullable=False),
        sa.Column("can_write", sa.Boolean(), nullable=False),
        sa.Column("can_refetch", sa.Boolean(), nullable=False),
        sa.Column("scope_text", sa.Text(), nullable=True),
        sa.Column("scope_tier", sa.String(20), nullable=False),
        sa.Column("verification_state", sa.String(20), nullable=False),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(50), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_id", name="uq_source_capability_snapshots_source_id"),
        sa.UniqueConstraint("source_connector_id", name="uq_source_capability_snapshots_connector_id"),
    )
    op.create_index("ix_source_capability_snapshots_user_id", "source_capability_snapshots", ["user_id"])
    op.create_index(
        "ix_source_capability_snapshots_provider_verification",
        "source_capability_snapshots",
        ["provider_type", "verification_state"],
    )

    op.create_table(
        "writeback_operations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("media_item_id", sa.String(36), sa.ForeignKey("media_items.id"), nullable=False),
        sa.Column("origin_asset_ref_id", sa.String(36), sa.ForeignKey("origin_asset_refs.id"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("source_id", sa.String(36), sa.ForeignKey("sources.id"), nullable=True),
        sa.Column("source_connector_id", sa.String(36), sa.ForeignKey("source_connectors.id"), nullable=True),
        sa.Column("provider_type", sa.String(50), nullable=False),
        sa.Column("operation_type", sa.String(30), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("requested_filename", sa.String(255), nullable=True),
        sa.Column("requested_metadata_payload", sa.Text(), nullable=True),
        sa.Column("requested_metadata_payload_hash", sa.String(64), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("last_attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(50), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("media_item_id", "operation_type", name="uq_writeback_operations_item_operation"),
    )
    op.create_index("ix_writeback_operations_origin_asset_ref_id", "writeback_operations", ["origin_asset_ref_id"])
    op.create_index("ix_writeback_operations_user_id", "writeback_operations", ["user_id"])
    op.create_index("ix_writeback_operations_source_id", "writeback_operations", ["source_id"])
    op.create_index("ix_writeback_operations_source_connector_id", "writeback_operations", ["source_connector_id"])
    op.create_index("ix_writeback_operations_state_operation", "writeback_operations", ["state", "operation_type"])


def downgrade() -> None:
    op.drop_index("ix_writeback_operations_state_operation", table_name="writeback_operations")
    op.drop_index("ix_writeback_operations_source_connector_id", table_name="writeback_operations")
    op.drop_index("ix_writeback_operations_source_id", table_name="writeback_operations")
    op.drop_index("ix_writeback_operations_user_id", table_name="writeback_operations")
    op.drop_index("ix_writeback_operations_origin_asset_ref_id", table_name="writeback_operations")
    op.drop_table("writeback_operations")

    op.drop_index("ix_source_capability_snapshots_provider_verification", table_name="source_capability_snapshots")
    op.drop_index("ix_source_capability_snapshots_user_id", table_name="source_capability_snapshots")
    op.drop_table("source_capability_snapshots")
