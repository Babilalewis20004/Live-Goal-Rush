"""Comments, moderation, reactions and polls."""

import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.api.deps import (
    CommentServiceDep,
    CurrentUserDep,
    OptionalUserDep,
    PollServiceDep,
    ReactionServiceDep,
    ReviewerDep,
)
from app.models.enums import CommentTarget, PollStatus, ReactionTarget, ReportStatus
from app.schemas.common import Page
from app.schemas.community import (
    CommentEdit,
    CommentIn,
    CommentOut,
    CommentPage,
    ModerationAction,
    PollIn,
    PollOut,
    ReactionIn,
    ReactionSummary,
    ReportIn,
    ReportOut,
    VoteIn,
)
from app.services.community_service import CommentService, CommunityError, RateLimited
from app.worker.social_tasks import notify_comment_reply, notify_poll_results

logger = logging.getLogger(__name__)

comments_router = APIRouter()
moderation_router = APIRouter()
reactions_router = APIRouter()
polls_router = APIRouter()
editor_polls_router = APIRouter()


def _http(exc: CommunityError) -> HTTPException:
    headers = {"Retry-After": "30"} if isinstance(exc, RateLimited) else None
    return HTTPException(status_code=exc.status_code, detail=str(exc), headers=headers)


async def _run(call):
    try:
        return await call
    except CommunityError as exc:
        raise _http(exc) from exc


def _enqueue(task, *args) -> None:
    try:
        task.delay(*args)
    except Exception:
        logger.warning("Could not enqueue %s%s", getattr(task, "name", task), args, exc_info=True)


# -- comments ---------------------------------------------------------------------------------


@comments_router.get("", response_model=CommentPage)
async def list_comments(
    service: CommentServiceDep,
    viewer: OptionalUserDep,
    target_type: CommentTarget,
    target_id: Annotated[int, Query(ge=1)],
    sort: Annotated[str, Query(pattern="^(newest|top)$")] = "newest",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 20,
) -> CommentPage:
    return await _run(service.list(target_type, target_id, sort=sort, page=page, page_size=page_size, viewer=viewer))


@comments_router.post("", response_model=CommentOut, status_code=status.HTTP_201_CREATED)
async def create_comment(payload: CommentIn, user: CurrentUserDep, service: CommentServiceDep) -> CommentOut:
    comment = await _run(service.create(user, payload.target_type, payload.target_id, payload.body, payload.parent_id))
    if comment.parent_id is not None:
        _enqueue(notify_comment_reply, comment.id)
    out = CommentService._out(comment, removed=False)
    out.mine = True
    return out


@comments_router.patch("/{comment_id}", response_model=CommentOut)
async def edit_comment(comment_id: int, payload: CommentEdit, user: CurrentUserDep, service: CommentServiceDep) -> CommentOut:
    comment = await _run(service.edit(user, comment_id, payload.body))
    out = CommentService._out(comment, removed=False)
    out.mine = True
    return out


@comments_router.delete("/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(comment_id: int, user: CurrentUserDep, service: CommentServiceDep) -> None:
    await _run(service.delete(user, comment_id))


@comments_router.put("/{comment_id}/like")
async def like_comment(comment_id: int, user: CurrentUserDep, service: CommentServiceDep) -> dict[str, int | bool]:
    return {"like_count": await _run(service.like(user, comment_id, True)), "liked_by_me": True}


@comments_router.delete("/{comment_id}/like")
async def unlike_comment(comment_id: int, user: CurrentUserDep, service: CommentServiceDep) -> dict[str, int | bool]:
    return {"like_count": await _run(service.like(user, comment_id, False)), "liked_by_me": False}


@comments_router.post("/{comment_id}/report", status_code=status.HTTP_204_NO_CONTENT)
async def report_comment(comment_id: int, payload: ReportIn, user: CurrentUserDep, service: CommentServiceDep) -> None:
    await _run(service.report(user, comment_id, payload.reason))


# -- moderation (editors / admins) ------------------------------------------------------------------


@moderation_router.get("/reports", response_model=Page[ReportOut])
async def list_reports(
    user: ReviewerDep,
    service: CommentServiceDep,
    report_status: Annotated[ReportStatus, Query(alias="status")] = ReportStatus.OPEN,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[ReportOut]:
    items, total = await _run(service.list_reports(user, report_status, page, page_size))
    return Page(items=items, total=total, page=page, page_size=page_size)


@moderation_router.post("/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def moderate_comment(comment_id: int, payload: ModerationAction, user: ReviewerDep, service: CommentServiceDep) -> None:
    await _run(service.moderate(user, comment_id, payload.action))


# -- reactions ---------------------------------------------------------------------------------------


@reactions_router.get("/{target_type}/{target_id}", response_model=ReactionSummary)
async def get_reactions(
    target_type: ReactionTarget, target_id: int, service: ReactionServiceDep, viewer: OptionalUserDep, response: Response
) -> ReactionSummary:
    return await _run(service.summary(target_type, target_id, viewer))


@reactions_router.put("/{target_type}/{target_id}", response_model=ReactionSummary)
async def react(
    target_type: ReactionTarget, target_id: int, payload: ReactionIn, user: CurrentUserDep, service: ReactionServiceDep
) -> ReactionSummary:
    return await _run(service.react(user, target_type, target_id, payload.kind))


@reactions_router.delete("/{target_type}/{target_id}", response_model=ReactionSummary)
async def remove_reaction(
    target_type: ReactionTarget, target_id: int, user: CurrentUserDep, service: ReactionServiceDep
) -> ReactionSummary:
    return await _run(service.remove(user, target_type, target_id))


# -- polls ------------------------------------------------------------------------------------------------


@polls_router.get("", response_model=list[PollOut])
async def list_polls(
    service: PollServiceDep,
    viewer: OptionalUserDep,
    match_id: Annotated[int | None, Query(ge=1)] = None,
    article_id: Annotated[int | None, Query(ge=1)] = None,
    poll_status: Annotated[PollStatus | None, Query(alias="status")] = None,
    standalone: bool = False,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[PollOut]:
    return await service.list(
        match_id=match_id, article_id=article_id, status=poll_status, standalone=standalone, limit=limit, viewer=viewer
    )


@polls_router.get("/{poll_id}", response_model=PollOut)
async def get_poll(poll_id: int, service: PollServiceDep, viewer: OptionalUserDep) -> PollOut:
    return await _run(service.get(poll_id, viewer))


@polls_router.post("/{poll_id}/vote", response_model=PollOut)
async def vote(poll_id: int, payload: VoteIn, user: CurrentUserDep, service: PollServiceDep) -> PollOut:
    return await _run(service.vote(user, poll_id, payload.option_id))


@editor_polls_router.post("", response_model=PollOut, status_code=status.HTTP_201_CREATED)
async def create_poll(payload: PollIn, user: ReviewerDep, service: PollServiceDep) -> PollOut:
    poll = await _run(service.create(user, payload))
    return await service.get(poll.id, user)


@editor_polls_router.post("/{poll_id}/close", response_model=PollOut)
async def close_poll(poll_id: int, user: ReviewerDep, service: PollServiceDep) -> PollOut:
    poll, newly_closed = await _run(service.close(user, poll_id))
    if newly_closed:
        _enqueue(notify_poll_results, poll_id)
    return poll


@editor_polls_router.delete("/{poll_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_poll(poll_id: int, user: ReviewerDep, service: PollServiceDep) -> None:
    await _run(service.delete(user, poll_id))
