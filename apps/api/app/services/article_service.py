"""Football content: authoring, publishing and discovery (discovery §8-16, §28).

Reads that serve the public go through `_public()` -- published, not in the
future -- so a draft or archived article can never leak through any list,
detail, related, search or per-entity endpoint. Authoring is role-gated and
ownership-checked here, not only in the router.

Public reads are cached in Redis under a *version* (`RedisKeys.ARTICLES_VERSION`)
that every mutation bumps; one INCR invalidates every cached list, detail and
related entry at once.
"""

from __future__ import annotations

import difflib
import logging
import random
import string
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy import and_, case, delete, exists, func, or_, select, union, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.logging_config import log_event
from app.core.redis_client import RedisService
from app.core.redis_keys import RedisKeys
from app.models.article import (
    Article,
    ArticleGalleryItem,
    ArticleCategory,
    ArticleTag,
    article_competitions,
    article_matches,
    article_players,
    article_tag_links,
    article_teams,
)
from app.models.competition import Competition
from app.models.enums import ArticleStatus, RevisionAction, UserRole
from app.models.match import Match
from app.models.media import Media
from app.models.player import Player
from app.models.revision import ArticleRevision
from app.models.team import Team
from app.models.user import User
from app.schemas.article import (
    ArticleAdminOut,
    ArticleAdminSummary,
    ArticleDetail,
    ArticleIn,
    ArticleSummary,
    ArticleUpdate,
    CategoryIn,
    CategoryOut,
    TagOut,
)
from app.schemas.common import Page
from app.schemas.competition import CompetitionOut
from app.schemas.revision import DiffLine, FieldChange, RevisionDetail, RevisionDiff, RevisionOut
from app.schemas.match import MatchSummary
from app.schemas.player import PlayerOut
from app.schemas.team import TeamOut
from app.services.cache import CacheAside
from app.services import audit_service as audit
from app.services.football_service import NotFoundError, _MATCH_LOAD_OPTIONS
from app.services.html_sanitizer import html_to_blocks, html_to_text, is_safe_url, sanitize_html
from app.services.media_service import to_gallery_image, to_out
from app.services.metrics import metrics
from app.services.search_ranking import CONTAINS, FUZZY, escape_like, matches, normalize_query, tier
from app.services.slug import slugify

logger = logging.getLogger(__name__)

_SUMMARY_LOAD = (selectinload(Article.category), selectinload(Article.author), selectinload(Article.tags))
_RELATED_CANDIDATES = 200

# Related-article scoring weights (discovery §28) -- fixed and explainable.
W_COMPETITION, W_TEAM, W_PLAYER, W_MATCH, W_CATEGORY, W_TAG = 8.0, 6.0, 5.0, 4.0, 3.0, 2.0
_MAX_TAG_POINTS = 3
_RECENCY_POINTS = 2.0


class ArticleNotFoundError(NotFoundError):
    pass


class ArticlePermissionError(Exception):
    pass


class ArticleValidationError(Exception):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def can_author(user: User) -> bool:
    """May use the editorial tools at all."""
    return user.role in (UserRole.AUTHOR, UserRole.EDITOR, UserRole.ADMIN)


def is_reviewer(user: User) -> bool:
    """May review, publish, schedule, unpublish and archive."""
    return user.role in (UserRole.EDITOR, UserRole.ADMIN)


def can_edit(user: User, article: Article) -> bool:
    """May open this article in the editor. Everyone sees their own; an editor
    also sees what has left draft; nobody but an admin sees another person's draft."""
    if user.role == UserRole.ADMIN or article.author_id == user.id:
        return True
    return user.role == UserRole.EDITOR and article.status != ArticleStatus.DRAFT


