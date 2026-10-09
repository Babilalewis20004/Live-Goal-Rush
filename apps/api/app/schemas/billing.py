from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class PlanOut(BaseModel):
    code: str
    name: str
    interval: str
    price_minor: int
    currency: str
    entitlements: list[str]


class FeatureOut(BaseModel):
    key: str
    label: str


class EntitlementsOut(BaseModel):
    entitlements: list[str]
    premium: bool
    features: list[FeatureOut]
    """Every Premium feature with whether the caller has it -- see `entitlements`."""


class SubscriptionOut(BaseModel):
    status: Literal["none", "incomplete", "active", "past_due", "cancelled", "expired"]
    plan: str | None = None
    entitlements: list[str] = Field(default_factory=list)
    current_period_end: datetime | None = None
    cancel_at_period_end: bool = False


class CheckoutRequest(BaseModel):
    plan_code: str = Field(min_length=1, max_length=32)


class CheckoutOut(BaseModel):
    url: str
    session_id: str


class WebhookAck(BaseModel):
    result: Literal["processed", "ignored", "duplicate"]


class AdPlacementOut(BaseModel):
    placement: str
    eligible: bool
    reason: str
