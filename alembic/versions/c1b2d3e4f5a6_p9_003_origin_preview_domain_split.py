"""p9_003_origin_preview_domain_split: add origin_asset_refs and preview_assets tables.

Revision ID: c1b2d3e4f5a6
Revises: b0a1c2d3e4f5
Create Date: 2026-04-09

Changes:
  - Create origin_asset_refs table (P9-003 / ARCH-002)
  - Create preview_assets table (P9-003 / ARCH-002)

Both tables are additive. No existing columns are removed or modified.

MediaItem.storage_path, MediaItem.thumbnail_path, and
MediaItem.source_file_fingerprint remain as compatibility mirrors during
rollout per the locked P9-003 scope.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = 'c1b2d3e4f5a6'
down_revision = 'b0a1c2d3e4f5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -----------------------------------------------------------------------
    # origin_asset_refs
    # -----------------------------------------------------------------------
    op.create_table(
        'origin_asset_refs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('media_item_id', sa.String(36),
                  sa.ForeignKey('media_items.id'), nullable=False),
        sa.Column('user_id', sa.String(36),
                  sa.ForeignKey('users.id'), nullable=False),
        sa.Column('source_id', sa.String(36),
                  sa.ForeignKey('sources.id'), nullable=True),
        sa.Column('source_object_id', sa.String(36),
                  sa.ForeignKey('source_objects.id'), nullable=True),
        sa.Column('provider_type', sa.String(50), nullable=False),
        sa.Column('provider_object_id', sa.String(1024), nullable=True),
        sa.Column('locator_snapshot', sa.String(1024), nullable=True),
        sa.Column('revision_marker', sa.String(255), nullable=True),
        sa.Column('app_storage_path', sa.String(500), nullable=True),
        sa.Column('local_file_fingerprint', sa.String(64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('media_item_id', name='uq_origin_asset_refs_media_item_id'),
    )
    op.create_index('ix_origin_asset_refs_user_id',
                    'origin_asset_refs', ['user_id'])
    op.create_index('ix_origin_asset_refs_source_id',
                    'origin_asset_refs', ['source_id'])
    op.create_index('ix_origin_asset_refs_source_object_id',
                    'origin_asset_refs', ['source_object_id'])
    op.create_index('ix_origin_asset_refs_provider_type_provider_object_id',
                    'origin_asset_refs', ['provider_type', 'provider_object_id'])

    # -----------------------------------------------------------------------
    # preview_assets
    # -----------------------------------------------------------------------
    op.create_table(
        'preview_assets',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('media_item_id', sa.String(36),
                  sa.ForeignKey('media_items.id'), nullable=False),
        sa.Column('user_id', sa.String(36),
                  sa.ForeignKey('users.id'), nullable=False),
        sa.Column('variant_type', sa.String(20), nullable=False),
        sa.Column('storage_path', sa.String(500), nullable=False),
        sa.Column('mime_type', sa.String(50), nullable=False),
        sa.Column('width', sa.Integer(), nullable=True),
        sa.Column('height', sa.Integer(), nullable=True),
        sa.Column('file_size', sa.BigInteger(), nullable=True),
        sa.Column('checksum', sa.String(64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('media_item_id', 'variant_type',
                            name='uq_preview_assets_item_variant'),
    )
    op.create_index('ix_preview_assets_user_id', 'preview_assets', ['user_id'])
    op.create_index('ix_preview_assets_storage_path',
                    'preview_assets', ['storage_path'])


def downgrade() -> None:
    op.drop_index('ix_preview_assets_storage_path', table_name='preview_assets')
    op.drop_index('ix_preview_assets_user_id', table_name='preview_assets')
    op.drop_table('preview_assets')

    op.drop_index('ix_origin_asset_refs_provider_type_provider_object_id',
                  table_name='origin_asset_refs')
    op.drop_index('ix_origin_asset_refs_source_object_id',
                  table_name='origin_asset_refs')
    op.drop_index('ix_origin_asset_refs_source_id',
                  table_name='origin_asset_refs')
    op.drop_index('ix_origin_asset_refs_user_id', table_name='origin_asset_refs')
    op.drop_table('origin_asset_refs')
