"""add worker attempts and durable control

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("audit_events") as batch:
        batch.drop_constraint(op.f("ck_audit_events_action_values"), type_="check")
        batch.create_check_constraint(
            op.f("ck_audit_events_action_values"),
            "action IN ('login', 'submit', 'cancel', 'retry', 'pause', 'resume', "
            "'publish', 'withdraw', 'retention', 'update', 'delete', 'logout', "
            "'claim', 'start', 'complete', 'fail', 'recover')",
        )
    op.create_table(
        "worker_control",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "paused", sa.Boolean(create_constraint=True, name="paused_boolean"), nullable=False
        ),
        sa.Column("pause_reason", sa.String(length=64), nullable=True),
        sa.Column("fencing_counter", sa.BigInteger(), nullable=False),
        sa.Column("worker_id", sa.String(length=64), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "fencing_counter >= 0", name=op.f("ck_worker_control_fencing_nonnegative")
        ),
        sa.CheckConstraint("id = 1", name=op.f("ck_worker_control_singleton")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_worker_control")),
    )
    op.create_table(
        "job_attempts",
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("fencing_token", sa.BigInteger(), nullable=False),
        sa.Column("worker_id", sa.String(length=64), nullable=False),
        sa.Column(
            "phase",
            sa.Enum(
                "leased",
                "running",
                "completed",
                "failed",
                "cancelled",
                name="attempt_phase_values",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("leased_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "error_code",
            sa.Enum(
                "validation_error",
                "worker_lost",
                "engine_unavailable",
                "out_of_memory",
                "timeout",
                "cancelled",
                name="attempt_error_values",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=True,
        ),
        sa.Column("retry_after_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_sha256", sa.String(length=64), nullable=True),
        sa.CheckConstraint(
            "(phase = 'completed' AND result_sha256 IS NOT NULL AND error_code IS NULL) OR "
            "(phase != 'completed' AND result_sha256 IS NULL)",
            name=op.f("ck_job_attempts_result_shape"),
        ),
        sa.CheckConstraint(
            "(phase IN ('completed', 'failed', 'cancelled') AND finished_at IS NOT NULL) OR "
            "(phase IN ('leased', 'running') AND finished_at IS NULL)",
            name=op.f("ck_job_attempts_terminal_time"),
        ),
        sa.CheckConstraint(
            "phase != 'failed' OR error_code IS NOT NULL",
            name=op.f("ck_job_attempts_failure_error"),
        ),
        sa.CheckConstraint(
            "phase NOT IN ('running', 'completed') OR started_at IS NOT NULL",
            name=op.f("ck_job_attempts_start_required"),
        ),
        sa.CheckConstraint(
            "retry_after_at IS NULL OR (phase = 'failed' AND number = 1 "
            "AND error_code IN ('worker_lost', 'engine_unavailable'))",
            name=op.f("ck_job_attempts_retry_shape"),
        ),
        sa.CheckConstraint("deadline_at >= leased_at", name=op.f("ck_job_attempts_deadline_order")),
        sa.CheckConstraint("fencing_token > 0", name=op.f("ck_job_attempts_fencing_positive")),
        sa.CheckConstraint("number BETWEEN 1 AND 2", name=op.f("ck_job_attempts_number_bounds")),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name=op.f("fk_job_attempts_job_id_jobs"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("job_id", "number", name=op.f("pk_job_attempts")),
        sa.UniqueConstraint("fencing_token", name=op.f("uq_job_attempts_fencing_token")),
    )
    with op.batch_alter_table("job_attempts", schema=None) as batch_op:
        batch_op.create_index("ix_job_attempts_retry", ["retry_after_at"], unique=False)

    # Preserve fencing monotonicity for any leases created before this revision.
    op.execute(
        sa.text(
            "INSERT INTO worker_control (id, paused, fencing_counter) "
            "SELECT 1, false, coalesce(max(fencing_token), 0) FROM jobs"
        )
    )


def downgrade() -> None:
    # Deliberately refuse narrowing if retained worker audit events would be lost.
    with op.batch_alter_table("audit_events") as batch:
        batch.drop_constraint(op.f("ck_audit_events_action_values"), type_="check")
        batch.create_check_constraint(
            op.f("ck_audit_events_action_values"),
            "action IN ('login', 'submit', 'cancel', 'retry', 'pause', 'resume', "
            "'publish', 'withdraw', 'retention', 'update', 'delete', 'logout')",
        )
    with op.batch_alter_table("job_attempts", schema=None) as batch_op:
        batch_op.drop_index("ix_job_attempts_retry")

    op.drop_table("job_attempts")
    op.drop_table("worker_control")
