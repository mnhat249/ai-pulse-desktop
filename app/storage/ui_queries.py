"""Truy vấn cho luồng giao diện: kết nối sqlite3 riêng, chỉ đọc, ngắn (không qua asyncio)."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from app.core import sources

ClusterFilter = Literal["all", "unread", "bookmarked"]

BUSY_TIMEOUT_SECONDS = 5


def source_label(source: str) -> str:
    return sources.info(source).label


@dataclass(frozen=True)
class ClusterView:
    id: int
    title: str
    original_title: str
    innovation: str | None
    impact: str | None
    importance: float
    sources: tuple[str, ...]
    primary_url: str | None
    urls: tuple[str, ...]
    read: bool
    bookmarked: bool
    summarized: bool
    last_seen: datetime
    labels: tuple[str, ...] = field(default_factory=tuple)

    @property
    def source_text(self) -> str:
        return " · ".join(self.labels)


@dataclass(frozen=True)
class SourceStatusView:
    source: str
    last_run: datetime
    ok: bool
    error: str | None
    item_count: int


def open_reader(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=BUSY_TIMEOUT_SECONDS, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


def _utc(value: str | None) -> datetime:
    if not value:
        return datetime.fromtimestamp(0, tz=UTC)
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def _build_view(conn: sqlite3.Connection, row: sqlite3.Row) -> ClusterView:
    members = conn.execute(
        "SELECT r.source, r.title, r.url FROM raw_items r "
        "JOIN cluster_items ci ON ci.item_id = r.id WHERE ci.cluster_id = ? ORDER BY r.id",
        (row["id"],),
    ).fetchall()
    digest = json.loads(row["digest"]) if row["digest"] else None
    sources = tuple(dict.fromkeys(m["source"] for m in members))
    labels = tuple(dict.fromkeys(source_label(s) for s in sources))
    original = members[0]["title"] if members else ""
    return ClusterView(
        id=row["id"],
        title=digest["title_vi"] if digest else original,
        original_title=original,
        innovation=digest["innovation"] if digest else None,
        impact=digest["impact"] if digest else None,
        importance=float(row["importance"]),
        sources=sources,
        primary_url=row["primary_url"],
        urls=tuple(dict.fromkeys(m["url"] for m in members)),
        read=row["read_at"] is not None,
        bookmarked=bool(row["bookmarked"]),
        summarized=digest is not None,
        last_seen=_utc(row["last_seen"]),
        labels=labels,
    )


_SELECT = (
    "SELECT c.id, c.importance, c.digest, c.primary_url, c.last_seen, "
    "u.read_at AS read_at, COALESCE(u.bookmarked, 0) AS bookmarked "
    "FROM clusters c LEFT JOIN user_state u ON u.cluster_id = c.id "
    "WHERE c.is_noise = 0"
)


def list_clusters(
    conn: sqlite3.Connection,
    *,
    view: ClusterFilter = "all",
    source: str | None = None,
    limit: int = 30,
) -> list[ClusterView]:
    """Cụm không phải rác, điểm cao trước; lọc chưa đọc / bookmark / theo nguồn."""
    sql = _SELECT
    params: list[object] = []
    if view == "unread":
        sql += " AND u.read_at IS NULL"
    elif view == "bookmarked":
        sql += " AND u.bookmarked = 1"
    if source:
        sql += (
            " AND EXISTS (SELECT 1 FROM cluster_items ci JOIN raw_items r ON r.id = ci.item_id "
            "WHERE ci.cluster_id = c.id AND r.source = ?)"
        )
        params.append(source)
    sql += " ORDER BY c.importance DESC, c.last_seen DESC, c.id DESC LIMIT ?"
    params.append(limit)
    return [_build_view(conn, row) for row in conn.execute(sql, params).fetchall()]


def get_cluster(conn: sqlite3.Connection, cluster_id: int) -> ClusterView | None:
    row = conn.execute(_SELECT + " AND c.id = ?", (cluster_id,)).fetchone()
    return _build_view(conn, row) if row else None


def count_unread(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM clusters c LEFT JOIN user_state u ON u.cluster_id = c.id "
        "WHERE c.is_noise = 0 AND u.read_at IS NULL"
    ).fetchone()
    return int(row[0])


def list_sources(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT DISTINCT source FROM raw_items ORDER BY source").fetchall()
    return [r[0] for r in rows]


def source_statuses(conn: sqlite3.Connection) -> list[SourceStatusView]:
    """Lần chạy cuối của mỗi nguồn (màn hình "tình trạng nguồn")."""
    rows = conn.execute(
        "SELECT s.* FROM source_runs s "
        "JOIN (SELECT source, MAX(id) AS id FROM source_runs GROUP BY source) m ON m.id = s.id "
        "ORDER BY s.source"
    ).fetchall()
    return [
        SourceStatusView(
            r["source"], _utc(r["started_at"]), bool(r["ok"]), r["error"], int(r["item_count"])
        )
        for r in rows
    ]


def last_error(conn: sqlite3.Connection, source: str) -> str | None:
    """Lỗi gần nhất của nguồn (kể cả khi lần chạy cuối đã thành công)."""
    row = conn.execute(
        "SELECT error FROM source_runs WHERE source = ? AND ok = 0 ORDER BY id DESC LIMIT 1",
        (source,),
    ).fetchone()
    return None if row is None else row[0]
