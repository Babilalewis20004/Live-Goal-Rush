"""Subscriptions, entitlements and payment events (Phase 6).

Provider-independent: nothing here names a payment processor. The processor's
identifiers are opaque strings, and no card data is ever stored -- checkout
happens on the processor's hosted page.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import PaymentEventStatus, SubscriptionStatus


class SubscriptionPlan(Base):
    __tablename__ = "subscription_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    interval: Mapped[str] = mapped_column(String(8), nullable=False)  # "month" | "year"
    price_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    """Price in the currency's minor unit (pence/cents)."""
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    entitlements: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    provider_price_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        Index("ix_subscriptions_user_status", "user_id", "status"),
        UniqueConstraint("provider", "provider_subscription_id", name="uq_subscriptions_provider_sub"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    plan_id: Mapped[int] = mapped_column(ForeignKey("subscription_plans.id"), nullable=False)
    status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(SubscriptionStatus, native_enum=False, validate_strings=True, length=16), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_subscription_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provider_customer_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """`occurred_at` of the newest processor event applied. Older events delivered later are ignored."""
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Entitlement(Base):
    """A grant independent of any subscription (admin comp, promotion). A
    user's effective entitlements are these plus those of an active plan."""

    __tablename__ = "entitlements"
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_entitlements_user_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(48), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PaymentEvent(Base):
    """Every webhook delivery, keyed by the processor's event id. The unique
    constraint is what makes processing idempotent: a redelivery hits it and is
    acknowledged without re-applying anything."""

    __tablename__ = "payment_events"
    __table_args__ = (UniqueConstraint("provider", "event_id", name="uq_payment_events_provider_event"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[PaymentEventStatus] = mapped_column(
        Enum(PaymentEventStatus, native_enum=False, validate_strings=True, length=16), nullable=False
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    """Sanitised event body (ids and amounts); never card data."""
    error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
