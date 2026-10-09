from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models.enums import CommentStatus, CommentTarget, PollKind, PollStatus, ReactionKind, ReactionTarget, ReportStatus


class CommentAuthor(BaseModel):
    id: int
    display_name: str
    """A display name, or "Fan" when the user set none -- never an email address."""
    profile_public: bool = False
    """Clients link to `/profiles/{id}` only when true."""


class CommentOut(BaseModel):
    id: int
    author: CommentAuthor | None
    """None for a removed comment shown only as a placeholder for its replies."""
    body: str
    created_at: datetime
    edited_at: datetime | None = None
    like_count: int = 0
    reply_count: int = 0
    removed: bool = False
    parent_id: int | None = None
    # viewer-specific (filled per request; never cached with the page)
    liked_by_me: bool = False
    mine: bool = False
    replies: list["CommentOut"] = Field(default_factory=list)


class CommentPage(BaseModel):
    items: list[CommentOut]
    total: int
    """Top-level comments."""
    total_comments: int
    """Every visible comment including replies."""
    page: int
    page_size: int


class CommentIn(BaseModel):
    target_type: CommentTarget
    target_id: int = Field(ge=1)
    body: str = Field(min_length=1, max_length=4000)
    """The service enforces the configured limit (`COMMENT_MAX_LENGTH`) after trimming."""
    parent_id: int | None = Field(default=None, ge=1)


class CommentEdit(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class ReportIn(BaseModel):
    reason: str = Field(default="", max_length=200)


class ReportOut(BaseModel):
    id: int
    comment_id: int
    comment_body: str
    comment_status: CommentStatus
    comment_author: str
    target_type: CommentTarget
    target_id: int
    reason: str
    status: ReportStatus
    created_at: datetime
    report_count: int


class ModerationAction(BaseModel):
    action: Literal["hide", "restore", "delete"]


class ReactionSummary(BaseModel):
    counts: dict[str, int]
    total: int
    mine: ReactionKind | None = None


class ReactionIn(BaseModel):
    kind: ReactionKind


class PollOptionOut(BaseModel):
    id: int
    label: str
    votes: int
    percent: float


class PollOut(BaseModel):
    id: int
    question: str
    kind: PollKind
    status: PollStatus
    match_id: int | None
    article_id: int | None
    closes_at: datetime | None
    total_votes: int
    options: list[PollOptionOut]
    my_vote: int | None = None
    """The option id the signed-in caller chose."""
    winner_option_id: int | None = None
    """Set once closed and a single option leads."""


class PollIn(BaseModel):
    question: str = Field(min_length=5, max_length=200)
    kind: PollKind = PollKind.QUESTION
    options: list[str] = Field(default_factory=list, max_length=6)
    """2-6 labels. For a match poll with none given: home win / draw / away win."""
    match_id: int | None = Field(default=None, ge=1)
    article_id: int | None = Field(default=None, ge=1)
    closes_at: datetime | None = None


class VoteIn(BaseModel):
    option_id: int = Field(ge=1)


class Badge(BaseModel):
    key: str
    label: str
    description: str


class ActivityItem(BaseModel):
    kind: Literal["comment"]
    text: str
    target_type: CommentTarget
    target_id: int
    target_label: str
    target_slug: str | None = None
    created_at: datetime


class ProfileStats(BaseModel):
    comments: int
    poll_votes: int
    followed_teams: int
    followed_competitions: int


class FavouriteName(BaseModel):
    id: int
    name: str


class ProfileOut(BaseModel):
    id: int
    display_name: str
    bio: str | None
    joined: datetime
    badges: list[Badge]
    stats: ProfileStats
    favourite_teams: list[FavouriteName] = Field(default_factory=list)
    favourite_competitions: list[FavouriteName] = Field(default_factory=list)
    activity: list[ActivityItem] = Field(default_factory=list)


class MyProfileOut(ProfileOut):
    profile_public: bool
    role: str


class ProfileUpdate(BaseModel):
    profile_public: bool | None = None
    bio: str | None = Field(default=None, max_length=280)


CommentOut.model_rebuild()


class ProfileReportIn(BaseModel):
    reason: str = Field(default="", max_length=200)


class SuspendIn(BaseModel):
    reason: str = Field(default="", max_length=200)
