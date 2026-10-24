from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

import httpx

from app.adapters.base import SourceError, collect, parse_items, parse_json, request
from app.config import HackerNewsSettings
from app.core.models import RawItem, utcnow
from app.core.sources import SourceInfo, register

SEARCH_URL = "https://hn.algolia.com/api/v1/search_by_date"
ITEM_URL = "https://news.ycombinator.com/item?id={}"

register(
    SourceInfo("hackernews", "HN", "#B5481B", rank=3, heat_metric="points", title="Hacker News")
)


def keyword_pattern(keywords: list[str]) -> re.Pattern[str]:
    alternatives = "|".join(re.escape(k) for k in keywords)
    return re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)", re.IGNORECASE)


def build_story(hit: dict[str, Any]) -> RawItem:
    story_id = str(hit["objectID"])
    hn_url = ITEM_URL.format(story_id)
    story_url = hit.get("url")
    return RawItem(
        source="hackernews",
        source_id=story_id,
        url=story_url or hn_url,
        title=hit["title"],
        text=hit.get("story_text") or "",
        author=hit.get("author"),
        published_at=datetime.fromtimestamp(int(hit["created_at_i"]), tz=UTC),
        metrics={
            "points": float(hit.get("points") or 0),
            "comments": float(hit.get("num_comments") or 0),
        },
        links=[u for u in (story_url, hn_url) if u],
    )


class HackerNewsAdapter:
    name = "hackernews"

    def __init__(self, settings: HackerNewsSettings) -> None:
        self.interval_minutes = settings.interval_minutes
        self._settings = settings
        self._pattern = keyword_pattern(settings.keywords)
        self.warnings: list[str] = []

    async def _search(self, client: httpx.AsyncClient, keyword: str) -> list[dict[str, Any]]:
        since = int(utcnow().timestamp()) - self._settings.lookback_hours * 3600
        response = await request(
            client,
            self.name,
            SEARCH_URL,
            params={
                "tags": "story",
                "query": keyword,
                "restrictSearchableAttributes": "title",
                "numericFilters": f"points>={self._settings.min_points},created_at_i>{since}",
                "hitsPerPage": 50,
            },
        )
        body = parse_json(self.name, response)
        if not isinstance(body, dict) or not isinstance(body.get("hits"), list):
            raise SourceError(self.name, "định dạng dữ liệu đã đổi: thiếu 'hits'")
        return list(body["hits"])

    async def fetch(self, client: httpx.AsyncClient) -> list[RawItem]:
        self.warnings = []

        async def search(keyword: str) -> list[dict[str, Any]]:
            return await self._search(client, keyword)

        found = await collect(self.name, self._settings.keywords, search, self.warnings)
        hits: dict[str, dict[str, Any]] = {}
        for hit in found:
            if self._pattern.search(hit.get("title") or ""):
                hits.setdefault(str(hit.get("objectID")), hit)
        return parse_items(self.name, hits.values(), build_story)
