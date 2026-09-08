"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-27

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0001_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'pipeline',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('audio_url', sa.String(), nullable=False),
        sa.Column('customer_webhook_url', sa.String(), nullable=False),
        sa.Column('editor_email', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('current_step', sa.String(), nullable=True),
        sa.Column('steps_state', postgresql.JSONB, nullable=False, server_default='{}'),
        sa.Column('stores_state', postgresql.JSONB, nullable=False, server_default='{}'),
        sa.Column('is_pipeline_level_crash', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('exception', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_pipeline_status', 'pipeline', ['status'])
    op.create_index('ix_pipeline_current_step', 'pipeline', ['current_step'])


def downgrade() -> None:
    op.drop_index('ix_pipeline_current_step', table_name='pipeline')
    op.drop_index('ix_pipeline_status', table_name='pipeline')
    op.drop_table('pipeline')
