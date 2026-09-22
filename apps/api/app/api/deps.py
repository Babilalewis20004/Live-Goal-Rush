from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis_client import RedisService, get_redis_service
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.user import User
from app.services.auth_service import AuthService
from app.services.cache import CacheAside
from app.services.favourites_service import FavouritesService
from app.services.football_service import FootballService
from app.services.notification_preferences_service import (
    DevicesService,
    NotificationPreferencesService,
)
from app.services.providers import get_provider
from app.services.providers.base import FootballDataProvider

RedisServiceDep = Annotated[RedisService, Depends(get_redis_service)]


def get_cache(redis: RedisServiceDep) -> CacheAside:
    return CacheAside(redis)


CacheDep = Annotated[CacheAside, Depends(get_cache)]


def get_football_service(
    db: Annotated[AsyncSession, Depends(get_db)],
    provider: Annotated[FootballDataProvider, Depends(get_provider)],
    cache: CacheDep,
) -> FootballService:
    return FootballService(db=db, provider=provider, cache=cache)


FootballServiceDep = Annotated[FootballService, Depends(get_football_service)]


def pagination_params(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> tuple[int, int]:
    return page, page_size


PaginationDep = Annotated[tuple[int, int], Depends(pagination_params)]


def get_auth_service(
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: RedisServiceDep,
) -> AuthService:
    return AuthService(db=db, redis=redis)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


async def get_current_user(
    db: Annotated[AsyncSession, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
    access_token: Annotated[str | None, Cookie()] = None,
) -> User:
    """Web sends the token as an httpOnly `access_token` cookie; mobile
    (which has no cookie jar semantics worth relying on) sends
    `Authorization: Bearer <token>` instead -- this is the WebSocket auth
    extension point's HTTP-side counterpart, checked wherever a route
    declares `CurrentUserDep`."""
    token: str | None = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[len("bearer ") :]
    elif access_token:
        token = access_token

    unauthenticated = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if token is None:
        raise unauthenticated
    try:
        payload = decode_access_token(token)
        user_id = int(payload["sub"])
    except Exception as exc:
        raise unauthenticated from exc

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise unauthenticated
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


def get_favourites_service(db: Annotated[AsyncSession, Depends(get_db)]) -> FavouritesService:
    return FavouritesService(db=db)


FavouritesServiceDep = Annotated[FavouritesService, Depends(get_favourites_service)]


def get_devices_service(db: Annotated[AsyncSession, Depends(get_db)]) -> DevicesService:
    return DevicesService(db=db)


DevicesServiceDep = Annotated[DevicesService, Depends(get_devices_service)]


def get_notification_preferences_service(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> NotificationPreferencesService:
    return NotificationPreferencesService(db=db)


NotificationPreferencesServiceDep = Annotated[
    NotificationPreferencesService, Depends(get_notification_preferences_service)
]
