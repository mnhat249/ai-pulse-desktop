from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.metrics import WINDOW_HOURS, star_velocity
from app.core.models import RawItem
from app.storage.tables import metric_snapshots, raw_items, seen_items, source_runs, user_state

AGE_METRIC = "age_hours"
STARS_METRIC = "stars"
VELOCITY_METRIC = "stars_per_24h"


@dataclass(frozen=True)
class IngestResult:
    item_id: int
    is_new: bool


async def upsert_raw_item(conn: AsyncConnection, item: RawItem, now: datetime) -> IngestResult:
    stmt = (
        sqlite_insert(raw_items)
        .values(
            source=item.source,
            source_id=item.source_id,
            url=item.url,
            title=item.title,
            text=item.text,
            author=item.author,
            published_at=item.published_at,
            fetched_at=now,
            links=item.links,
        )
        .on_conflict_do_nothing(index_elements=["source", "source_id"])
    )
    result = await conn.execute(stmt)
    if result.rowcount == 1 and result.inserted_primary_key is not None:
        return IngestResult(int(result.inserted_primary_key[0]), True)
    row = await conn.execute(
        select(raw_items.c.id).where(
            raw_items.c.source == item.source, raw_items.c.source_id == item.source_id
        )
    )
    return IngestResult(int(row.scalar_one()), False)


async def _star_baseline(
    conn: AsyncConnection, item_id: int, now: datetime
) -> tuple[float, float] | None:
    """Mốc gần nhất cách đây từ 24 đến 48 giờ; không có thì mốc cũ nhất trong 24 giờ."""
    base = select(metric_snapshots.c.value, metric_snapshots.c.captured_at).where(
        metric_snapshots.c.item_id == item_id, metric_snapshots.c.metric == STARS_METRIC
    )
    day_ago = now - timedelta(hours=WINDOW_HOURS)
    old = (
        await conn.execute(
            base.where(
                metric_snapshots.c.captured_at <= day_ago,
                metric_snapshots.c.captured_at >= now - timedelta(hours=2 * WINDOW_HOURS),
            ).order_by(metric_snapshots.c.captured_at.desc())
        )
    ).first()
    if old is None:
        old = (
            await conn.execute(
                base.where(
                    metric_snapshots.c.captured_at > day_ago,
                    metric_snapshots.c.captured_at <= now - timedelta(hours=1),
                ).order_by(metric_snapshots.c.captured_at.asc())
            )
        ).first()
    if old is None:
        return None
    elapsed = (now - old.captured_at).total_seconds() / 3600
    return float(old.value), elapsed


async def _was_purged(conn: AsyncConnection, item: RawItem) -> bool:
    """Bài đã bị dọn (không còn trong raw_items nhưng còn dấu vết): feed vẫn trả lại bài cũ."""
    exists = await conn.execute(
        select(raw_items.c.id).where(
            raw_items.c.source == item.source, raw_items.c.source_id == item.source_id
        )
    )
    if exists.first() is not None:
        return False
    seen = await conn.execute(
        select(seen_items.c.source).where(
            seen_items.c.source == item.source, seen_items.c.source_id == item.source_id
        )
    )
    return seen.first() is not None


async def ingest_item(conn: AsyncConnection, item: RawItem, now: datetime) -> IngestResult:
    if await _was_purged(conn, item):
        return IngestResult(0, False)
    result = await upsert_raw_item(conn, item, now)
    rows = [
        {"item_id": result.item_id, "metric": name, "value": value, "captured_at": now}
        for name, value in item.metrics.items()
        if name != AGE_METRIC
    ]
    if STARS_METRIC in item.metrics:
        baseline = await _star_baseline(conn, result.item_id, now)
        velocity = star_velocity(item.metrics[STARS_METRIC], item.metrics.get(AGE_METRIC), baseline)
        if velocity is not None:
            rows.append(
                {
                    "item_id": result.item_id,
                    "metric": VELOCITY_METRIC,
                    "value": velocity,
                    "captured_at": now,
                }
            )
    if rows:
        await conn.execute(metric_snapshots.insert(), rows)
    return result


async def ingest_new_items(
    conn: AsyncConnection, items: list[RawItem], now: datetime
) -> list[RawItem]:
    """Ghi cả lô trong một giao dịch; trả về các bài mới."""
    return [item for item in items if (await ingest_item(conn, item, now)).is_new]


async def ingest_items(conn: AsyncConnection, items: list[RawItem], now: datetime) -> int:
    return len(await ingest_new_items(conn, items, now))


async def set_cluster_read(
    conn: AsyncConnection, cluster_id: int, read: bool, now: datetime
) -> None:
    stmt = sqlite_insert(user_state).values(
        cluster_id=cluster_id, read_at=now if read else None, bookmarked=False
    )
    await conn.execute(
        stmt.on_conflict_do_update(
            index_elements=["cluster_id"], set_={"read_at": now if read else None}
        )
    )


async def set_cluster_bookmark(conn: AsyncConnection, cluster_id: int, bookmarked: bool) -> None:
    stmt = sqlite_insert(user_state).values(cluster_id=cluster_id, bookmarked=bookmarked)
    await conn.execute(
        stmt.on_conflict_do_update(index_elements=["cluster_id"], set_={"bookmarked": bookmarked})
    )


async def record_source_run(
    conn: AsyncConnection,
    source: str,
    started_at: datetime,
    ok: bool,
    item_count: int,
    error: str | None,
) -> None:
    await conn.execute(
        source_runs.insert().values(
            source=source, started_at=started_at, ok=ok, item_count=item_count, error=error
        )
    )
