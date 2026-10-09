"""Stored predictions, their evaluation, and persisted insights (Phase 6).

Predictions are statistical estimates, never advice. They are stored with the
model version and the data they were derived from, and are locked once the
match kicks off, so they can later be compared honestly with what happened.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import InsightEntityType


class Prediction(Base):
    __tablename__ = "predictions"
    __table_args__ = (UniqueConstraint("match_id", "model_version", name="uq_predictions_match_model"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"), nullable=False, index=True)
    model_version: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    home_win: Mapped[float] = mapped_column(Float, nullable=False)
    draw: Mapped[float] = mapped_column(Float, nullable=False)
    away_win: Mapped[float] = mapped_column(Float, nullable=False)
    expected_home_goals: Mapped[float] = mapped_column(Float, nullable=False)
    expected_away_goals: Mapped[float] = mapped_column(Float, nullable=False)
    expected_total_goals: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[str] = mapped_column(String(8), nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    factors: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    data_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """Kickoff time of the newest finished match the estimate was computed from."""
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PredictionEvaluation(Base):
    __tablename__ = "prediction_evaluations"

    id: Mapped[int] = mapped_column(primary_key=True)
    prediction_id: Mapped[int] = mapped_column(
        ForeignKey("predictions.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    model_version: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    predicted_outcome: Mapped[str] = mapped_column(String(8), nullable=False)
    actual_outcome: Mapped[str] = mapped_column(String(8), nullable=False)
    correct: Mapped[bool] = mapped_column(nullable=False)
    brier_score: Mapped[float] = mapped_column(Float, nullable=False)
    home_win: Mapped[float] = mapped_column(Float, nullable=False)
    """Copied so calibration needs no join."""
    total_goals_error: Mapped[float] = mapped_column(Float, nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class InsightRecord(Base):
    """A generated insight with the data version it came from. Regenerated
    only when `source_data_version` changes, so the job is idempotent."""

    __tablename__ = "insights"
    __table_args__ = (
        UniqueConstraint("entity_type", "entity_id", "insight_type", name="uq_insights_entity_type"),
        Index("ix_insights_entity", "entity_type", "entity_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[InsightEntityType] = mapped_column(
        Enum(InsightEntityType, native_enum=False, validate_strings=True, length=16), nullable=False
    )
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    insight_type: Mapped[str] = mapped_column(String(48), nullable=False)
    text: Mapped[str] = mapped_column(String(300), nullable=False)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_data_version: Mapped[str] = mapped_column(String(64), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
