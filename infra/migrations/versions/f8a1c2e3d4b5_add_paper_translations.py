"""add paper_translations

Revision ID: f8a1c2e3d4b5
Revises: 4425bcca6b75
Create Date: 2026-07-08 17:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f8a1c2e3d4b5'
down_revision = '4425bcca6b75'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'paper_translations',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column(
            'paper_id',
            sa.String(36),
            sa.ForeignKey('papers.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('target_lang', sa.String(16), nullable=False, server_default='zh'),
        sa.Column('mode', sa.String(16), nullable=False, server_default='fast'),
        sa.Column('segments', sa.JSON, nullable=True),
        sa.Column('bilingual_pdf_path', sa.String(512), nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False),
        sa.Column('updated_at', sa.DateTime, nullable=False),
        sa.UniqueConstraint('paper_id', 'target_lang', 'mode', name='uq_paper_translation'),
    )
    op.create_index('ix_paper_translations_paper_id', 'paper_translations', ['paper_id'])


def downgrade() -> None:
    op.drop_index('ix_paper_translations_paper_id', table_name='paper_translations')
    op.drop_table('paper_translations')
