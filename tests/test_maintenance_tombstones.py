from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.models import RawItem
from app.maintenance import MaintenanceState, purge_old
from app.storage.ops import ingest_new_items
from app.storage.tables import clusters, raw_items, seen_items
from app.storage.writer import Writer
from tests.test_maintenance import NOW, counts, seed


def feed_item(source: str = "github", source_id: str = "old") -> RawItem:
    return RawItem(
        source=source,
        source_id=source_id,
        url=f"https://github.com/o/{source_id}",
        title=f"o/{source_id}",
        published_at=NOW,
        metrics={"stars": 5},
    )


async def tombstones(engine: AsyncEngine) -> int:
    async with engine.connect() as conn:
        return int((await conn.execute(select(func.count()).select_from(seen_items))).scalar_one())


async def test_purged_items_are_not_reingested_as_new_when_the_feed_returns_them(
    engine: AsyncEngine,
) -> None:
    writer = Writer(engine)
    writer.start()
    await seed(engine, writer)
    assert await writer.submit(lambda c: purge_old(c, 30, NOW)) == (2, 2)
    before = await counts(engine)
    again = await writer.submit(lambda c: ingest_new_items(c, [feed_item()], NOW))
    assert again == [] and await counts(engine) == before  # không tạo lại bài, không thêm snapshot
    other = await writer.submit(lambda c: ingest_new_items(c, [feed_item("hackernews")], NOW))
    await writer.stop()
    assert len(other) == 1  # dấu vết chỉ chặn đúng cặp (nguồn, id) đã dọn


async def test_tombstones_expire_after_tombstone_days(engine: AsyncEngine) -> None:
    writer = Writer(engine)
    writer.start()
    await seed(engine, writer)
    await writer.submit(lambda c: purge_old(c, 30, NOW, tombstone_days=180))
    assert await tombstones(engine) == 2
    later = NOW + timedelta(days=181)
    await writer.submit(lambda c: purge_old(c, 30, later, tombstone_days=180))
    async with engine.connect() as conn:
        left = {r[0] for r in (await conn.execute(select(seen_items.c.source_id))).all()}
    assert left == {"new"}  # dấu vết cũ hết hạn; chỉ còn dấu vết mới của cụm "new" vừa quá hạn
    revived = await writer.submit(lambda c: ingest_new_items(c, [feed_item()], later))
    await writer.stop()
    assert len(revived) == 1


async def add_orphan(conn) -> None:  # type: ignore[no-untyped-def]
    old = NOW - timedelta(days=45)
    await conn.execute(
        raw_items.insert().values(
            source="github",
            source_id="orphan",
            url="https://github.com/o/orphan",
            title="o/orphan",
            text="",
            published_at=old,
            fetched_at=old,
            links=[],
        )
    )


async def test_orphan_items_are_cleaned_even_when_no_cluster_is_stale(engine: AsyncEngine) -> None:
    writer = Writer(engine)
    writer.start()
    await seed(engine, writer)
    await writer.submit(lambda c: purge_old(c, 30, NOW))  # dọn lần đầu: cụm cũ + bài mồ côi
    await writer.submit(add_orphan)  # bài mồ côi mới xuất hiện sau đó (ví dụ do lỗi xử lý)
    removed = await writer.submit(lambda c: purge_old(c, 30, NOW))
    await writer.stop()
    assert removed == (0, 1)  # không còn cụm quá hạn nhưng bài mồ côi vẫn được dọn


async def test_purge_handles_far_more_clusters_than_one_sql_chunk(engine: AsyncEngine) -> None:
    writer = Writer(engine)
    writer.start()
    old = NOW - timedelta(days=60)

    async def bulk(conn) -> None:  # type: ignore[no-untyped-def]
        await conn.execute(
            clusters.insert(),
            [
                {"first_seen": old, "last_seen": old, "importance": 0.0, "is_noise": False}
                for _ in range(1300)
            ],
        )

    await writer.submit(bulk)
    removed = await writer.submit(lambda c: purge_old(c, 30, NOW))
    await writer.stop()
    assert removed == (1300, 0) and (await counts(engine))["clusters"] == 0


def test_state_file_is_written_atomically(tmp_path: Path) -> None:
    path = tmp_path / "m.json"
    state = MaintenanceState(path)
    state.mark("backup", NOW)
    state.mark("vacuum", NOW)
    assert json.loads(path.read_text(encoding="utf-8")).keys() == {"backup", "vacuum"}
    assert not list(tmp_path.glob("*.tmp"))


def test_first_maintenance_runs_within_a_few_minutes_of_startup() -> None:
    from app.scheduler import MAINTENANCE_FIRST_RUN_MINUTES

    assert MAINTENANCE_FIRST_RUN_MINUTES <= 3  # app thường chỉ mở vài phút vẫn được dọn và sao lưu
