"""phase 7 operations hardening

Adds the operational tables (failed background jobs, administrative audit trail), the account-erasure
marker, the webhook ordering column, and a case-insensitive email index.

Expand-only: every change is additive (new tables, nullable columns, new indexes), so the previous
application version keeps working against the new schema and a rollback of the application needs no
database rollback. See docs/deployment/migrations.md.

Revision ID: c7e0a3f19d42
Revises: a7c3d9e1b402
Create Date: 2026-10-08 18:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c7e0a3f19d42"
down_revision: Union[str, None] = "a7c3d9e1b402"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "failed_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_name", sa.String(length=200), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=True),
        sa.Column("error_type", sa.String(length=120), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("classification", sa.String(length=24), nullable=False),
        sa.Column("retries", sa.Integer(), server_default="0", nullable=False),
        sa.Column("occurrences", sa.Integer(), server_default="1", nullable=False),
        sa.Column("entity", sa.String(length=120), nullable=True),
        sa.Column("args_summary", sa.String(length=500), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["resolved_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_failed_jobs_failed_at", "failed_jobs", ["failed_at"])
    op.create_index("ix_failed_jobs_task_failed", "failed_jobs", ["task_name", "failed_at"])

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("actor_label", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.String(length=300), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_log_created", "audit_log", ["created_at"])
    op.create_index("ix_audit_log_target", "audit_log", ["target_type", "target_id", "created_at"])
    op.create_index("ix_audit_log_actor", "audit_log", ["actor_id", "created_at"])
    op.create_index("ix_audit_log_action", "audit_log", ["action", "created_at"])

    op.add_column("users", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("subscriptions", sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=True))

    # -- indexes added from measured query patterns (docs/operations/database.md) ------------------------
    # Article search ORs title/excerpt/tag matches; the excerpt branch had no trigram index.
    op.create_index(
        "ix_articles_excerpt_trgm", "articles", ["excerpt"], postgresql_using="gin", postgresql_ops={"excerpt": "gin_trgm_ops"}
    )

    # Trending teams counts follows created in a short window; it scanned the whole table (22 ms -> 1.5 ms at 60k rows).
    op.create_index("ix_favourite_teams_created", "favourite_teams", ["created_at"])

    # Self-referencing ON DELETE SET NULL key with no index: each deleted token scanned the table (186 s -> 1.2 s).
    op.create_index("ix_refresh_tokens_replaced_by", "refresh_tokens", ["replaced_by_id"])

    # Email matching is case-insensitive from this release (lookups use lower(email)).
    op.create_index("ix_users_email_lower", "users", [sa.text("lower(email)")])


def downgrade() -> None:
    op.drop_index("ix_refresh_tokens_replaced_by", table_name="refresh_tokens")
    op.drop_index("ix_favourite_teams_created", table_name="favourite_teams")
    op.drop_index("ix_articles_excerpt_trgm", table_name="articles", postgresql_using="gin")
    op.drop_index("ix_users_email_lower", table_name="users")
    op.drop_column("subscriptions", "last_event_at")
    op.drop_column("users", "deleted_at")
    op.drop_table("audit_log")
    op.drop_table("failed_jobs")
