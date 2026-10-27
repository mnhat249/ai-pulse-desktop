"""Truy vấn cho luồng giao diện: kết nối sqlite3 riêng, chỉ đọc, ngắn (không qua asyncio)."""

from __future__ import annotations

import html
import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

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
    intro: str | None = None  # đoạn giới thiệu do LLM viết; tóm tắt cũ không có
    excerpt: str = ""  # đoạn đầu nội dung gốc, dùng khi chưa có `intro`

    @property
    def lead_text(self) -> str:
        """Đoạn mở đầu hiện dưới tiêu đề: giới thiệu của LLM, không có thì nội dung gốc."""
        return self.intro or self.excerpt

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


def _topics_of(
    digest: dict[str, Any] | None,
    titles: list[str],
    sources: tuple[str, ...],
    rules: tuple[TopicRule, ...],
) -> tuple[str, ...]:
    parts = list(titles)
    if digest:
        parts += [digest.get(k) or "" for k in ("title_vi", "intro", "innovation", "impact")]
    return match_topics("\n".join(parts), rules, sources)


def _build_view(
    conn: sqlite3.Connection, row: sqlite3.Row, rules: tuple[TopicRule, ...] = DEFAULT_RULES
) -> ClusterView:
    members = conn.execute(
        "SELECT r.source, r.title, r.url, r.text FROM raw_items r "
        "JOIN cluster_items ci ON ci.item_id = r.id WHERE ci.cluster_id = ? ORDER BY r.id",
        (row["id"],),
    ).fetchall()
    digest = json.loads(row["digest"]) if row["digest"] else None
    sources = tuple(dict.fromkeys(m["source"] for m in members))
    labels = tuple(dict.fromkeys(source_label(s) for s in sources))
    titles = [m["title"] for m in members]
    original = titles[0] if titles else ""
    excerpt = next((e for e in (plain_excerpt(m["text"], LEAD_CHARS) for m in members) if e), "")
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
        topics=_topics_of(digest, titles, sources, rules),
        intro=digest.get("intro") if digest else None,
        excerpt=excerpt,
    )


_SELECT = (
    "SELECT c.id, c.importance, c.digest, c.primary_url, c.last_seen, "
    "u.read_at AS read_at, COALESCE(u.bookmarked, 0) AS bookmarked "
    "FROM clusters c LEFT JOIN user_state u ON u.cluster_id = c.id "
    "WHERE c.is_noise = 0"
)


def _filter_sql(view: ClusterFilter, source: str | None) -> tuple[str, list[object]]:
    sql = ""
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
    return sql, params


_ORDER = " ORDER BY c.importance DESC, c.last_seen DESC, c.id DESC"
_TOPIC_SELECT = (  # đủ để khớp chủ đề: tóm tắt, tiêu đề và nguồn của mọi bài trong cụm
    "SELECT c.id, c.digest, "
    "(SELECT group_concat(r.title, char(10)) FROM cluster_items ci "
    "JOIN raw_items r ON r.id = ci.item_id WHERE ci.cluster_id = c.id) AS titles, "
    "(SELECT group_concat(DISTINCT r.source) FROM cluster_items ci "
    "JOIN raw_items r ON r.id = ci.item_id WHERE ci.cluster_id = c.id) AS srcs "
    "FROM clusters c LEFT JOIN user_state u ON u.cluster_id = c.id WHERE c.is_noise = 0"
)
_COUNT = (
    "SELECT COUNT(*) FROM clusters c LEFT JOIN user_state u ON u.cluster_id = c.id "
    "WHERE c.is_noise = 0"
)


@lru_cache(maxsize=4096)
def _row_topics(
    digest: str | None, titles: str, sources: str, rules: tuple[TopicRule, ...]
) -> tuple[str, ...]:
    """Chủ đề của một cụm, nhớ theo nội dung: lần làm mới sau không phải dò regex lại."""
    return _topics_of(
        json.loads(digest) if digest else None,
        titles.split("\n"),
        tuple(sources.split(",")),
        rules,
    )


