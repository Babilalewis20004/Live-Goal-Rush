from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis_client import RedisService, get_redis_service
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.enums import UserRole
from app.models.user import User
from app.services.analytics_service import AnalyticsService
from app.services.article_service import ArticleService
from app.services.billing.entitlements import entitlements_for, payment_required
from app.services.billing.providers import ProviderError, get_billing_provider
from app.services.billing.service import BillingService
from app.services.metrics import metrics
from app.services.moderation_service import ModerationService
from app.services.prediction_service import PredictionService
from app.services.auth_service import AuthService
from app.services.cache import CacheAside
from app.services.community_service import CommentService, PollService, ReactionService
from app.services.discovery_service import DiscoveryService
from app.services.favourites_service import FavouritesService
from app.services.football_service import FootballService
from app.services.form_service import FormService
from app.services.insights_service import InsightsService
from app.services.media_service import MediaService
from app.services.match_centre_service import MatchCentreService
from app.services.notification_preferences_service import (
    DevicesService,
    NotificationPreferencesService,
)
from app.services.providers import get_provider
from app.services.search_service import SearchService
from app.services.profile_service import ProfileService
from app.services.providers.base import FootballDataProvider
from app.services.storage import StorageBackend, get_storage
from app.services.team_player_service import TeamPlayerService

RedisServiceDep = Annotated[RedisService, Depends(get_redis_service)]


ProviderDep = Annotated[FootballDataProvider, Depends(get_provider)]


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


def get_match_centre_service(
    db: Annotated[AsyncSession, Depends(get_db)],
    provider: Annotated[FootballDataProvider, Depends(get_provider)],
    cache: CacheDep,
) -> MatchCentreService:
    return MatchCentreService(db=db, provider=provider, cache=cache)


MatchCentreServiceDep = Annotated[MatchCentreService, Depends(get_match_centre_service)]


def get_team_player_service(
    db: Annotated[AsyncSession, Depends(get_db)],
    provider: Annotated[FootballDataProvider, Depends(get_provider)],
    cache: CacheDep,
) -> TeamPlayerService:
    return TeamPlayerService(db=db, provider=provider, cache=cache)


TeamPlayerServiceDep = Annotated[TeamPlayerService, Depends(get_team_player_service)]


def get_form_service(
    db: Annotated[AsyncSession, Depends(get_db)],
    cache: CacheDep,
) -> FormService:
    return FormService(db=db, cache=cache)


FormServiceDep = Annotated[FormService, Depends(get_form_service)]


DbDep = Annotated[AsyncSession, Depends(get_db)]


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


async def _resolve_user(
    db: AsyncSession, authorization: str | None, access_token: str | None, request: Request | None = None
) -> User | None:
    token: str | None = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[len("bearer ") :]
    elif access_token:
        token = access_token
    if token is None:
        return None
    try:
        payload = decode_access_token(token)
        user_id = int(payload["sub"])
    except Exception:
        return None
    user = await db.get(User, user_id)
    if user is None or not user.is_active or user.suspended_at is not None:
        return None
    if request is not None:
        request.state.user_id = user.id  # read by the request-log middleware (never the token or email)
    return user


async def get_current_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
    access_token: Annotated[str | None, Cookie()] = None,
) -> User:
    """Web sends the token as an httpOnly `access_token` cookie; mobile
    (which has no cookie jar semantics worth relying on) sends
    `Authorization: Bearer <token>` instead -- this is the WebSocket auth
    extension point's HTTP-side counterpart, checked wherever a route
    declares `CurrentUserDep`."""
    user = await _resolve_user(db, authorization, access_token, request)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def get_optional_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
    access_token: Annotated[str | None, Cookie()] = None,
) -> User | None:
    """Public endpoints that behave slightly better when the caller is signed
    in (e.g. remembering a search). An invalid token is treated as anonymous."""
    return await _resolve_user(db, authorization, access_token, request)


CurrentUserDep = Annotated[User, Depends(get_current_user)]
OptionalUserDep = Annotated[User | None, Depends(get_optional_user)]


def get_admin(user: CurrentUserDep) -> User:
    """Operations endpoints (users, audit log, failed jobs, system health). Admin only -- an editor's
    content powers do not extend to inspecting accounts or infrastructure."""
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator access required")
    return user


AdminDep = Annotated[User, Depends(get_admin)]


