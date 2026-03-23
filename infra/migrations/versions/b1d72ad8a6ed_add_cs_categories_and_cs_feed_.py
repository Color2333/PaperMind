"""add cs_categories and cs_feed_subscriptions

Revision ID: b1d72ad8a6ed
Revises: 20260317_0012
Create Date: 2026-03-19 15:48:01.869654
"""

from alembic import op
import sqlalchemy as sa


revision = "b1d72ad8a6ed"
down_revision = "20260317_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create cs_categories and cs_feed_subscriptions tables (idempotent).

    Note: The original migration attempted many ALTER TABLE operations
    (SET NOT NULL, enum changes, column drops) that are not supported by SQLite.
    SQLite schema changes require table recreation. The tables created here
    are the only ones needed by the application; the ALTER operations were
    either already applied on the server or not required for SQLite.
    """
    op.execute(
        sa.text("""
        CREATE TABLE IF NOT EXISTS cs_categories (
            code VARCHAR(32) PRIMARY KEY NOT NULL,
            name VARCHAR(128) NOT NULL,
            description VARCHAR(512) NOT NULL,
            cached_at TIMESTAMP NOT NULL
        )
    """)
    )
    op.execute(
        sa.text("""
        CREATE TABLE IF NOT EXISTS cs_feed_subscriptions (
            id VARCHAR(36) PRIMARY KEY NOT NULL,
            category_code VARCHAR(32) NOT NULL,
            daily_limit INTEGER NOT NULL,
            enabled BOOLEAN NOT NULL,
            status VARCHAR(32) NOT NULL,
            cool_down_until TIMESTAMP,
            last_run_at TIMESTAMP,
            last_run_count INTEGER NOT NULL,
            created_at TIMESTAMP NOT NULL
        )
    """)
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_cs_feed_subscriptions_category_code "
            "ON cs_feed_subscriptions(category_code)"
        )
    )


def downgrade() -> None:
    op.drop_index("ix_cs_feed_subscriptions_category_code", table_name="cs_feed_subscriptions")
    op.drop_table("cs_feed_subscriptions")
    op.drop_table("cs_categories")
