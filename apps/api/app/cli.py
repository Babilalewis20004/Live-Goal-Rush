"""Operator commands.

    python -m app.cli set-role someone@example.com editor
    python -m app.cli grant-entitlement someone@example.com advanced_analytics --days 30
    python -m app.cli revoke-entitlement someone@example.com advanced_analytics

Roles are the only authorization beyond "signed in": `editor` can write and
publish their own articles, `admin` can manage everyone's and create
categories. There is intentionally no API for granting a role -- it is an
operator decision, made with database access, not something an account can ask
for.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select

from app.db.session import AsyncSessionLocal
from app.models.billing import Entitlement
from app.models.enums import UserRole
from app.models.user import User
from app.services import audit_service as audit
from app.services.billing.entitlements import ALL_ENTITLEMENTS


async def set_role(email: str, role: UserRole) -> bool:
    async with AsyncSessionLocal() as db:
        user = await db.scalar(select(User).where(func.lower(User.email) == email.strip().lower()))
        if user is None:
            return False
        previous = user.role
        user.role = role
        audit.record(
            db, action="user.role_change", target_type="user", target_id=user.id, actor_label="cli",
            details={"from": previous.value, "to": role.value},
        )
        await db.commit()
        return True


async def grant_entitlement(email: str, key: str, days: int | None) -> bool:
    """A grant independent of any subscription (a comp, a promotion). Idempotent: re-granting extends it."""
    async with AsyncSessionLocal() as db:
        user = await db.scalar(select(User).where(func.lower(User.email) == email.strip().lower()))
        if user is None:
            return False
        expires = datetime.now(timezone.utc) + timedelta(days=days) if days else None
        existing = await db.scalar(select(Entitlement).where(Entitlement.user_id == user.id, Entitlement.key == key))
        if existing is None:
            db.add(Entitlement(user_id=user.id, key=key, source="operator", expires_at=expires))
        else:
            existing.expires_at = expires
        audit.record(
            db, action="entitlement.grant", target_type="user", target_id=user.id, actor_label="cli",
            details={"key": key, "days": days},
        )
        await db.commit()
        return True


async def revoke_entitlement(email: str, key: str) -> bool:
    async with AsyncSessionLocal() as db:
        user = await db.scalar(select(User).where(func.lower(User.email) == email.strip().lower()))
        if user is None:
            return False
        await db.execute(delete(Entitlement).where(Entitlement.user_id == user.id, Entitlement.key == key))
        audit.record(db, action="entitlement.revoke", target_type="user", target_id=user.id, actor_label="cli", details={"key": key})
        await db.commit()
        return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    set_role_cmd = sub.add_parser("set-role", help="grant a user the user/editor/admin role")
    set_role_cmd.add_argument("email")
    set_role_cmd.add_argument("role", choices=[r.value for r in UserRole])
    grant_cmd = sub.add_parser("grant-entitlement", help="give a user a Premium entitlement without a subscription")
    grant_cmd.add_argument("email")
    grant_cmd.add_argument("key", choices=sorted(ALL_ENTITLEMENTS))
    grant_cmd.add_argument("--days", type=int, default=None, help="expire after this many days (default: never)")
    revoke_cmd = sub.add_parser("revoke-entitlement", help="remove an operator-granted entitlement")
    revoke_cmd.add_argument("email")
    revoke_cmd.add_argument("key", choices=sorted(ALL_ENTITLEMENTS))
    args = parser.parse_args(argv)

    if args.command == "set-role":
        if asyncio.run(set_role(args.email, UserRole(args.role))):
            print(f"{args.email} is now {args.role}")
            return 0
        print(f"No user with email {args.email}", file=sys.stderr)
        return 1
    if args.command in ("grant-entitlement", "revoke-entitlement"):
        ok = (
            asyncio.run(grant_entitlement(args.email, args.key, args.days))
            if args.command == "grant-entitlement"
            else asyncio.run(revoke_entitlement(args.email, args.key))
        )
        if ok:
            print(f"{args.command}: {args.email} {args.key}")
            return 0
        print(f"No user with email {args.email}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
