"""add user_events (what users do, by name only)

Revision ID: f3a5c1d29e08
Revises: e29a4b0c8d97
Create Date: 2026-11-27 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f3a5c1d29e08'
down_revision: Union[str, Sequence[str], None] = 'e29a4b0c8d97'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'user_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=40), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_user_events_user_created', 'user_events', ['user_id', 'created_at'], unique=False)
    op.create_index('ix_user_events_name_created', 'user_events', ['name', 'created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_user_events_name_created', table_name='user_events')
    op.drop_index('ix_user_events_user_created', table_name='user_events')
    op.drop_table('user_events')
