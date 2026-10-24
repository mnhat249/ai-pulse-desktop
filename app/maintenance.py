"""Dọn dữ liệu định kỳ: xóa cụm cũ (trừ bookmark), sao lưu hằng tuần, VACUUM hằng tuần."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from app.config import MaintenanceSettings, Settings
from app.core.models import utcnow
from app.storage.db import backup_database
from app.storage.tables import (
    cluster_items,
    clusters,
    metric_snapshots,
    raw_items,
    seen_items,
    user_state,
)
from app.storage.writer import Writer

logger = logging.getLogger(__name__)

BACKUP_PREFIX = "neuralradar-weekly-"
CHUNK_SIZE = 500
SNAPSHOT_KEEP_DAYS = 7
VACUUM_TIMEOUT_SECONDS = 60


@dataclass(frozen=True)
class MaintenanceReport:
    purged_clusters: int = 0
    purged_items: int = 0
    backup: Path | None = None
    pruned_backups: int = 0
    vacuumed: bool = False


async def purge_old(
    conn: AsyncConnection, retention_days: int, now: datetime, tombstone_days: int = 180
) -> tuple[int, int]:
    """Xóa cụm không có bài mới từ `retention_days` ngày (trừ cụm có bookmark) và bài mồ côi.

    Snapshot chỉ số, khóa chuẩn và vector đi theo bài nhờ khóa ngoại ON DELETE CASCADE. Mỗi bài
    bị xóa để lại một dấu vết `(source, source_id)` trong `seen_items`: feed vẫn trả lại bài cũ,
    không có dấu vết thì lần quét sau sẽ nạp lại thành "tin mới". Dấu vết cũ hơn `tombstone_days`
    ngày thì bỏ.
    """
    cutoff = now - timedelta(days=retention_days)
    stale = (
        select(clusters.c.id)
        .outerjoin(user_state, user_state.c.cluster_id == clusters.c.id)
        .where(
            clusters.c.last_seen < cutoff,
            (user_state.c.bookmarked.is_(None)) | (user_state.c.bookmarked.is_(False)),
        )
    )
    ids = [row[0] for row in (await conn.execute(stale)).all()]
    for chunk in _chunks(ids):
        await conn.execute(delete(cluster_items).where(cluster_items.c.cluster_id.in_(chunk)))
        await conn.execute(delete(user_state).where(user_state.c.cluster_id.in_(chunk)))
        await conn.execute(delete(clusters).where(clusters.c.id.in_(chunk)))
    orphans = (
        select(raw_items.c.id, raw_items.c.source, raw_items.c.source_id)
        .outerjoin(cluster_items, cluster_items.c.item_id == raw_items.c.id)
        .where(cluster_items.c.item_id.is_(None), raw_items.c.fetched_at < cutoff)
    )
    orphan_rows = (await conn.execute(orphans)).all()
    for chunk in _chunks(orphan_rows):
        await conn.execute(
            sqlite_insert(seen_items)
            .values(
                [{"source": r.source, "source_id": r.source_id, "purged_at": now} for r in chunk]
            )
            .on_conflict_do_nothing()
        )
        await conn.execute(delete(raw_items).where(raw_items.c.id.in_([r.id for r in chunk])))
    await conn.execute(
        delete(seen_items).where(seen_items.c.purged_at < now - timedelta(days=tombstone_days))
    )
    await prune_snapshots(conn, now)
    return len(ids), len(orphan_rows)


async def prune_snapshots(conn: AsyncConnection, now: datetime) -> int:
    """Bỏ snapshot cũ hơn `SNAPSHOT_KEEP_DAYS` ngày, luôn giữ snapshot mới nhất của mỗi chỉ số."""
    newest = (
        select(func.max(metric_snapshots.c.id))
        .group_by(metric_snapshots.c.item_id, metric_snapshots.c.metric)
        .scalar_subquery()
    )
    result = await conn.execute(
        delete(metric_snapshots).where(
            metric_snapshots.c.captured_at < now - timedelta(days=SNAPSHOT_KEEP_DAYS),
            metric_snapshots.c.id.not_in(newest),
        )
    )
    return int(result.rowcount or 0)


def _chunks(rows: Sequence[Any]) -> Iterator[Sequence[Any]]:
    """Chia lô để câu lệnh IN không vượt giới hạn số tham số của SQLite."""
    for start in range(0, len(rows), CHUNK_SIZE):
        yield rows[start : start + CHUNK_SIZE]


def prune_backups(backup_dir: Path, keep: int) -> int:
    """Giữ `keep` bản sao lưu hằng tuần mới nhất, xóa các bản cũ hơn."""
    files = sorted(backup_dir.glob(f"{BACKUP_PREFIX}*.db"), key=lambda p: p.name, reverse=True)
    for old in files[keep:]:
        old.unlink(missing_ok=True)
    return max(0, len(files) - keep)


def vacuum(db_path: Path) -> None:
    conn = sqlite3.connect(db_path, timeout=VACUUM_TIMEOUT_SECONDS)
    try:
        conn.execute("VACUUM")
    finally:
        conn.close()


class MaintenanceState:
    """Lần gần nhất đã sao lưu / VACUUM, lưu trong một file JSON cạnh DB."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: dict[str, str] = {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            self._data = {k: str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}
        except (OSError, ValueError):
            self._data = {}

    def due(self, key: str, every_days: int, now: datetime) -> bool:
        last = self._data.get(key)
        if not last:
            return True
        try:
            return now - datetime.fromisoformat(last) >= timedelta(days=every_days)
        except ValueError:
            return True

    def mark(self, key: str, now: datetime) -> None:
        self._data[key] = now.isoformat()
        try:
            temp = self._path.with_suffix(".json.tmp")
            temp.write_text(json.dumps(self._data), encoding="utf-8")
            os.replace(temp, self._path)
        except OSError:
            logger.exception("Không lưu được trạng thái bảo trì")


