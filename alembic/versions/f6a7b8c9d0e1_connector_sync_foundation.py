"""Connector sync foundation: source_connectors, sync_runs, source_objects tables;
extend sources with connector_status and last_synced_at.

Revision ID: f6a7b8c9d0e1
Revises: a1b2c3d4e5f6
Create Date: 2026-04-02

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'f6a7b8c9d0e1'
down_revision = 'c7d8e9f0a1b2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Extend sources table with connector summary fields
    op.add_column('sources', sa.Column('connector_status', sa.String(30), nullable=True))
    op.add_column('sources', sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True))

    # New table: source_connectors — one-to-one connector configuration per connected source
    op.create_table(
        'source_connectors',
        sa.Column('id', sa.String(36), nullable=False, primary_key=True),
        sa.Column('source_id', sa.String(36), sa.ForeignKey('sources.id'), nullable=False),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('connector_type', sa.String(50), nullable=False),
        sa.Column('bucket_name', sa.String(255), nullable=False),
        sa.Column('prefix', sa.String(500), nullable=True),
        sa.Column('region', sa.String(100), nullable=True),
        sa.Column('endpoint_url', sa.String(500), nullable=True),
        sa.Column('credentials_encrypted', sa.Text, nullable=False),
        sa.Column('config_validated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_validation_error', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_source_connectors_source_id', 'source_connectors', ['source_id'], unique=True)
    op.create_index('ix_source_connectors_user_id', 'source_connectors', ['user_id'])

    # New table: sync_runs — one run record per manual sync trigger
    op.create_table(
        'sync_runs',
        sa.Column('id', sa.String(36), nullable=False, primary_key=True),
        sa.Column('source_id', sa.String(36), sa.ForeignKey('sources.id'), nullable=False),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('connector_type', sa.String(50), nullable=False),
        sa.Column('trigger_type', sa.String(20), nullable=False, server_default='manual'),
        sa.Column('status', sa.String(30), nullable=False, server_default='pending'),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('discovered_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column('imported_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column('duplicate_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column('skipped_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column('failed_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column('error_summary', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_sync_runs_source_id', 'sync_runs', ['source_id'])
    op.create_index('ix_sync_runs_user_id', 'sync_runs', ['user_id'])
    op.create_index('ix_sync_runs_status', 'sync_runs', ['status'])

    # New table: source_objects — per-object sync memory for idempotency
    op.create_table(
        'source_objects',
        sa.Column('id', sa.String(36), nullable=False, primary_key=True),
        sa.Column('source_id', sa.String(36), sa.ForeignKey('sources.id'), nullable=False),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('external_object_key', sa.String(1024), nullable=False),
        sa.Column('external_version', sa.String(255), nullable=True),
        sa.Column('external_last_modified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('external_size', sa.BigInteger, nullable=True),
        sa.Column('last_sync_run_id', sa.String(36), sa.ForeignKey('sync_runs.id'), nullable=True),
        sa.Column('last_imported_media_item_id', sa.String(36), sa.ForeignKey('media_items.id'), nullable=True),
        sa.Column('last_content_hash', sa.String(64), nullable=True),
        sa.Column('state', sa.String(30), nullable=False),
        sa.Column('last_error', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_source_objects_source_key', 'source_objects', ['source_id', 'external_object_key'], unique=True)
    op.create_index('ix_source_objects_user_id', 'source_objects', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_source_objects_user_id', table_name='source_objects')
    op.drop_index('ix_source_objects_source_key', table_name='source_objects')
    op.drop_table('source_objects')

    op.drop_index('ix_sync_runs_status', table_name='sync_runs')
    op.drop_index('ix_sync_runs_user_id', table_name='sync_runs')
    op.drop_index('ix_sync_runs_source_id', table_name='sync_runs')
    op.drop_table('sync_runs')

    op.drop_index('ix_source_connectors_user_id', table_name='source_connectors')
    op.drop_index('ix_source_connectors_source_id', table_name='source_connectors')
    op.drop_table('source_connectors')

    op.drop_column('sources', 'last_synced_at')
    op.drop_column('sources', 'connector_status')
