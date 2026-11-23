"""add memory provenance

Revision ID: a83a4882b1de
Revises: 35e9221142eb
Create Date: 2026-11-24 00:47:01.431878

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a83a4882b1de'
down_revision: Union[str, Sequence[str], None] = '35e9221142eb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Provenance only: memories stay per user + character. The conversation link
    is SET NULL so deleting a chat never deletes what a character remembers.
    """
    op.add_column('character_memories', sa.Column('source_conversation_id', sa.UUID(), nullable=True))
    op.add_column('character_memories', sa.Column('source_kind', sa.String(length=20), nullable=True))
    op.create_foreign_key(
        'fk_character_memories_source_conversation_id',
        'character_memories',
        'conversations',
        ['source_conversation_id'],
        ['id'],
        ondelete='SET NULL',
    )
    op.create_check_constraint(
        'ck_character_memory_source_kind',
        'character_memories',
        "source_kind IS NULL OR source_kind IN ('direct', 'group')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('ck_character_memory_source_kind', 'character_memories', type_='check')
    op.drop_constraint('fk_character_memories_source_conversation_id', 'character_memories', type_='foreignkey')
    op.drop_column('character_memories', 'source_kind')
    op.drop_column('character_memories', 'source_conversation_id')
