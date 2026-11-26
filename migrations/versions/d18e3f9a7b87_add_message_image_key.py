"""add messages.image_key and the generated_images cache

Revision ID: d18e3f9a7b87
Revises: c07d2e8f6a76
Create Date: 2026-11-26 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd18e3f9a7b87'
down_revision: Union[str, Sequence[str], None] = 'c07d2e8f6a76'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('messages', sa.Column('image_key', sa.String(length=80), nullable=True))
    op.create_table(
        'generated_images',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('character_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('scene_key', sa.String(length=200), nullable=False),
        sa.Column('image_key', sa.String(length=80), nullable=False),
        sa.Column('use_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['character_id'], ['characters.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_generated_images_character_id'), 'generated_images', ['character_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_generated_images_character_id'), table_name='generated_images')
    op.drop_table('generated_images')
    op.drop_column('messages', 'image_key')
