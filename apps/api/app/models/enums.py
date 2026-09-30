import enum


class CompetitionType(str, enum.Enum):
    LEAGUE = "league"
    CUP = "cup"
    INTERNATIONAL = "international"


class MatchStatus(str, enum.Enum):
    SCHEDULED = "scheduled"
    LIVE = "live"
    HALFTIME = "halftime"
    FINISHED = "finished"
    POSTPONED = "postponed"
    CANCELLED = "cancelled"


class MatchEventType(str, enum.Enum):
    GOAL = "goal"
    OWN_GOAL = "own_goal"
    PENALTY = "penalty"
    PENALTY_MISSED = "penalty_missed"
    YELLOW_CARD = "yellow_card"
    SECOND_YELLOW = "second_yellow"
    RED_CARD = "red_card"
    SUBSTITUTION = "substitution"
    VAR = "var"


class DevicePlatform(str, enum.Enum):
    """Phase 3 §16: a user may register several of these (phone, tablet,
    browser) -- never assumed to be one-to-one with a user."""

    EXPO_IOS = "expo_ios"
    EXPO_ANDROID = "expo_android"
    WEB = "web"


class NotificationScope(str, enum.Enum):
    """What a `NotificationPreference` row narrows to (Phase 3 §14).
    `GLOBAL` preferences have `scope_id = None`; the others pair with a
    team/competition/match id."""

    GLOBAL = "global"
    TEAM = "team"
    COMPETITION = "competition"
    MATCH = "match"
