from __future__ import annotations

from datetime import datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field

from app.models.enums import ContentNotificationKind, EngagementEntity
from app.schemas.article import ArticleSummary
from app.schemas.competition import CompetitionOut
from app.schemas.match import MatchSummary
from app.schemas.player import PlayerOut
from app.schemas.team import TeamOut

T = TypeVar("T")


class Trending(BaseModel, Generic[T]):
    """One trending entity. `signals` shows exactly what contributed, so the
    ranking is explainable; `score` is only meaningful for ordering."""

    item: T
    score: float
    signals: dict[str, int] = Field(default_factory=dict)


class TrendingOut(BaseModel):
    window_hours: int
    teams: list[Trending[TeamOut]] = Field(default_factory=list)
    players: list[Trending[PlayerOut]] = Field(default_factory=list)
    competitions: list[Trending[CompetitionOut]] = Field(default_factory=list)
    articles: list[Trending[ArticleSummary]] = Field(default_factory=list)


class DiscoveryHome(BaseModel):
    """The public (anonymous-safe) half of the home page. Live and upcoming
    matches stay on their existing real-time endpoints/WebSocket; this adds
    what Phase 5 brings. A section with no data is simply empty."""

    latest_results: list[MatchSummary] = Field(default_factory=list)
    featured_articles: list[ArticleSummary] = Field(default_factory=list)
    latest_articles: list[ArticleSummary] = Field(default_factory=list)
    trending_teams: list[Trending[TeamOut]] = Field(default_factory=list)
    trending_players: list[Trending[PlayerOut]] = Field(default_factory=list)
    trending_articles: list[Trending[ArticleSummary]] = Field(default_factory=list)
    popular_competitions: list[CompetitionOut] = Field(default_factory=list)
    generated_at: datetime


FeedReason = Literal[
    "live_followed_match",
    "followed_team_today",
    "followed_competition_today",
    "followed_team_upcoming",
    "followed_competition_upcoming",
    "recent_result",
    "news_followed_team",
    "news_followed_competition",
    "news_searched",
    "community_match",
    "community_article",
    "trending",
    "latest",
]


class FeedItem(BaseModel):
    kind: Literal["match", "article"]
    reason: FeedReason
    explanation: str
    """Human readable, e.g. "Liverpool is playing today"."""
    rank: int
    """1 = most relevant tier (see `discovery_service.FEED_TIERS`)."""
    match: MatchSummary | None = None
    article: ArticleSummary | None = None


class FeedOut(BaseModel):
    items: list[FeedItem]
    personalised: bool
    """False when the user follows nothing yet: the feed is then the general
    one (trending/latest), and says so."""


class SearchSuggestion(BaseModel):
    type: Literal["team", "player", "competition", "article"]
    id: int
    label: str
    slug: str | None = None
    """Articles are addressed by slug."""


class SearchSuggestions(BaseModel):
    query: str
    suggestions: list[SearchSuggestion] = Field(default_factory=list)


class PopularSearches(BaseModel):
    queries: list[str] = Field(default_factory=list)


class RecentSearchesOut(BaseModel):
    queries: list[str] = Field(default_factory=list)


class SearchTrackIn(BaseModel):
    query: str = Field(min_length=1, max_length=100)
    entity_type: EngagementEntity | None = None
    entity_id: int | None = Field(default=None, ge=1)


class ViewTrackIn(BaseModel):
    entity_type: EngagementEntity
    entity_id: int | None = Field(default=None, ge=1)
    slug: str | None = Field(default=None, max_length=160)
    """Articles may be addressed by slug instead of id."""


class ContentPreferenceOut(BaseModel):
    kind: ContentNotificationKind
    enabled: bool
    default: bool
    """What applies when the user hasn't chosen."""


class ContentPreferenceIn(BaseModel):
    kind: ContentNotificationKind
    enabled: bool
