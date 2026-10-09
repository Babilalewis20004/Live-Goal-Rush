from fastapi import APIRouter, HTTPException

from app.api.deps import CurrentUserDep, ProfileServiceDep
from app.schemas.community import MyProfileOut, ProfileOut, ProfileUpdate

router = APIRouter()
me_router = APIRouter()


@router.get("/{user_id}", response_model=ProfileOut)
async def get_public_profile(user_id: int, service: ProfileServiceDep) -> ProfileOut:
    """404 unless the user chose to make their profile public -- the same answer
    for "no such user" and "private", so profiles can't be probed for existence."""
    profile = await service.get_public(user_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


@me_router.get("", response_model=MyProfileOut)
async def get_my_profile(user: CurrentUserDep, service: ProfileServiceDep) -> MyProfileOut:
    return await service.get_mine(user)


@me_router.patch("", response_model=MyProfileOut)
async def update_my_profile(payload: ProfileUpdate, user: CurrentUserDep, service: ProfileServiceDep) -> MyProfileOut:
    return await service.update(user, payload)


# -- Phase 6b: reporting and moderation of profiles -----------------------------------------------------

from typing import Annotated  # noqa: E402

from fastapi import Depends, Query, status  # noqa: E402

from app.api.deps import ModerationServiceDep, ReviewerDep  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.rate_limit import rate_limiter  # noqa: E402
from app.models.enums import ReportStatus  # noqa: E402
from app.schemas.common import Page  # noqa: E402
from app.schemas.community import ProfileReportIn, SuspendIn  # noqa: E402
from app.services.moderation_service import ModerationError, ProfileReportOut  # noqa: E402

moderation_router = APIRouter()


def _http(exc: ModerationError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


@router.post(
    "/{user_id}/report",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(rate_limiter("profile-report", settings.profile_reports_per_hour, 3600))],
)
async def report_profile(user_id: int, payload: ProfileReportIn, user: CurrentUserDep, service: ModerationServiceDep) -> None:
    try:
        await service.report_profile(user, user_id, payload.reason)
    except ModerationError as exc:
        raise _http(exc) from exc


@moderation_router.get("/profile-reports", response_model=Page[ProfileReportOut])
async def list_profile_reports(
    user: ReviewerDep,
    service: ModerationServiceDep,
    report_status: Annotated[ReportStatus, Query(alias="status")] = ReportStatus.OPEN,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[ProfileReportOut]:
    try:
        items, total = await service.list_profile_reports(user, report_status, page, page_size)
    except ModerationError as exc:
        raise _http(exc) from exc
    return Page(items=items, total=total, page=page, page_size=page_size)


@moderation_router.post("/profile-reports/{report_id}/{action}", status_code=status.HTTP_204_NO_CONTENT)
async def resolve_profile_report(report_id: int, action: str, user: ReviewerDep, service: ModerationServiceDep) -> None:
    try:
        await service.resolve_profile_report(user, report_id, action)
    except ModerationError as exc:
        raise _http(exc) from exc


@moderation_router.post("/users/{user_id}/suspend", status_code=status.HTTP_204_NO_CONTENT)
async def suspend_user(user_id: int, payload: SuspendIn, user: CurrentUserDep, service: ModerationServiceDep) -> None:
    try:
        await service.suspend(user, user_id, payload.reason)
    except ModerationError as exc:
        raise _http(exc) from exc


@moderation_router.post("/users/{user_id}/unsuspend", status_code=status.HTTP_204_NO_CONTENT)
async def unsuspend_user(user_id: int, user: CurrentUserDep, service: ModerationServiceDep) -> None:
    try:
        await service.unsuspend(user, user_id)
    except ModerationError as exc:
        raise _http(exc) from exc
