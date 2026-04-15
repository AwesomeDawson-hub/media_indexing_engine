"""p12_009_source_capture_metadata: add source capture datetime and GPS fields to media_items.

Revision ID: e3f4a5b6c7d8
Revises: b1c2d3e4f5a6
Create Date: 2026-04-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "e3f4a5b6c7d8"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # P12-009: first-class source-truth capture metadata fields on media_items.
    # All columns are additive and nullable so existing rows remain unaffected.
    # Backfill is handled separately by scripts/backfill_p12_009_capture_metadata.py.
    op.add_column(
        "media_items",
        sa.Column(
            "source_capture_datetime_utc",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "media_items",
        sa.Column("source_capture_datetime_raw", sa.String(64), nullable=True),
    )
    op.add_column(
        "media_items",
        sa.Column("source_capture_time_offset_minutes", sa.Integer(), nullable=True),
    )
    op.add_column(
        "media_items",
        sa.Column("source_gps_latitude", sa.Float(), nullable=True),
    )
    op.add_column(
        "media_items",
        sa.Column("source_gps_longitude", sa.Float(), nullable=True),
    )
    op.add_column(
        "media_items",
        sa.Column("source_gps_altitude_meters", sa.Float(), nullable=True),
    )
    # Index for date-taken filtering
    op.create_index(
        "ix_media_items_source_capture_datetime_utc",
        "media_items",
        ["source_capture_datetime_utc"],
    )


def downgrade() -> None:
    op.drop_index("ix_media_items_source_capture_datetime_utc", table_name="media_items")
    op.drop_column("media_items", "source_gps_altitude_meters")
    op.drop_column("media_items", "source_gps_longitude")
    op.drop_column("media_items", "source_gps_latitude")
    op.drop_column("media_items", "source_capture_time_offset_minutes")
    op.drop_column("media_items", "source_capture_datetime_raw")
    op.drop_column("media_items", "source_capture_datetime_utc")
