"""add API admission and session metadata

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("audit_events") as batch:
        batch.drop_constraint(op.f("ck_audit_events_action_values"), type_="check")
        batch.create_check_constraint(
            op.f("ck_audit_events_action_values"),
            "action IN ('login', 'submit', 'cancel', 'retry', 'pause', 'resume', "
            "'publish', 'withdraw', 'retention', 'update', 'delete', 'logout')",
        )
    op.create_table(
        "admin_sessions",
        sa.Column("token_sha256", sa.String(length=64), nullable=False),
        sa.Column("csrf_token", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("token_sha256", name=op.f("pk_admin_sessions")),
    )
    with op.batch_alter_table("admin_sessions", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_admin_sessions_expires_at"), ["expires_at"], unique=False
        )

    op.create_table(
        "api_control",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("login_window", sa.DateTime(timezone=True), nullable=False),
        sa.Column("failed_logins", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("mutation_window", sa.DateTime(timezone=True), nullable=False),
        sa.Column("mutation_count", sa.Integer(), nullable=False),
        sa.CheckConstraint("id = 1", name=op.f("ck_api_control_singleton")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_control")),
    )
    op.create_table(
        "api_requests",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("response", sa.JSON(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_api_requests")),
    )
    op.create_table(
        "experiment_metadata",
        sa.Column("experiment_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("version >= 1", name=op.f("ck_experiment_metadata_version_positive")),
        sa.ForeignKeyConstraint(
            ["experiment_id"],
            ["experiments.id"],
            name=op.f("fk_experiment_metadata_experiment_id_experiments"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("experiment_id", name=op.f("pk_experiment_metadata")),
    )
    op.bulk_insert(
        sa.table(
            "api_control",
            sa.column("id", sa.Integer),
            sa.column("revision", sa.BigInteger),
            sa.column("login_window", sa.DateTime),
            sa.column("failed_logins", sa.Integer),
            sa.column("mutation_window", sa.DateTime),
            sa.column("mutation_count", sa.Integer),
        ),
        [
            {
                "id": 1,
                "revision": 0,
                "login_window": datetime(1970, 1, 1),
                "failed_logins": 0,
                "mutation_window": datetime(1970, 1, 1),
                "mutation_count": 0,
            }
        ],
    )


def downgrade() -> None:
    # Refuse narrowing the audit enum if newer action records still exist.
    # Export/archive them explicitly first; never silently erase audit history.
    with op.batch_alter_table("audit_events") as batch:
        batch.drop_constraint(op.f("ck_audit_events_action_values"), type_="check")
        batch.create_check_constraint(
            op.f("ck_audit_events_action_values"),
            "action IN ('login', 'submit', 'cancel', 'retry', 'pause', 'resume', "
            "'publish', 'withdraw', 'retention')",
        )
    op.drop_table("experiment_metadata")
    op.drop_table("api_requests")
    op.drop_table("api_control")
    with op.batch_alter_table("admin_sessions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_admin_sessions_expires_at"))

    op.drop_table("admin_sessions")
