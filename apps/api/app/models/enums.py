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
    RED_CARD = "red_card"
    SUBSTITUTION = "substitution"
    VAR = "var"
