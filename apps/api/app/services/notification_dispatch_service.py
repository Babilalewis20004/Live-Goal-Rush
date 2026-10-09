"""Notification preference-matching + dedup (Phase 3 §12/§14/§15).

Called once per `RealtimeEvent`, never once per user -- see
`_qualifying_scopes_by_user`'s docstring for the query shape that keeps
this O(favouriters of this match), not O(all users).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.events.schemas import RealtimeEvent, RealtimeEventType
from app.models.enums import NotificationScope
from app.models.favourite import FavouriteCompetition, FavouriteMatch, FavouriteTeam
from app.models.match import Match
from app.models.notification import NotificationLog, NotificationPreference
from app.services.metrics import metrics

logger = logging.getLogger(__name__)

# Sensible defaults (Phase 3 §14): these fire for every follower unless
# explicitly muted. Everything else in RealtimeEventType (MATCH_UPDATED,
# SUBSTITUTION, SECOND_HALF_STARTED, MATCH_POSTPONED, MATCH_CANCELLED) is
# default-off -- mostly noise -- and only fires if a user has explicitly
# opted in via a `NotificationPreference(enabled=True)` row.
DEFAULT_ON_EVENT_TYPES = frozenset(
    {
        RealtimeEventType.MATCH_STARTED,
        RealtimeEventType.GOAL,
        RealtimeEventType.CARD,
        RealtimeEventType.HALF_TIME,
        RealtimeEventType.MATCH_FINISHED,
    }
)


@dataclass(frozen=True)
class NotificationTarget:
    user_id: int
    match_id: int
    event_type: RealtimeEventType
    dedup_key: str


_IN_CHUNK = 5000
_CLAIM_CHUNK = 2000


def _chunks(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _dedup_key(event: RealtimeEvent) -> str:
    """Event-scoped types (GOAL/CARD) key off the underlying `MatchEvent`
    id already present in `data["event"]["id"]` (see
    `change_detection.py::_event_added`) -- stable even if the same event
    is re-published. Status-transition types key off
    `{match_id}:{event_type}`, since change detection only ever fires one
    of those per actual transition."""
    match_event = event.data.get("event")
    if isinstance(match_event, dict) and "id" in match_event:
        return f"event:{match_event['id']}"
    return f"{event.match_id}:{event.type.value}"


async def _qualifying_scopes_by_user(
    db: AsyncSession, match: Match
) -> dict[int, set[tuple[NotificationScope, int | None]]]:
    """Three lookups, each an indexed FK equality filter against this
    single match's ids (home/away team, competition, the match itself) --
    O(favouriters of this match), never O(all users). Returns, per
    candidate user, every `(scope_type, scope_id)` they qualify under (a
    user following both teams in a derby gets both)."""
    by_user: dict[int, set[tuple[NotificationScope, int | None]]] = {}

    team_rows = await db.execute(
        select(FavouriteTeam.user_id, FavouriteTeam.team_id).where(
            FavouriteTeam.team_id.in_([match.home_team_id, match.away_team_id])
        )
    )
    for user_id, team_id in team_rows:
        by_user.setdefault(user_id, set()).add((NotificationScope.TEAM, team_id))

    competition_rows = await db.execute(
        select(FavouriteCompetition.user_id).where(
            FavouriteCompetition.competition_id == match.competition_id
        )
    )
    for (user_id,) in competition_rows:
        by_user.setdefault(user_id, set()).add((NotificationScope.COMPETITION, match.competition_id))

    match_rows = await db.execute(select(FavouriteMatch.user_id).where(FavouriteMatch.match_id == match.id))
    for (user_id,) in match_rows:
        by_user.setdefault(user_id, set()).add((NotificationScope.MATCH, match.id))

    return by_user


async def resolve_targets(db: AsyncSession, event: RealtimeEvent) -> list[NotificationTarget]:
    """Returns every user who should receive `event`, already deduplicated
    against `NotificationLog` -- callers never need to check for
    duplicates themselves. Empty when nobody favourited anything this
    match touches, or everyone who did has muted this event type.
    """
    match_id = int(event.match_id)
    match = await db.get(Match, match_id)
    if match is None:
        return []

    qualifying_by_user = await _qualifying_scopes_by_user(db, match)
    if not qualifying_by_user:
        return []

    candidate_ids = list(qualifying_by_user.keys())
    prefs: dict[tuple[int, NotificationScope, int | None], bool] = {}
    for chunk in _chunks(candidate_ids, _IN_CHUNK):
        pref_rows = await db.execute(
            select(NotificationPreference).where(
                NotificationPreference.user_id.in_(chunk),
                NotificationPreference.event_type == event.type,
            )
        )
        prefs.update({(p.user_id, p.scope_type, p.scope_id): p.enabled for p in pref_rows.scalars()})

    default_on = event.type in DEFAULT_ON_EVENT_TYPES
    notify_user_ids: list[int] = []
    for user_id, scopes in qualifying_by_user.items():
        # An explicit global mute for this event type wins outright, no
        # matter how many scopes would otherwise qualify the user.
        if prefs.get((user_id, NotificationScope.GLOBAL, None)) is False:
            continue
        effective = any(
            prefs.get((user_id, scope_type, scope_id), default_on) for scope_type, scope_id in scopes
        )
        if effective:
            notify_user_ids.append(user_id)

    if not notify_user_ids:
        return []

    dedup_key = _dedup_key(event)
    # One multi-row INSERT per chunk. A single statement carries 4 bind parameters per recipient and the driver
    # allows 32,767, so a team with more than ~8,000 followers made the whole dispatch fail -- precisely the
    # matches with the most fans. Each chunk is its own atomic claim; a retry after a partial failure re-claims
    # nothing already claimed (ON CONFLICT DO NOTHING), so no one is notified twice.
    claimed_ids: set[int] = set()
    for chunk in _chunks(notify_user_ids, _CLAIM_CHUNK):
        claim_stmt = (
            pg_insert(NotificationLog)
            .values(
                [
                    {"user_id": uid, "match_id": match_id, "event_type": event.type.value, "dedup_key": dedup_key}
                    for uid in chunk
                ]
            )
            .on_conflict_do_nothing(index_elements=["user_id", "dedup_key"])
            .returning(NotificationLog.user_id)
        )
        claimed_ids.update(row[0] for row in await db.execute(claim_stmt))
        await db.commit()

    deduplicated = len(notify_user_ids) - len(claimed_ids)
    if deduplicated:
        metrics.notification_deduplicated(deduplicated)
        logger.info(
            "Deduplicated %d notification(s) for match=%s dedup_key=%s", deduplicated, match_id, dedup_key
        )

    return [
        NotificationTarget(user_id=uid, match_id=match_id, event_type=event.type, dedup_key=dedup_key)
        for uid in notify_user_ids
        if uid in claimed_ids
    ]
