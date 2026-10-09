"""Article notifications (discovery §39/§40) -- deliberately conservative.

* **Opt-in**: every kind defaults to *off*. A user gets nothing until they
  switch a kind on (`/notifications/content-preferences`).
* **Relevant**: team/competition/match-report kinds additionally require the
  article to actually be linked to something the user follows. Transfer news
  needs a transfers category or tag; general news is only ever sent for
  *featured* articles.
* **Capped**: at most `content_notification_daily_cap` article pushes per user
  per UTC day, however many articles qualify.
* **Once**: `(user, article)` is unique in `content_notification_log`, and
  `articles.notified_at` is claimed atomically, so a republish, a retried task
  or a duplicate enqueue never notifies twice.
* **Phase 3 controls still apply**: delivery goes through the same device
  registry and senders as match notifications -- no device, no push. (Phase 3
  has per-event mute switches for *match* events; those are about match
  events and don't gate articles, which have their own preferences.)
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timezone

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.article import (
    Article,
    ArticleCategory,
    ArticleTag,
    article_competitions,
    article_matches,
    article_tag_links,
    article_teams,
)
from app.models.content_notification import ContentNotificationLog, ContentNotificationPreference
from app.models.device import Device
from app.models.enums import ArticleStatus, ContentNotificationKind
from app.models.favourite import FavouriteCompetition, FavouriteMatch, FavouriteTeam
from app.models.match import Match
from app.schemas.discovery import ContentPreferenceOut

logger = logging.getLogger(__name__)

# Article/news kinds are opt-in (off). The kinds that are about *your own* actions --
# replies to your comments and updates to your articles -- default on; poll
# results default off. Everything is switchable in /notifications/content-preferences.
CONTENT_DEFAULTS: dict[ContentNotificationKind, bool] = {
    **{kind: False for kind in ContentNotificationKind},
    ContentNotificationKind.COMMENT_REPLIES: True,
    ContentNotificationKind.EDITORIAL_UPDATES: True,
    # About your own account, so on by default; the rest of the Phase 6b kinds are opt-in.
    ContentNotificationKind.SUBSCRIPTION_EVENTS: True,
}


async def list_preferences(db: AsyncSession, user_id: int) -> list[ContentPreferenceOut]:
    rows = await db.execute(
        select(ContentNotificationPreference.kind, ContentNotificationPreference.enabled).where(
            ContentNotificationPreference.user_id == user_id
        )
    )
    explicit = {kind: enabled for kind, enabled in rows}
    return [
        ContentPreferenceOut(kind=kind, enabled=explicit.get(kind, CONTENT_DEFAULTS[kind]), default=CONTENT_DEFAULTS[kind])
        for kind in ContentNotificationKind
    ]


async def set_preference(db: AsyncSession, user_id: int, kind: ContentNotificationKind, enabled: bool) -> ContentPreferenceOut:
    await db.execute(
        pg_insert(ContentNotificationPreference)
        .values(user_id=user_id, kind=kind, enabled=enabled)
        .on_conflict_do_update(index_elements=["user_id", "kind"], set_={"enabled": enabled, "updated_at": func.now()})
    )
    await db.commit()
    return ContentPreferenceOut(kind=kind, enabled=enabled, default=CONTENT_DEFAULTS[kind])


def _opted_in(kind: ContentNotificationKind):
    return select(ContentNotificationPreference.user_id).where(
        ContentNotificationPreference.kind == kind, ContentNotificationPreference.enabled.is_(True)
    )


async def resolve_article_targets(db: AsyncSession, article: Article) -> set[int]:
    """Users who opted in to a kind that this article qualifies for, have a
    registered device, and are under today's cap. Does *not* claim anything."""
    team_ids = set((await db.execute(select(article_teams.c.team_id).where(article_teams.c.article_id == article.id))).scalars())
    competition_ids = set(
        (await db.execute(select(article_competitions.c.competition_id).where(article_competitions.c.article_id == article.id))).scalars()
    )
    category = await db.get(ArticleCategory, article.category_id) if article.category_id else None
    if category and category.competition_id:
        competition_ids.add(category.competition_id)
    match_ids = set((await db.execute(select(article_matches.c.match_id).where(article_matches.c.article_id == article.id))).scalars())
    tag_slugs = set(
        (
            await db.execute(
                select(ArticleTag.slug).join(article_tag_links, article_tag_links.c.tag_id == ArticleTag.id).where(
                    article_tag_links.c.article_id == article.id
                )
            )
        ).scalars()
    )

    users: set[int] = set()

    if team_ids:
        users |= set(
            (
                await db.execute(
                    select(FavouriteTeam.user_id).where(
                        FavouriteTeam.team_id.in_(team_ids),
                        FavouriteTeam.user_id.in_(_opted_in(ContentNotificationKind.TEAM_NEWS)),
                    )
                )
            ).scalars()
        )
    if competition_ids:
        users |= set(
            (
                await db.execute(
                    select(FavouriteCompetition.user_id).where(
                        FavouriteCompetition.competition_id.in_(competition_ids),
                        FavouriteCompetition.user_id.in_(_opted_in(ContentNotificationKind.COMPETITION_NEWS)),
                    )
                )
            ).scalars()
        )
    if match_ids and category is not None and category.slug == "match-reports":
        match_rows = (await db.execute(select(Match.home_team_id, Match.away_team_id, Match.competition_id).where(Match.id.in_(match_ids)))).all()
        report_teams = {t for home, away, _ in match_rows for t in (home, away)}
        report_competitions = {c for _, _, c in match_rows}
        reporters = set(
            (
                await db.execute(
                    select(FavouriteMatch.user_id).where(
                        FavouriteMatch.match_id.in_(match_ids),
                        FavouriteMatch.user_id.in_(_opted_in(ContentNotificationKind.MATCH_REPORTS)),
                    )
                )
            ).scalars()
        )
        reporters |= set(
            (
                await db.execute(
                    select(FavouriteTeam.user_id).where(
                        FavouriteTeam.team_id.in_(report_teams),
                        FavouriteTeam.user_id.in_(_opted_in(ContentNotificationKind.MATCH_REPORTS)),
                    )
                )
            ).scalars()
        )
        reporters |= set(
            (
                await db.execute(
                    select(FavouriteCompetition.user_id).where(
                        FavouriteCompetition.competition_id.in_(report_competitions),
                        FavouriteCompetition.user_id.in_(_opted_in(ContentNotificationKind.MATCH_REPORTS)),
                    )
                )
            ).scalars()
        )
        users |= reporters
    if (category is not None and category.slug == "transfers") or "transfer" in tag_slugs or "transfers" in tag_slugs:
        users |= set((await db.execute(_opted_in(ContentNotificationKind.TRANSFER_NEWS))).scalars())
    if article.is_featured:
        users |= set((await db.execute(_opted_in(ContentNotificationKind.GENERAL_NEWS))).scalars())

    if not users:
        return set()

    with_devices = set((await db.execute(select(Device.user_id).where(Device.user_id.in_(users)).distinct())).scalars())
    if not with_devices:
        return set()

    day_start = datetime.combine(datetime.now(timezone.utc).date(), time.min, tzinfo=timezone.utc)
    capped = set(
        (
            await db.execute(
                select(ContentNotificationLog.user_id)
                .where(ContentNotificationLog.user_id.in_(with_devices), ContentNotificationLog.created_at >= day_start)
                .group_by(ContentNotificationLog.user_id)
                .having(func.count() >= settings.content_notification_daily_cap)
            )
        ).scalars()
    )
    return with_devices - capped


