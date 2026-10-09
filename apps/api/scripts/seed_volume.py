"""Fill the user-generated tables with realistic volume, for load tests and query analysis (Phase 7).

    python scripts/seed_volume.py --dsn postgresql://football:football@localhost:15432/football_perf --scale 1

NEVER point this at a database with real users: it inserts tens of thousands of fake accounts. Matches, teams
and competitions are not generated -- run it against a database that already synced them from the provider
(or the seed), so foreign keys resolve to real rows.

Scale 1 ~ a mid-sized community: 20k users, 3k articles, 400k comments, 300k reactions, 100k poll votes,
600k notification-ledger rows, 300k engagement buckets, 50k payment events. Everything is set-based SQL
(`generate_series`), so scale 1 loads in well under a minute. Password hashes are a fixed non-working value.
"""

from __future__ import annotations

import argparse
import asyncio
import time

import asyncpg

STEPS: list[tuple[str, str]] = [
    (
        "users",
        """
        INSERT INTO users (email, hashed_password, display_name, is_active, role, profile_public, created_at, updated_at)
        SELECT 'load' || g || '@example.test', '$2b$12$loadtestloadtestloadtestuOQmQ0vSxwQJb7V7Y1zv3b7uXQ9m', 'Load User ' || g, true, 'USER',
               (g % 7 = 0), now() - (g % 400) * interval '1 day', now()
        FROM generate_series(1::bigint, {users}) g
        ON CONFLICT (email) DO NOTHING
        """,
    ),
    (
        "articles",
        """
        INSERT INTO articles (slug, title, excerpt, content, status, published_at, is_featured, view_count, created_at, updated_at)
        SELECT 'load-article-' || g, 'Load article ' || g || ' ' || md5(g::text), 'Excerpt ' || g, repeat('Lorem ipsum dolor sit amet. ', 60),
               'PUBLISHED', now() - (g % 900) * interval '1 hour', (g % 50 = 0), (g * 7) % 5000, now(), now()
        FROM generate_series(1::bigint, {articles}) g
        ON CONFLICT (slug) DO NOTHING
        """,
    ),
    (
        "comments",
        """
        INSERT INTO comments (user_id, target_type, target_id, body, status, like_count, report_count, created_at)
        SELECT u.id, CASE WHEN g % 3 = 0 THEN 'MATCH' ELSE 'ARTICLE' END,
               CASE WHEN g % 3 = 0 THEN m.id ELSE a.id END,
               'Comment number ' || g || ' - ' || md5(g::text), CASE WHEN g % 200 = 0 THEN 'HIDDEN' ELSE 'VISIBLE' END,
               (g % 11), 0, now() - (g % 20000) * interval '1 minute'
        FROM generate_series(1::bigint, {comments}) g
        CROSS JOIN LATERAL (SELECT {user_base} + ((g * 7919) % {users})::int AS id) u
        CROSS JOIN LATERAL (SELECT ({match_ids})[1 + ((g * 104729) % {n_matches})::int] AS id) m
        CROSS JOIN LATERAL (SELECT {article_base} + ((g * 15485863) % {articles})::int AS id) a
        """,
    ),
    (
        "comment replies",
        """
        INSERT INTO comments (user_id, target_type, target_id, parent_id, body, status, like_count, report_count, created_at)
        SELECT c.user_id % {users} + 1, c.target_type, c.target_id, c.id, 'Reply to ' || c.id, 'VISIBLE', 0, 0, c.created_at + interval '5 minutes'
        FROM comments c WHERE c.parent_id IS NULL AND c.id % 10 = 0
        """,
    ),
    (
        "reactions",
        """
        INSERT INTO reactions (user_id, target_type, target_id, kind, created_at)
        SELECT u.id, 'ARTICLE', a.id, (ARRAY['THUMBS_UP','FIRE','WOW','GOAL','HEART','LAUGH','CLAP'])[1 + g % 7], now()
        FROM generate_series(1::bigint, {reactions}) g
        CROSS JOIN LATERAL (SELECT {user_base} + ((g * 7919) % {users})::int AS id) u
        CROSS JOIN LATERAL (SELECT {article_base} + ((g * 31) % {articles})::int AS id) a
        ON CONFLICT DO NOTHING
        """,
    ),
    (
        "polls",
        """
        WITH p AS (
          INSERT INTO polls (question, kind, status, match_id, created_at)
          SELECT 'Who wins fixture ' || m.id || '?', 'MATCH', CASE WHEN g % 4 = 0 THEN 'CLOSED' ELSE 'OPEN' END, m.id, now()
          FROM generate_series(1::bigint, {polls}) g
          CROSS JOIN LATERAL (SELECT ({match_ids})[1 + ((g * 13) % {n_matches})::int] AS id) m
          RETURNING id
        )
        INSERT INTO poll_options (poll_id, label, position)
        SELECT p.id, l.label, l.pos FROM p CROSS JOIN (VALUES ('Home', 0), ('Draw', 1), ('Away', 2)) AS l(label, pos)
        """,
    ),
    (
        "poll votes",
        """
        INSERT INTO poll_votes (poll_id, option_id, user_id, created_at)
        SELECT o.poll_id, o.id, u.id, now()
        FROM generate_series(1::bigint, {votes}) g
        CROSS JOIN LATERAL (SELECT {user_base} + ((g * 7919) % {users})::int AS id) u
        CROSS JOIN LATERAL (SELECT id, poll_id FROM poll_options WHERE id = {option_base} + ((g * 3) % {n_options})::int) o
        ON CONFLICT DO NOTHING
        """,
    ),
    (
        "notification ledger",
        """
        INSERT INTO notification_log (user_id, match_id, event_type, dedup_key, delivered_at, created_at, updated_at)
        SELECT u.id, m.id, 'GOAL', 'goal:' || m.id || ':' || g, now(), now() - (g % 40000) * interval '1 minute', now()
        FROM generate_series(1::bigint, {ledger}) g
        CROSS JOIN LATERAL (SELECT {user_base} + ((g * 7919) % {users})::int AS id) u
        CROSS JOIN LATERAL (SELECT ({match_ids})[1 + ((g * 17) % {n_matches})::int] AS id) m
        ON CONFLICT DO NOTHING
        """,
    ),
    (
        "engagement buckets",
        """
        INSERT INTO engagement_buckets (entity_type, entity_id, signal, bucket, count)
        SELECT 'article', 1 + g % {articles}, (ARRAY['view','search'])[1 + g % 2], date_trunc('hour', now()) - (g % 720) * interval '1 hour', 1 + g % 40
        FROM generate_series(1::bigint, {buckets}) g
        ON CONFLICT DO NOTHING
        """,
    ),
    (
        "sessions",
        """
        INSERT INTO refresh_tokens (user_id, token_hash, expires_at, revoked_at, user_agent, ip_address, created_at, updated_at)
        SELECT u.id, md5(g::text) || md5((g * 3)::text), now() + (g % 60 - 20) * interval '1 day', CASE WHEN g % 5 = 0 THEN now() - interval '2 days' END,
               'load-agent', '203.0.113.' || (g % 250), now(), now()
        FROM generate_series(1::bigint, {sessions}) g
        CROSS JOIN LATERAL (SELECT {user_base} + ((g * 7919) % {users})::int AS id) u
        ON CONFLICT DO NOTHING
        """,
    ),
    (
        "payment events",
        """
        INSERT INTO payment_events (provider, event_id, event_type, status, payload, attempts, received_at, processed_at)
        SELECT 'stripe', 'evt_load_' || g, 'invoice.paid', CASE WHEN g % 500 = 0 THEN 'FAILED' ELSE 'PROCESSED' END, '{{"id":"x"}}'::jsonb, 1,
               now() - (g % 200000) * interval '1 minute', now()
        FROM generate_series(1::bigint, {payments}) g
        ON CONFLICT DO NOTHING
        """,
    ),
    (
        "recent searches",
        """
        INSERT INTO recent_searches (user_id, query, last_searched_at)
        SELECT u.id, 'query ' || (g % 5000), now() - (g % 9000) * interval '1 minute'
        FROM generate_series(1::bigint, {searches}) g
        CROSS JOIN LATERAL (SELECT {user_base} + ((g * 7919) % {users})::int AS id) u
        ON CONFLICT DO NOTHING
        """,
    ),
    (
        "devices",
        """
        INSERT INTO devices (user_id, platform, expo_push_token, last_seen_at, created_at, updated_at)
        SELECT {user_base} + (g * 2)::int % {users}, 'EXPO_IOS', 'ExponentPushToken[load-' || g || ']', now(), now(), now()
        FROM generate_series(1::bigint, {devices}) g
        ON CONFLICT DO NOTHING
        """,
    ),
    (
        "favourite teams",
        """
        INSERT INTO favourite_teams (user_id, team_id, created_at, updated_at)
        SELECT u.id, t.id, now(), now()
        FROM generate_series(1::bigint, {favourites}) g
        CROSS JOIN LATERAL (SELECT {user_base} + ((g * 7919) % {users})::int AS id) u
        CROSS JOIN LATERAL (SELECT ({team_ids})[1 + (CASE WHEN g % 10 < 4 THEN g % 3 ELSE (g * 3) % {n_teams} END)::int] AS id) t
        ON CONFLICT DO NOTHING
        """,
    ),
]


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", required=True)
    parser.add_argument("--scale", type=float, default=1.0)
    parser.add_argument("--only", default="", help="comma list of step names to run (default: all)")
    args = parser.parse_args()
    s = args.scale
    sizes = dict(
        users=int(20_000 * s), articles=int(3_000 * s), comments=int(400_000 * s), reactions=int(300_000 * s),
        polls=int(200 * s), votes=int(100_000 * s), ledger=int(600_000 * s), buckets=int(300_000 * s),
        sessions=int(80_000 * s), payments=int(50_000 * s), searches=int(50_000 * s), favourites=int(60_000 * s), devices=int(10_000 * s),
    )
    conn = await asyncpg.connect(args.dsn)
    try:
        context: dict = {}
        only = {n.strip() for n in args.only.split(",") if n.strip()}
        for name, sql in STEPS:
            started = time.perf_counter()
            if only and name not in only:
                if name in ("comments", "poll votes"):
                    pass  # still needs its lookups below
                else:
                    continue
            if name == "comments":  # the prerequisite rows now exist; look up what the later steps index into
                context["user_base"] = await conn.fetchval("SELECT min(id) FROM users WHERE email LIKE 'load%'")
                context["article_base"] = await conn.fetchval("SELECT min(id) FROM articles WHERE slug LIKE 'load-article-%'")
                match_ids = [r[0] for r in await conn.fetch("SELECT id FROM matches ORDER BY id")]
                team_ids = [r[0] for r in await conn.fetch("SELECT id FROM teams ORDER BY id")]
                context.update(match_ids="ARRAY[%s]::int[]" % ",".join(map(str, match_ids)), n_matches=len(match_ids),
                               team_ids="ARRAY[%s]::int[]" % ",".join(map(str, team_ids)), n_teams=len(team_ids))
            if name == "poll votes":
                context["option_base"] = await conn.fetchval("SELECT min(id) FROM poll_options")
                context["n_options"] = await conn.fetchval("SELECT count(*) FROM poll_options")
            if only and name not in only:
                continue
            status = await conn.execute(sql.format(**sizes, **context))
            print(f"{name:<22} {status:<22} {time.perf_counter() - started:6.1f}s", flush=True)
        await conn.execute("ANALYZE")
        print("ANALYZE done")
        for table in ("users", "articles", "comments", "reactions", "poll_votes", "notification_log", "engagement_buckets", "payment_events"):
            print(f"{table:<20} {await conn.fetchval(f'select count(*) from {table}'):>10,}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
