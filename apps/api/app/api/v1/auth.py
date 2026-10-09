"""Authentication endpoints (Phase 3 §5/§23).

Web auth transport is httpOnly cookies (`access_token`/`refresh_token`),
set here on every register/login/refresh -- a browser page's own JS never
sees them (spec §22). Mobile has no equivalent cookie-jar story worth
relying on, so a request carrying `X-Client: mobile` additionally gets the
raw tokens in the JSON body; the Expo app stores them in
`expo-secure-store` and sends `Authorization: Bearer` on every later
request (see `api/deps.py::get_current_user`).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response, status

from app.api.deps import AuthServiceDep
from app.core.config import settings
from app.core.rate_limit import rate_limiter
from app.schemas.user import (
    AuthResponse,
    PasswordResetConfirm,
    PasswordResetRequest,
    PasswordResetRequestOut,
    RefreshRequest,
    TokenResponse,
    UserLogin,
    UserOut,
    UserRegister,
)
from app.services.auth_service import (
    AccountSuspendedError,
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    InvalidTokenError,
    RateLimitedError,
)

router = APIRouter()

_ACCESS_COOKIE = "access_token"
_REFRESH_COOKIE = "refresh_token"


def _is_mobile(x_client: str | None) -> bool:
    return (x_client or "").strip().lower() == "mobile"


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    secure = settings.is_deployed
    response.set_cookie(
        _ACCESS_COOKIE,
        access_token,
        httponly=True,
        samesite="lax",
        secure=secure,
        max_age=settings.access_token_expire_minutes * 60,
        path="/",
    )
    response.set_cookie(
        _REFRESH_COOKIE,
        refresh_token,
        httponly=True,
        samesite="lax",
        secure=secure,
        max_age=settings.refresh_token_expire_days * 24 * 3600,
        path="/",
    )


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(_ACCESS_COOKIE, path="/")
    response.delete_cookie(_REFRESH_COOKIE, path="/")


def _auth_response(user, tokens, x_client: str | None) -> AuthResponse:
    body_tokens = (
        TokenResponse(access_token=tokens.access_token, refresh_token=tokens.refresh_token)
        if _is_mobile(x_client)
        else None
    )
    return AuthResponse(user=UserOut.model_validate(user), tokens=body_tokens)


@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limiter("register", settings.rate_limit_register_per_hour, 3600))],
)
async def register(
    payload: UserRegister,
    request: Request,
    response: Response,
    service: AuthServiceDep,
    x_client: Annotated[str | None, Header()] = None,
) -> AuthResponse:
    try:
        user, tokens = await service.register(
            payload.email,
            payload.password,
            payload.display_name,
            user_agent=request.headers.get("user-agent"),
            ip_address=_client_ip(request),
        )
    except EmailAlreadyRegisteredError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="An account with that email already exists"
        ) from exc
    _set_auth_cookies(response, tokens.access_token, tokens.refresh_token)
    return _auth_response(user, tokens, x_client)


@router.post(
    "/login",
    response_model=AuthResponse,
    dependencies=[Depends(rate_limiter("login", settings.rate_limit_login_per_minute, 60))],
)
async def login(
    payload: UserLogin,
    request: Request,
    response: Response,
    service: AuthServiceDep,
    x_client: Annotated[str | None, Header()] = None,
) -> AuthResponse:
    try:
        user, tokens = await service.login(
            payload.email,
            payload.password,
            user_agent=request.headers.get("user-agent"),
            ip_address=_client_ip(request),
        )
    except RateLimitedError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts for this account. Please try again shortly.",
            headers={"Retry-After": "60"},
        ) from exc
    except AccountSuspendedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This account has been suspended.") from exc
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password"
        ) from exc
    _set_auth_cookies(response, tokens.access_token, tokens.refresh_token)
    return _auth_response(user, tokens, x_client)


@router.post("/refresh", response_model=AuthResponse)
async def refresh_tokens(
    payload: RefreshRequest,
    request: Request,
    response: Response,
    service: AuthServiceDep,
    x_client: Annotated[str | None, Header()] = None,
    refresh_token_cookie: Annotated[str | None, Cookie(alias="refresh_token")] = None,
) -> AuthResponse:
    raw_token = payload.refresh_token or refresh_token_cookie
    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing refresh token")
    try:
        user, tokens = await service.refresh(
            raw_token,
            user_agent=request.headers.get("user-agent"),
            ip_address=_client_ip(request),
        )
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token"
        ) from exc
    _set_auth_cookies(response, tokens.access_token, tokens.refresh_token)
    return _auth_response(user, tokens, x_client)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    service: AuthServiceDep,
    payload: RefreshRequest | None = None,
    refresh_token_cookie: Annotated[str | None, Cookie(alias="refresh_token")] = None,
) -> None:
    raw_token = (payload.refresh_token if payload else None) or refresh_token_cookie
    await service.logout(raw_token)
    _clear_auth_cookies(response)


@router.post(
    "/password-reset/request",
    response_model=PasswordResetRequestOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[
        Depends(rate_limiter("password-reset", settings.rate_limit_password_reset_per_hour, 3600))
    ],
)
async def request_password_reset(
    payload: PasswordResetRequest, service: AuthServiceDep
) -> PasswordResetRequestOut:
    dev_reset_url = await service.request_password_reset(payload.email)
    return PasswordResetRequestOut(
        detail="If an account with that email exists, a password reset link has been sent.",
        dev_reset_url=dev_reset_url,
    )


@router.post("/password-reset/confirm", status_code=status.HTTP_204_NO_CONTENT)
async def confirm_password_reset(payload: PasswordResetConfirm, service: AuthServiceDep) -> None:
    try:
        await service.confirm_password_reset(payload.token, payload.new_password)
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired reset token"
        ) from exc
