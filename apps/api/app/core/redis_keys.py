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
    def competition_standings(competition_id: int | str) -> str:
        return f"football:competition:{competition_id}:standings"

    @staticmethod
    def team_fixtures(team_id: int | str) -> str:
        return f"football:team:{team_id}:fixtures"

    # -- pub/sub ----------------------------------------------------------
    MATCH_EVENTS_CHANNEL = "football:events"
    """Single Redis Pub/Sub channel the worker publishes RealtimeEvent
    payloads to; the WebSocket layer subscribes once and fans out to the
    right connections (general + match-specific) based on the payload's
    match_id, rather than using one channel per match."""
