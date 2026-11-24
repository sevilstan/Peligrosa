"""add reflection message count

Revision ID: d52e8f3b1c21
Revises: c41d7e2a9b10
Create Date: 2026-11-24 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd52e8f3b1c21'
down_revision: Union[str, Sequence[str], None] = 'c41d7e2a9b10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'conversations',
        sa.Column('reflection_message_count', sa.Integer(), server_default='0', nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('conversations', 'reflection_message_count')
