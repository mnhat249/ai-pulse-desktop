from __future__ import annotations

from typing import Any

import httpx

from app.adapters.base import SourceError, parse_datetime, parse_items, parse_json, request
from app.config import HuggingFaceSettings
from app.core.models import RawItem

PAPERS_URL = "https://huggingface.co/api/daily_papers"
MODELS_URL = "https://huggingface.co/api/models"


def build_paper(entry: dict[str, Any]) -> RawItem:
    paper = entry["paper"]
    paper_id = paper["id"]
    authors = paper.get("authors") or []
    links = [f"https://arxiv.org/abs/{paper_id}"]
    if paper.get("githubRepo"):
        links.append(paper["githubRepo"])
    return RawItem(
        source="hf_papers",
        source_id=paper_id,
        url=f"https://huggingface.co/papers/{paper_id}",
        title=paper["title"],
        text=paper.get("summary") or "",
        author=authors[0].get("name") if authors else None,
        published_at=parse_datetime(paper["publishedAt"]),
        metrics={
            "upvotes": float(paper.get("upvotes", 0)),
            "comments": float(entry.get("numComments", 0)),
        },
        links=links,
    )


def build_model(model: dict[str, Any]) -> RawItem:
    model_id = model["id"]
    tags = " ".join(model.get("tags") or [])
    return RawItem(
        source="hf_models",
        source_id=model_id,
        url=f"https://huggingface.co/{model_id}",
        title=model_id,
        text=f"{model.get('pipeline_tag') or ''} {tags}".strip(),
        author=model_id.split("/")[0] if "/" in model_id else None,
        published_at=parse_datetime(model["createdAt"]),
        metrics={
            "trendingScore": float(model.get("trendingScore", 0)),
            "likes": float(model.get("likes", 0)),
            "downloads": float(model.get("downloads", 0)),
        },
        links=[f"https://huggingface.co/{model_id}"],
    )


def _expect_list(source: str, body: Any) -> list[Any]:
    if not isinstance(body, list):
        raise SourceError(source, "định dạng dữ liệu đã đổi: không phải danh sách")
    return body


class HFPapersAdapter:
    name = "hf_papers"

    def __init__(self, settings: HuggingFaceSettings) -> None:
        self.interval_minutes = settings.interval_minutes
        self._limit = settings.papers_limit
        self.warnings: list[str] = []

    async def fetch(self, client: httpx.AsyncClient) -> list[RawItem]:
        response = await request(client, self.name, PAPERS_URL, params={"limit": self._limit})
        entries = _expect_list(self.name, parse_json(self.name, response))
        return parse_items(self.name, entries, build_paper)


class HFModelsAdapter:
    name = "hf_models"

    def __init__(self, settings: HuggingFaceSettings) -> None:
        self.interval_minutes = settings.interval_minutes
        self._limit = settings.models_limit
        self.warnings: list[str] = []

    async def fetch(self, client: httpx.AsyncClient) -> list[RawItem]:
        response = await request(
            client,
            self.name,
            MODELS_URL,
            params={"sort": "trendingScore", "direction": -1, "limit": self._limit},
        )
        models = _expect_list(self.name, parse_json(self.name, response))
        return parse_items(self.name, models, build_model)
