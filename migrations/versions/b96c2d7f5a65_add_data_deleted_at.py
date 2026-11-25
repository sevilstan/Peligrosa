"""add data_deleted_at

Revision ID: b96c2d7f5a65
Revises: a85b1c6e4f54
Create Date: 2026-11-25 14:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b96c2d7f5a65'
down_revision: Union[str, Sequence[str], None] = 'a85b1c6e4f54'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('users', sa.Column('data_deleted_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'data_deleted_at')
