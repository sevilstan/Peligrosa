"""add user name_status

Revision ID: c07d2e8f6a76
Revises: b96c2d7f5a65
Create Date: 2026-11-26 01:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c07d2e8f6a76'
down_revision: Union[str, Sequence[str], None] = 'b96c2d7f5a65'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('name_status', sa.String(length=10), server_default='unasked', nullable=False),
    )


def downgrade() -> None:
    op.drop_column('users', 'name_status')
