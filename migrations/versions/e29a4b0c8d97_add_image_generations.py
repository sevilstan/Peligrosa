"""add image_generations (image generation and delivery ledger)

Revision ID: e29a4b0c8d97
Revises: d18e3f9a7b87
Create Date: 2026-11-27 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e29a4b0c8d97'
down_revision: Union[str, Sequence[str], None] = 'd18e3f9a7b87'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'image_generations',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('character_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('kind', sa.String(length=10), nullable=False),
        sa.Column('source', sa.String(length=10), nullable=False),
        sa.Column('status', sa.String(length=10), nullable=False),
        sa.Column('delivery', sa.String(length=10), nullable=True),
        sa.Column('image_key', sa.String(length=120), nullable=True),
        sa.Column('provider', sa.String(length=30), nullable=False),
        sa.Column('model', sa.String(length=60), nullable=True),
        sa.Column('provider_credits', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['character_id'], ['characters.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_image_generations_character_id'), 'image_generations', ['character_id'], unique=False)
    op.create_index('ix_image_generations_created', 'image_generations', ['created_at'], unique=False)
    op.create_index('ix_image_generations_user_image', 'image_generations', ['user_id', 'image_key'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_image_generations_user_image', table_name='image_generations')
    op.drop_index('ix_image_generations_created', table_name='image_generations')
    op.drop_index(op.f('ix_image_generations_character_id'), table_name='image_generations')
    op.drop_table('image_generations')
