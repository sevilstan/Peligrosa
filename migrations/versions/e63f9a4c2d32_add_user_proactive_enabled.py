"""add user proactive enabled

Revision ID: e63f9a4c2d32
Revises: d52e8f3b1c21
Create Date: 2026-11-24 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e63f9a4c2d32'
down_revision: Union[str, Sequence[str], None] = 'd52e8f3b1c21'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema. Existing users stay opted out."""
    op.add_column(
        'users',
        sa.Column('proactive_enabled', sa.Boolean(), server_default='false', nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'proactive_enabled')
