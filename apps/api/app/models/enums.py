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


class ArticleStatus(str, enum.Enum):
    """Discovery §10: only PUBLISHED articles are ever public."""

    DRAFT = "draft"
    IN_REVIEW = "in_review"
    SCHEDULED = "scheduled"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class UserRole(str, enum.Enum):
    """Content authorization. Everyone is USER; EDITORs write and publish
    their own articles; ADMINs manage everything. Granted out of band (see
    `app/cli.py`) -- there is deliberately no self-service way to get a role."""

    USER = "user"
    AUTHOR = "author"
    EDITOR = "editor"
    ADMIN = "admin"


class EngagementSignal(str, enum.Enum):
    VIEW = "view"
    SEARCH = "search"


class EngagementEntity(str, enum.Enum):
    ARTICLE = "article"
    TEAM = "team"
    PLAYER = "player"
    COMPETITION = "competition"
    MATCH = "match"


class ContentNotificationKind(str, enum.Enum):
    """Discovery §40: what kinds of article a user can be pushed."""

    TEAM_NEWS = "team_news"
    COMPETITION_NEWS = "competition_news"
    MATCH_REPORTS = "match_reports"
    TRANSFER_NEWS = "transfer_news"
    GENERAL_NEWS = "general_news"
    COMMENT_REPLIES = "comment_replies"
    POLL_RESULTS = "poll_results"
    EDITORIAL_UPDATES = "editorial_updates"
    PREDICTION_AVAILABLE = "prediction_available"
    TEAM_INSIGHTS = "team_insights"
    POLL_CLOSING = "poll_closing"
    SUBSCRIPTION_EVENTS = "subscription_events"


class CommentTarget(str, enum.Enum):
    ARTICLE = "article"
    MATCH = "match"


class CommentStatus(str, enum.Enum):
    VISIBLE = "visible"
    HIDDEN = "hidden"
    """Removed from public view by moderation (or automatically after several
    independent reports) -- kept so a moderator can restore it."""
    DELETED = "deleted"
    """Deleted by its author: shown as a tombstone only if it has replies."""


class ReportStatus(str, enum.Enum):
    OPEN = "open"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class ReactionKind(str, enum.Enum):
    THUMBS_UP = "thumbs_up"  # 👍
    FIRE = "fire"  # 🔥
    WOW = "wow"  # 😮
    GOAL = "goal"  # ⚽
    HEART = "heart"  # ❤️
    LAUGH = "laugh"  # 😂
    CLAP = "clap"  # 👏


class ReactionTarget(str, enum.Enum):
    ARTICLE = "article"
    MATCH = "match"


class PollKind(str, enum.Enum):
    MATCH = "match"
    TRANSFER = "transfer"
    QUESTION = "question"


class PollStatus(str, enum.Enum):
    OPEN = "open"
    CLOSED = "closed"


class RevisionAction(str, enum.Enum):
    CREATE = "create"
    UPDATE = "update"
    STATUS = "status"
    RESTORE = "restore"
    SCHEDULED = "scheduled"


class SubscriptionStatus(str, enum.Enum):
    INCOMPLETE = "incomplete"
    """Checkout started, not yet paid -- grants nothing."""
    ACTIVE = "active"
    PAST_DUE = "past_due"
    """A renewal payment failed; access continues for a short grace period."""
    CANCELLED = "cancelled"
    """Cancelled by the user: access continues until `current_period_end`."""
    EXPIRED = "expired"


class PaymentEventStatus(str, enum.Enum):
    RECEIVED = "received"
    PROCESSED = "processed"
    IGNORED = "ignored"
    FAILED = "failed"


class InsightEntityType(str, enum.Enum):
    TEAM = "team"
    PLAYER = "player"
    MATCH = "match"