def get_editor(user: CurrentUserDep) -> User:
    """Any staff role: author, editor or admin (granted via `app/cli.py`). What each
    may *do* is decided by `ArticleService`, not here."""
    if user.role not in (UserRole.AUTHOR, UserRole.EDITOR, UserRole.ADMIN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Editorial access required")
    return user


EditorDep = Annotated[User, Depends(get_editor)]


def get_reviewer(user: CurrentUserDep) -> User:
    """Editors and admins: review, publish, moderate, create polls."""
    if user.role not in (UserRole.EDITOR, UserRole.ADMIN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Editor access required")
    return user


ReviewerDep = Annotated[User, Depends(get_reviewer)]


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


# -- Discovery (Phase 5): content, trending/feed, unified search -----------------


def get_article_service(
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: RedisServiceDep,
) -> ArticleService:
    return ArticleService(db=db, redis=redis)


ArticleServiceDep = Annotated[ArticleService, Depends(get_article_service)]


def get_discovery_service(
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: RedisServiceDep,
    articles: ArticleServiceDep,
) -> DiscoveryService:
    return DiscoveryService(db=db, redis=redis, articles=articles)


DiscoveryServiceDep = Annotated[DiscoveryService, Depends(get_discovery_service)]


def get_search_service(
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: RedisServiceDep,
    football: Annotated[FootballService, Depends(get_football_service)],
    articles: ArticleServiceDep,
) -> SearchService:
    return SearchService(db=db, redis=redis, football=football, articles=articles)


SearchServiceDep = Annotated[SearchService, Depends(get_search_service)]


# -- Phase 6: media, community, profiles, insights ---------------------------------------


def get_storage_dep() -> StorageBackend:
    return get_storage()


StorageDep = Annotated[StorageBackend, Depends(get_storage_dep)]


def get_media_service(
    db: Annotated[AsyncSession, Depends(get_db)], storage: StorageDep, redis: RedisServiceDep
) -> MediaService:
    return MediaService(db=db, storage=storage, redis=redis)


MediaServiceDep = Annotated[MediaService, Depends(get_media_service)]


def get_comment_service(db: Annotated[AsyncSession, Depends(get_db)], redis: RedisServiceDep) -> CommentService:
    return CommentService(db=db, redis=redis)


CommentServiceDep = Annotated[CommentService, Depends(get_comment_service)]


def get_reaction_service(db: Annotated[AsyncSession, Depends(get_db)], redis: RedisServiceDep) -> ReactionService:
    return ReactionService(db=db, redis=redis)


ReactionServiceDep = Annotated[ReactionService, Depends(get_reaction_service)]


def get_poll_service(db: Annotated[AsyncSession, Depends(get_db)], redis: RedisServiceDep) -> PollService:
    return PollService(db=db, redis=redis)


PollServiceDep = Annotated[PollService, Depends(get_poll_service)]


def get_profile_service(db: Annotated[AsyncSession, Depends(get_db)]) -> ProfileService:
    return ProfileService(db=db)


ProfileServiceDep = Annotated[ProfileService, Depends(get_profile_service)]


def get_insights_service(db: Annotated[AsyncSession, Depends(get_db)], cache: CacheDep) -> InsightsService:
    return InsightsService(db=db, cache=cache)


InsightsServiceDep = Annotated[InsightsService, Depends(get_insights_service)]


def get_analytics_service(db: Annotated[AsyncSession, Depends(get_db)], cache: CacheDep) -> AnalyticsService:
    return AnalyticsService(db, cache)


AnalyticsServiceDep = Annotated[AnalyticsService, Depends(get_analytics_service)]


def get_prediction_service(db: Annotated[AsyncSession, Depends(get_db)], cache: CacheDep) -> PredictionService:
    return PredictionService(db, cache)


PredictionServiceDep = Annotated[PredictionService, Depends(get_prediction_service)]


def get_billing_service(db: Annotated[AsyncSession, Depends(get_db)]) -> BillingService:
    try:
        provider = get_billing_provider()
    except ProviderError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Billing is not available") from exc
    return BillingService(db, provider)


BillingServiceDep = Annotated[BillingService, Depends(get_billing_service)]


async def get_entitlements(
    db: Annotated[AsyncSession, Depends(get_db)], user: OptionalUserDep
) -> frozenset[str]:
    """What the caller may use, computed from the database on every request (never from
    the client, never cached) -- the single source for premium enforcement."""
    return await entitlements_for(db, user)


EntitlementsDep = Annotated[frozenset[str], Depends(get_entitlements)]


def require_entitlement(ents: frozenset[str], key: str) -> None:
    """Raise 402 naming the missing entitlement; counts the denial."""
    if key not in ents:
        metrics.count("premium_feature_denied_total")
        raise payment_required(key)
    metrics.count("premium_feature_usage_total")


def get_moderation_service(db: Annotated[AsyncSession, Depends(get_db)]) -> ModerationService:
    return ModerationService(db)


ModerationServiceDep = Annotated[ModerationService, Depends(get_moderation_service)]
