from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import JSONResponse

from app.api.deps import AuthServiceDep, BillingServiceDep, CurrentUserDep, DbDep
from app.core.rate_limit import rate_limiter
from app.schemas.user import AccountDeleteRequest, PasswordChange, UserOut, UserUpdate
from app.services import account_service
from app.services.auth_service import InvalidCredentialsError

router = APIRouter()


@router.get("/me", response_model=UserOut)
async def get_me(current_user: CurrentUserDep) -> UserOut:
    return UserOut.model_validate(current_user)


@router.patch("/me", response_model=UserOut)
async def update_me(
    payload: UserUpdate, current_user: CurrentUserDep, service: AuthServiceDep
) -> UserOut:
    user = await service.update_profile(current_user, display_name=payload.display_name)
    return UserOut.model_validate(user)


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    payload: PasswordChange, current_user: CurrentUserDep, service: AuthServiceDep
) -> None:
    try:
        await service.change_password(current_user, payload.current_password, payload.new_password)
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect"
        ) from exc


@router.get("/me/export", dependencies=[Depends(rate_limiter("data-export", 5, 3600))])
async def export_my_data(current_user: CurrentUserDep, db: DbDep) -> JSONResponse:
    """Everything the signed-in user has given us or created, as a JSON download. Never includes credentials,
    payment-processor identifiers, IP addresses or anything about other people."""
    data = await account_service.export_user_data(db, current_user)
    return JSONResponse(
        content=data,
        headers={"Content-Disposition": 'attachment; filename="livepitch-my-data.json"', "Cache-Control": "no-store"},
    )


@router.delete(
    "/me",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(rate_limiter("account-delete", 5, 3600))],
)
async def delete_my_account(
    payload: AccountDeleteRequest, response: Response, current_user: CurrentUserDep, db: DbDep, billing: BillingServiceDep
) -> None:
    """Erases the account's personal data (irreversible; see `account_service`). Requires the current password,
    so a hijacked session alone cannot destroy an account, and cancels any subscription first."""
    try:
        await account_service.delete_account(db, current_user, payload.password, billing)
    except account_service.AccountError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
