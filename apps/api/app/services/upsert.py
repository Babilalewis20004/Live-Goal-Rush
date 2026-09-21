from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base

ModelT = TypeVar("ModelT", bound=Base)


async def upsert_by_provider_id(
    db: AsyncSession, model: type[ModelT], provider_id: str, values: dict
) -> ModelT:
    """Get-or-create a row by its unique `provider_id`, updating fields in
    place if it already exists. Shared by every entity that is 1:1 with an
    external provider record (competitions, teams, players, matches)."""
    result = await db.execute(select(model).where(model.provider_id == provider_id))
    obj = result.scalar_one_or_none()
    if obj is None:
        obj = model(provider_id=provider_id, **values)
        db.add(obj)
    else:
        for key, value in values.items():
            setattr(obj, key, value)
    await db.flush()
    return obj
