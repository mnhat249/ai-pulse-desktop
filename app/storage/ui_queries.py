"""Truy vấn cho luồng giao diện: kết nối sqlite3 riêng, chỉ đọc, ngắn (không qua asyncio)."""

from __future__ import annotations

import html
import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from app.core import sources
from app.core.topics import DEFAULT_RULES, TopicRule, match_topics

ClusterFilter = Literal["all", "unread", "bookmarked"]

BUSY_TIMEOUT_SECONDS = 5
MAX_TOPIC_SCAN_ROWS = 500  # khi lọc chủ đề: số cụm tối đa duyệt qua để gom đủ `limit`


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
    topics: tuple[str, ...] = field(default_factory=tuple)  # khóa chủ đề khớp (xem core.topics)

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


def _build_view(
    conn: sqlite3.Connection, row: sqlite3.Row, rules: tuple[TopicRule, ...] = DEFAULT_RULES
) -> ClusterView:
    members = conn.execute(
        "SELECT r.source, r.title, r.url FROM raw_items r "
        "JOIN cluster_items ci ON ci.item_id = r.id WHERE ci.cluster_id = ? ORDER BY r.id",
        (row["id"],),
    ).fetchall()
    digest = json.loads(row["digest"]) if row["digest"] else None
    sources = tuple(dict.fromkeys(m["source"] for m in members))
    labels = tuple(dict.fromkeys(source_label(s) for s in sources))
    original = members[0]["title"] if members else ""
    title = digest["title_vi"] if digest else original
    innovation = digest["innovation"] if digest else None
    impact = digest["impact"] if digest else None
    haystack = "\n".join([title, *(m["title"] for m in members), innovation or "", impact or ""])
    return ClusterView(
        id=row["id"],
        title=title,
        original_title=original,
        innovation=innovation,
        impact=impact,
        importance=float(row["importance"]),
        sources=sources,
        primary_url=row["primary_url"],
        urls=tuple(dict.fromkeys(m["url"] for m in members)),
        read=row["read_at"] is not None,
        bookmarked=bool(row["bookmarked"]),
        summarized=digest is not None,
        last_seen=_utc(row["last_seen"]),
        labels=labels,
        topics=match_topics(haystack, rules, sources),
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
    topics: tuple[str, ...] | None = None,
    topic_rules: tuple[TopicRule, ...] = DEFAULT_RULES,
) -> list[ClusterView]:
    """Cụm không phải rác, điểm cao trước; lọc chưa đọc / bookmark / theo nguồn / theo chủ đề.

    `topics` là các khóa chủ đề (cụm khớp một trong số đó thì giữ lại); None = không lọc.
    Khi lọc, duyệt theo trang tới khi đủ `limit` hoặc hết `MAX_TOPIC_SCAN_ROWS` dòng.
    """
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
    sql += " ORDER BY c.importance DESC, c.last_seen DESC, c.id DESC LIMIT ? OFFSET ?"
    if topics is None:
        rows = conn.execute(sql, [*params, limit, 0]).fetchall()
        return [_build_view(conn, row, topic_rules) for row in rows]
    wanted = set(topics)
    page = max(limit, 50)
    found: list[ClusterView] = []
    scanned = 0
    while len(found) < limit and scanned < MAX_TOPIC_SCAN_ROWS:
        size = min(page, MAX_TOPIC_SCAN_ROWS - scanned)
        rows = conn.execute(sql, [*params, size, scanned]).fetchall()
        for row in rows:
            cluster = _build_view(conn, row, topic_rules)
            if wanted.intersection(cluster.topics):
                found.append(cluster)
                if len(found) == limit:
                    break
        scanned += size
        if len(rows) < size:
            break
    return found


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


EXCERPT_CHARS = 300
_TAG = re.compile(r"<[^>]*>")


def plain_excerpt(text: str | None, limit: int = EXCERPT_CHARS) -> str:
    """Bỏ thẻ HTML, giải mã ký tự đặc biệt, gộp khoảng trắng và cắt tối đa `limit` ký tự."""
    clean = " ".join(html.unescape(_TAG.sub(" ", text or "")).split())
    if len(clean) <= limit:
        return clean
    return clean[:limit].rstrip() + "…"


@dataclass(frozen=True)
class SourceItemView:
    source: str
    label: str
    title: str
    url: str


@dataclass(frozen=True)
class ClusterDetails:
    """Phần nặng của thẻ, chỉ đọc khi thẻ được mở."""

    excerpt: str
    items: tuple[SourceItemView, ...]


def cluster_details(conn: sqlite3.Connection, cluster_id: int) -> ClusterDetails:
    """Đoạn đầu nội dung bài chính (bài đầu có chữ) và từng bài trong cụm."""
    rows = conn.execute(
        "SELECT r.source, r.title, r.url, r.text FROM raw_items r "
        "JOIN cluster_items ci ON ci.item_id = r.id WHERE ci.cluster_id = ? ORDER BY r.id",
        (cluster_id,),
    ).fetchall()
    excerpt = next((e for e in (plain_excerpt(r["text"]) for r in rows) if e), "")
    items = tuple(
        SourceItemView(r["source"], source_label(r["source"]), r["title"], r["url"]) for r in rows
    )
    return ClusterDetails(excerpt, items)
