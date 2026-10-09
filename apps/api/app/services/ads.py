"""Advertising abstraction (Phase 6b): placements and eligibility, nothing more.

There is no ad network, no tracking pixel and no per-user targeting here. The
server only answers one question -- "may this viewer be shown a slot at this
placement?" -- so a client can reserve (or skip) space. Ads are off globally
unless `ADS_ENABLED=true`; Premium viewers (the `ad_free` entitlement) never
get a slot; live match surfaces are deliberately never eligible.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import settings
from app.services.billing.entitlements import AD_FREE

PLACEMENTS = ("home", "news", "match_centre")
"""`match_centre` is the finished/upcoming match page; a live match never shows ads."""


@dataclass(frozen=True)
class AdEligibility:
    placement: str
    eligible: bool
    reason: str


def eligibility(placement: str, entitlements: frozenset[str], *, live: bool = False) -> AdEligibility:
    if placement not in PLACEMENTS:
        return AdEligibility(placement, False, "unknown placement")
    if not settings.ads_enabled:
        return AdEligibility(placement, False, "ads are disabled")
    if AD_FREE in entitlements:
        return AdEligibility(placement, False, "ad-free plan")
    if live and placement == "match_centre":
        return AdEligibility(placement, False, "no ads during live matches")
    return AdEligibility(placement, True, "eligible")
