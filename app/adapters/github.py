from __future__ import annotations

from datetime import timedelta
from typing import Any

import httpx

from app.adapters.base import (
    SourceError,
    collect,
    parse_datetime,
    parse_items,
    parse_json,
    request,
)
from app.config import GitHubSettings
from app.core.models import RawItem, utcnow
from app.core.sources import SourceInfo, register

SEARCH_URL = "https://api.github.com/search/repositories"

register(SourceInfo("github", "GitHub", "#3B5B7A", rank=0, heat_metric="stars_per_24h"))


def build_item(repo: dict[str, Any]) -> RawItem:
    created = parse_datetime(repo["created_at"])
    age_hours = (utcnow() - created).total_seconds() / 3600
    topics = " ".join(repo.get("topics") or [])
    description = repo.get("description") or ""
    links = [repo["html_url"]]
    if repo.get("homepage"):
        links.append(repo["homepage"])
    return RawItem(
        source="github",
        source_id=str(repo["id"]),
        url=repo["html_url"],
        title=repo["full_name"],
        text=f"{description}\n{topics}".strip(),
        author=repo["owner"]["login"],
        published_at=created,
        metrics={
            "stars": float(repo["stargazers_count"]),
            "forks": float(repo.get("forks_count", 0)),
            "age_hours": age_hours,
        },
        links=links,
    )


class GitHubAdapter:
    name = "github"

    def __init__(self, settings: GitHubSettings, token: str | None = None) -> None:
        self.interval_minutes = settings.interval_minutes
        self._settings = settings
        self._token = token
        self._etags: dict[str, str] = {}
        self.warnings: list[str] = []

    def _queries(self) -> list[str]:
        now = utcnow()
        pushed = (now - timedelta(hours=self._settings.pushed_within_hours)).strftime("%Y-%m-%d")
        created = (now - timedelta(days=self._settings.created_within_days)).strftime("%Y-%m-%d")
        out: list[str] = []
        for topic in self._settings.topics:
            out.append(f"topic:{topic} pushed:>{pushed}")
            out.append(f"topic:{topic} created:>{created}")
        return out

    def _headers(self, query: str) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        if query in self._etags:
            headers["If-None-Match"] = self._etags[query]
        return headers

    async def _search(self, client: httpx.AsyncClient, query: str) -> list[dict[str, Any]]:
        response = await request(
            client,
            self.name,
            SEARCH_URL,
            params={
                "q": query,
                "sort": "stars",
                "order": "desc",
                "per_page": self._settings.per_page,
            },
            headers=self._headers(query),
        )
        if response.status_code == 304:
            return []
        if etag := response.headers.get("etag"):
            self._etags[query] = etag
        body = parse_json(self.name, response)
        if not isinstance(body, dict) or not isinstance(body.get("items"), list):
            raise SourceError(self.name, "định dạng dữ liệu đã đổi: thiếu 'items'")
        return list(body["items"])

    async def fetch(self, client: httpx.AsyncClient) -> list[RawItem]:
        self.warnings = []

        async def search(query: str) -> list[dict[str, Any]]:
            return await self._search(client, query)

        found = await collect(self.name, self._queries(), search, self.warnings)
        repos: dict[Any, dict[str, Any]] = {}
        for index, repo in enumerate(found):
            key = repo.get("id", ("?", index)) if isinstance(repo, dict) else ("?", index)
            repos.setdefault(key, repo)
        return parse_items(self.name, repos.values(), build_item, self.warnings)
