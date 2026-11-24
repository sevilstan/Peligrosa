"""add character relationships and emotions

Revision ID: c41d7e2a9b10
Revises: a83a4882b1de
Create Date: 2026-11-24 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c41d7e2a9b10'
down_revision: Union[str, Sequence[str], None] = 'a83a4882b1de'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DIMENSIONS = {
    'trust': 50,
    'affection': 50,
    'respect': 50,
    'jealousy': 0,
    'rivalry': 0,
    'familiarity': 0,
    'tension': 0,
}


def upgrade() -> None:
    """Upgrade schema. New tables only; nothing existing is touched."""
    op.create_table(
        'character_relationships',
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('character_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('other_character_id', postgresql.UUID(as_uuid=True), nullable=False),
        *(
            sa.Column(name, sa.SmallInteger(), server_default=str(default), nullable=False)
            for name, default in DIMENSIONS.items()
        ),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('character_id <> other_character_id', name='ck_character_relationship_not_self'),
        *(
            sa.CheckConstraint(f'{name} >= 0 AND {name} <= 100', name=f'ck_character_relationship_{name}')
            for name in DIMENSIONS
        ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['character_id'], ['characters.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['other_character_id'], ['characters.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id', 'character_id', 'other_character_id'),
    )
    op.create_table(
        'character_emotions',
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('character_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('mood', sa.String(length=30), nullable=False),
        sa.Column('intensity', sa.SmallInteger(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('intensity >= 0 AND intensity <= 100', name='ck_character_emotion_intensity'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['character_id'], ['characters.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id', 'character_id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('character_emotions')
    op.drop_table('character_relationships')
