from __future__ import annotations

import asyncio
import calendar
import html
import re
from datetime import UTC, datetime
from typing import Any

import feedparser
import httpx

from app.adapters.base import SourceError, request
from app.config import FeedSettings, feed_slug
from app.core.models import RawItem, utcnow
from app.core.sources import SourceInfo, register

MAX_TEXT_CHARS = 2000
RSS_COLOR = "#4D5E26"
TAG = re.compile(r"<[^>]+>")
SPACES = re.compile(r"\s+")
ACCEPT = "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8"

register(SourceInfo("rss_", "RSS", RSS_COLOR, rank=20), prefix=True)


def plain_text(markup: str) -> str:
    """Bỏ thẻ HTML, giải mã ký tự đặc biệt, gọn khoảng trắng, cắt độ dài."""
    text = SPACES.sub(" ", html.unescape(TAG.sub(" ", markup))).strip()
    return text[:MAX_TEXT_CHARS]


def entry_time(entry: Any) -> datetime:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    now = utcnow()
    if parsed:
        return min(datetime.fromtimestamp(calendar.timegm(parsed), tz=UTC), now)  # bài đặt lịch
    return now


def build_entry(source: str, entry: Any) -> RawItem:
    link = entry["link"]
    summary = entry.get("summary") or ""
    if not summary and entry.get("content"):
        summary = entry["content"][0].get("value", "")
    return RawItem(
        source=source,
        source_id=entry.get("id") or link,
        url=link,
        title=plain_text(entry["title"]),
        text=plain_text(summary),
        author=entry.get("author"),
        published_at=entry_time(entry),
        links=[link],
    )


class RSSAdapter:
    """Một adapter dùng chung cho mọi feed RSS/Atom; mỗi feed là một nguồn riêng `rss_<tên>`."""

    def __init__(self, feed: FeedSettings) -> None:
        self.name = f"rss_{feed_slug(feed.name)}"
        self.interval_minutes = feed.interval_minutes
        self.warnings: list[str] = []
        self._feed = feed
        register(SourceInfo(self.name, feed.name, RSS_COLOR, rank=20, title=f"RSS · {feed.name}"))

    async def fetch(self, client: httpx.AsyncClient) -> list[RawItem]:
        self.warnings = []
        response = await request(client, self.name, self._feed.url, headers={"Accept": ACCEPT})
        parsed = await asyncio.to_thread(feedparser.parse, response.content)
        if not parsed.entries:
            reason = "không phải RSS/Atom hợp lệ" if parsed.bozo else "feed không có bài nào"
            raise SourceError(self.name, reason)
        newest = sorted(parsed.entries, key=entry_time, reverse=True)[: self._feed.max_entries]
        items: list[RawItem] = []
        for entry in newest:
            try:
                items.append(build_entry(self.name, entry))
            except (KeyError, TypeError, ValueError) as exc:
                self.warnings.append(f"bỏ một bài hỏng: {exc!r}")
        if not items:
            raise SourceError(self.name, "định dạng dữ liệu đã đổi: mọi bài đều thiếu tiêu đề/link")
        return items
