"""Insights about *your* favourites (Phase 6b) and the notifications built on them.

Every sentence is a plain statement of a stored fact -- a fixture that exists, a
result that was recorded. Notifications reuse the Phase 6 pipeline
(`social_notification_service.deliver`): preferences are respected (all of these
kinds are opt-in except subscription events, which are about the user's own
account), each is sent at most once per user and subject, and nobody is
notified about their own action.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.community import Poll, PollVote
from app.models.competition import Competition
from app.models.enums import ContentNotificationKind, MatchStatus, PollStatus
from app.models.favourite import FavouriteCompetition, FavouriteMatch, FavouriteTeam
from app.models.match import Match
from app.services.notifications.service import NotificationService
from app.services.social_notification_service import deliver

logger = logging.getLogger(__name__)

MAX_PERSONAL_INSIGHTS = 8
RECENT_RESULT_DAYS = 3


class PersonalInsight(BaseModel):
    key: str
    text: str
    entity_type: str
    entity_id: int


def _day_bounds(now: datetime) -> tuple[datetime, datetime]:
    start = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


async def for_user(db: AsyncSession, user_id: int, now: datetime | None = None) -> list[PersonalInsight]:
    now = now or datetime.now(timezone.utc)
    start, end = _day_bounds(now)
    team_ids = set((await db.execute(select(FavouriteTeam.team_id).where(FavouriteTeam.user_id == user_id))).scalars())
    comp_ids = set(
        (await db.execute(select(FavouriteCompetition.competition_id).where(FavouriteCompetition.user_id == user_id))).scalars()
    )
    out: list[PersonalInsight] = []

    if team_ids:
        today = (
            await db.execute(
                select(Match)
                .where(
                    Match.kickoff_time >= start, Match.kickoff_time < end,
                    (Match.home_team_id.in_(team_ids)) | (Match.away_team_id.in_(team_ids)),
                )
                .options(selectinload(Match.home_team), selectinload(Match.away_team))
                .order_by(Match.kickoff_time)
            )
        ).scalars().all()
        for m in today:
            mine, other = (m.home_team, m.away_team) if m.home_team_id in team_ids else (m.away_team, m.home_team)
            if m.status in (MatchStatus.LIVE, MatchStatus.HALFTIME):
                text = f"{mine.name} are playing {other.name} right now ({m.home_score}-{m.away_score})."
            elif m.status == MatchStatus.FINISHED:
                text = f"{mine.name} v {other.name} finished {m.home_score}-{m.away_score} today."
            else:
                text = f"{mine.name} play {other.name} today at {m.kickoff_time:%H:%M} UTC."
            out.append(PersonalInsight(key="team_today", text=text, entity_type="match", entity_id=m.id))

        recent = (
            await db.execute(
                select(Match)
                .where(
                    Match.status == MatchStatus.FINISHED, Match.kickoff_time < start,
                    Match.kickoff_time >= start - timedelta(days=RECENT_RESULT_DAYS),
                    (Match.home_team_id.in_(team_ids)) | (Match.away_team_id.in_(team_ids)),
                )
                .options(selectinload(Match.home_team), selectinload(Match.away_team))
                .order_by(Match.kickoff_time.desc())
            )
        ).scalars().all()
        seen: set[int] = set()
        for m in recent:
            tid = m.home_team_id if m.home_team_id in team_ids else m.away_team_id
            if tid in seen:
                continue
            seen.add(tid)
            mine, other = (m.home_team, m.away_team) if tid == m.home_team_id else (m.away_team, m.home_team)
            gf, ga = (m.home_score, m.away_score) if tid == m.home_team_id else (m.away_score, m.home_score)
            verb = "won" if gf > ga else "drew" if gf == ga else "lost"
            out.append(PersonalInsight(key="team_last_result", text=f"{mine.name} {verb} {gf}-{ga} against {other.name} in their last match.", entity_type="match", entity_id=m.id))

    if comp_ids:
        rows = (
            await db.execute(
                select(Match.competition_id, Match.id)
                .where(Match.competition_id.in_(comp_ids), Match.kickoff_time >= start, Match.kickoff_time < end)
            )
        ).all()
        counts: dict[int, int] = {}
        for cid, _ in rows:
            counts[cid] = counts.get(cid, 0) + 1
        names = dict((await db.execute(select(Competition.id, Competition.name).where(Competition.id.in_(counts)))).all()) if counts else {}
        for cid, n in counts.items():
            out.append(
                PersonalInsight(
                    key="competition_today", text=f"{names.get(cid, 'A competition you follow')} has {n} match{'es' if n != 1 else ''} today.",
                    entity_type="competition", entity_id=cid,
                )
            )
    return out[:MAX_PERSONAL_INSIGHTS]


# -- notifications -----------------------------------------------------------------------------------


async def _followers(db: AsyncSession, match: Match) -> set[int]:
    by_team = (
        await db.execute(
            select(FavouriteTeam.user_id).where(FavouriteTeam.team_id.in_([match.home_team_id, match.away_team_id]))
        )
    ).scalars()
    by_match = (await db.execute(select(FavouriteMatch.user_id).where(FavouriteMatch.match_id == match.id))).scalars()
    return set(by_team) | set(by_match)


async def notify_prediction_available(db: AsyncSession, match_id: int, *, service: NotificationService | None = None) -> int:
    match = (
        await db.execute(select(Match).where(Match.id == match_id).options(selectinload(Match.home_team), selectinload(Match.away_team)))
    ).scalar_one_or_none()
    if match is None or match.status != MatchStatus.SCHEDULED:
        return 0
    return await deliver(
        db, await _followers(db, match), ContentNotificationKind.PREDICTION_AVAILABLE, f"prediction:{match_id}",
        "Match estimate available", f"{match.home_team.name} v {match.away_team.name}: a statistical estimate is ready.",
        {"type": "match", "id": match_id}, service=service,
    )


async def notify_matchday(db: AsyncSession, *, now: datetime | None = None, hours: int = 24, service: NotificationService | None = None) -> int:
    """Followers of a team playing within `hours`, once per match."""
    now = now or datetime.now(timezone.utc)
    matches = (
        await db.execute(
            select(Match)
            .where(Match.status == MatchStatus.SCHEDULED, Match.kickoff_time > now, Match.kickoff_time <= now + timedelta(hours=hours))
            .options(selectinload(Match.home_team), selectinload(Match.away_team))
        )
    ).scalars().all()
    sent = 0
    for m in matches:
        sent += await deliver(
            db, await _followers(db, m), ContentNotificationKind.TEAM_INSIGHTS, f"matchday:{m.id}", "Match coming up",
            f"{m.home_team.name} v {m.away_team.name} kicks off at {m.kickoff_time:%H:%M} UTC.",
            {"type": "match", "id": m.id}, service=service,
        )
    return sent


async def notify_polls_closing(db: AsyncSession, *, now: datetime | None = None, minutes: int = 60, service: NotificationService | None = None) -> int:
    """Nudge followers of the match who have not voted yet that a poll closes within `minutes`."""
    now = now or datetime.now(timezone.utc)
    polls = (
        await db.execute(
            select(Poll).where(
                Poll.status == PollStatus.OPEN, Poll.closes_at.is_not(None), Poll.closes_at > now,
                Poll.closes_at <= now + timedelta(minutes=minutes), Poll.match_id.is_not(None),
            )
        )
    ).scalars().all()
    sent = 0
    for poll in polls:
        match = (
            await db.execute(select(Match).where(Match.id == poll.match_id).options(selectinload(Match.home_team), selectinload(Match.away_team)))
        ).scalar_one_or_none()
        if match is None:
            continue
        voted = set((await db.execute(select(PollVote.user_id).where(PollVote.poll_id == poll.id))).scalars())
        audience = (await _followers(db, match)) - voted
        sent += await deliver(
            db, audience, ContentNotificationKind.POLL_CLOSING, f"pollclosing:{poll.id}", "Poll closing soon",
            poll.question, {"type": "poll", "id": poll.id}, service=service,
        )
    return sent


_SUBSCRIPTION_TEXT = {
    "subscription.activated": ("Premium is active", "Thanks for subscribing. Your Premium features are ready."),
    "subscription.cancelled": ("Subscription cancelled", "You keep Premium until the end of the period you paid for."),
    "subscription.expired": ("Premium has ended", "Your subscription has ended. Free features stay available."),
    "payment.failed": ("Payment problem", "We couldn't take your latest payment. Please update your payment method."),
}


async def notify_subscription_event(
    db: AsyncSession, user_id: int, kind: str, event_id: str, *, service: NotificationService | None = None
) -> int:
    text = _SUBSCRIPTION_TEXT.get(kind)
    if text is None:
        return 0
    return await deliver(
        db, {user_id}, ContentNotificationKind.SUBSCRIPTION_EVENTS, f"subscription:{event_id}", text[0], text[1],
        {"type": "premium", "id": 0}, service=service,
    )
