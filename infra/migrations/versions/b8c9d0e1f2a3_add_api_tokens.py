"""add api_tokens and device_auth_requests

Revision ID: b8c9d0e1f2a3
Revises: f6a7b8c9d0e1
Create Date: 2026-09-02 12:00:00.000000

目的：登录/权限系统升级 —— 数据库化 API 令牌（CLI / MCP / 外部 harness 用，
哈希存储 + read/write scope + 可吊销）与设备码授权请求（pm login 设备码流程）。

- api_tokens：DB 只存 SHA-256 哈希，明文仅创建时返回一次
- device_auth_requests：状态机 pending → approved/denied/expired，
  批准后关联生成的 ApiToken
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = "b8c9d0e1f2a3"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def _json_type() -> sa.types.TypeEngine:
    if op.get_bind().dialect.name == "postgresql":
        return JSONB()
    return sa.JSON()


def upgrade() -> None:
    op.create_table(
        "api_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("token_prefix", sa.String(16), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("scopes", _json_type(), nullable=False),
        sa.Column("created_by", sa.String(16), nullable=False, server_default="web"),
        sa.Column("device_request_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_api_tokens_token_hash", "api_tokens", ["token_hash"], unique=True)
    op.create_index("ix_api_tokens_created_at", "api_tokens", ["created_at"])

    op.create_table(
        "device_auth_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("device_code_hash", sa.String(64), nullable=False),
        sa.Column("user_code", sa.String(9), nullable=False),
        sa.Column("client_name", sa.String(128), nullable=False, server_default="pm-cli"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column(
            "api_token_id",
            sa.String(36),
            sa.ForeignKey("api_tokens.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_device_auth_requests_device_code_hash",
        "device_auth_requests",
        ["device_code_hash"],
        unique=True,
    )
    op.create_index("ix_device_auth_requests_user_code", "device_auth_requests", ["user_code"])
    op.create_index("ix_device_auth_requests_status", "device_auth_requests", ["status"])


def downgrade() -> None:
    op.drop_table("device_auth_requests")
    op.drop_table("api_tokens")