def _topic_ids(
    conn: sqlite3.Connection,
    where: str,
    params: list[object],
    topics: tuple[str, ...],
    rules: tuple[TopicRule, ...],
    stop_after: int,
) -> list[int]:
    """Id các cụm khớp chủ đề, theo thứ tự hiển thị, trong `MAX_TOPIC_SCAN_ROWS` cụm đầu.

    Dừng khi đã đủ `stop_after` cụm; chỉ dò các luật của chủ đề đang lọc.
    """
    wanted = tuple(rule for rule in rules if rule.key in topics)
    found: list[int] = []
    if stop_after <= 0 or not wanted:
        return found
    cursor = conn.execute(
        _TOPIC_SELECT + where + _ORDER + " LIMIT ?", [*params, MAX_TOPIC_SCAN_ROWS]
    )
    for row in cursor:
        if _row_topics(row["digest"], row["titles"] or "", row["srcs"] or "", wanted):
            found.append(int(row["id"]))
            if len(found) >= stop_after:
                break
    cursor.close()
    return found


def list_clusters(
    conn: sqlite3.Connection,
    *,
    view: ClusterFilter = "all",
    source: str | None = None,
    limit: int = 30,
    offset: int = 0,
    topics: tuple[str, ...] | None = None,
    topic_rules: tuple[TopicRule, ...] = DEFAULT_RULES,
) -> list[ClusterView]:
    """Cụm không phải rác, điểm cao trước; lọc chưa đọc / bookmark / theo nguồn / theo chủ đề.

    `topics` là các khóa chủ đề (cụm khớp một trong số đó thì giữ lại); None = không lọc.
    Khi lọc chủ đề, chỉ xét `MAX_TOPIC_SCAN_ROWS` cụm đầu. `offset` để phân trang.
    """
    where, params = _filter_sql(view, source)
    if topics is None:
        rows = conn.execute(
            _SELECT + where + _ORDER + " LIMIT ? OFFSET ?", [*params, limit, offset]
        ).fetchall()
        return [_build_view(conn, row, topic_rules) for row in rows]
    page = _topic_ids(conn, where, params, topics, topic_rules, offset + limit)[offset:]
    if not page:
        return []
    marks = ",".join("?" * len(page))
    rows = conn.execute(_SELECT + f" AND c.id IN ({marks})", page).fetchall()
    by_id = {int(row["id"]): row for row in rows}
    return [_build_view(conn, by_id[cid], topic_rules) for cid in page if cid in by_id]


def count_clusters(
    conn: sqlite3.Connection,
    *,
    view: ClusterFilter = "all",
    source: str | None = None,
    topics: tuple[str, ...] | None = None,
    topic_rules: tuple[TopicRule, ...] = DEFAULT_RULES,
    cap: int = MAX_TOPIC_SCAN_ROWS,
) -> int:
    """Số cụm khớp bộ lọc, tối đa `cap` (để tính số trang); cùng quy tắc với `list_clusters`."""
    where, params = _filter_sql(view, source)
    if topics is not None:
        return len(_topic_ids(conn, where, params, topics, topic_rules, cap))
    row = conn.execute(_COUNT + where, params).fetchone()
    return min(int(row[0]), cap)


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
LEAD_CHARS = 280  # đoạn mở đầu dưới tiêu đề khi chưa có giới thiệu của LLM
_TAG = re.compile(r"<[^>]*>")
_SENTENCE_END = re.compile(r"[.!?](?=\s+(\S))")


def plain_excerpt(text: str | None, limit: int = EXCERPT_CHARS) -> str:
    """Bỏ thẻ HTML, giải mã ký tự đặc biệt, gộp khoảng trắng và cắt tối đa `limit` ký tự.

    Cắt ở cuối câu nếu câu đó qua nửa `limit`; không thì cắt ở ranh giới từ và thêm "…".
    """
    clean = " ".join(html.unescape(_TAG.sub(" ", text or "")).split())
    if len(clean) <= limit:
        return clean
    head = clean[: limit + 1]
    ends = [
        m.end()
        for m in _SENTENCE_END.finditer(head)
        if m.group(1)[0].isupper() or m.group(1)[0].isdigit()
    ]
    if ends and ends[-1] > limit // 2:
        return head[: ends[-1]]
    cut = head.rfind(" ", 0, limit)
    return clean[: cut if cut > limit // 2 else limit].rstrip() + "…"


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
