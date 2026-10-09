"""Write the ids and tokens the k6 scenarios use (load/k6/world.json).

    JWT_SECRET=... python scripts/make_loadtest_data.py --dsn postgresql://user:pw@host/db --out ../../load/k6/world.json

Reads existing rows (matches, teams, articles, polls) and mints short-lived access tokens for the seeded
`load*@example.test` users (scripts/seed_volume.py). The output contains bearer tokens: it is git-ignored and must
never be committed or pointed at a database with real accounts.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncpg  # noqa: E402


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--users", type=int, default=500)
    args = parser.parse_args()
    os.environ.setdefault("DATABASE_URL", args.dsn.replace("postgresql://", "postgresql+asyncpg://"))
    from app.core.security import create_access_token

    conn = await asyncpg.connect(args.dsn)
    try:
        world = {
            "match_ids": [r[0] for r in await conn.fetch("select id from matches order by random() limit 200")],
            "team_ids": [r[0] for r in await conn.fetch("select id from teams order by random() limit 100")],
            "team_names": [r[0] for r in await conn.fetch("select name from teams order by random() limit 100")],
            "slugs": [r[0] for r in await conn.fetch("select slug from articles where status = 'PUBLISHED' order by random() limit 100")],
            "article_ids": [r[0] for r in await conn.fetch("select id from articles where status = 'PUBLISHED' order by random() limit 100")],
            "poll_ids": [r[0] for r in await conn.fetch("select id from polls where status = 'OPEN' order by random() limit 50")],
        }
        user_ids = [r[0] for r in await conn.fetch("select id from users where email like 'load%' order by random() limit $1", args.users)]
    finally:
        await conn.close()
    world["tokens"] = [create_access_token(uid) for uid in user_ids]
    with open(args.out, "w", encoding="utf8") as handle:
        json.dump(world, handle)
    print({k: len(v) for k, v in world.items()})


if __name__ == "__main__":
    asyncio.run(main())
