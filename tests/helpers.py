from __future__ import annotations

import json
import re
import zlib
from datetime import UTC, datetime

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings
from app.core.models import RawItem
from app.pipeline.digest import Provider
from app.pipeline.embeddings import Vector, normalize
from app.pipeline.process import Processor
from app.storage.ops import ingest_items
from app.storage.tables import cluster_items, clusters, raw_items
from app.storage.writer import Writer

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
DIM = 64


class FakeEmbedder:
    """Túi từ băm: hai văn bản chung nhiều từ thì cosine cao."""

    model_name = "fake-bow"

    async def embed(self, texts: list[str]) -> list[Vector]:
        out = []
        for text in texts:
            vec = np.zeros(DIM, dtype=np.float32)
            for word in re.findall(r"\w+", text.lower()):
                vec[zlib.crc32(word.encode()) % DIM] += 1
            out.append(normalize(vec))
        return out


class BrokenEmbedder:
    model_name = "broken"

    async def embed(self, texts: list[str]) -> list[Vector]:
        raise RuntimeError("không tải được model")


def item(
    source: str,
    sid: str,
    url: str,
    title: str,
    text: str = "Mô tả đủ dài về một dự án AI mới",
    links: list[str] | None = None,
    **metrics: float,
) -> RawItem:
    return RawItem(
        source=source,
        source_id=sid,
        url=url,
        title=title,
        text=text,
        published_at=NOW,
        links=links or [],
        metrics=metrics,
    )


def gh(sid: str, repo: str, title: str | None = None, **kw: float) -> RawItem:
    metrics = {"stars": 500.0, "stars_per_24h": 40.0, **kw}
    return item("github", sid, f"https://github.com/{repo}", title or repo, **metrics)


def digest_json(**override: object) -> dict[str, object]:
    base: dict[str, object] = {
        "cluster_id": 1,
        "title_vi": "T",
        "innovation": "a",
        "impact": "b",
        "importance": 3,
        "is_noise": False,
        "noise_reason": None,
    }
    return {**base, **override}


class FakeLLM:
    def __init__(self, name: str = "gemini", fail: bool = False, bad: int = 0) -> None:
        self.name = name
        self.fail = fail
        self.bad = bad
        self.prompts: list[str] = []

    async def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self.fail:
            raise RuntimeError("429")
        if self.bad > 0:
            self.bad -= 1
            return "đây không phải JSON"
        ids = [int(i) for i in re.findall(r'cluster_id="(\d+)"', prompt)]
        entries = [
            digest_json(
                cluster_id=i,
                title_vi=f"Tiêu đề {i}",
                innovation="Cái mới",
                impact="Dùng để làm gì đó",
                importance=4,
            )
            for i in ids
        ]
        return json.dumps({"items": entries})


async def make(
    engine: AsyncEngine,
    items: list[RawItem],
    *,
    embedder: object | None = None,
    providers: list[Provider] | None = None,
    settings: Settings | None = None,
) -> tuple[Processor, Writer]:
    writer = Writer(engine)
    writer.start()
    await writer.submit(lambda c: ingest_items(c, items, NOW))
    proc = Processor(
        settings or Settings(),
        engine,
        writer,
        embedder,  # type: ignore[arg-type]
        providers or [],
    )
    return proc, writer


async def all_clusters(engine: AsyncEngine) -> list[dict[str, object]]:
    async with engine.connect() as conn:
        rows = (await conn.execute(select(clusters).order_by(clusters.c.id))).mappings().all()
        out: list[dict[str, object]] = []
        for row in rows:
            members = (
                await conn.execute(
                    select(raw_items.c.source, raw_items.c.source_id)
                    .join(cluster_items, cluster_items.c.item_id == raw_items.c.id)
                    .where(cluster_items.c.cluster_id == row["id"])
                    .order_by(raw_items.c.id)
                )
            ).all()
            out.append({**row, "members": [(m[0], m[1]) for m in members]})
    return out


def member_count(cluster: dict[str, object]) -> int:
    members = cluster["members"]
    assert isinstance(members, list)
    return len(members)
