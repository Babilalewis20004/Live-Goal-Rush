from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api.deps import AuthServiceDep, CurrentUserDep
from app.schemas.user import PasswordChange, UserOut, UserUpdate
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
