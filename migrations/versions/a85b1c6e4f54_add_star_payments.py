"""add star payments

Revision ID: a85b1c6e4f54
Revises: f74a0b5d3e43
Create Date: 2026-11-25 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a85b1c6e4f54'
down_revision: Union[str, Sequence[str], None] = 'f74a0b5d3e43'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'star_payments',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('telegram_charge_id', sa.String(length=255), nullable=False),
        sa.Column('product', sa.String(length=40), nullable=False),
        sa.Column('stars', sa.Integer(), nullable=False),
        sa.Column('credits_granted', sa.Integer(), nullable=False),
        sa.Column('days_granted', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('refunded_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('telegram_charge_id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('star_payments')
