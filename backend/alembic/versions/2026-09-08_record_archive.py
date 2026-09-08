"""record archive table for DLQ retention

Revision ID: 0002_record
Revises: 0001_initial
Create Date: 2026-09-08

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0002_record'
down_revision: Union[str, None] = '0001_initial'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'record',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('parent_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('payload', postgresql.JSONB, nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_record_kind', 'record', ['kind'])
    op.create_index('ix_record_parent_id', 'record', ['parent_id'])


def downgrade() -> None:
    op.drop_index('ix_record_parent_id', table_name='record')
    op.drop_index('ix_record_kind', table_name='record')
    op.drop_table('record')
