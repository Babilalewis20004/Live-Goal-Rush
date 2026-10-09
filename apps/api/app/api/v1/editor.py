"""Editorial API: create, edit, review, schedule, publish, revisions.

Roles (see docs/architecture/editorial-workflow.md):

* AUTHOR  - writes drafts, submits them for review, withdraws them
* EDITOR  - reviews (approve / reject), publishes, schedules, unpublishes, archives
* ADMIN   - everything, and creates categories

The router only checks "is this a staff role?" (`EditorDep`); the per-action and
per-article rules live in `ArticleService`, so they cannot be bypassed by adding a
route that forgets them.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import AdminDep, ArticleServiceDep, CurrentUserDep, EditorDep
from app.models.enums import ArticleStatus, UserRole
from app.schemas.article import (
    ArticleAdminOut,
    ArticleAdminSummary,
    ArticleIn,
    ArticleUpdate,
    CategoryIn,
    CategoryOut,
)
from app.schemas.common import Page
from app.schemas.revision import ApproveIn, RejectIn, RevisionDetail, RevisionDiff, RevisionOut, ScheduleIn
from app.services.article_service import (
    ArticleNotFoundError,
    ArticlePermissionError,
    ArticleService,
    ArticleValidationError,
)
from app.worker.discovery_tasks import dispatch_article_notifications
from app.worker.social_tasks import notify_editorial

logger = logging.getLogger(__name__)

router = APIRouter()


def _enqueue(task, *args) -> None:
    """Background work never blocks or fails a request."""
    try:
        task.delay(*args)
    except Exception:
        logger.warning("Could not enqueue %s%s", getattr(task, "name", task), args, exc_info=True)


def _after(article_id: int, previous: ArticleStatus | None, article, became_published: bool) -> None:
    if became_published:
        _enqueue(dispatch_article_notifications, article_id)
        _enqueue(notify_editorial, article_id, "published")
    elif article.status != previous:
        event = {
            ArticleStatus.IN_REVIEW: "submitted",
            ArticleStatus.SCHEDULED: "scheduled",
            ArticleStatus.DRAFT: "rejected" if previous == ArticleStatus.IN_REVIEW else None,
        }.get(article.status)
        if event:
            _enqueue(notify_editorial, article_id, event)


async def _run(call):
    try:
        return await call
    except ArticleNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Article not found") from exc
    except ArticlePermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ArticleValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("", response_model=Page[ArticleAdminSummary])
async def list_my_articles(
    user: EditorDep,
    service: ArticleServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    status_filter: Annotated[ArticleStatus | None, Query(alias="status")] = None,
) -> Page[ArticleAdminSummary]:
    """Authors see their own; editors their own plus everything past draft (the
    review queue is `?status=in_review`); admins see all."""
    return await _run(service.list_admin(user, status=status_filter, page=page, page_size=page_size))


@router.post("", response_model=ArticleAdminOut, status_code=status.HTTP_201_CREATED)
async def create_article(payload: ArticleIn, user: EditorDep, service: ArticleServiceDep) -> ArticleAdminOut:
    article, became_published = await _run(service.create(user, payload))
    _after(article.id, None, article, became_published)
    return await service.to_admin(article)


@router.get("/categories", response_model=list[CategoryOut])
async def editor_categories(user: EditorDep, service: ArticleServiceDep) -> list[CategoryOut]:
    from app.services.article_seed import ensure_default_categories

    await ensure_default_categories(service.db)
    return await service.list_categories()


@router.post("/categories", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
async def create_category(payload: CategoryIn, user: AdminDep, service: ArticleServiceDep) -> CategoryOut:
    # `AdminDep` runs before the body is parsed, so a non-admin gets 403 whatever they send.
    return await _run(service.create_category(payload))


@router.get("/{article_id}", response_model=ArticleAdminOut)
async def get_article(article_id: int, user: EditorDep, service: ArticleServiceDep) -> ArticleAdminOut:
    article = await _run(service.get_for_edit(user, article_id))
    return await service.to_admin(article)


@router.patch("/{article_id}", response_model=ArticleAdminOut)
async def update_article(
    article_id: int, payload: ArticleUpdate, user: EditorDep, service: ArticleServiceDep
) -> ArticleAdminOut:
    before = (await _run(service.get_for_edit(user, article_id))).status
    article, became_published = await _run(service.update(user, article_id, payload))
    _after(article.id, before, article, became_published)
    return await service.to_admin(article)


async def _transition(
    article_id: int, user, service: ArticleService, target: ArticleStatus, **kwargs
) -> ArticleAdminOut:
    before = (await _run(service.get_for_edit(user, article_id))).status
    article, became_published = await _run(service.set_status(user, article_id, target, **kwargs))
    _after(article.id, before, article, became_published)
    return await service.to_admin(article)


@router.post("/{article_id}/submit", response_model=ArticleAdminOut)
async def submit_for_review(article_id: int, user: EditorDep, service: ArticleServiceDep) -> ArticleAdminOut:
    """Author -> review queue."""
    return await _transition(article_id, user, service, ArticleStatus.IN_REVIEW)


@router.post("/{article_id}/withdraw", response_model=ArticleAdminOut)
async def withdraw_from_review(article_id: int, user: EditorDep, service: ArticleServiceDep) -> ArticleAdminOut:
    """Take an article back out of review (back to draft) so it can be edited."""
    return await _transition(article_id, user, service, ArticleStatus.DRAFT)


@router.post("/{article_id}/approve", response_model=ArticleAdminOut)
async def approve_article(
    article_id: int, user: EditorDep, service: ArticleServiceDep, payload: ApproveIn | None = None
) -> ArticleAdminOut:
    """Editor: publish now, or schedule if `publish_at` is given."""
    payload = payload or ApproveIn()
    target = ArticleStatus.SCHEDULED if payload.publish_at else ArticleStatus.PUBLISHED
    return await _transition(
        article_id, user, service, target, publish_at=payload.publish_at, unpublish_at=payload.unpublish_at
    )


@router.post("/{article_id}/reject", response_model=ArticleAdminOut)
async def reject_article(
    article_id: int, user: EditorDep, service: ArticleServiceDep, payload: RejectIn | None = None
) -> ArticleAdminOut:
    """Editor: send back to the author as a draft, with a note."""
    return await _transition(article_id, user, service, ArticleStatus.DRAFT, note=(payload or RejectIn()).note)


@router.post("/{article_id}/publish", response_model=ArticleAdminOut)
async def publish_article(article_id: int, user: EditorDep, service: ArticleServiceDep) -> ArticleAdminOut:
    return await _transition(article_id, user, service, ArticleStatus.PUBLISHED)


@router.post("/{article_id}/schedule", response_model=ArticleAdminOut)
async def schedule_article(
    article_id: int, payload: ScheduleIn, user: EditorDep, service: ArticleServiceDep
) -> ArticleAdminOut:
    """Editor: go live automatically at `publish_at` (and optionally archive at `unpublish_at`)."""
    return await _transition(
        article_id, user, service, ArticleStatus.SCHEDULED, publish_at=payload.publish_at, unpublish_at=payload.unpublish_at
    )


@router.post("/{article_id}/unpublish", response_model=ArticleAdminOut)
async def unpublish_article(article_id: int, user: EditorDep, service: ArticleServiceDep) -> ArticleAdminOut:
    """Back to draft: no longer public, still editable. (Also cancels a schedule.)"""
    return await _transition(article_id, user, service, ArticleStatus.DRAFT)


@router.post("/{article_id}/archive", response_model=ArticleAdminOut)
async def archive_article(article_id: int, user: EditorDep, service: ArticleServiceDep) -> ArticleAdminOut:
    return await _transition(article_id, user, service, ArticleStatus.ARCHIVED)


@router.delete("/{article_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_article(article_id: int, user: EditorDep, service: ArticleServiceDep) -> None:
    await _run(service.delete(user, article_id))


# -- revisions -----------------------------------------------------------------------------


@router.get("/{article_id}/revisions", response_model=list[RevisionOut])
async def list_revisions(article_id: int, user: EditorDep, service: ArticleServiceDep) -> list[RevisionOut]:
    return await _run(service.list_revisions(user, article_id))


@router.get("/{article_id}/revisions/compare", response_model=RevisionDiff)
async def compare_revisions(
    article_id: int,
    user: EditorDep,
    service: ArticleServiceDep,
    from_version: Annotated[int, Query(ge=1)],
    to_version: Annotated[int, Query(ge=1)],
) -> RevisionDiff:
    return await _run(service.compare_revisions(user, article_id, from_version, to_version))


@router.get("/{article_id}/revisions/{version}", response_model=RevisionDetail)
async def get_revision(article_id: int, version: int, user: EditorDep, service: ArticleServiceDep) -> RevisionDetail:
    return await _run(service.get_revision(user, article_id, version))


@router.post("/{article_id}/revisions/{version}/restore", response_model=ArticleAdminOut)
async def restore_revision(article_id: int, version: int, user: EditorDep, service: ArticleServiceDep) -> ArticleAdminOut:
    """Restore an older version's content and metadata as a new revision. Publication
    state is left alone: restoring text is not publishing."""
    article = await _run(service.restore_revision(user, article_id, version))
    return await service.to_admin(article)
