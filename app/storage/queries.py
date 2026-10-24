from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.storage.tables import raw_items, source_runs


@dataclass(frozen=True)
class SourceStatus:
    source: str
    last_run: datetime
    last_ok: bool
    last_error: str | None
    last_item_count: int


async def count_raw_items(engine: AsyncEngine) -> int:
    async with engine.connect() as conn:
        return int((await conn.execute(select(func.count()).select_from(raw_items))).scalar_one())


async def source_statuses(engine: AsyncEngine) -> list[SourceStatus]:
    latest = (
        select(source_runs.c.source, func.max(source_runs.c.id).label("run_id"))
        .group_by(source_runs.c.source)
        .subquery()
    )
    stmt = (
        select(source_runs)
        .join(latest, source_runs.c.id == latest.c.run_id)
        .order_by(source_runs.c.source)
    )
    async with engine.connect() as conn:
        rows = (await conn.execute(stmt)).all()
    return [SourceStatus(r.source, r.started_at, r.ok, r.error, r.item_count) for r in rows]
