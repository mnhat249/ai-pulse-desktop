from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.models import RawItem
from app.storage.db import make_engine, migrate
from app.storage.ops import ingest_items, record_source_run
from app.storage.queries import count_raw_items, source_statuses
from app.storage.tables import metadata, metric_snapshots
from app.storage.writer import Writer

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)


def item(n: int, **kw: object) -> RawItem:
    base: dict[str, object] = {
        "source": "github",
        "source_id": str(n),
        "url": f"https://github.com/o/r{n}",
        "title": f"o/r{n}",
        "published_at": NOW,
    }
    return RawItem(**{**base, **kw})


def test_migration_creates_all_tables_matching_models(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    migrate(db)
    sync = create_engine(f"sqlite:///{db.as_posix()}")
    tables = set(inspect(sync).get_table_names()) - {"alembic_version"}
    assert tables == {
        "raw_items",
        "metric_snapshots",
        "clusters",
        "cluster_items",
        "user_state",
        "source_runs",
        "llm_usage",
        "item_keys",
        "item_embeddings",
        "seen_items",
    }
    with sync.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), metadata)
    sync.dispose()
    assert diff == []


def test_migrate_leaves_database_in_wal_mode(tmp_path: Path) -> None:
    import sqlite3

    db = tmp_path / "w.db"
    migrate(db)
    conn = sqlite3.connect(db)
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        conn.close()


def test_migrate_is_idempotent_and_does_not_backup_fresh_db(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    backups = tmp_path / "backups"
    migrate(db, backups)
    migrate(db, backups)
    assert not backups.exists()


async def test_pragmas_wal_and_busy_timeout(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        assert (await conn.execute(text("PRAGMA journal_mode"))).scalar_one() == "wal"
        assert (await conn.execute(text("PRAGMA busy_timeout"))).scalar_one() == 5000
        assert (await conn.execute(text("PRAGMA foreign_keys"))).scalar_one() == 1


async def test_ten_writers_and_a_reader_never_hit_database_locked(tmp_path: Path) -> None:
    db = tmp_path / "c.db"
    migrate(db)
    write_engine, read_engine = make_engine(db), make_engine(db)
    writer = Writer(write_engine)
    writer.start()
    done = asyncio.Event()
    reads = 0

    async def reader() -> None:
        nonlocal reads
        while not done.is_set():
            await count_raw_items(read_engine)
            reads += 1

    async def producer(p: int) -> None:
        for n in range(100):
            items = [item(p * 1000 + n, source=f"s{p}")]
            await writer.submit(lambda conn, i=items: ingest_items(conn, i, NOW))

    reader_task = asyncio.create_task(reader())
    await asyncio.gather(*(producer(p) for p in range(10)))
    done.set()
    await reader_task
    await writer.stop()
    assert await count_raw_items(read_engine) == 1000
    assert reads > 0
    await write_engine.dispose()
    await read_engine.dispose()


async def test_failing_op_does_not_poison_the_batch(engine: AsyncEngine) -> None:
    writer = Writer(engine)
    writer.start()

    async def bad(conn: AsyncConnection) -> None:
        raise RuntimeError("boom")

    results = await asyncio.gather(
        writer.submit(lambda c: ingest_items(c, [item(1)], NOW)),
        writer.submit(bad),
        writer.submit(lambda c: ingest_items(c, [item(2)], NOW)),
        return_exceptions=True,
    )
    await writer.stop()
    assert results[0] == 1 and results[2] == 1
    assert isinstance(results[1], RuntimeError)
    assert await count_raw_items(engine) == 2


async def test_stop_drains_queue_and_submit_after_stop_fails(engine: AsyncEngine) -> None:
    writer = Writer(engine)
    writer.start()
    pending = asyncio.create_task(writer.submit(lambda c: ingest_items(c, [item(1)], NOW)))
    await asyncio.sleep(0)
    await writer.stop()
    assert await pending == 1
    with pytest.raises(RuntimeError):
        await writer.submit(lambda c: ingest_items(c, [item(2)], NOW))


async def test_same_source_and_id_is_stored_once(engine: AsyncEngine) -> None:
    writer = Writer(engine)
    writer.start()
    assert await writer.submit(lambda c: ingest_items(c, [item(1), item(1)], NOW)) == 1
    assert await writer.submit(lambda c: ingest_items(c, [item(1)], NOW)) == 0
    await writer.stop()
    assert await count_raw_items(engine) == 1


async def test_metrics_snapshots_and_star_velocity(engine: AsyncEngine) -> None:
    writer = Writer(engine)
    writer.start()
    first = item(1, metrics={"stars": 100, "age_hours": 500})
    second = item(1, metrics={"stars": 160, "age_hours": 524})
    await writer.submit(lambda c: ingest_items(c, [first], NOW))
    await writer.submit(lambda c: ingest_items(c, [second], NOW + timedelta(hours=24)))
    await writer.stop()
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                select(metric_snapshots.c.metric, metric_snapshots.c.value).order_by(
                    metric_snapshots.c.id
                )
            )
        ).all()
    assert ("stars", 160.0) in rows
    assert ("stars_per_24h", 60.0) in rows
    assert not any(metric == "stars_per_24h" and value == 100 for metric, value in rows[:2])
    assert all(metric != "age_hours" for metric, _ in rows)


