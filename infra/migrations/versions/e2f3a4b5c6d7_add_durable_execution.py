"""add durable execution tables

设计③ §1（Stage C2）：jobs / tasks / task_attempts / artifacts。
主键 UUIDv7 hex；Job 状态由子 Task 收敛；tasks↔artifacts FK 环用 use_alter。

Revision ID: e2f3a4b5c6d7
Revises: d1e5a9c3b7f2
Create Date: 2026-09-02
"""

from alembic import op
import sqlalchemy as sa

from packages.domain.enums import JobStatus, TaskAttemptStatus, TaskStatus

# revision identifiers, used by Alembic.
revision = "e2f3a4b5c6d7"
down_revision = "d1e5a9c3b7f2"
branch_labels = None
depends_on = None


def _enum(cls, name: str) -> sa.Enum:
    # SQLAlchemy Enum 默认存成员 name，与 ORM 模型行为一致
    return sa.Enum(*[m.name for m in cls], name=name)


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("status", _enum(JobStatus, "job_status"), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=True),
        sa.Column("priority", sa.Integer, nullable=False),
        sa.Column("budget", sa.JSON, nullable=False),
        sa.Column(
            "research_run_id",
            sa.String(32),
            sa.ForeignKey("research_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("progress", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("started_at", sa.DateTime, nullable=True),
        sa.Column("finished_at", sa.DateTime, nullable=True),
        sa.UniqueConstraint("idempotency_key", name="uq_jobs_idempotency"),
    )
    op.create_index("ix_jobs_kind_status", "jobs", ["kind", "status"])
    op.create_index("ix_jobs_status", "jobs", ["status"])

    op.create_table(
        "tasks",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "job_id", sa.String(32), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("capability", sa.String(64), nullable=False),
        sa.Column("handler_version", sa.Integer, nullable=False),
        sa.Column("input_schema_version", sa.Integer, nullable=False),
        sa.Column("status", _enum(TaskStatus, "task_status"), nullable=False),
        sa.Column("depends_on", sa.JSON, nullable=False),
        sa.Column("input_ref", sa.JSON, nullable=False),
        sa.Column(
            "output_artifact_id",
            sa.String(32),
            sa.ForeignKey(
                "artifacts.id", ondelete="SET NULL", use_alter=True, name="fk_tasks_output_artifact"
            ),
            nullable=True,
        ),
        sa.Column("idempotency_key", sa.String(128), nullable=True),
        sa.Column("priority", sa.Integer, nullable=False),
        sa.Column("resource_class", sa.String(32), nullable=False),
        sa.Column("timeout_s", sa.Integer, nullable=False),
        sa.Column("max_attempts", sa.Integer, nullable=False),
        sa.Column("attempt_count", sa.Integer, nullable=False),
        sa.Column("lease_token", sa.String(64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime, nullable=True),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("idempotency_key", name="uq_tasks_idempotency"),
    )
    op.create_index("ix_tasks_job_status", "tasks", ["job_id", "status"])
    op.create_index("ix_tasks_status_resource", "tasks", ["status", "resource_class"])
    op.create_index("ix_tasks_status", "tasks", ["status"])

    op.create_table(
        "task_attempts",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "task_id",
            sa.String(32),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("attempt_no", sa.Integer, nullable=False),
        sa.Column("executor_id", sa.String(64), nullable=False),
        sa.Column("fencing_token", sa.Integer, nullable=False),
        sa.Column("status", _enum(TaskAttemptStatus, "task_attempt_status"), nullable=False),
        sa.Column("error_class", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("log_ref", sa.JSON, nullable=False),
        sa.Column("cost_refs", sa.JSON, nullable=False),
        sa.Column("started_at", sa.DateTime, nullable=False),
        sa.Column("finished_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_task_attempts_task", "task_attempts", ["task_id", "attempt_no"])

    op.create_table(
        "artifacts",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "task_id",
            sa.String(32),
            sa.ForeignKey("tasks.id", ondelete="CASCADE", use_alter=True, name="fk_artifacts_task"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("uri", sa.String(1024), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("metadata_json", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_artifacts_task", "artifacts", ["task_id", "kind"])


def downgrade() -> None:
    op.drop_table("artifacts")
    op.drop_table("task_attempts")
    op.drop_table("tasks")
    op.drop_table("jobs")
