from __future__ import annotations

import logging
from typing import Any

import httpx

from app.adapters.base import SourceError, collect, parse_datetime, parse_json, request
from app.adapters.hackernews import keyword_pattern
from app.config import BlueskySettings
from app.core.models import RawItem
from app.core.sources import SourceInfo, register

logger = logging.getLogger(__name__)

FEED_URL = "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed"
POST_URL = "https://bsky.app/profile/{handle}/post/{rkey}"
TITLE_CHARS = 110
MAX_LINKS = 3

register(SourceInfo("bluesky", "Bluesky", "#1F5FA8", rank=10, heat_metric="likes"))


def post_links(post: dict[str, Any]) -> list[str]:
    record = post.get("record") or {}
    links: list[str] = []
    external = (post.get("embed") or {}).get("external") or {}
    if external.get("uri"):
        links.append(external["uri"])
    for facet in record.get("facets") or []:
        for feature in facet.get("features") or []:
            if feature.get("$type") == "app.bsky.richtext.facet#link" and feature.get("uri"):
                links.append(feature["uri"])
    return list(dict.fromkeys(links))[:MAX_LINKS]


def build_post(post: dict[str, Any]) -> RawItem:
    record = post["record"]
    handle = post["author"]["handle"]
    text = (record.get("text") or "").strip()
    external = (post.get("embed") or {}).get("external") or {}
    extra = " ".join(p for p in (external.get("title"), external.get("description")) if p)
    first_line = text.splitlines()[0] if text else extra
    title = first_line if len(first_line) <= TITLE_CHARS else first_line[: TITLE_CHARS - 1] + "…"
    return RawItem(
        source="bluesky",
        source_id=post["uri"],
        url=POST_URL.format(handle=handle, rkey=post["uri"].rsplit("/", 1)[-1]),
        title=title,
        text=f"{text}\n{extra}".strip(),
        author=handle,
        published_at=parse_datetime(record["createdAt"]),
        metrics={
            "likes": float(post.get("likeCount", 0)),
            "reposts": float(post.get("repostCount", 0)),
            "replies": float(post.get("replyCount", 0)),
        },
        links=post_links(post),
    )


class BlueskyAdapter:
    name = "bluesky"

    def __init__(self, settings: BlueskySettings) -> None:
        self.interval_minutes = settings.interval_minutes
        self.warnings: list[str] = []
        self._settings = settings
        self._pattern = keyword_pattern(settings.keywords)

    async def _author_posts(self, client: httpx.AsyncClient, handle: str) -> list[dict[str, Any]]:
        response = await request(
            client,
            self.name,
            FEED_URL,
            params={
                "actor": handle,
                "limit": self._settings.per_handle_limit,
                "filter": "posts_no_replies",
            },
        )
        body = parse_json(self.name, response)
        if not isinstance(body, dict) or not isinstance(body.get("feed"), list):
            raise SourceError(self.name, "định dạng dữ liệu đã đổi: thiếu 'feed'")
        # bỏ bài repost: tác giả thật của bài không phải người đang theo dõi
        return [e["post"] for e in body["feed"] if "reason" not in e and "post" in e]

    async def fetch(self, client: httpx.AsyncClient) -> list[RawItem]:
        self.warnings = []

        async def search(handle: str) -> list[dict[str, Any]]:
            return await self._author_posts(client, handle)

        posts = await collect(self.name, self._settings.handles, search, self.warnings)
        items: list[RawItem] = []
        for post in posts:
            try:
                item = build_post(post)
            except (KeyError, TypeError, ValueError, IndexError) as exc:
                self.warnings.append(f"bỏ một bài hỏng: {exc!r}")
                continue
            if self._pattern.search(item.text):
                items.append(item)
        return list({i.source_id: i for i in items}.values())
