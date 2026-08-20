# Adds versioned candidate matching configuration, jobs, and score storage.
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

from app.models.database import Base

revision: str = "20260820_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Create matching tables and additive JobPost columns.
def upgrade() -> None:
    bind = op.get_bind()
    inspector = None if context.is_offline_mode() else sa.inspect(bind)
    if inspector is not None and "job_posts" not in inspector.get_table_names():
        Base.metadata.create_all(bind=bind)
        return

    op.add_column(
        "job_posts",
        sa.Column(
            "matching_config_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "job_posts",
        sa.Column(
            "matching_schema_version",
            sa.String(length=20),
            server_default="1.0.0",
            nullable=False,
        ),
    )
    op.add_column(
        "job_posts",
        sa.Column("current_score_version", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column("job_posts", sa.Column("matching_status", sa.String(length=20), server_default="unscored", nullable=False))
    op.add_column("job_posts", sa.Column("last_scored_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("job_posts", sa.Column("last_matching_error_code", sa.String(length=64), nullable=True))
    op.create_check_constraint(
        "ck_job_posts_current_score_version_nonnegative",
        "job_posts",
        "current_score_version >= 0",
    )
    op.create_check_constraint(
        "ck_job_posts_matching_status",
        "job_posts",
        "matching_status IN ('unscored', 'pending', 'running', 'ready', 'stale', 'failed')",
    )
    op.create_index(
        "idx_job_posts_matching_status_updated_at",
        "job_posts",
        ["matching_status", "updated_at"],
    )

    # Adopt matching tables that an older startup-time create_all already created.
    if inspector is not None and "matching_recalc_jobs" in inspector.get_table_names():
        Base.metadata.tables["candidate_match_scores"].create(bind=bind, checkfirst=True)
        return

    op.create_table(
        "matching_recalc_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_post_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_score_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("trigger", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("config_hash", sa.String(length=64), nullable=False),
        sa.Column("algorithm_version", sa.String(length=64), nullable=False),
        sa.Column("candidates_total", sa.Integer(), server_default="0", nullable=False),
        sa.Column("candidates_processed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("candidates_failed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("requested_by", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "candidates_processed + candidates_failed <= candidates_total",
            name="ck_matching_recalc_jobs_counter_total",
        ),
        sa.CheckConstraint(
            "candidates_total >= 0 AND candidates_processed >= 0 AND candidates_failed >= 0",
            name="ck_matching_recalc_jobs_counters_nonnegative",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_matching_recalc_jobs_status",
        ),
        sa.CheckConstraint(
            "target_score_version > 0",
            name="ck_matching_recalc_jobs_target_version_positive",
        ),
        sa.CheckConstraint(
            "trigger IN ('manual', 'cv_uploaded', 'jd_updated', 'config_updated', 'retry')",
            name="ck_matching_recalc_jobs_trigger",
        ),
        sa.ForeignKeyConstraint(["job_post_id"], ["job_posts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_post_id",
            "idempotency_key",
            name="uq_matching_recalc_jobs_job_idempotency",
        ),
        sa.UniqueConstraint(
            "job_post_id",
            "target_score_version",
            name="uq_matching_recalc_jobs_job_version",
        ),
    )
    op.create_index(
        "idx_matching_recalc_jobs_job_created",
        "matching_recalc_jobs",
        ["job_post_id", "created_at"],
    )
    op.create_index(
        "idx_matching_recalc_jobs_status_created",
        "matching_recalc_jobs",
        ["status", "created_at"],
    )

    op.create_table(
        "candidate_match_scores",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_post_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resume_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recalc_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("score_version", sa.Integer(), nullable=False),
        sa.Column("algorithm_version", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=20), nullable=False),
        sa.Column("config_hash", sa.String(length=64), nullable=False),
        sa.Column("cv_file_hash", sa.String(length=64), nullable=False),
        sa.Column("eligibility_status", sa.String(length=20), nullable=False),
        sa.Column("total_score", sa.DECIMAL(precision=5, scale=2), nullable=False),
        sa.Column("fit_band", sa.String(length=20), nullable=False),
        sa.Column("evidence_confidence", sa.DECIMAL(precision=5, scale=2), nullable=False),
        sa.Column("recommendation_rank", sa.Integer(), nullable=True),
        sa.Column("dimension_results", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("eligibility_results", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("interview_questions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("config_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("input_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "top_strengths",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "key_gaps",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("is_published", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("scored_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "eligibility_status IN ('passed', 'needs_review', 'failed')",
            name="ck_candidate_match_scores_eligibility",
        ),
        sa.CheckConstraint(
            "evidence_confidence >= 0 AND evidence_confidence <= 100",
            name="ck_candidate_match_scores_confidence",
        ),
        sa.CheckConstraint(
            "fit_band IN ('high', 'medium', 'low')",
            name="ck_candidate_match_scores_fit_band",
        ),
        sa.CheckConstraint(
            "recommendation_rank IS NULL OR recommendation_rank > 0",
            name="ck_candidate_match_scores_rank_positive",
        ),
        sa.CheckConstraint(
            "total_score >= 0 AND total_score <= 100",
            name="ck_candidate_match_scores_total_score",
        ),
        sa.CheckConstraint(
            "score_version > 0",
            name="ck_candidate_match_scores_version_positive",
        ),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"]),
        sa.ForeignKeyConstraint(["job_post_id"], ["job_posts.id"]),
        sa.ForeignKeyConstraint(["recalc_job_id"], ["matching_recalc_jobs.id"]),
        sa.ForeignKeyConstraint(["resume_id"], ["resumes.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_post_id",
            "candidate_id",
            "score_version",
            name="uq_candidate_match_scores_job_candidate_version",
        ),
        sa.UniqueConstraint(
            "recalc_job_id",
            "candidate_id",
            name="uq_candidate_match_scores_recalc_candidate",
        ),
    )
    op.create_index(
        "idx_match_scores_candidate_latest",
        "candidate_match_scores",
        ["job_post_id", "candidate_id", "score_version"],
    )
    op.create_index(
        "idx_match_scores_job_version_rank",
        "candidate_match_scores",
        ["job_post_id", "score_version", "is_published", "recommendation_rank"],
    )
    op.create_index(
        "idx_match_scores_job_version_score",
        "candidate_match_scores",
        ["job_post_id", "score_version", "eligibility_status", sa.text("total_score DESC")],
    )


# Remove only the additive candidate matching schema.
def downgrade() -> None:
    inspector = None if context.is_offline_mode() else sa.inspect(op.get_bind())
    tables = (
        {"job_posts", "matching_recalc_jobs", "candidate_match_scores"}
        if inspector is None
        else set(inspector.get_table_names())
    )
    if "candidate_match_scores" in tables:
        op.drop_table("candidate_match_scores")
    if "matching_recalc_jobs" in tables:
        op.drop_table("matching_recalc_jobs")
    if "job_posts" not in tables:
        return
    columns = (
        {
            "matching_config_json",
            "matching_schema_version",
            "current_score_version",
            "matching_status",
            "last_scored_at",
            "last_matching_error_code",
        }
        if inspector is None
        else {column["name"] for column in inspector.get_columns("job_posts")}
    )
    if "matching_status" in columns:
        op.drop_index("idx_job_posts_matching_status_updated_at", table_name="job_posts")
        op.drop_constraint("ck_job_posts_matching_status", "job_posts", type_="check")
        op.drop_constraint(
            "ck_job_posts_current_score_version_nonnegative",
            "job_posts",
            type_="check",
        )
    for column_name in (
        "last_matching_error_code",
        "last_scored_at",
        "matching_status",
        "current_score_version",
        "matching_schema_version",
        "matching_config_json",
    ):
        if column_name in columns:
            op.drop_column("job_posts", column_name)
