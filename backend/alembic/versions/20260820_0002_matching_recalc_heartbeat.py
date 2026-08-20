# Adds heartbeat tracking for recoverable candidate matching jobs.
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "20260820_0002"
down_revision: str | None = "20260820_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Add the heartbeat column and recovery lookup index when absent.
def upgrade() -> None:
    inspector = None if context.is_offline_mode() else sa.inspect(op.get_bind())
    columns = (
        set()
        if inspector is None
        else {
            column["name"]
            for column in inspector.get_columns("matching_recalc_jobs")
        }
    )
    if inspector is None or "heartbeat_at" not in columns:
        op.add_column(
            "matching_recalc_jobs",
            sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        )

    indexes = (
        set()
        if inspector is None
        else {
            index["name"]
            for index in inspector.get_indexes("matching_recalc_jobs")
        }
    )
    if inspector is None or "idx_matching_recalc_jobs_status_heartbeat" not in indexes:
        op.create_index(
            "idx_matching_recalc_jobs_status_heartbeat",
            "matching_recalc_jobs",
            ["status", "heartbeat_at"],
        )


# Remove heartbeat recovery metadata.
def downgrade() -> None:
    inspector = None if context.is_offline_mode() else sa.inspect(op.get_bind())
    indexes = (
        {"idx_matching_recalc_jobs_status_heartbeat"}
        if inspector is None
        else {
            index["name"]
            for index in inspector.get_indexes("matching_recalc_jobs")
        }
    )
    if "idx_matching_recalc_jobs_status_heartbeat" in indexes:
        op.drop_index(
            "idx_matching_recalc_jobs_status_heartbeat",
            table_name="matching_recalc_jobs",
        )

    columns = (
        {"heartbeat_at"}
        if inspector is None
        else {
            column["name"]
            for column in inspector.get_columns("matching_recalc_jobs")
        }
    )
    if "heartbeat_at" in columns:
        op.drop_column("matching_recalc_jobs", "heartbeat_at")