async def claim_article(db: AsyncSession, article_id: int) -> Article | None:
    """Atomically mark the article as notified. Returns it only to the one
    caller that won the claim (and only if it is still published)."""
    claimed = await db.execute(
        update(Article)
        .where(Article.id == article_id, Article.notified_at.is_(None), Article.status == ArticleStatus.PUBLISHED)
        .values(notified_at=func.now())
        .returning(Article.id)
    )
    if claimed.scalar_one_or_none() is None:
        await db.rollback()
        return None
    await db.commit()
    return await db.get(Article, article_id)


async def claim_users(db: AsyncSession, article_id: int, user_ids: set[int]) -> set[int]:
    """Per-user dedup: only users without an existing log row come back."""
    if not user_ids:
        return set()
    result = await db.execute(
        pg_insert(ContentNotificationLog)
        .values([{"user_id": uid, "article_id": article_id} for uid in user_ids])
        .on_conflict_do_nothing(index_elements=["user_id", "article_id"])
        .returning(ContentNotificationLog.user_id)
    )
    claimed = {row[0] for row in result}
    await db.commit()
    return claimed


__all__ = [
    "CONTENT_DEFAULTS",
    "claim_article",
    "claim_users",
    "list_preferences",
    "resolve_article_targets",
    "set_preference",
]
