from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings
from app.maintenance import (
    BACKUP_PREFIX,
    MaintenanceState,
    prune_backups,
    purge_old,
    run_maintenance,
    vacuum,
)
from app.storage.tables import (
    cluster_items,
    clusters,
    item_embeddings,
    item_keys,
    metric_snapshots,
    raw_items,
    user_state,
)
from app.storage.writer import Writer

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


async def seed(engine: AsyncEngine, writer: Writer) -> dict[str, int]:
    """4 cụm: mới, cũ, cũ có bookmark, cũ đã đọc; mỗi cụm một bài kèm snapshot/khóa/vector."""
    old = NOW - timedelta(days=45)
    ids: dict[str, int] = {}

    async def op(conn) -> None:  # type: ignore[no-untyped-def]
        for name, seen in (("new", NOW), ("old", old), ("marked", old), ("read", old)):
            cluster = await conn.execute(
                clusters.insert().values(
                    first_seen=seen, last_seen=seen, importance=1.0, is_noise=False
                )
            )
            cluster_id = int(cluster.inserted_primary_key[0])
            ids[name] = cluster_id
            item = await conn.execute(
                raw_items.insert().values(
                    source="github",
                    source_id=name,
                    url=f"https://github.com/o/{name}",
                    title=f"o/{name}",
                    text="",
                    published_at=seen,
                    fetched_at=seen,
                    links=[],
                )
            )
            item_id = int(item.inserted_primary_key[0])
            await conn.execute(
                cluster_items.insert().values(cluster_id=cluster_id, item_id=item_id)
            )
            await conn.execute(
                metric_snapshots.insert().values(
                    item_id=item_id, metric="stars", value=5, captured_at=seen
                )
            )
            await conn.execute(item_keys.insert().values(item_id=item_id, key=f"github:o/{name}"))
            await conn.execute(
                item_embeddings.insert().values(
                    item_id=item_id, model="m", vector=b"\x00\x00\x00\x00"
                )
            )
        await conn.execute(
            user_state.insert().values(cluster_id=ids["marked"], bookmarked=True, read_at=old)
        )
        await conn.execute(
            user_state.insert().values(cluster_id=ids["read"], bookmarked=False, read_at=old)
        )

    await writer.submit(op)
    return ids


async def counts(engine: AsyncEngine) -> dict[str, int]:
    async with engine.connect() as conn:
        out = {}
        for table in (
            clusters,
            raw_items,
            cluster_items,
            metric_snapshots,
            item_keys,
            item_embeddings,
            user_state,
        ):
            out[table.name] = int(
                (await conn.execute(select(func.count()).select_from(table))).scalar_one()
            )
    return out


async def test_purge_removes_old_clusters_but_keeps_bookmarked_and_recent(
    engine: AsyncEngine,
) -> None:
    writer = Writer(engine)
    writer.start()
    ids = await seed(engine, writer)
    assert (await counts(engine))["clusters"] == 4
    removed = await writer.submit(lambda c: purge_old(c, 30, NOW))
    await writer.stop()
    assert removed == (2, 2)  # cụm "old" và "read"
    after = await counts(engine)
    assert after == {
        "clusters": 2,
        "raw_items": 2,
        "cluster_items": 2,
        "metric_snapshots": 2,  # snapshot, khóa chuẩn, vector đi theo bài (CASCADE)
        "item_keys": 2,
        "item_embeddings": 2,
        "user_state": 1,  # chỉ còn trạng thái của cụm có bookmark
    }
    async with engine.connect() as conn:
        left = {r[0] for r in (await conn.execute(select(clusters.c.id))).all()}
    assert left == {ids["new"], ids["marked"]}


async def test_purge_does_nothing_when_nothing_is_old(engine: AsyncEngine) -> None:
    writer = Writer(engine)
    writer.start()
    await seed(engine, writer)
    removed = await writer.submit(lambda c: purge_old(c, 365, NOW))
    await writer.stop()
    assert removed == (0, 0) and (await counts(engine))["clusters"] == 4


async def test_retention_days_comes_from_settings_and_a_recent_cluster_is_never_purged(
    engine: AsyncEngine,
) -> None:
    writer = Writer(engine)
    writer.start()
    await seed(engine, writer)
    removed = await writer.submit(lambda c: purge_old(c, 1, NOW))
    await writer.stop()
    assert removed[0] == 2  # "new" có last_seen = NOW nên vẫn giữ dù hạn chỉ 1 ngày


def test_prune_backups_keeps_the_newest_n(tmp_path: Path) -> None:
    for day in range(1, 11):
        (tmp_path / f"{BACKUP_PREFIX}202610{day:02d}-000000.db").write_bytes(b"x")
    (tmp_path / "neuralradar-20260101-000000-0001.db").write_bytes(
        b"x"
    )  # bản của migrate: giữ nguyên
    assert prune_backups(tmp_path, 7) == 3
    names = sorted(p.name for p in tmp_path.glob(f"{BACKUP_PREFIX}*.db"))
    assert names[0].startswith(f"{BACKUP_PREFIX}20261004") and len(names) == 7
    assert (tmp_path / "neuralradar-20260101-000000-0001.db").exists()
    assert prune_backups(tmp_path, 7) == 0


def test_state_due_logic_and_persistence(tmp_path: Path) -> None:
    path = tmp_path / "m.json"
    state = MaintenanceState(path)
    assert state.due("backup", 7, NOW)
    state.mark("backup", NOW)
    assert not state.due("backup", 7, NOW + timedelta(days=6))
    assert state.due("backup", 7, NOW + timedelta(days=7))
    assert not MaintenanceState(path).due(
        "backup", 7, NOW + timedelta(days=1)
    )  # nhớ sau khi mở lại
    assert state.due("vacuum", 7, NOW)  # khóa khác độc lập


