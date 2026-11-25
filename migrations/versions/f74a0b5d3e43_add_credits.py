"""add credits

Revision ID: f74a0b5d3e43
Revises: e63f9a4c2d32
Create Date: 2026-11-25 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f74a0b5d3e43'
down_revision: Union[str, Sequence[str], None] = 'e63f9a4c2d32'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema. Existing users get their trial lazily on first use."""
    op.add_column('users', sa.Column('credits', sa.Integer(), server_default='0', nullable=False))
    op.add_column('users', sa.Column('subscription_until', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('trial_granted_at', sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        'credit_transactions',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('amount', sa.Integer(), nullable=False),
        sa.Column('balance_after', sa.Integer(), nullable=False),
        sa.Column('reason', sa.String(length=30), nullable=False),
        sa.Column('conversation_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_credit_transactions_user_created', 'credit_transactions', ['user_id', 'created_at']
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_credit_transactions_user_created', table_name='credit_transactions')
    op.drop_table('credit_transactions')
    op.drop_column('users', 'trial_granted_at')
    op.drop_column('users', 'subscription_until')
    op.drop_column('users', 'credits')
