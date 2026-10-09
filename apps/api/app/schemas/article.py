from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import ArticleStatus
from app.schemas.competition import CompetitionOut
from app.schemas.media import GalleryImage, GalleryItemIn
from app.schemas.match import MatchSummary
from app.schemas.player import PlayerOut
from app.schemas.team import TeamOut


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    name: str
    competition_id: int | None = None


class TagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    name: str


class ArticleSummary(BaseModel):
    """List/card shape. Deliberately has no author email or any other private
    field -- only the display name."""

    id: int
    slug: str
    title: str
    excerpt: str
    featured_image_url: str | None = None
    featured_image_alt: str | None = None
    published_at: datetime | None = None
    category: CategoryOut | None = None
    author_name: str | None = None
    tags: list[TagOut] = Field(default_factory=list)
    relation: str | None = None
    """On an entity's news list: how this article relates to it ("match",
    "team", "competition", "player")."""
    reason: str | None = None
    """On related-article lists: why it was suggested, in words."""


class ContentBlock(BaseModel):
    type: Literal["heading", "paragraph", "list_item", "quote"]
    text: str


class ArticleDetail(ArticleSummary):
    content: str
    """Sanitized HTML, safe to render as-is."""
    content_text: str
    """The same body as plain, blank-line separated paragraphs."""
    content_blocks: list[ContentBlock] = Field(default_factory=list)
    """The same body as typed blocks, for clients that render natively (mobile)."""
    updated_at: datetime
    view_count: int = 0
    canonical_path: str
    teams: list[TeamOut] = Field(default_factory=list)
    players: list[PlayerOut] = Field(default_factory=list)
    competitions: list[CompetitionOut] = Field(default_factory=list)
    matches: list[MatchSummary] = Field(default_factory=list)
    gallery: list[GalleryImage] = Field(default_factory=list)


class ArticleAdminSummary(ArticleSummary):
    """Editor list row: a card plus where it is in the workflow."""

    status: ArticleStatus
    is_featured: bool


class ArticleAdminOut(ArticleDetail):
    status: ArticleStatus
    is_featured: bool
    author_id: int | None = None
    publish_at: datetime | None = None
    unpublish_at: datetime | None = None
    review_note: str | None = None
    featured_media_id: int | None = None


class ArticleIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    excerpt: str = Field(default="", max_length=500)
    content: str = Field(default="", max_length=100_000)
    featured_image_url: str | None = Field(default=None, max_length=512)
    featured_image_alt: str | None = Field(default=None, max_length=200)
    category_id: int | None = None
    tags: list[str] = Field(default_factory=list, max_length=10)
    team_ids: list[int] = Field(default_factory=list, max_length=20)
    player_ids: list[int] = Field(default_factory=list, max_length=20)
    competition_ids: list[int] = Field(default_factory=list, max_length=20)
    match_ids: list[int] = Field(default_factory=list, max_length=20)
    is_featured: bool = False
    status: ArticleStatus = ArticleStatus.DRAFT
    publish_at: datetime | None = None
    unpublish_at: datetime | None = None
    featured_media_id: int | None = None
    gallery: list[GalleryItemIn] = Field(default_factory=list, max_length=30)

    @field_validator("tags")
    @classmethod
    def _tag_length(cls, tags: list[str]) -> list[str]:
        for tag in tags:
            if not 1 <= len(tag.strip()) <= 50:
                raise ValueError("each tag must be 1-50 characters")
        return tags


class ArticleUpdate(BaseModel):
    """PATCH body: only the fields present are changed."""

    title: str | None = Field(default=None, min_length=3, max_length=200)
    excerpt: str | None = Field(default=None, max_length=500)
    content: str | None = Field(default=None, max_length=100_000)
    featured_image_url: str | None = Field(default=None, max_length=512)
    featured_image_alt: str | None = Field(default=None, max_length=200)
    category_id: int | None = None
    tags: list[str] | None = Field(default=None, max_length=10)
    team_ids: list[int] | None = Field(default=None, max_length=20)
    player_ids: list[int] | None = Field(default=None, max_length=20)
    competition_ids: list[int] | None = Field(default=None, max_length=20)
    match_ids: list[int] | None = Field(default=None, max_length=20)
    is_featured: bool | None = None
    status: ArticleStatus | None = None
    publish_at: datetime | None = None
    unpublish_at: datetime | None = None
    featured_media_id: int | None = None
    gallery: list[GalleryItemIn] | None = Field(default=None, max_length=30)


class CategoryIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    slug: str | None = Field(default=None, max_length=80)
    competition_id: int | None = None
