"""Public news API (discovery §14-16). Everything here serves *published*
articles only; drafts and archived articles are reachable solely through the
editor endpoints."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import ArticleServiceDep, PaginationDep
from app.schemas.article import ArticleDetail, ArticleSummary, CategoryOut, TagOut
from app.schemas.common import Page
from app.services.article_service import ArticleNotFoundError

router = APIRouter()


@router.get("", response_model=Page[ArticleSummary])
async def list_articles(
    service: ArticleServiceDep,
    pagination: PaginationDep,
    category: Annotated[str | None, Query(max_length=80)] = None,
    tag: Annotated[str | None, Query(max_length=80)] = None,
    featured: bool | None = None,
    team_id: Annotated[int | None, Query(ge=1)] = None,
    player_id: Annotated[int | None, Query(ge=1)] = None,
    competition_id: Annotated[int | None, Query(ge=1)] = None,
    match_id: Annotated[int | None, Query(ge=1)] = None,
) -> Page[ArticleSummary]:
    page, page_size = pagination
    return await service.list_public(
        page=page,
        page_size=page_size,
        category=category,
        tag=tag,
        featured=featured,
        team_id=team_id,
        player_id=player_id,
        competition_id=competition_id,
        match_id=match_id,
    )


@router.get("/categories", response_model=list[CategoryOut])
async def list_categories(service: ArticleServiceDep) -> list[CategoryOut]:
    return await service.list_categories()


@router.get("/tags", response_model=list[TagOut])
async def popular_tags(service: ArticleServiceDep, limit: Annotated[int, Query(ge=1, le=50)] = 20) -> list[TagOut]:
    return await service.popular_tags(limit)


@router.get("/{slug}", response_model=ArticleDetail)
async def get_article(slug: str, service: ArticleServiceDep) -> ArticleDetail:
    try:
        return await service.get_public(slug)
    except ArticleNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Article not found") from exc


@router.get("/{slug}/related", response_model=list[ArticleSummary])
async def related_articles(
    slug: str, service: ArticleServiceDep, limit: Annotated[int, Query(ge=1, le=12)] = 4
) -> list[ArticleSummary]:
    try:
        return await service.related(slug, limit)
    except ArticleNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Article not found") from exc
