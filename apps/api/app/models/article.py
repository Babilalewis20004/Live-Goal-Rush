"""Football content (discovery). Articles *link to* the existing
Team/Player/Competition/Match rows through association tables -- no football
entity is duplicated, and deleting one of them just drops the link."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import ArticleStatus
from app.models.mixins import TimestampMixin


def _link_table(name: str, entity_table: str, entity_column: str) -> Table:
    return Table(
        name,
        Base.metadata,
        Column("article_id", ForeignKey("articles.id", ondelete="CASCADE"), primary_key=True),
        Column(entity_column, ForeignKey(f"{entity_table}.id", ondelete="CASCADE"), primary_key=True),
        # "Which articles mention this team?" is the hot direction; the
        # composite primary key already covers article -> entities.
        Index(f"ix_{name}_{entity_column}", entity_column),
    )


article_teams = _link_table("article_teams", "teams", "team_id")
article_players = _link_table("article_players", "players", "player_id")
article_competitions = _link_table("article_competitions", "competitions", "competition_id")
article_matches = _link_table("article_matches", "matches", "match_id")
article_tag_links = _link_table("article_tag_links", "article_tags", "tag_id")


class ArticleGalleryItem(Base):
    """An image in an article's gallery (ordered, optionally captioned)."""

    __tablename__ = "article_gallery"

    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"), primary_key=True)
    media_id: Mapped[int] = mapped_column(ForeignKey("media.id", ondelete="RESTRICT"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    caption: Mapped[str] = mapped_column(String(200), nullable=False, default="")

    media: Mapped["Media"] = relationship(lazy="selectin")  # noqa: F821


class ArticleCategory(Base, TimestampMixin):
    __tablename__ = "article_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    competition_id: Mapped[int | None] = mapped_column(
        ForeignKey("competitions.id", ondelete="SET NULL"), nullable=True
    )
    """Optional: a category such as "Premier League" can point at the real
    competition, so its articles also surface on that competition's page."""


class ArticleTag(Base, TimestampMixin):
    """Reusable label. `slug` is unique, which is what prevents "Real Madrid"
    and "real-madrid" from becoming two tags."""

    __tablename__ = "article_tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)


class Article(Base, TimestampMixin):
    __tablename__ = "articles"
    __table_args__ = (
        # The public feed: published, newest first.
        Index("ix_articles_status_published_at", "status", "published_at"),
        Index("ix_articles_category_published", "category_id", "published_at"),
        Index(
            "ix_articles_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
        # Phase 7: article search matches `excerpt ILIKE '%q%'`; without this every search read every article.
        Index(
            "ix_articles_excerpt_trgm",
            "excerpt",
            postgresql_using="gin",
            postgresql_ops={"excerpt": "gin_trgm_ops"},
        ),
        # Featured shelf: a tiny partial index.
        # The scheduler's two lookups, each a tiny partial index.
        Index("ix_articles_scheduled", "publish_at", postgresql_where=text("status = 'SCHEDULED'")),
        Index(
            "ix_articles_unpublish_due",
            "unpublish_at",
            postgresql_where=text("status = 'PUBLISHED' AND unpublish_at IS NOT NULL"),
        ),
        Index(
            "ix_articles_featured",
            "published_at",
            postgresql_where=text("is_featured AND status = 'PUBLISHED'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    excerpt: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    """Sanitized HTML (see `services/html_sanitizer.py`). Sanitized on every
    write, never on read, so what is in the database is always safe to emit."""
    featured_image_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    featured_image_alt: Mapped[str | None] = mapped_column(String(200), nullable=True)
    author_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[ArticleStatus] = mapped_column(
        Enum(ArticleStatus, native_enum=False, validate_strings=True, length=16),
        default=ArticleStatus.DRAFT,
        nullable=False,
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_featured: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("article_categories.id", ondelete="SET NULL"), nullable=True
    )
    view_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    """Lifetime views, advanced by the engagement aggregation job (never per request)."""
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    publish_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """When a SCHEDULED article goes live (Celery beat publishes it)."""
    unpublish_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """When a live article is archived automatically. Also enforced on read."""
    review_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    """Why an editor sent it back to draft."""
    featured_media_id: Mapped[int | None] = mapped_column(ForeignKey("media.id", ondelete="SET NULL"), nullable=True)
    """Set once content notifications for this article were dispatched, so an
    unpublish -> republish never notifies twice."""

    category: Mapped["ArticleCategory | None"] = relationship()
    author: Mapped["User | None"] = relationship()  # noqa: F821
    tags: Mapped[list["ArticleTag"]] = relationship(secondary=article_tag_links)
    gallery: Mapped[list["ArticleGalleryItem"]] = relationship(
        cascade="all, delete-orphan", order_by="ArticleGalleryItem.position", lazy="selectin"
    )