async def test_new_repo_velocity_uses_age(engine: AsyncEngine) -> None:
    writer = Writer(engine)
    writer.start()
    await writer.submit(
        lambda c: ingest_items(c, [item(1, metrics={"stars": 60, "age_hours": 12})], NOW)
    )
    await writer.stop()
    async with engine.connect() as conn:
        velocity = (
            await conn.execute(
                select(metric_snapshots.c.value).where(metric_snapshots.c.metric == "stars_per_24h")
            )
        ).scalar_one()
    assert velocity == pytest.approx(120)


async def test_source_status_returns_latest_run_per_source(engine: AsyncEngine) -> None:
    writer = Writer(engine)
    writer.start()
    await writer.submit(lambda c: record_source_run(c, "hn", NOW, False, 0, "timeout"))
    await writer.submit(
        lambda c: record_source_run(c, "hn", NOW + timedelta(minutes=15), True, 7, None)
    )
    await writer.submit(lambda c: record_source_run(c, "github", NOW, False, 0, "403"))
    await writer.stop()
    statuses = {s.source: s for s in await source_statuses(engine)}
    assert statuses["hn"].last_ok and statuses["hn"].last_item_count == 7
    assert not statuses["github"].last_ok and statuses["github"].last_error == "403"


def test_backup_database_includes_data_still_in_the_wal_file(tmp_path: Path) -> None:
    import sqlite3

    from app.storage.db import backup_database

    db, target = tmp_path / "b.db", tmp_path / "backup.db"
    migrate(db)
    writer = sqlite3.connect(db)
    writer.execute("PRAGMA wal_autocheckpoint=0")
    writer.execute(
        "INSERT INTO source_runs (source, started_at, ok, item_count) "
        "VALUES ('x', '2026-01-01', 1, 5)"
    )
    writer.commit()
    assert (tmp_path / "b.db-wal").stat().st_size > 0
    backup_database(db, target)
    writer.close()
    copy = sqlite3.connect(target)
    try:
        assert copy.execute("SELECT item_count FROM source_runs").fetchall() == [(5,)]
    finally:
        copy.close()


def test_migrate_backs_up_an_existing_database_before_upgrading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sqlite3

    import app.storage.db as dbmod

    db, backups = tmp_path / "m.db", tmp_path / "backups"
    migrate(db)
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO llm_usage (day, provider, calls) VALUES ('d', 'p', 7)")
    conn.commit()
    conn.close()
    monkeypatch.setattr(dbmod, "_current_revision", lambda _p: "0000")
    monkeypatch.setattr(dbmod.command, "upgrade", lambda *_a, **_k: None)
    migrate(db, backups)
    (backup,) = backups.iterdir()
    assert backup.name.endswith("-0000.db")
    check = sqlite3.connect(backup)
    try:
        assert check.execute("SELECT calls FROM llm_usage").fetchall() == [(7,)]
    finally:
        check.close()