class ArticleService:
    def __init__(self, db: AsyncSession, redis: RedisService | None = None) -> None:
        self.db = db
        self.redis = redis
        self.cache = CacheAside(redis) if redis is not None else None

    # -- cache version ---------------------------------------------------------

    async def _version(self) -> str:
        if self.redis is None:
            return "0"
        try:
            raw = await self.redis.raw.get(RedisKeys.ARTICLES_VERSION)
            return str(raw) if raw is not None else "0"
        except Exception:
            return "0"

    async def bump_version(self) -> None:
        if self.redis is None:
            return
        try:
            # The discovery home embeds article lists and keys itself on this
            # version too, so it is invalidated by the same increment.
            await self.redis.raw.incr(RedisKeys.ARTICLES_VERSION)
        except Exception:
            logger.warning("Could not bump the articles cache version", exc_info=True)

    async def _cached(self, name: str, model, loader):
        if self.cache is None:
            return await loader()
        key = RedisKeys.article_cache(await self._version(), name)
        return await self.cache.get_or_set_model(
            key, model, loader, ttl_seconds=settings.article_cache_ttl_seconds
        )

    # -- shaping ---------------------------------------------------------------

    @staticmethod
    def to_summary(article: Article, *, relation: str | None = None, reason: str | None = None) -> ArticleSummary:
        return ArticleSummary(
            id=article.id,
            slug=article.slug,
            title=article.title,
            excerpt=article.excerpt,
            featured_image_url=article.featured_image_url,
            featured_image_alt=article.featured_image_alt,
            published_at=article.published_at,
            category=CategoryOut.model_validate(article.category) if article.category else None,
            author_name=article.author.display_name if article.author else None,
            tags=[TagOut.model_validate(t) for t in sorted(article.tags, key=lambda t: t.name)],
            relation=relation,
            reason=reason,
        )

    async def _linked(self, article: Article) -> dict:
        teams = (
            await self.db.execute(
                select(Team).join(article_teams, article_teams.c.team_id == Team.id)
                .where(article_teams.c.article_id == article.id).order_by(Team.name)
            )
        ).scalars().all()
        players = (
            await self.db.execute(
                select(Player).join(article_players, article_players.c.player_id == Player.id)
                .where(article_players.c.article_id == article.id).order_by(Player.name)
            )
        ).scalars().all()
        competitions = (
            await self.db.execute(
                select(Competition).join(article_competitions, article_competitions.c.competition_id == Competition.id)
                .where(article_competitions.c.article_id == article.id).order_by(Competition.name)
            )
        ).scalars().all()
        found_matches = (
            await self.db.execute(
                select(Match).join(article_matches, article_matches.c.match_id == Match.id)
                .where(article_matches.c.article_id == article.id)
                .options(*_MATCH_LOAD_OPTIONS).order_by(Match.kickoff_time.desc())
            )
        ).scalars().all()
        return {
            "teams": [TeamOut.model_validate(t) for t in teams],
            "players": [PlayerOut.model_validate(p) for p in players],
            "competitions": [CompetitionOut.model_validate(c) for c in competitions],
            "matches": [MatchSummary.model_validate(m) for m in found_matches],
        }

    async def to_detail(self, article: Article) -> ArticleDetail:
        summary = self.to_summary(article).model_dump()
        return ArticleDetail(
            **summary,
            content=article.content,
            content_text=html_to_text(article.content),
            content_blocks=html_to_blocks(article.content),
            gallery=[to_gallery_image(g) for g in article.gallery],
            updated_at=article.updated_at,
            view_count=article.view_count,
            canonical_path=f"/article/{article.slug}",
            **await self._linked(article),
        )

    async def to_admin(self, article: Article) -> ArticleAdminOut:
        detail = (await self.to_detail(article)).model_dump()
        return ArticleAdminOut(
            **detail,
            status=article.status,
            is_featured=article.is_featured,
            author_id=article.author_id,
            publish_at=article.publish_at,
            unpublish_at=article.unpublish_at,
            review_note=article.review_note,
            featured_media_id=article.featured_media_id,
        )

    # -- public reads ------------------------------------------------------------

    @staticmethod
    def _public():
        return and_(
            Article.status == ArticleStatus.PUBLISHED,
            Article.published_at <= func.now(),
            or_(Article.unpublish_at.is_(None), Article.unpublish_at > func.now()),
        )

    @staticmethod
    def _has_team(team_ids: list[int]):
        return exists().where(article_teams.c.article_id == Article.id, article_teams.c.team_id.in_(team_ids))

    @staticmethod
    def _has_player(player_id: int):
        return exists().where(article_players.c.article_id == Article.id, article_players.c.player_id == player_id)

    @staticmethod
    def _has_match(match_id: int):
        return exists().where(article_matches.c.article_id == Article.id, article_matches.c.match_id == match_id)

    @staticmethod
    def _has_competition(competition_id: int):
        """Linked to the competition directly, or filed under a category that
        *is* that competition."""
        return or_(
            exists().where(
                article_competitions.c.article_id == Article.id,
                article_competitions.c.competition_id == competition_id,
            ),
            Article.category_id.in_(select(ArticleCategory.id).where(ArticleCategory.competition_id == competition_id)),
        )

    async def _page(
        self, where, order_by, page: int, page_size: int, relation_column=None, relation_labels=None, shape=None
    ):
        total = (await self.db.execute(select(func.count()).select_from(Article).where(where))).scalar_one()
        columns = [Article] + ([relation_column] if relation_column is not None else [])
        stmt = (
            select(*columns).where(where).order_by(*order_by).options(*_SUMMARY_LOAD)
            .offset((page - 1) * page_size).limit(page_size)
        )
        result = await self.db.execute(stmt)
        items = []
        if relation_column is not None:
            for article, rel in result.all():
                items.append(self.to_summary(article, relation=relation_labels[rel]))
        else:
            items = [(shape or self.to_summary)(a) for a in result.scalars().all()]
        page_type = Page[ArticleAdminSummary] if shape else Page[ArticleSummary]
        return page_type(items=items, total=total, page=page, page_size=page_size)

    async def list_public(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        category: str | None = None,
        tag: str | None = None,
        featured: bool | None = None,
        team_id: int | None = None,
        player_id: int | None = None,
        competition_id: int | None = None,
        match_id: int | None = None,
    ) -> Page[ArticleSummary]:
        async def load() -> Page[ArticleSummary]:
            clauses = [self._public()]
            if category:
                clauses.append(Article.category_id.in_(select(ArticleCategory.id).where(ArticleCategory.slug == category)))
            if tag:
                clauses.append(
                    exists().where(
                        article_tag_links.c.article_id == Article.id,
                        article_tag_links.c.tag_id.in_(select(ArticleTag.id).where(ArticleTag.slug == tag)),
                    )
                )
            if featured is not None:
                clauses.append(Article.is_featured.is_(featured))
            if team_id is not None:
                clauses.append(self._has_team([team_id]))
            if player_id is not None:
                clauses.append(self._has_player(player_id))
            if competition_id is not None:
                clauses.append(self._has_competition(competition_id))
            if match_id is not None:
                clauses.append(self._has_match(match_id))
            return await self._page(and_(*clauses), (Article.published_at.desc(), Article.id.desc()), page, page_size)

        name = f"list:{page}:{page_size}:{category}:{tag}:{featured}:{team_id}:{player_id}:{competition_id}:{match_id}"
        return await self._cached(name, Page[ArticleSummary], load)

    async def list_for_team(self, team_id: int, page: int, page_size: int) -> Page[ArticleSummary]:
        if await self.db.get(Team, team_id) is None:
            raise NotFoundError("team")
        return await self.list_public(team_id=team_id, page=page, page_size=page_size)

    async def list_for_player(self, player_id: int, page: int, page_size: int) -> Page[ArticleSummary]:
        if await self.db.get(Player, player_id) is None:
            raise NotFoundError("player")
        return await self.list_public(player_id=player_id, page=page, page_size=page_size)

    async def list_for_competition(self, competition_id: int, page: int, page_size: int) -> Page[ArticleSummary]:
        if await self.db.get(Competition, competition_id) is None:
            raise NotFoundError("competition")
        return await self.list_public(competition_id=competition_id, page=page, page_size=page_size)

    async def list_for_match(self, match_id: int, page: int, page_size: int) -> Page[ArticleSummary]:
        """Match page news: articles about *this match*, then its teams, then
        its competition -- never unrelated ones. Each carries how it relates."""
        match = await self.db.get(Match, match_id)
        if match is None:
            raise NotFoundError("match")

        async def load() -> Page[ArticleSummary]:
            by_match = self._has_match(match_id)
            by_team = self._has_team([match.home_team_id, match.away_team_id])
            by_competition = self._has_competition(match.competition_id)
            relation = case((by_match, 0), (by_team, 1), (by_competition, 2), else_=3).label("relation")
            return await self._page(
                and_(self._public(), or_(by_match, by_team, by_competition)),
                (relation, Article.published_at.desc(), Article.id.desc()),
                page,
                page_size,
                relation_column=relation,
                relation_labels={0: "match", 1: "team", 2: "competition"},
            )

        return await self._cached(f"match:{match_id}:{page}:{page_size}", Page[ArticleSummary], load)

    async def get_public(self, slug: str) -> ArticleDetail:
        async def load() -> ArticleDetail:
            article = await self.db.scalar(
                select(Article).where(Article.slug == slug, self._public()).options(*_SUMMARY_LOAD)
            )
            if article is None:
                raise ArticleNotFoundError(slug)
            return await self.to_detail(article)

        return await self._cached(f"detail:{slug}", ArticleDetail, load)

    async def public_id_for_slug(self, slug: str) -> int | None:
        return await self.db.scalar(select(Article.id).where(Article.slug == slug, self._public()))

    async def latest(self, limit: int, *, featured: bool | None = None) -> list[ArticleSummary]:
        page = await self.list_public(page=1, page_size=limit, featured=featured)
        return page.items

    async def by_ids(self, ids: list[int]) -> list[ArticleSummary]:
        """Published articles for `ids`, in the order given (anything not
        published is dropped -- this is how cached id lists stay safe)."""
        if not ids:
            return []
        articles = {
            a.id: a
            for a in (
                await self.db.execute(select(Article).where(Article.id.in_(ids), self._public()).options(*_SUMMARY_LOAD))
            ).scalars()
        }
        return [self.to_summary(articles[i]) for i in ids if i in articles]

    # -- categories & tags -----------------------------------------------------

    async def list_categories(self) -> list[CategoryOut]:
        rows = (await self.db.execute(select(ArticleCategory).order_by(ArticleCategory.name))).scalars().all()
        return [CategoryOut.model_validate(r) for r in rows]

    async def create_category(self, payload: CategoryIn) -> CategoryOut:
        slug = slugify(payload.slug or payload.name, max_length=80)
        if not slug:
            raise ArticleValidationError("Category needs a name with letters or numbers")
        if payload.competition_id is not None and await self.db.get(Competition, payload.competition_id) is None:
            raise ArticleValidationError("Unknown competition")
        if await self.db.scalar(select(ArticleCategory.id).where(ArticleCategory.slug == slug)):
            raise ArticleValidationError("A category with that name already exists")
        category = ArticleCategory(slug=slug, name=payload.name.strip(), competition_id=payload.competition_id)
        self.db.add(category)
        await self.db.commit()
        await self.bump_version()
        return CategoryOut.model_validate(category)

    async def popular_tags(self, limit: int = 20) -> list[TagOut]:
        rows = await self.db.execute(
            select(ArticleTag)
            .join(article_tag_links, article_tag_links.c.tag_id == ArticleTag.id)
            .join(Article, Article.id == article_tag_links.c.article_id)
            .where(self._public())
            .group_by(ArticleTag.id)
            .order_by(func.count().desc(), ArticleTag.name)
            .limit(limit)
        )
        return [TagOut.model_validate(t) for t in rows.scalars()]

    async def _resolve_tags(self, names: list[str]) -> list[ArticleTag]:
        wanted: dict[str, str] = {}
        for name in names:
            clean = " ".join(name.split())
            slug = slugify(clean, max_length=80)
            if slug and slug not in wanted:
                wanted[slug] = clean[:80]
        if not wanted:
            return []
        await self.db.execute(
            pg_insert(ArticleTag).values([{"slug": s, "name": n} for s, n in wanted.items()]).on_conflict_do_nothing(index_elements=["slug"])
        )
        rows = await self.db.execute(select(ArticleTag).where(ArticleTag.slug.in_(wanted)))
        return list(rows.scalars())

    # -- related -----------------------------------------------------------------

    async def related(self, slug: str, limit: int = 4) -> list[ArticleSummary]:
        """Deterministic scoring: shared competition 8, team 6, player 5,
        match 4, same category 3, shared tags 2 each (max 3), plus up to 2 for
        recency. Every suggestion says why. Candidates are bounded, never the
        whole table."""

        async def load() -> list[ArticleSummary]:
            source = await self.db.scalar(select(Article).where(Article.slug == slug, self._public()))
            if source is None:
                raise ArticleNotFoundError(slug)
            return await self._compute_related(source, limit)

        if self.cache is None:
            return await load()
        key = RedisKeys.article_cache(await self._version(), f"related:{slug}:{limit}")
        return await self.cache.get_or_set_list(key, ArticleSummary, load, ttl_seconds=settings.article_cache_ttl_seconds)

    async def _link_ids(self, table, column, article_ids: list[int]) -> dict[int, set[int]]:
        out: dict[int, set[int]] = {}
        rows = await self.db.execute(select(table.c.article_id, table.c[column]).where(table.c.article_id.in_(article_ids)))
        for article_id, entity_id in rows:
            out.setdefault(article_id, set()).add(entity_id)
        return out

    async def _compute_related(self, source: Article, limit: int) -> list[ArticleSummary]:
        sid = [source.id]
        s_teams = (await self._link_ids(article_teams, "team_id", sid)).get(source.id, set())
        s_players = (await self._link_ids(article_players, "player_id", sid)).get(source.id, set())
        s_comps = (await self._link_ids(article_competitions, "competition_id", sid)).get(source.id, set())
        s_matches = (await self._link_ids(article_matches, "match_id", sid)).get(source.id, set())
        s_tags = (await self._link_ids(article_tag_links, "tag_id", sid)).get(source.id, set())
        if source.category_id:
            category_comp = await self.db.scalar(
                select(ArticleCategory.competition_id).where(ArticleCategory.id == source.category_id)
            )
            if category_comp:
                s_comps = s_comps | {category_comp}

        shared = []
        if s_teams:
            shared.append(self._has_team(list(s_teams)))
        if s_players:
            shared.append(exists().where(article_players.c.article_id == Article.id, article_players.c.player_id.in_(s_players)))
        if s_comps:
            shared.append(
                exists().where(article_competitions.c.article_id == Article.id, article_competitions.c.competition_id.in_(s_comps))
            )
        if s_matches:
            shared.append(exists().where(article_matches.c.article_id == Article.id, article_matches.c.match_id.in_(s_matches)))
        if s_tags:
            shared.append(exists().where(article_tag_links.c.article_id == Article.id, article_tag_links.c.tag_id.in_(s_tags)))
        if source.category_id:
            shared.append(Article.category_id == source.category_id)
        if not shared:
            return []

        candidates = list(
            (
                await self.db.execute(
                    select(Article)
                    .where(self._public(), Article.id != source.id, or_(*shared))
                    .order_by(Article.published_at.desc())
                    .limit(_RELATED_CANDIDATES)
                    .options(*_SUMMARY_LOAD)
                )
            ).scalars()
        )
        if not candidates:
            return []
        ids = [c.id for c in candidates]
        c_teams = await self._link_ids(article_teams, "team_id", ids)
        c_players = await self._link_ids(article_players, "player_id", ids)
        c_comps = await self._link_ids(article_competitions, "competition_id", ids)
        c_matches = await self._link_ids(article_matches, "match_id", ids)
        c_tags = await self._link_ids(article_tag_links, "tag_id", ids)
        category_comps: dict[int, int | None] = {
            cid: comp
            for cid, comp in await self.db.execute(
                select(ArticleCategory.id, ArticleCategory.competition_id).where(
                    ArticleCategory.id.in_({c.category_id for c in candidates if c.category_id})
                )
            )
        }

        now = _utcnow()
        scored: list[tuple[float, datetime, Article, str]] = []
        for c in candidates:
            comps = set(c_comps.get(c.id, set()))
            if c.category_id and category_comps.get(c.category_id):
                comps.add(category_comps[c.category_id])
            reasons: list[str] = []
            score = 0.0
            if comps & s_comps:
                score += W_COMPETITION
                reasons.append("same competition")
            if c_teams.get(c.id, set()) & s_teams:
                score += W_TEAM
                reasons.append("same team")
            if c_players.get(c.id, set()) & s_players:
                score += W_PLAYER
                reasons.append("same player")
            if c_matches.get(c.id, set()) & s_matches:
                score += W_MATCH
                reasons.append("same match")
            if source.category_id and c.category_id == source.category_id:
                score += W_CATEGORY
                reasons.append("same category")
            shared_tags = len(c_tags.get(c.id, set()) & s_tags)
            if shared_tags:
                score += W_TAG * min(shared_tags, _MAX_TAG_POINTS)
                reasons.append("shared tags")
            age_days = max((now - c.published_at).total_seconds() / 86400.0, 0.0)
            score += _RECENCY_POINTS / (1.0 + age_days / 7.0)
            scored.append((score, c.published_at, c, ", ".join(reasons) or "recent"))

        scored.sort(key=lambda t: (-t[0], -t[1].timestamp(), -t[2].id))
        return [self.to_summary(c, reason=reason.capitalize()) for _, _, c, reason in scored[:limit]]

    # -- search -------------------------------------------------------------------

    async def search(self, query: str, limit: int = 10) -> list[ArticleSummary]:
        query = normalize_query(query)
        if not query:
            return []
        escaped = escape_like(query)
        excerpt_hit = Article.excerpt.ilike(f"%{escaped}%", escape="\\")
        tag_hit = exists().where(
            article_tag_links.c.article_id == Article.id,
            article_tag_links.c.tag_id.in_(select(ArticleTag.id).where(ArticleTag.name.ilike(f"%{escaped}%", escape="\\"))),
        )
        # Candidate ids come from one index-backed query per kind of hit and are merged with UNION. The previous
        # single query OR-ed the three conditions together, which the planner can only run by reading every
        # published article and filtering it (measured: 80 ms at 3k articles, growing linearly).
        candidates = [select(Article.id).where(matches(Article.title, query))]
        if len(query) >= 3:
            candidates.append(select(Article.id).where(excerpt_hit))
            candidates.append(
                select(article_tag_links.c.article_id).where(
                    article_tag_links.c.tag_id.in_(select(ArticleTag.id).where(ArticleTag.name.ilike(f"%{escaped}%", escape="\\")))
                )
            )
        candidate_ids = union(*candidates).subquery()
        rank = func.least(tier(Article.title, query), case((excerpt_hit | tag_hit, CONTAINS), else_=FUZZY))
        rows = await self.db.execute(
            select(Article)
            .where(self._public(), Article.id.in_(select(candidate_ids.c.id)))
            .order_by(rank, Article.published_at.desc())
            .limit(limit)
            .options(*_SUMMARY_LOAD)
        )
        return [self.to_summary(a) for a in rows.scalars()]

    async def suggest(self, query: str, limit: int = 3) -> list[tuple[int, str, str]]:
        """(id, slug, title) of published articles whose title starts with, or
        contains, `query` -- for the suggestions dropdown."""
        escaped = escape_like(normalize_query(query))
        if not escaped:
            return []
        rows = await self.db.execute(
            select(Article.id, Article.slug, Article.title)
            .where(self._public(), Article.title.ilike(f"%{escaped}%", escape="\\"))
            .order_by(tier(Article.title, query), Article.published_at.desc())
            .limit(limit)
        )
        return [(i, s, t) for i, s, t in rows]

    # -- authoring ---------------------------------------------------------------

    def _check_image(self, url: str | None) -> str | None:
        if not url:
            return None
        url = url.strip()
        if not is_safe_url(url, schemes=frozenset({"http", "https"}), allow_relative=False):
            raise ArticleValidationError("Featured image must be an http(s) URL")
        host = (urlparse(url).hostname or "").lower()
        allowed = settings.article_image_host_list
        if allowed and not any(host == h or host.endswith("." + h) for h in allowed):
            raise ArticleValidationError("Featured image host is not allowed")
        return url

    async def _existing(self, model, ids: list[int], label: str) -> list[int]:
        unique = list(dict.fromkeys(ids))
        if not unique:
            return []
        found = set((await self.db.execute(select(model.id).where(model.id.in_(unique)))).scalars())
        missing = [i for i in unique if i not in found]
        if missing:
            raise ArticleValidationError(f"Unknown {label} ids: {missing}")
        return unique

    async def _unique_slug(self, title: str) -> str:
        base = slugify(title, max_length=120) or "article"
        slug, n = base, 1
        while await self.db.scalar(select(Article.id).where(Article.slug == slug)):
            n += 1
            slug = f"{base}-{n}"
        return slug

    async def _set_links(self, article: Article, data: dict) -> None:
        for table, column, key, model, label in (
            (article_teams, "team_id", "team_ids", Team, "team"),
            (article_players, "player_id", "player_ids", Player, "player"),
            (article_competitions, "competition_id", "competition_ids", Competition, "competition"),
            (article_matches, "match_id", "match_ids", Match, "match"),
        ):
            ids = data.get(key)
            if ids is None:
                continue
            valid = await self._existing(model, ids, label)
            await self.db.execute(delete(table).where(table.c.article_id == article.id))
            if valid:
                await self.db.execute(table.insert(), [{"article_id": article.id, column: i} for i in valid])

    @staticmethod
    def _auto_excerpt(content_html: str) -> str:
        text = " ".join(html_to_text(content_html).split())
        if len(text) <= 200:
            return text
        return text[:200].rsplit(" ", 1)[0].rstrip(",.;:") + "…"

    async def _check_category(self, category_id: int | None) -> None:
        if category_id is not None and await self.db.get(ArticleCategory, category_id) is None:
            raise ArticleValidationError("Unknown category")

    # -- workflow ------------------------------------------------------------------
    #
    #   AUTHOR  writes drafts, submits them for review, withdraws them
    #   EDITOR  reviews: approve (publish now / schedule) or reject (back to draft
    #           with a note); also publishes, schedules, unpublishes, archives
    #   ADMIN   everything
    #
    # An author can never publish; an editor never sees another person's draft.

    @staticmethod
    def _aware(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    def _validate_schedule(self, publish_at: datetime | None, unpublish_at: datetime | None, *, need_publish_at: bool) -> None:
        now = _utcnow()
        if need_publish_at:
            if publish_at is None:
                raise ArticleValidationError("Choose when to publish this article")
            if publish_at <= now:
                raise ArticleValidationError("The publish time must be in the future")
        if unpublish_at is not None and unpublish_at <= (publish_at or now):
            raise ArticleValidationError("The unpublish time must be after the publish time")

    def _transition(
        self,
        user: User,
        article: Article,
        target: ArticleStatus,
        *,
        publish_at: datetime | None = None,
        unpublish_at: datetime | None = None,
        note: str | None = None,
    ) -> bool:
        """Apply a status change if `user` may make it. Returns True when this is a
        move *into* PUBLISHED (the caller then notifies)."""
        current = article.status
        reviewer = is_reviewer(user)
        owner = article.author_id == user.id
        publish_at, unpublish_at = self._aware(publish_at), self._aware(unpublish_at)
        has_content = bool(html_to_text(article.content).strip())

        if target == current and target != ArticleStatus.SCHEDULED:
            return False

        if target == ArticleStatus.IN_REVIEW:
            if current != ArticleStatus.DRAFT:
                raise ArticleValidationError("Only drafts can be submitted for review")
            if not (owner or reviewer):
                raise ArticlePermissionError("You can only submit your own articles")
            if not has_content:
                raise ArticleValidationError("Add some content before submitting for review")
            article.review_note = None

        elif target == ArticleStatus.DRAFT:
            if current == ArticleStatus.IN_REVIEW:
                if not (owner or reviewer):
                    raise ArticlePermissionError("Only the author or an editor can do this")
                article.review_note = (note or "").strip()[:500] or None if reviewer and not owner else None
            elif not reviewer:
                raise ArticlePermissionError("Only editors can unpublish an article")
            article.publish_at = None

        elif target in (ArticleStatus.PUBLISHED, ArticleStatus.SCHEDULED, ArticleStatus.ARCHIVED):
            if not reviewer:
                raise ArticlePermissionError("Only editors can publish, schedule or archive articles")
            if target == ArticleStatus.PUBLISHED:
                if not has_content:
                    raise ArticleValidationError("An article needs content before it can be published")
                self._validate_schedule(None, unpublish_at, need_publish_at=False)
                if article.published_at is None:
                    article.published_at = _utcnow()
                article.publish_at = None
                if unpublish_at is not None:
                    article.unpublish_at = unpublish_at
                article.review_note = None
            elif target == ArticleStatus.SCHEDULED:
                if not has_content:
                    raise ArticleValidationError("An article needs content before it can be scheduled")
                when = publish_at or article.publish_at
                until = unpublish_at if unpublish_at is not None else article.unpublish_at
                self._validate_schedule(when, until, need_publish_at=True)
                article.publish_at, article.unpublish_at = when, until
                article.review_note = None

        article.status = target
        return target == ArticleStatus.PUBLISHED and current != ArticleStatus.PUBLISHED

    def _check_write(self, user: User, article: Article) -> None:
        if is_reviewer(user):
            return
        if article.author_id != user.id:
            raise ArticlePermissionError("You can only edit your own articles")
        if article.status != ArticleStatus.DRAFT:
            raise ArticlePermissionError("You can edit a draft. Withdraw the article from review to change it.")

    # -- media -----------------------------------------------------------------------

    async def _apply_media(self, user: User, article: Article, data: dict) -> None:
        if data.get("featured_media_id") is not None:
            media = await self.db.scalar(select(Media).where(Media.id == data["featured_media_id"]))
            if media is None:
                raise ArticleValidationError("Unknown featured image")
            if not is_reviewer(user) and media.uploader_id != user.id:
                raise ArticlePermissionError("You can only use your own uploads")
            article.featured_media_id = media.id
            article.featured_image_url = to_out(media).url
            article.featured_image_alt = (data.get("featured_image_alt") or media.alt_text or article.title)[:200]
        elif "featured_media_id" in data and data["featured_media_id"] is None and article.featured_media_id is not None:
            article.featured_media_id = None
            if "featured_image_url" not in data:
                article.featured_image_url = None
                article.featured_image_alt = None
        if data.get("gallery") is not None:
            wanted = data["gallery"]
            ids = [g["media_id"] for g in wanted]
            media_rows = {m.id: m for m in (await self.db.execute(select(Media).where(Media.id.in_(ids)))).scalars()}
            missing = [i for i in ids if i not in media_rows]
            if missing:
                raise ArticleValidationError(f"Unknown gallery images: {missing}")
            if not is_reviewer(user) and any(m.uploader_id != user.id for m in media_rows.values()):
                raise ArticlePermissionError("You can only use your own uploads")
            await self.db.execute(delete(ArticleGalleryItem).where(ArticleGalleryItem.article_id == article.id))
            seen: set[int] = set()
            for position, item in enumerate(wanted):
                if item["media_id"] in seen:
                    continue
                seen.add(item["media_id"])
                self.db.add(ArticleGalleryItem(article_id=article.id, media_id=item["media_id"], position=position, caption=item.get("caption", "")))
            await self.db.flush()
            await self.db.refresh(article, attribute_names=["gallery"])

    # -- revisions ---------------------------------------------------------------------

    async def _snapshot(self, article: Article) -> dict:
        async def ids(table, column) -> list[int]:
            rows = await self.db.execute(select(table.c[column]).where(table.c.article_id == article.id))
            return sorted(r[0] for r in rows)

        gallery = (
            await self.db.execute(
                select(ArticleGalleryItem.media_id, ArticleGalleryItem.caption)
                .where(ArticleGalleryItem.article_id == article.id)
                .order_by(ArticleGalleryItem.position)
            )
        ).all()
        return {
            "title": article.title,
            "excerpt": article.excerpt,
            "content": article.content,
            "featured_image_url": article.featured_image_url,
            "featured_image_alt": article.featured_image_alt,
            "featured_media_id": article.featured_media_id,
            "category_id": article.category_id,
            "is_featured": article.is_featured,
            "status": article.status.value,
            "publish_at": article.publish_at.isoformat() if article.publish_at else None,
            "unpublish_at": article.unpublish_at.isoformat() if article.unpublish_at else None,
            "tags": sorted(t.name for t in article.tags),
            "team_ids": await ids(article_teams, "team_id"),
            "player_ids": await ids(article_players, "player_id"),
            "competition_ids": await ids(article_competitions, "competition_id"),
            "match_ids": await ids(article_matches, "match_id"),
            "gallery": [{"media_id": m, "caption": c} for m, c in gallery],
        }

    async def _record_revision(self, article: Article, editor_id: int | None, action: RevisionAction) -> None:
        """Append a revision in the *same transaction* as the change, so a saved
        article always has the revision that describes it. Unchanged saves add nothing."""
        snapshot = await self._snapshot(article)
        latest = (
            await self.db.execute(
                select(ArticleRevision).where(ArticleRevision.article_id == article.id).order_by(ArticleRevision.version.desc()).limit(1)
            )
        ).scalar_one_or_none()
        changes = list(snapshot) if latest is None else [k for k in snapshot if latest.snapshot.get(k) != snapshot[k]]
        if latest is not None and not changes:
            return
        self.db.add(
            ArticleRevision(
                article_id=article.id,
                version=(latest.version + 1) if latest else 1,
                editor_id=editor_id,
                action=action,
                snapshot=snapshot,
                changes=changes,
            )
        )

    async def _revision_access(self, user: User, article_id: int) -> Article:
        if not can_author(user):
            raise ArticlePermissionError("Editors only")
        article = await self.db.scalar(select(Article).where(Article.id == article_id).options(*_SUMMARY_LOAD))
        if article is None:
            raise ArticleNotFoundError(str(article_id))
        if not can_edit(user, article):
            raise ArticlePermissionError("You can only view revisions of your own articles")
        return article

    @staticmethod
    def _revision_out(revision: ArticleRevision, editor_name: str | None) -> RevisionOut:
        return RevisionOut(
            version=revision.version, action=revision.action, editor_name=editor_name, created_at=revision.created_at, changes=revision.changes
        )

    async def list_revisions(self, user: User, article_id: int) -> list[RevisionOut]:
        await self._revision_access(user, article_id)
        rows = await self.db.execute(
            select(ArticleRevision, User.display_name)
            .outerjoin(User, User.id == ArticleRevision.editor_id)
            .where(ArticleRevision.article_id == article_id)
            .order_by(ArticleRevision.version.desc())
        )
        return [self._revision_out(r, name) for r, name in rows]

    async def _get_revision(self, article_id: int, version: int) -> tuple[ArticleRevision, str | None]:
        row = (
            await self.db.execute(
                select(ArticleRevision, User.display_name)
                .outerjoin(User, User.id == ArticleRevision.editor_id)
                .where(ArticleRevision.article_id == article_id, ArticleRevision.version == version)
            )
        ).first()
        if row is None:
            raise ArticleNotFoundError(f"revision {version}")
        return row[0], row[1]

    async def get_revision(self, user: User, article_id: int, version: int) -> RevisionDetail:
        await self._revision_access(user, article_id)
        revision, name = await self._get_revision(article_id, version)
        return RevisionDetail(**self._revision_out(revision, name).model_dump(), snapshot=revision.snapshot)

    async def compare_revisions(self, user: User, article_id: int, from_version: int, to_version: int) -> RevisionDiff:
        await self._revision_access(user, article_id)
        a, _ = await self._get_revision(article_id, from_version)
        b, _ = await self._get_revision(article_id, to_version)
        changes = [
            FieldChange(field=k, before=a.snapshot.get(k), after=b.snapshot.get(k))
            for k in b.snapshot
            if k != "content" and a.snapshot.get(k) != b.snapshot.get(k)
        ]
        before = [blk["text"] for blk in html_to_blocks(a.snapshot.get("content", ""))]
        after = [blk["text"] for blk in html_to_blocks(b.snapshot.get("content", ""))]
        lines: list[DiffLine] = []
        for line in difflib.unified_diff(before, after, lineterm="", n=1):
            if line.startswith(("---", "+++", "@@")):
                continue
            lines.append(DiffLine(kind={"+": "add", "-": "del"}.get(line[:1], "ctx"), text=line[1:]))
        if a.snapshot.get("content") != b.snapshot.get("content"):
            changes.insert(0, FieldChange(field="content", before=None, after=None))
        return RevisionDiff(article_id=article_id, from_version=from_version, to_version=to_version, changes=changes, content_diff=lines)

    async def restore_revision(self, user: User, article_id: int, version: int) -> Article:
        """Put an old version's *content and metadata* back. Publication state
        (status/schedule) is deliberately left alone: restoring text is not publishing."""
        article = await self._revision_access(user, article_id)
        self._check_write(user, article)
        revision, _ = await self._get_revision(article_id, version)
        snap = revision.snapshot
        article.title = snap["title"]
        article.excerpt = snap["excerpt"]
        article.content = sanitize_html(snap["content"], image_hosts=tuple(settings.article_image_host_list))
        article.featured_image_url = snap.get("featured_image_url")
        article.featured_image_alt = snap.get("featured_image_alt")
        article.is_featured = bool(snap.get("is_featured"))
        category_ok = snap.get("category_id") and await self.db.get(ArticleCategory, snap["category_id"])
        article.category_id = snap["category_id"] if category_ok else None
        media_id = snap.get("featured_media_id")
        article.featured_media_id = media_id if media_id and await self.db.get(Media, media_id) else None
        article.tags = await self._resolve_tags(snap.get("tags", []))
        # entities may have been deleted since: keep only those that still exist
        for table, column, model, key in (
            (article_teams, "team_id", Team, "team_ids"),
            (article_players, "player_id", Player, "player_ids"),
            (article_competitions, "competition_id", Competition, "competition_ids"),
            (article_matches, "match_id", Match, "match_ids"),
        ):
            wanted = snap.get(key, [])
            valid = set((await self.db.execute(select(model.id).where(model.id.in_(wanted)))).scalars()) if wanted else set()
            await self.db.execute(delete(table).where(table.c.article_id == article.id))
            if valid:
                await self.db.execute(table.insert(), [{"article_id": article.id, column: i} for i in sorted(valid)])
        gallery = snap.get("gallery", [])
        wanted_ids = [g["media_id"] for g in gallery]
        existing = set((await self.db.execute(select(Media.id).where(Media.id.in_(wanted_ids)))).scalars()) if wanted_ids else set()
        await self.db.execute(delete(ArticleGalleryItem).where(ArticleGalleryItem.article_id == article.id))
        for position, g in enumerate(x for x in gallery if x["media_id"] in existing):
            self.db.add(ArticleGalleryItem(article_id=article.id, media_id=g["media_id"], position=position, caption=g.get("caption", "")))
        await self.db.flush()
        await self.db.refresh(article, attribute_names=["gallery"])
        await self._record_revision(article, user.id, RevisionAction.RESTORE)
        await self.db.commit()
        await self.bump_version()
        log_event(logger, "article_restore", article_id=article.id, version=version, user_id=user.id)
        return await self._reload(article.id)

    # -- create / update / status ----------------------------------------------------------

    async def create(self, author: User, payload: ArticleIn) -> tuple[Article, bool]:
        if not can_author(author):
            raise ArticlePermissionError("Authors and editors only")
        reviewer = is_reviewer(author)
        if not reviewer and payload.status not in (ArticleStatus.DRAFT, ArticleStatus.IN_REVIEW):
            raise ArticlePermissionError("Only editors can publish or schedule. Submit it for review instead.")
        await self._check_category(payload.category_id)
        content = sanitize_html(payload.content, image_hosts=tuple(settings.article_image_host_list))
        article = Article(
            slug=await self._unique_slug(payload.title),
            title=" ".join(payload.title.split()),
            content=content,
            excerpt=(payload.excerpt.strip() or self._auto_excerpt(content)),
            featured_image_url=self._check_image(payload.featured_image_url),
            featured_image_alt=(payload.featured_image_alt or payload.title)[:200] if payload.featured_image_url else None,
            author_id=author.id,
            category_id=payload.category_id,
            is_featured=payload.is_featured and reviewer,
            status=ArticleStatus.DRAFT,
        )
        article.tags = await self._resolve_tags(payload.tags)
        for attempt in range(3):
            self.db.add(article)
            try:
                await self.db.flush()
                break
            except IntegrityError:  # slug raced with another editor
                await self.db.rollback()
                article.slug = f"{article.slug}-{''.join(random.choices(string.ascii_lowercase + string.digits, k=4))}"
                article.tags = await self._resolve_tags(payload.tags)
        else:
            raise ArticleValidationError("Could not allocate a unique URL for this article")
        data = payload.model_dump()
        await self._set_links(article, data)
        await self._apply_media(author, article, data)
        became_published = self._transition(
            author, article, payload.status, publish_at=payload.publish_at, unpublish_at=payload.unpublish_at
        )
        if payload.unpublish_at is not None and payload.status == ArticleStatus.DRAFT:
            article.unpublish_at = self._aware(payload.unpublish_at)
        await self.db.flush()
        await self.db.refresh(article, attribute_names=["tags"])
        await self._record_revision(article, author.id, RevisionAction.CREATE)
        await self.db.commit()
        await self.bump_version()
        log_event(logger, "article_create", article_id=article.id, user_id=author.id, status=article.status.value)
        if became_published:
            metrics.article_published()
            log_event(logger, "article_publish", article_id=article.id, user_id=author.id)
        return await self._reload(article.id), became_published

    async def _reload(self, article_id: int) -> Article:
        return (
            await self.db.execute(
                select(Article).where(Article.id == article_id).options(*_SUMMARY_LOAD).execution_options(populate_existing=True)
            )
        ).scalar_one()

    async def get_for_edit(self, user: User, article_id: int) -> Article:
        if not can_author(user):
            raise ArticlePermissionError("Authors and editors only")
        article = await self.db.scalar(select(Article).where(Article.id == article_id).options(*_SUMMARY_LOAD))
        if article is None:
            raise ArticleNotFoundError(str(article_id))
        if not can_edit(user, article):
            raise ArticlePermissionError("You can only edit your own articles")
        return article

    async def update(self, user: User, article_id: int, payload: ArticleUpdate) -> tuple[Article, bool]:
        article = await self.get_for_edit(user, article_id)
        data = payload.model_dump(exclude_unset=True)
        content_fields = set(data) - {"status", "publish_at", "unpublish_at"}
        if content_fields:
            self._check_write(user, article)
        if "title" in data and data["title"] is not None:
            article.title = " ".join(data["title"].split())  # the slug stays put: URLs are stable
        if "content" in data and data["content"] is not None:
            article.content = sanitize_html(data["content"], image_hosts=tuple(settings.article_image_host_list))
            if not data.get("excerpt") and not article.excerpt:
                article.excerpt = self._auto_excerpt(article.content)
        if "excerpt" in data and data["excerpt"] is not None:
            article.excerpt = data["excerpt"].strip() or self._auto_excerpt(article.content)
        if "featured_image_url" in data:
            article.featured_image_url = self._check_image(data["featured_image_url"])
            if article.featured_image_url is None:
                article.featured_image_alt = None
            else:
                article.featured_media_id = None  # an external URL replaces an uploaded image
        if article.featured_image_url and ("featured_image_alt" in data or not article.featured_image_alt):
            article.featured_image_alt = (data.get("featured_image_alt") or article.title)[:200]
        if "category_id" in data:
            await self._check_category(data["category_id"])
            article.category_id = data["category_id"]
        if data.get("is_featured") is not None:
            if not is_reviewer(user):
                raise ArticlePermissionError("Only editors can feature an article")
            article.is_featured = data["is_featured"]
        if data.get("tags") is not None:
            article.tags = await self._resolve_tags(data["tags"])
        await self._set_links(article, data)
        await self._apply_media(user, article, data)
        if ("publish_at" in data or "unpublish_at" in data) and "status" not in data:
            if not is_reviewer(user):
                raise ArticlePermissionError("Only editors can schedule an article")
            new_publish = self._aware(data["publish_at"]) if "publish_at" in data else article.publish_at
            new_unpublish = self._aware(data["unpublish_at"]) if "unpublish_at" in data else article.unpublish_at
            self._validate_schedule(
                new_publish, new_unpublish, need_publish_at=article.status == ArticleStatus.SCHEDULED and "publish_at" in data
            )
            article.publish_at, article.unpublish_at = new_publish, new_unpublish
        became_published = False
        if data.get("status") is not None:
            became_published = self._transition(
                user, article, data["status"], publish_at=data.get("publish_at"), unpublish_at=data.get("unpublish_at")
            )
        await self.db.flush()
        await self.db.refresh(article, attribute_names=["tags"])
        await self._record_revision(article, user.id, RevisionAction.UPDATE if "status" not in data else RevisionAction.STATUS)
        await self.db.commit()
        await self.bump_version()
        log_event(logger, "article_update", article_id=article.id, user_id=user.id, fields=sorted(data))
        if became_published:
            metrics.article_published()
            log_event(logger, "article_publish", article_id=article.id, user_id=user.id)
        return await self._reload(article.id), became_published

    async def set_status(
        self,
        user: User,
        article_id: int,
        status: ArticleStatus,
        *,
        publish_at: datetime | None = None,
        unpublish_at: datetime | None = None,
        note: str | None = None,
    ) -> tuple[Article, bool]:
        article = await self.get_for_edit(user, article_id)
        previous = article.status
        became_published = self._transition(user, article, status, publish_at=publish_at, unpublish_at=unpublish_at, note=note)
        await self.db.flush()
        await self._record_revision(article, user.id, RevisionAction.STATUS)
        await self.db.commit()
        await self.bump_version()
        log_event(
            logger, "article_status", article_id=article.id, user_id=user.id, from_status=previous.value, to_status=article.status.value
        )
        if became_published:
            metrics.article_published()
            log_event(logger, "article_publish", article_id=article.id, user_id=user.id)
        return await self._reload(article.id), became_published

    async def delete(self, user: User, article_id: int) -> None:
        article = await self.get_for_edit(user, article_id)
        if not is_reviewer(user) and article.status != ArticleStatus.DRAFT:
            raise ArticlePermissionError("You can only delete your own drafts")
        audit.record(
            self.db, action="article.delete", target_type="article", target_id=article_id, actor=user,
            details={"status": article.status.value, "author_id": article.author_id},
        )
        await self.db.delete(article)
        await self.db.commit()
        await self.bump_version()
        log_event(logger, "article_delete", article_id=article_id, user_id=user.id)

    async def list_admin(
        self, user: User, *, status: ArticleStatus | None, page: int, page_size: int
    ) -> Page[ArticleAdminSummary]:
        if not can_author(user):
            raise ArticlePermissionError("Authors and editors only")
        clauses = []
        if user.role == UserRole.EDITOR:
            # an editor's desk: their own work plus everything that has left draft
            clauses.append(or_(Article.author_id == user.id, Article.status != ArticleStatus.DRAFT))
        elif user.role != UserRole.ADMIN:
            clauses.append(Article.author_id == user.id)
        if status is not None:
            clauses.append(Article.status == status)
        where = and_(*clauses) if clauses else Article.id.is_not(None)
        return await self._page(
            where,
            (Article.updated_at.desc(), Article.id.desc()),
            page,
            page_size,
            shape=lambda a: ArticleAdminSummary(
                **self.to_summary(a).model_dump(), status=a.status, is_featured=a.is_featured
            ),
        )

    # -- scheduler ---------------------------------------------------------------------

    async def run_schedule(self) -> tuple[list[int], list[int]]:
        """Publish due SCHEDULED articles and archive PUBLISHED ones past their
        `unpublish_at`. Each is a single `UPDATE ... WHERE <still due> RETURNING`,
        so concurrent runs (two workers, a retried task, a restart mid-run) cannot
        process the same article twice, and running it again is a no-op."""
        published = list(
            (
                await self.db.execute(
                    update(Article)
                    .where(Article.status == ArticleStatus.SCHEDULED, Article.publish_at <= func.now())
                    .values(
                        status=ArticleStatus.PUBLISHED,
                        published_at=func.coalesce(Article.publish_at, func.now()),
                        publish_at=None,
                    )
                    .returning(Article.id)
                )
            ).scalars()
        )
        archived = list(
            (
                await self.db.execute(
                    update(Article)
                    .where(
                        Article.status == ArticleStatus.PUBLISHED,
                        Article.unpublish_at.is_not(None),
                        Article.unpublish_at <= func.now(),
                    )
                    .values(status=ArticleStatus.ARCHIVED)
                    .returning(Article.id)
                )
            ).scalars()
        )
        for article_id in published + archived:
            article = await self.db.scalar(select(Article).where(Article.id == article_id).options(*_SUMMARY_LOAD))
            if article is not None:
                await self._record_revision(article, None, RevisionAction.SCHEDULED)
        await self.db.commit()
        if published or archived:
            await self.bump_version()
            metrics.scheduled_publish(len(published))
            metrics.article_published(len(published))
            log_event(logger, "scheduled_publish", published=published, archived=archived)
        return published, archived
