from fastapi import APIRouter

from app.api.v1 import (
    admin,
    analytics,
    articles,
    auth,
    billing,
    community,
    capabilities,
    competitions,
    devices,
    discovery,
    editor,
    engagement,
    favourites,
    matches,
    media,
    notifications,
    players,
    profiles,
    search,
    teams,
    users,
)

api_router = APIRouter()
api_router.include_router(matches.router, prefix="/matches", tags=["matches"])
api_router.include_router(competitions.router, prefix="/competitions", tags=["competitions"])
api_router.include_router(teams.router, prefix="/teams", tags=["teams"])
api_router.include_router(players.router, prefix="/players", tags=["players"])
api_router.include_router(capabilities.router, prefix="/capabilities", tags=["capabilities"])
api_router.include_router(search.router, prefix="/search", tags=["search"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(favourites.router, prefix="/favourites", tags=["favourites"])
api_router.include_router(devices.router, prefix="/devices", tags=["devices"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
api_router.include_router(articles.router, prefix="/articles", tags=["news"])
api_router.include_router(editor.router, prefix="/editor/articles", tags=["editor"])
api_router.include_router(discovery.router, prefix="/discovery", tags=["discovery"])
api_router.include_router(discovery.feed_router, prefix="/feed", tags=["discovery"])
api_router.include_router(engagement.router, prefix="/engagement", tags=["discovery"])
api_router.include_router(media.router, prefix="/editor/media", tags=["media"])
api_router.include_router(media.public_router, prefix="/media", tags=["media"])
api_router.include_router(community.comments_router, prefix="/comments", tags=["community"])
api_router.include_router(community.moderation_router, prefix="/moderation", tags=["community"])
api_router.include_router(community.reactions_router, prefix="/reactions", tags=["community"])
api_router.include_router(community.polls_router, prefix="/polls", tags=["community"])
api_router.include_router(community.editor_polls_router, prefix="/editor/polls", tags=["community"])
api_router.include_router(profiles.router, prefix="/profiles", tags=["profiles"])
api_router.include_router(profiles.moderation_router, prefix="/moderation", tags=["community"])
api_router.include_router(profiles.me_router, prefix="/users/me/profile", tags=["profiles"])
api_router.include_router(analytics.teams_router, prefix="/teams", tags=["analytics"])
api_router.include_router(analytics.players_router, prefix="/players", tags=["analytics"])
api_router.include_router(analytics.matches_router, prefix="/matches", tags=["analytics"])
api_router.include_router(analytics.predictions_router, prefix="/predictions", tags=["analytics"])
api_router.include_router(analytics.me_router, prefix="/me", tags=["analytics"])
api_router.include_router(billing.subscription_router, prefix="/subscription", tags=["billing"])
api_router.include_router(billing.webhook_router, prefix="/billing", tags=["billing"])
api_router.include_router(billing.me_router, prefix="/me", tags=["billing"])
api_router.include_router(billing.ads_router, prefix="/ads", tags=["billing"])
# Operations endpoints last: Starlette tries routes in order, and the public hot paths should not wait behind them.
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