async def run_maintenance(
    settings: Settings, writer: Writer, now: datetime | None = None
) -> MaintenanceReport:
    """Một lần bảo trì; mỗi bước lỗi riêng chỉ được log, không chặn các bước sau."""
    now = now or utcnow()
    cfg: MaintenanceSettings = settings.maintenance
    state = MaintenanceState(settings.db_path.parent / "maintenance.json")
    purged_clusters = purged_items = pruned = 0
    backup: Path | None = None
    vacuumed = False
    try:
        purged_clusters, purged_items = await writer.submit(
            lambda conn: purge_old(conn, cfg.retention_days, now, cfg.tombstone_days)
        )
    except Exception:
        logger.exception("Không dọn được cụm cũ")
    if state.due("backup", cfg.backup_every_days, now):
        try:
            settings.backup_dir.mkdir(parents=True, exist_ok=True)
            target = settings.backup_dir / f"{BACKUP_PREFIX}{now:%Y%m%d-%H%M%S}.db"
            await asyncio.to_thread(backup_database, settings.db_path, target)
            backup = target
            state.mark("backup", now)
            pruned = prune_backups(settings.backup_dir, cfg.backups_to_keep)
        except Exception:
            logger.exception("Không sao lưu được DB")
    if state.due("vacuum", cfg.vacuum_every_days, now):
        try:
            await asyncio.to_thread(vacuum, settings.db_path)
            vacuumed = True
            state.mark("vacuum", now)
        except Exception:
            logger.exception("Không VACUUM được DB; thử lại lần bảo trì sau")
    logger.info(
        "Bảo trì: xóa %d cụm, %d bài; sao lưu=%s; VACUUM=%s",
        purged_clusters,
        purged_items,
        backup.name if backup else "không",
        vacuumed,
    )
    return MaintenanceReport(purged_clusters, purged_items, backup, pruned, vacuumed)
