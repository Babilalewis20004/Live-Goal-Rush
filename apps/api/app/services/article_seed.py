"""Default article categories (discovery §12). Nothing is hard-coded in the
clients: they read `/articles/categories`. Generic categories are fixed here;
every *competition* the provider has synced gets a category pointing at the
real `Competition` row, so "Premier League" news is also that competition's
news and categories follow the football data rather than a second list."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.article import ArticleCategory
from app.models.competition import Competition
from app.services.slug import slugify

logger = logging.getLogger(__name__)

GENERIC_CATEGORIES = (
    ("football-news", "Football News"),
    ("transfers", "Transfers"),
    ("match-reports", "Match Reports"),
    ("international-football", "International Football"),
)


async def ensure_default_categories(db: AsyncSession) -> None:
    """Idempotent. Never renames or removes a category an editor created."""
    rows = [{"slug": slug, "name": name, "competition_id": None} for slug, name in GENERIC_CATEGORIES]
    taken = set(slug for slug, _ in GENERIC_CATEGORIES)
    linked = set((await db.execute(select(ArticleCategory.competition_id).where(ArticleCategory.competition_id.is_not(None)))).scalars())
    for competition_id, name in (await db.execute(select(Competition.id, Competition.name).order_by(Competition.name))).all():
        if competition_id in linked:
            continue
        slug = slugify(name, max_length=80)
        if not slug or slug in taken:
            continue
        taken.add(slug)
        rows.append({"slug": slug, "name": name, "competition_id": competition_id})
    await db.execute(pg_insert(ArticleCategory).values(rows).on_conflict_do_nothing(index_elements=["slug"]))
    await db.commit()
