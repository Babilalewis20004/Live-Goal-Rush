"""Payment-provider abstraction (Phase 6b).

The rest of the app talks to `BillingProvider` and `BillingEvent` only; nothing
outside this file knows what a given processor's payload looks like. Two
implementations:

* `TestBillingProvider` -- deterministic, no network. Used by the test suite and
  local development (events are posted to the webhook signed with the shared
  secret). Refused in production.
* `StripeBillingProvider` -- Stripe Checkout + webhooks over plain HTTPS. It is
  written against Stripe's documented API shapes but has NOT been exercised
  against a live Stripe account in this repository's tests.

Card data never reaches this service: checkout happens on the processor's hosted page.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

import httpx

from app.core.config import settings


class InvalidSignature(Exception):
    """The webhook body was not signed by the processor (or is a stale replay)."""


class ProviderError(Exception):
    """The processor refused or could not be reached."""


@dataclass(frozen=True)
class CheckoutSession:
    url: str
    session_id: str


@dataclass(frozen=True)
class BillingEvent:
    """A processor event normalised to what the app acts on.

    kinds: "subscription.activated", "subscription.renewed", "subscription.cancelled",
    "subscription.expired", "payment.failed". Anything else is kind "ignored".
    """

    event_id: str
    kind: str
    raw_type: str
    user_id: int | None = None
    plan_code: str | None = None
    subscription_id: str | None = None
    customer_id: str | None = None
    period_end: datetime | None = None
    cancel_at_period_end: bool = False
    amount_minor: int | None = None
    currency: str | None = None
    occurred_at: datetime | None = None
    """When the processor created the event. Deliveries are not ordered, so this -- not arrival time -- decides
    whether an event is older than what has already been applied to a subscription."""


class BillingProvider(Protocol):
    name: str

    async def create_checkout(self, *, user_id: int, email: str, plan_code: str, price_id: str | None) -> CheckoutSession: ...

    async def cancel_subscription(self, subscription_id: str) -> None: ...

    def parse_webhook(self, payload: bytes, signature_header: str | None) -> BillingEvent: ...


# -- signature scheme shared by both providers: `t=<unix>,v1=<hex hmac-sha256 of "t.body">` ----------


def sign_payload(payload: bytes, secret: str, timestamp: int | None = None) -> str:
    ts = int(time.time()) if timestamp is None else timestamp
    digest = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={digest}"


def verify_signature(payload: bytes, header: str | None, secret: str, tolerance: int, now: float | None = None) -> None:
    if not header or not secret:
        raise InvalidSignature("missing signature")
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    try:
        ts = int(parts["t"])
        given = parts["v1"]
    except (KeyError, ValueError):
        raise InvalidSignature("malformed signature") from None
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, given):
        raise InvalidSignature("signature mismatch")
    if abs((now if now is not None else time.time()) - ts) > tolerance:
        raise InvalidSignature("stale signature")


def _dt(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


class TestBillingProvider:
    """Body: {"id", "type", "data": {...}} with the normalised kinds as `type`."""

    __test__ = False  # not a pytest class
    name = "test"

    async def create_checkout(self, *, user_id: int, email: str, plan_code: str, price_id: str | None) -> CheckoutSession:
        session_id = f"cs_test_{user_id}_{plan_code}_{int(time.time())}"
        return CheckoutSession(url=f"https://billing.invalid/checkout/{session_id}", session_id=session_id)

    async def cancel_subscription(self, subscription_id: str) -> None:
        return None

    def parse_webhook(self, payload: bytes, signature_header: str | None) -> BillingEvent:
        verify_signature(payload, signature_header, settings.billing_webhook_secret, settings.billing_webhook_tolerance_seconds)
        try:
            body = json.loads(payload)
            data = body.get("data", {})
            return BillingEvent(
                event_id=str(body["id"]),
                kind=str(body["type"]),
                raw_type=str(body["type"]),
                user_id=int(data["user_id"]) if data.get("user_id") is not None else None,
                plan_code=data.get("plan_code"),
                subscription_id=data.get("subscription_id"),
                customer_id=data.get("customer_id"),
                period_end=_dt(data.get("period_end")),
                cancel_at_period_end=bool(data.get("cancel_at_period_end", False)),
                amount_minor=data.get("amount_minor"),
                currency=data.get("currency"),
                occurred_at=_dt(body.get("created")),
            )
        except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise InvalidSignature(f"malformed event: {exc}") from None


class StripeBillingProvider:
    name = "stripe"
    _API = "https://api.stripe.com/v1"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {settings.stripe_secret_key}"}

    async def create_checkout(self, *, user_id: int, email: str, plan_code: str, price_id: str | None) -> CheckoutSession:
        if not price_id:
            raise ProviderError("This plan has no Stripe price configured")
        form = {
            "mode": "subscription",
            "line_items[0][price]": price_id,
            "line_items[0][quantity]": "1",
            "success_url": settings.billing_success_url,
            "cancel_url": settings.billing_cancel_url,
            "client_reference_id": str(user_id),
            "customer_email": email,
            "metadata[user_id]": str(user_id),
            "metadata[plan_code]": plan_code,
            "subscription_data[metadata][user_id]": str(user_id),
            "subscription_data[metadata][plan_code]": plan_code,
        }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(f"{self._API}/checkout/sessions", data=form, headers=self._headers())
            r.raise_for_status()
            body = r.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError("Could not start checkout") from exc
        return CheckoutSession(url=body["url"], session_id=body["id"])

    async def cancel_subscription(self, subscription_id: str) -> None:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(
                    f"{self._API}/subscriptions/{subscription_id}",
                    data={"cancel_at_period_end": "true"},
                    headers=self._headers(),
                )
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError("Could not cancel the subscription") from exc

    def parse_webhook(self, payload: bytes, signature_header: str | None) -> BillingEvent:
        verify_signature(payload, signature_header, settings.billing_webhook_secret, settings.billing_webhook_tolerance_seconds)
        try:
            body = json.loads(payload)
            event_id, typ = str(body["id"]), str(body["type"])
            obj = body["data"]["object"]
        except (KeyError, ValueError, TypeError):
            raise InvalidSignature("malformed event") from None
        meta = obj.get("metadata") or {}
        user_id = meta.get("user_id") or obj.get("client_reference_id")
        common = dict(
            event_id=event_id,
            raw_type=typ,
            user_id=int(user_id) if user_id and str(user_id).isdigit() else None,
            plan_code=meta.get("plan_code"),
            occurred_at=_dt(body.get("created")),
        )
        if typ == "checkout.session.completed":
            return BillingEvent(kind="subscription.activated", subscription_id=obj.get("subscription"), customer_id=obj.get("customer"), **common)
        if typ == "customer.subscription.updated":
            status = obj.get("status")
            kind = "subscription.cancelled" if obj.get("cancel_at_period_end") else (
                "subscription.renewed" if status == "active" else "ignored"
            )
            return BillingEvent(
                kind=kind, subscription_id=obj.get("id"), customer_id=obj.get("customer"),
                period_end=_dt(obj.get("current_period_end")), cancel_at_period_end=bool(obj.get("cancel_at_period_end")), **common,
            )
        if typ == "customer.subscription.deleted":
            return BillingEvent(kind="subscription.expired", subscription_id=obj.get("id"), customer_id=obj.get("customer"), **common)
        if typ == "invoice.payment_failed":
            return BillingEvent(
                kind="payment.failed", subscription_id=obj.get("subscription"), customer_id=obj.get("customer"),
                amount_minor=obj.get("amount_due"), currency=obj.get("currency"), **common,
            )
        return BillingEvent(kind="ignored", **common)


def get_billing_provider() -> BillingProvider:
    name = settings.billing_provider
    if name == "stripe":
        # A forgeable webhook would let anyone grant themselves Premium: never accept the dev default in production.
        if settings.environment == "production" and (
            settings.billing_webhook_secret == "dev-only-webhook-secret" or len(settings.billing_webhook_secret) < 16
        ):
            raise ProviderError("BILLING_WEBHOOK_SECRET must be set to a long random value in production")
        return StripeBillingProvider()
    if name == "test":
        if settings.environment == "production":
            raise ProviderError("The test billing provider is disabled in production")
        return TestBillingProvider()
    raise ProviderError(f"Unknown billing provider {name!r}")
