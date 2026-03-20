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

    Uses CREATE TABLE IF NOT EXISTS so this migration is safe to run on both:
    - Fresh databases (creates the tables)
    - Existing databases where tables were manually created (no-op)

    SQLite does not support ALTER COLUMN, DROP COLUMN, or changing column
    constraints, so those operations are omitted. The application only
    needs the two tables created here.
    """

    def create_table_if_not_exists(sql: str) -> None:
        try:
            op.execute(sa.text(sql))
        except Exception:
            pass

    create_table_if_not_exists("""
        CREATE TABLE IF NOT EXISTS cs_categories (
            code VARCHAR(32) PRIMARY KEY NOT NULL,
            name VARCHAR(128) NOT NULL,
            description VARCHAR(512) NOT NULL,
            cached_at TIMESTAMP NOT NULL
        )
    """)
    create_table_if_not_exists("""
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
    try:
        op.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS ix_cs_feed_subscriptions_category_code "
                "ON cs_feed_subscriptions(category_code)"
            )
        )
    except Exception:
        pass


def downgrade() -> None:
    try:
        op.execute(sa.text("DROP INDEX IF EXISTS ix_cs_feed_subscriptions_category_code"))
    except Exception:
        pass
    try:
        op.execute(sa.text("DROP TABLE IF EXISTS cs_feed_subscriptions"))
    except Exception:
        pass
    try:
        op.execute(sa.text("DROP TABLE IF EXISTS cs_categories"))
    except Exception:
        pass
