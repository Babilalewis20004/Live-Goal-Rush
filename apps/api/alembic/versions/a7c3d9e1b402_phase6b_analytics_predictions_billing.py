"""phase 6b analytics, predictions, insights, billing, moderation

Revision ID: a7c3d9e1b402
Revises: e6a1c0de0601
Create Date: 2026-10-08 09:00:00

Additive only: new tables, two nullable columns on users, and indexes that make
the analytics aggregates cheap. Nothing existing is altered or dropped.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "a7c3d9e1b402"
down_revision: Union[str, None] = "e6a1c0de0601"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _ts(name: str = "created_at") -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)


def upgrade() -> None:
    op.create_table(
        "predictions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("match_id", sa.Integer(), nullable=False),
        sa.Column("model_version", sa.String(length=32), nullable=False),
        sa.Column("home_win", sa.Float(), nullable=False),
        sa.Column("draw", sa.Float(), nullable=False),
        sa.Column("away_win", sa.Float(), nullable=False),
        sa.Column("expected_home_goals", sa.Float(), nullable=False),
        sa.Column("expected_away_goals", sa.Float(), nullable=False),
        sa.Column("expected_total_goals", sa.Float(), nullable=False),
        sa.Column("confidence", sa.String(length=8), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("factors", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("data_timestamp", sa.DateTime(timezone=True), nullable=True),
        _ts("generated_at"),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("match_id", "model_version", name="uq_predictions_match_model"),
    )
    op.create_index("ix_predictions_match_id", "predictions", ["match_id"])
    op.create_index("ix_predictions_model_version", "predictions", ["model_version"])

    op.create_table(
        "prediction_evaluations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("prediction_id", sa.Integer(), nullable=False),
        sa.Column("model_version", sa.String(length=32), nullable=False),
        sa.Column("predicted_outcome", sa.String(length=8), nullable=False),
        sa.Column("actual_outcome", sa.String(length=8), nullable=False),
        sa.Column("correct", sa.Boolean(), nullable=False),
        sa.Column("brier_score", sa.Float(), nullable=False),
        sa.Column("home_win", sa.Float(), nullable=False),
        sa.Column("total_goals_error", sa.Float(), nullable=False),
        _ts("evaluated_at"),
        sa.ForeignKeyConstraint(["prediction_id"], ["predictions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("prediction_id"),
    )
    op.create_index("ix_prediction_evaluations_model_version", "prediction_evaluations", ["model_version"])

    op.create_table(
        "insights",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("entity_type", sa.Enum("TEAM", "PLAYER", "MATCH", name="insightentitytype", native_enum=False, length=16), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("insight_type", sa.String(length=48), nullable=False),
        sa.Column("text", sa.String(length=300), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("source_data_version", sa.String(length=64), nullable=False),
        _ts("generated_at"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("entity_type", "entity_id", "insight_type", name="uq_insights_entity_type"),
    )
    op.create_index("ix_insights_entity", "insights", ["entity_type", "entity_id"])

    op.create_table(
        "subscription_plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("interval", sa.String(length=8), nullable=False),
        sa.Column("price_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("entitlements", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("provider_price_id", sa.String(length=128), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.Enum("INCOMPLETE", "ACTIVE", "PAST_DUE", "CANCELLED", "EXPIRED", name="subscriptionstatus", native_enum=False, length=16), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_subscription_id", sa.String(length=128), nullable=True),
        sa.Column("provider_customer_id", sa.String(length=128), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False),
        _ts(),
        _ts("updated_at"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plan_id"], ["subscription_plans.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "provider_subscription_id", name="uq_subscriptions_provider_sub"),
    )
    op.create_index("ix_subscriptions_user_status", "subscriptions", ["user_id", "status"])

    op.create_table(
        "entitlements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=48), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        _ts(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "key", name="uq_entitlements_user_key"),
    )
    op.create_index("ix_entitlements_user_id", "entitlements", ["user_id"])

    op.create_table(
        "payment_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("event_id", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.Enum("RECEIVED", "PROCESSED", "IGNORED", "FAILED", name="paymenteventstatus", native_enum=False, length=16), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error", sa.String(length=300), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        _ts("received_at"),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "event_id", name="uq_payment_events_provider_event"),
    )

    op.create_table(
        "profile_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("profile_user_id", sa.Integer(), nullable=False),
        sa.Column("reporter_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=200), nullable=False),
        sa.Column("status", sa.Enum("OPEN", "RESOLVED", "DISMISSED", name="reportstatus", native_enum=False, length=16), nullable=False),
        _ts(),
        sa.Column("resolved_by", sa.Integer(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["profile_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reporter_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resolved_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("profile_user_id", "reporter_id", name="uq_profile_reports_profile_reporter"),
    )
    op.create_index("ix_profile_reports_status", "profile_reports", ["status", "created_at"])

    op.add_column("users", sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("suspended_reason", sa.String(length=200), nullable=True))

    # Analytics read finished matches per team; these keep the aggregates index-driven.
    op.create_index("ix_match_statistics_team", "match_statistics", ["team_id"], if_not_exists=True)
    op.create_index("ix_player_match_statistics_team", "player_match_statistics", ["team_id"], if_not_exists=True)


def downgrade() -> None:
    op.drop_index("ix_player_match_statistics_team", table_name="player_match_statistics", if_exists=True)
    op.drop_index("ix_match_statistics_team", table_name="match_statistics", if_exists=True)
    op.drop_column("users", "suspended_reason")
    op.drop_column("users", "suspended_at")
    op.drop_index("ix_profile_reports_status", table_name="profile_reports")
    op.drop_table("profile_reports")
    op.drop_table("payment_events")
    op.drop_index("ix_entitlements_user_id", table_name="entitlements")
    op.drop_table("entitlements")
    op.drop_index("ix_subscriptions_user_status", table_name="subscriptions")
    op.drop_table("subscriptions")
    op.drop_table("subscription_plans")
    op.drop_index("ix_insights_entity", table_name="insights")
    op.drop_table("insights")
    op.drop_index("ix_prediction_evaluations_model_version", table_name="prediction_evaluations")
    op.drop_table("prediction_evaluations")
    op.drop_index("ix_predictions_model_version", table_name="predictions")
    op.drop_index("ix_predictions_match_id", table_name="predictions")
    op.drop_table("predictions")
