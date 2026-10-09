"""Namespaced Redis key builders (Phase 2 §4).

Centralized here so the cache layer, the sync workers, and the pub/sub
publisher/subscriber all agree on key shape without hand-typing strings
throughout the codebase.
"""

from datetime import date


class RedisKeys:
    LIVE_MATCHES = "football:live"
    TODAY_MATCHES = "football:matches:today"

    @staticmethod
    def upcoming_matches(on_date: date | str) -> str:
        return f"football:matches:upcoming:{on_date}"

    @staticmethod
    def match(match_id: int | str) -> str:
        return f"football:match:{match_id}"

    @staticmethod
    def match_events(match_id: int | str) -> str:
        return f"football:match:{match_id}:events"

    @staticmethod
    def match_state(match_id: int | str) -> str:
        """Last-published normalized state for a match, used by change
        detection to diff against the newly-synced state. Not a
        user-facing cache entry -- no TTL, overwritten on every sync."""
        return f"football:match:{match_id}:state"

    @staticmethod
    def competition_fixtures(competition_id: int | str, on_date: date | str) -> str:
        return f"football:competition:{competition_id}:fixtures:{on_date}"

    @staticmethod
    def competition_standings(competition_id: int | str, season: str | None = None) -> str:
        """`season=None` is the "current season" entry (latest stored
        season) -- the one invalidated when a match finishes."""
        base = f"football:competition:{competition_id}:standings"
        return base if season is None else f"{base}:{season}"

    @staticmethod
    def competition_seasons(competition_id: int | str) -> str:
        return f"football:competition:{competition_id}:seasons"

    @staticmethod
    def competition_top_scorers(competition_id: int | str, season: str | None = None) -> str:
        base = f"football:competition:{competition_id}:top-scorers"
        return base if season is None else f"{base}:{season}"

    @staticmethod
    def team_fixtures(team_id: int | str) -> str:
        return f"football:team:{team_id}:fixtures"

    # -- Phase 4: match centre / teams / players ---------------------------
    @staticmethod
    def match_lineups(match_id: int | str) -> str:
        return f"football:match:{match_id}:lineups"

    @staticmethod
    def match_statistics(match_id: int | str) -> str:
        return f"football:match:{match_id}:statistics"

    @staticmethod
    def match_player_statistics(match_id: int | str) -> str:
        return f"football:match:{match_id}:players"

    @staticmethod
    def match_form(match_id: int | str) -> str:
        return f"football:match:{match_id}:form"

    @staticmethod
    def match_head_to_head(match_id: int | str, window: str = "last5") -> str:
        base = f"football:match:{match_id}:h2h"
        return base if window == "last5" else f"{base}:{window}"

    @staticmethod
    def team(team_id: int | str) -> str:
        return f"football:team:{team_id}"

    @staticmethod
    def team_form(team_id: int | str, scope: str = "overall", limit: int = 5) -> str:
        base = f"football:team:{team_id}:form:{scope}"
        return base if limit == 5 else f"{base}:{limit}"

    @staticmethod
    def team_analytics(team_id: int | str, scope: str = "overall", window: int = 10) -> str:
        return f"football:team:{team_id}:analytics:{scope}:{window}"

    @staticmethod
    def player_analytics(player_id: int | str, window: int = 10) -> str:
        return f"football:player:{player_id}:analytics:{window}"

    @staticmethod
    def match_comparison(match_id: int | str, tier: str) -> str:
        return f"football:match:{match_id}:comparison:{tier}"

    @staticmethod
    def match_prediction(match_id: int | str) -> str:
        return f"football:match:{match_id}:prediction"

    @staticmethod
    def team_squad(team_id: int | str) -> str:
        return f"football:team:{team_id}:squad"

    @staticmethod
    def team_statistics(team_id: int | str) -> str:
        return f"football:team:{team_id}:statistics"

    @staticmethod
    def player(player_id: int | str) -> str:
        return f"football:player:{player_id}"

    @staticmethod
    def player_statistics(player_id: int | str) -> str:
        return f"football:player:{player_id}:statistics"

    @staticmethod
    def sync_requested(kind: str, identifier: int | str) -> str:
        """Debounce marker so read endpoints that enqueue a background
        sync (an empty squad, an unenriched player) enqueue it once per
        window, not once per request."""
        return f"football:sync-requested:{kind}:{identifier}"

    # -- discovery: content, trending, feeds, search -------------------------
    ARTICLES_VERSION = "football:articles:ver"
    """Bumped on every content mutation. Public article cache keys embed it, so
    one INCR invalidates every cached list/detail/related entry at once (the
    old keys simply age out via their TTL)."""

    @staticmethod
    def article_cache(version: int | str, name: str) -> str:
        return f"football:articles:{version}:{name}"

    @staticmethod
    def trending(entity_type: str, window_hours: int) -> str:
        return f"football:trending:{entity_type}:{window_hours}h"

    @staticmethod
    def discovery_home(version: int | str) -> str:
        return f"football:discovery:home:{version}"

    @staticmethod
    def user_feed(user_id: int | str) -> str:
        """Per-user, never shared: the key embeds the user id and is only ever
        read for the authenticated caller."""
        return f"football:feed:user:{user_id}"

    @staticmethod
    def search_suggestions(normalized_query: str) -> str:
        return f"football:search:suggest:{normalized_query}"

    @staticmethod
    def search_results(normalized_query: str, limit: int) -> str:
        return f"football:search:results:{limit}:{normalized_query}"

    @staticmethod
    def popular_searches(day: str) -> str:
        return f"football:search:popular:{day}"

    ENGAGEMENT_COUNTS_PREFIX = "football:engagement:counts:"
    ENGAGEMENT_FLUSH_PREFIX = "football:engagement:flush:"

    @staticmethod
    def engagement_counts(bucket_epoch: int) -> str:
        return f"football:engagement:counts:{bucket_epoch}"

    @staticmethod
    def engagement_seen(signal: str, entity_type: str, entity_id: int | str, viewer: str) -> str:
        return f"football:engagement:seen:{signal}:{entity_type}:{entity_id}:{viewer}"

    @staticmethod
    def content_notification_cap(user_id: int | str, day: str) -> str:
        return f"football:content-notify:cap:{user_id}:{day}"

    # -- rate limiting (Phase 3 §21) ---------------------------------------
    @staticmethod
    def rate_limit(bucket: str, identifier: str) -> str:
        """Not football-cache data, so deliberately outside the `football:`
        namespace -- `bucket` is a fixed label (e.g. "login-email",
        "register") and `identifier` the thing being limited (an IP or
        email)."""
        return f"ratelimit:{bucket}:{identifier}"

    # -- pub/sub ----------------------------------------------------------
    MATCH_EVENTS_CHANNEL = "football:events"
    """Single Redis Pub/Sub channel the worker publishes RealtimeEvent
    payloads to; the WebSocket layer subscribes once and fans out to the
    right connections (general + match-specific) based on the payload's
    match_id, rather than using one channel per match."""
