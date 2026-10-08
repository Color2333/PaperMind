"""add tasks.external_ref

C3 统一旧状态：durable Task 关联过渡期 tracker task_id（C7 后为 Go Core task id），
使旧轮询端点 /tasks/{id} 可以 durability 优先解析。

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-09-02
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'f3a4b5c6d7e8'
down_revision = 'e2f3a4b5c6d7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'tasks', sa.Column('external_ref', sa.String(128), nullable=True)
    )
    op.create_index('ix_tasks_external_ref', 'tasks', ['external_ref'])


def downgrade() -> None:
    op.drop_index('ix_tasks_external_ref', table_name='tasks')
    op.drop_column('tasks', 'external_ref')
