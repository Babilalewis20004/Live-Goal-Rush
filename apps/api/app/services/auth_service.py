"""Authentication business logic (Phase 3 §5).

Kept out of the route handlers (`api/v1/auth.py`/`users.py`), matching this
codebase's existing convention that services -- not routers -- own business
logic. There's no separate repositories/crud layer in this codebase either
(see `football_service.py`), so this service talks to the database
directly, the same way.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.redis_client import RedisService
from app.core.redis_keys import RedisKeys
from app.core.security import (
    create_access_token,
    generate_raw_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.models.session import PasswordResetToken, RefreshToken
from app.models.user import User

logger = logging.getLogger(__name__)

_LOGIN_ATTEMPTS_PER_EMAIL_WINDOW = 5
_LOGIN_EMAIL_WINDOW_SECONDS = 60


class AuthError(Exception):
    """Base class for auth failures the router translates into HTTP responses."""


class EmailAlreadyRegisteredError(AuthError):
    pass


class InvalidCredentialsError(AuthError):
    pass


class RateLimitedError(AuthError):
    pass


class InvalidTokenError(AuthError):
    pass


@dataclass
class IssuedTokens:
    access_token: str
    refresh_token: str


class AuthService:
    def __init__(self, db: AsyncSession, redis: RedisService) -> None:
        self._db = db
        self._redis = redis

    # -- registration / login -------------------------------------------------

    async def register(
        self,
        email: str,
        password: str,
        display_name: str | None,
        *,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> tuple[User, IssuedTokens]:
        existing = await self._db.scalar(select(User).where(User.email == email))
        if existing is not None:
            raise EmailAlreadyRegisteredError()
        user = User(email=email, hashed_password=hash_password(password), display_name=display_name)
        self._db.add(user)
        await self._db.commit()
        await self._db.refresh(user)
        logger.info("Registered new user id=%s", user.id)
        tokens = await self._issue_tokens(user, user_agent=user_agent, ip_address=ip_address)
        return user, tokens

    async def _check_login_rate_limit(self, email: str) -> None:
        key = RedisKeys.rate_limit("login-email", email)
        try:
            count = await self._redis.incr(key, ttl_seconds=_LOGIN_EMAIL_WINDOW_SECONDS)
        except Exception:
            logger.warning("Login rate limiter failed open", exc_info=True)
            return
        if count > _LOGIN_ATTEMPTS_PER_EMAIL_WINDOW:
            raise RateLimitedError()

    async def login(
        self,
        email: str,
        password: str,
        *,
        user_agent: str | None,
        ip_address: str | None,
    ) -> tuple[User, IssuedTokens]:
        await self._check_login_rate_limit(email)
        user = await self._db.scalar(select(User).where(User.email == email))
        if user is None or not user.is_active or not verify_password(password, user.hashed_password):
            logger.info("Login failed (invalid credentials)")
            raise InvalidCredentialsError()
        tokens = await self._issue_tokens(user, user_agent=user_agent, ip_address=ip_address)
        logger.info("User id=%s logged in", user.id)
        return user, tokens

    # -- token issuance / refresh ----------------------------------------------

    async def _issue_tokens(
        self, user: User, *, user_agent: str | None, ip_address: str | None
    ) -> IssuedTokens:
        access_token = create_access_token(user.id)
        raw_refresh = generate_raw_token()
        refresh_row = RefreshToken(
            user_id=user.id,
            token_hash=hash_token(raw_refresh),
            expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days),
            user_agent=user_agent,
            ip_address=ip_address,
        )
        self._db.add(refresh_row)
        await self._db.commit()
        return IssuedTokens(access_token=access_token, refresh_token=raw_refresh)

    async def refresh(
        self,
        raw_refresh_token: str,
        *,
        user_agent: str | None,
        ip_address: str | None,
    ) -> tuple[User, IssuedTokens]:
        token_hash = hash_token(raw_refresh_token)
        row = await self._db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
        if row is None:
            raise InvalidTokenError()
        if row.revoked_at is not None:
            # This token was already rotated away -- presenting it again
            # means whoever holds it isn't the legitimate client anymore.
            # Revoke the whole chain rather than just this row.
            logger.warning("Refresh token reuse detected for user_id=%s", row.user_id)
            await self._revoke_all_for_user(row.user_id)
            raise InvalidTokenError()
        if row.expires_at < datetime.now(timezone.utc):
            raise InvalidTokenError()

        user = await self._db.get(User, row.user_id)
        if user is None or not user.is_active:
            raise InvalidTokenError()

        new_tokens = await self._issue_tokens(user, user_agent=user_agent, ip_address=ip_address)
        new_row = await self._db.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == hash_token(new_tokens.refresh_token))
        )
        row.revoked_at = datetime.now(timezone.utc)
        row.replaced_by_id = new_row.id if new_row is not None else None
        await self._db.commit()
        return user, new_tokens

    async def _revoke_all_for_user(self, user_id: int) -> None:
        result = await self._db.execute(
            select(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        )
        now = datetime.now(timezone.utc)
        for row in result.scalars():
            row.revoked_at = now
        await self._db.commit()

    async def logout(self, raw_refresh_token: str | None) -> None:
        if not raw_refresh_token:
            return
        token_hash = hash_token(raw_refresh_token)
        row = await self._db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
        if row is not None and row.revoked_at is None:
            row.revoked_at = datetime.now(timezone.utc)
            await self._db.commit()

    # -- profile / password -----------------------------------------------------

    async def update_profile(self, user: User, *, display_name: str | None) -> User:
        user.display_name = display_name
        await self._db.commit()
        await self._db.refresh(user)
        return user

    async def change_password(self, user: User, current_password: str, new_password: str) -> None:
        if not verify_password(current_password, user.hashed_password):
            raise InvalidCredentialsError()
        user.hashed_password = hash_password(new_password)
        await self._db.commit()
        # Changing the password invalidates every other logged-in session.
        await self._revoke_all_for_user(user.id)

    # -- password reset -----------------------------------------------------------

    async def request_password_reset(self, email: str) -> str | None:
        """Always looks and behaves the same whether or not `email` exists,
        so the response never reveals account existence (Phase 3 §5).
        Returns a dev-only reset URL (never in production) for local
        testing without a real email provider -- see module docstring."""
        user = await self._db.scalar(select(User).where(User.email == email))
        if user is None:
            logger.info("Password reset requested for an unregistered email")
            return None

        raw_token = generate_raw_token()
        reset_row = PasswordResetToken(
            user_id=user.id,
            token_hash=hash_token(raw_token),
            expires_at=datetime.now(timezone.utc)
            + timedelta(minutes=settings.password_reset_token_expire_minutes),
        )
        self._db.add(reset_row)
        await self._db.commit()

        reset_url = f"/reset-password?token={raw_token}"
        logger.info("Password reset link for user_id=%s: %s", user.id, reset_url)
        return reset_url if settings.environment != "production" else None

    async def confirm_password_reset(self, raw_token: str, new_password: str) -> None:
        token_hash = hash_token(raw_token)
        row = await self._db.scalar(
            select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
        )
        if row is None or row.used_at is not None or row.expires_at < datetime.now(timezone.utc):
            raise InvalidTokenError()
        user = await self._db.get(User, row.user_id)
        if user is None:
            raise InvalidTokenError()

        user.hashed_password = hash_password(new_password)
        row.used_at = datetime.now(timezone.utc)
        await self._db.commit()
        await self._revoke_all_for_user(user.id)
