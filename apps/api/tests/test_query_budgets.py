"""N+1 guard (Phase 7 §26): the number of SQL statements each hot endpoint issues must not grow with the amount
of data. Each endpoint is measured against a small and a large dataset; a handler that loads related rows in a
loop issues more statements for the larger one and fails here, whatever its absolute cost.

`BUDGETS` are generous ceilings (current cost plus headroom) as a second line of defence."""

import os

import pytest
from sqlalchemy import event

from app.core.security import create_access_token

API = "/api/v1"


class Counter:
    def __init__(self, engine):
        self.engine = engine.sync_engine
        self.count = 0
        self.statements: list[str] = []

    def _on(self, conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        self.count += 1
        self.statements.append(statement)

    def __enter__(self):
        event.listen(self.engine, "before_cursor_execute", self._on)
        return self

    def __exit__(self, *exc):
        event.remove(self.engine, "before_cursor_execute", self._on)


async def measure(client, engine, path, headers=None, params=None) -> tuple[int, int]:
    with Counter(engine) as counter:
        resp = await client.get(f"{API}{path}", headers=headers, params=params)
    return resp.status_code, counter.count


# endpoint -> ceiling of statements per request (measured cost + 2). The cache is empty on the first call, so these
# are cold-cache costs.
BUDGETS = {
    "/matches/today": 6,
    "/matches/live": 6,
    "/matches/{m}": 10,
    "/matches/{m}/events": 10,
    "/matches/{m}/lineups": 8,
    "/matches/{m}/statistics": 4,
    "/competitions": 3,
    "/competitions/{c}/standings": 6,
    "/teams/{t}": 4,
    "/teams/{t}/fixtures": 7,
    "/search": 10,
}


@pytest.mark.parametrize("template", list(BUDGETS))
async def test_hot_endpoints_stay_within_their_statement_budget(phase4_client, test_engine, get_match_id, lookup, template):
    from app.models.competition import Competition
    from app.models.team import Team

    path = template.format(m=await get_match_id("epl-3"), c=await lookup(Competition, "Premier League"), t=await lookup(Team, "Arsenal"))
    params = {"q": "ars"} if template == "/search" else None
    status, count = await measure(phase4_client, test_engine, path, params=params)
    assert status == 200, path
    if os.environ.get("QUERY_BUDGET_REPORT"):
        print(f"QUERY-COUNT {template} {count}")
    assert count <= BUDGETS[template], f"{path} issued {count} statements (budget {BUDGETS[template]})"


async def test_comment_listing_cost_does_not_grow_with_the_number_of_comments(client, make_user, session_factory, test_engine):
    from app.models.community import Comment
    from app.models.enums import CommentStatus, CommentTarget

    users = [(await make_user(f"u{i}@example.com"))[0] for i in range(12)]

    async def add(n: int, offset: int):
        async with session_factory() as db:
            for i in range(n):
                db.add(Comment(user_id=users[(i + offset) % 12].id, target_type=CommentTarget.MATCH, target_id=7, body=f"c{offset + i}", status=CommentStatus.VISIBLE))
            await db.commit()

    await add(3, 0)
    _, few = await measure(client, test_engine, "/comments", params={"target_type": "match", "target_id": 7, "page_size": 20})
    await client.get(f"{API}/comments", params={"target_type": "match", "target_id": 7})  # warm cache must not hide a loop
    await add(40, 3)
    # a new comment bumps the cache version, so this is a cold read of a 43-comment thread
    _, many = await measure(client, test_engine, "/comments", params={"target_type": "match", "target_id": 7, "page_size": 20})
    assert many <= few + 1, f"comment listing went from {few} to {many} statements as comments grew"


async def test_the_feed_and_discovery_cost_does_not_grow_with_the_number_of_articles(client, make_user, publish_article, test_engine):
    from app.models.enums import UserRole

    _ed, headers = await make_user("ed@example.com", UserRole.EDITOR)
    await publish_article(headers, title="Opening story")
    _, before = await measure(client, test_engine, "/discovery/home")
    for i in range(12):
        await publish_article(headers, title=f"Story number {i}")
    _, after = await measure(client, test_engine, "/discovery/home")
    assert after <= before + 3, f"discovery home went from {before} to {after} statements with 12 more articles"


async def test_the_article_list_cost_does_not_grow_with_the_number_of_articles(client, make_user, publish_article, test_engine):
    from app.models.enums import UserRole

    _ed, headers = await make_user("ed@example.com", UserRole.EDITOR)
    await publish_article(headers, title="First story")
    _, few = await measure(client, test_engine, "/articles", params={"page_size": 20})
    for i in range(15):
        await publish_article(headers, title=f"More news {i}")
    _, many = await measure(client, test_engine, "/articles", params={"page_size": 20, "page": 1})
    assert many <= few + 1, f"article list went from {few} to {many} statements"


async def test_notification_fan_out_cost_does_not_grow_per_follower(session_factory, make_user, seeded_client, test_engine, lookup):
    """Resolving who to notify must be a handful of set-based queries, however many people follow the team."""
    from app.events.schemas import RealtimeEvent, RealtimeEventType
    from app.models.favourite import FavouriteTeam
    from app.models.match import Match
    from app.models.team import Team
    from app.services.notification_dispatch_service import resolve_targets
    from sqlalchemy import select

    team_id = await lookup(Team, "Arsenal")
    async with session_factory() as db:
        match = await db.scalar(select(Match).where((Match.home_team_id == team_id) | (Match.away_team_id == team_id)).limit(1))
    users = [(await make_user(f"fan{i}@example.com"))[0] for i in range(25)]

    async def follow(upto: int):
        async with session_factory() as db:
            for u in users[:upto]:
                if not await db.scalar(select(FavouriteTeam.id).where(FavouriteTeam.user_id == u.id)):
                    db.add(FavouriteTeam(user_id=u.id, team_id=team_id))
            await db.commit()

    async def resolve(tag: str) -> tuple[int, int]:
        ev = RealtimeEvent(type=RealtimeEventType.GOAL, match_id=str(match.id), data={"event": {"id": tag}})
        with Counter(test_engine) as counter:
            async with session_factory() as db:
                targets = await resolve_targets(db, ev)
        return len(targets), counter.count

    await follow(3)
    few_targets, few = await resolve("g-1")
    await follow(25)
    many_targets, many = await resolve("g-2")
    assert (few_targets, many_targets) == (3, 25)
    assert many == few, f"resolving {many_targets} followers took {many} statements, {few_targets} took {few}"