def test_corrupt_state_file_means_everything_is_due(tmp_path: Path) -> None:
    path = tmp_path / "m.json"
    path.write_text("không phải json", encoding="utf-8")
    assert MaintenanceState(path).due("backup", 7, NOW)
    path.write_text(json.dumps({"backup": "hôm qua"}), encoding="utf-8")
    assert MaintenanceState(path).due("backup", 7, NOW)


def test_vacuum_shrinks_a_database_after_deletes(tmp_path: Path) -> None:
    db = tmp_path / "v.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, blob BLOB)")
    conn.executemany("INSERT INTO t (blob) VALUES (?)", [(b"x" * 4000,)] * 2000)
    conn.commit()
    conn.execute("DELETE FROM t")
    conn.commit()
    conn.close()
    before = db.stat().st_size
    vacuum(db)
    assert db.stat().st_size < before / 4


async def full_settings(engine: AsyncEngine, tmp_path: Path) -> Settings:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)

    class Isolated(Settings):
        @property
        def db_path(self) -> Path:  # type: ignore[override]
            return Path(engine.url.database or "")

        @property
        def backup_dir(self) -> Path:  # type: ignore[override]
            return home / "backups"

    return Isolated.model_validate({"maintenance": {"retention_days": 30, "backups_to_keep": 2}})


async def test_run_maintenance_purges_backs_up_vacuums_and_then_waits_a_week(
    engine: AsyncEngine, tmp_path: Path
) -> None:
    writer = Writer(engine)
    writer.start()
    await seed(engine, writer)
    settings = await full_settings(engine, tmp_path)
    first = await run_maintenance(settings, writer, NOW)
    assert first.purged_clusters == 2 and first.vacuumed and first.backup is not None
    assert first.backup.is_file() and first.backup.name.startswith(BACKUP_PREFIX)
    backup = sqlite3.connect(first.backup)
    try:
        assert backup.execute("SELECT COUNT(*) FROM clusters").fetchone()[0] == 2
    finally:
        backup.close()
    again = await run_maintenance(settings, writer, NOW + timedelta(days=2))
    assert again.backup is None and not again.vacuumed and again.purged_clusters == 0
    for week in (1, 2, 3):
        later = await run_maintenance(settings, writer, NOW + timedelta(days=7 * week))
        assert later.backup is not None
    await writer.stop()
    kept = sorted(settings.backup_dir.glob(f"{BACKUP_PREFIX}*.db"))
    assert len(kept) == 2  # chỉ giữ 2 bản mới nhất theo cài đặt


async def test_a_failing_step_does_not_stop_the_others(
    engine: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.maintenance as module

    writer = Writer(engine)
    writer.start()
    settings = await full_settings(engine, tmp_path)

    def broken(_db: Path, _target: Path) -> None:
        raise OSError("ổ đĩa đầy")

    monkeypatch.setattr(module, "backup_database", broken)
    report = await run_maintenance(settings, writer, NOW)
    await writer.stop()
    assert report.backup is None and report.vacuumed  # sao lưu lỗi nhưng VACUUM vẫn chạy


async def test_radar_schedules_a_daily_maintenance_job(engine: AsyncEngine) -> None:
    from tests.test_scheduler import Fake, make_radar

    radar, writer = await make_radar(engine, [Fake("a")])
    radar.start()
    assert radar._scheduler is not None
    job = radar._scheduler.get_job("maintenance")
    assert job is not None and job.trigger.interval == timedelta(hours=24)  # type: ignore[attr-defined]
    await radar.stop()
    await writer.stop()


async def test_prune_snapshots_drops_old_but_keeps_the_newest_per_metric(
    engine: AsyncEngine,
) -> None:
    writer = Writer(engine)
    writer.start()
    ids = await seed(engine, writer)
    async with engine.connect() as conn:
        item_id = (
            await conn.execute(
                select(cluster_items.c.item_id).where(cluster_items.c.cluster_id == ids["new"])
            )
        ).scalar_one()

    async def add(conn) -> None:  # type: ignore[no-untyped-def]
        for days_ago, value in ((20, 1.0), (10, 2.0), (1, 3.0)):
            await conn.execute(
                metric_snapshots.insert().values(
                    item_id=item_id,
                    metric="stars",
                    value=value,
                    captured_at=NOW - timedelta(days=days_ago),
                )
            )

    await writer.submit(add)
    await writer.submit(lambda c: purge_old(c, 30, NOW))
    await writer.stop()
    async with engine.connect() as conn:
        values = sorted(
            r[0]
            for r in (
                await conn.execute(
                    select(metric_snapshots.c.value).where(metric_snapshots.c.item_id == item_id)
                )
            ).all()
        )
    assert values == [3.0, 5.0]


async def test_prune_snapshots_keeps_the_only_snapshot_even_when_old(engine: AsyncEngine) -> None:
    writer = Writer(engine)
    writer.start()
    ids = await seed(engine, writer)
    async with engine.connect() as conn:
        item_id = (
            await conn.execute(
                select(cluster_items.c.item_id).where(cluster_items.c.cluster_id == ids["marked"])
            )
        ).scalar_one()
    await writer.submit(lambda c: purge_old(c, 30, NOW))
    await writer.stop()
    async with engine.connect() as conn:
        left = (
            await conn.execute(
                select(func.count())
                .select_from(metric_snapshots)
                .where(metric_snapshots.c.item_id == item_id)
            )
        ).scalar_one()
    assert left == 1  # cụm bookmark 45 ngày tuổi: snapshot duy nhất không bị xóa
