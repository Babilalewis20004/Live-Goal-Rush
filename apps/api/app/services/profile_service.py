"""User profiles (Phase 6): favourites, badges and activity.

A profile is private until its owner makes it public (`users.profile_public`).
A public profile exposes a display name, an optional short bio, the month they
joined, badges, followed teams/competitions and recent *public* comments -- and
nothing else: no email, no role, no hidden or deleted comments, no notification
or search settings.

Badges are derived from counts every time, not stored: there is nothing to
award, revoke or get out of sync, and the rules are visible here.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.article import Article
from app.models.community import Comment, PollVote
from app.models.competition import Competition
from app.models.enums import ArticleStatus, CommentStatus, CommentTarget, UserRole
from app.models.favourite import FavouriteCompetition, FavouriteTeam
from app.models.match import Match
from app.models.team import Team
from app.models.user import User
from app.schemas.community import ActivityItem, Badge, FavouriteName, MyProfileOut, ProfileOut, ProfileStats, ProfileUpdate

ACTIVITY_LIMIT = 10


def compute_badges(*, comments: int, poll_votes: int, followed_teams: int, role: UserRole, published_articles: int) -> list[Badge]:
    badges: list[Badge] = []
    if role == UserRole.ADMIN:
        badges.append(Badge(key="admin", label="Admin", description="Runs LivePitch"))
    elif role == UserRole.EDITOR:
        badges.append(Badge(key="editor", label="Editor", description="Part of the editorial team"))
    if published_articles >= 1:
        badges.append(Badge(key="writer", label="Writer", description=f"Has published {published_articles} article{'s' if published_articles != 1 else ''}"))
    if comments >= 50:
        badges.append(Badge(key="regular", label="Regular", description="Posted 50 or more comments"))
    elif comments >= 10:
        badges.append(Badge(key="commentator", label="Commentator", description="Posted 10 or more comments"))
    elif comments >= 1:
        badges.append(Badge(key="first_word", label="First word", description="Posted a first comment"))
    if poll_votes >= 5:
        badges.append(Badge(key="pollster", label="Pollster", description="Voted in 5 or more polls"))
    if followed_teams >= 3:
        badges.append(Badge(key="supporter", label="Supporter", description="Follows 3 or more teams"))
    return badges


class ProfileService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _activity(self, user_id: int) -> list[ActivityItem]:
        comments = (
            await self.db.execute(
                select(Comment).where(Comment.user_id == user_id, Comment.status == CommentStatus.VISIBLE)
                .order_by(Comment.created_at.desc()).limit(ACTIVITY_LIMIT)
            )
        ).scalars().all()
        article_ids = {c.target_id for c in comments if c.target_type == CommentTarget.ARTICLE}
        match_ids = {c.target_id for c in comments if c.target_type == CommentTarget.MATCH}
        articles = {
            i: (title, slug)
            for i, title, slug in (await self.db.execute(select(Article.id, Article.title, Article.slug).where(Article.id.in_(article_ids), Article.status == ArticleStatus.PUBLISHED))).all()
        } if article_ids else {}
        matches: dict[int, str] = {}
        if match_ids:
            home, away = Team.__table__.alias("h"), Team.__table__.alias("a")
            rows = await self.db.execute(
                select(Match.id, home.c.name, away.c.name)
                .join(home, home.c.id == Match.home_team_id).join(away, away.c.id == Match.away_team_id)
                .where(Match.id.in_(match_ids))
            )
            matches = {i: f"{h} v {a}" for i, h, a in rows}
        items = []
        for c in comments:
            if c.target_type == CommentTarget.ARTICLE:
                if c.target_id not in articles:
                    continue  # the article was unpublished: don't surface it
                label, slug = articles[c.target_id]
            else:
                if c.target_id not in matches:
                    continue
                label, slug = matches[c.target_id], None
            text = " ".join(c.body.split())
            items.append(
                ActivityItem(
                    kind="comment", text=text if len(text) <= 160 else text[:159].rstrip() + "…", target_type=c.target_type,
                    target_id=c.target_id, target_label=label, target_slug=slug, created_at=c.created_at,
                )
            )
        return items

    async def build(self, user: User) -> ProfileOut:
        comments = (await self.db.execute(select(func.count()).select_from(Comment).where(Comment.user_id == user.id, Comment.status == CommentStatus.VISIBLE))).scalar_one()
        votes = (await self.db.execute(select(func.count()).select_from(PollVote).where(PollVote.user_id == user.id))).scalar_one()
        teams = (await self.db.execute(select(Team.id, Team.name).join(FavouriteTeam, FavouriteTeam.team_id == Team.id).where(FavouriteTeam.user_id == user.id).order_by(Team.name))).all()
        competitions = (
            await self.db.execute(
                select(Competition.id, Competition.name).join(FavouriteCompetition, FavouriteCompetition.competition_id == Competition.id)
                .where(FavouriteCompetition.user_id == user.id).order_by(Competition.name)
            )
        ).all()
        published = 0
        if user.role in (UserRole.AUTHOR, UserRole.EDITOR, UserRole.ADMIN):
            published = (await self.db.execute(select(func.count()).select_from(Article).where(Article.author_id == user.id, Article.status == ArticleStatus.PUBLISHED))).scalar_one()
        return ProfileOut(
            id=user.id,
            display_name=(user.display_name or "Fan").strip() or "Fan",
            bio=user.bio,
            joined=user.created_at,
            badges=compute_badges(comments=comments, poll_votes=votes, followed_teams=len(teams), role=user.role, published_articles=published),
            stats=ProfileStats(comments=comments, poll_votes=votes, followed_teams=len(teams), followed_competitions=len(competitions)),
            favourite_teams=[FavouriteName(id=i, name=n) for i, n in teams],
            favourite_competitions=[FavouriteName(id=i, name=n) for i, n in competitions],
            activity=await self._activity(user.id),
        )

    async def get_mine(self, user: User) -> MyProfileOut:
        base = await self.build(user)
        return MyProfileOut(**base.model_dump(), profile_public=user.profile_public, role=user.role.value)

    async def get_public(self, user_id: int) -> ProfileOut | None:
        """None unless the user exists, is active and chose to be public."""
        user = await self.db.get(User, user_id)
        if user is None or not user.is_active or not user.profile_public:
            return None
        return await self.build(user)

    async def update(self, user: User, payload: ProfileUpdate) -> MyProfileOut:
        data = payload.model_dump(exclude_unset=True)
        if data.get("profile_public") is not None:
            user.profile_public = data["profile_public"]
        if "bio" in data:
            bio = " ".join((data["bio"] or "").split())
            user.bio = bio or None
        await self.db.commit()
        return await self.get_mine(user)
