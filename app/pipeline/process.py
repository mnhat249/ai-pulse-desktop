from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import partial
from typing import Any, TypeVar

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.config import Settings, app_home, get_secret
from app.core.models import Digest, utcnow
from app.pipeline.cluster import ItemRow, assign_item, load_unclustered, refresh_cluster
from app.pipeline.digest import ClusterInput, Provider, digest_batch, load_prompt
from app.pipeline.embeddings import Embedder, FastEmbedder, Vector, embedding_text, to_bytes
from app.pipeline.llm import GeminiClient, GroqClient
from app.storage.tables import cluster_items, clusters, item_embeddings, llm_usage, raw_items
from app.storage.writer import Writer

logger = logging.getLogger(__name__)

MAX_BATCHES_PER_RUN = 3
MAX_MEMBER_TITLES = 3
DEFER_MINUTES = 60
BACKFILL_BATCH = 100
_T = TypeVar("_T")


@dataclass
class ProcessResult:
    clustered: int = 0
    touched: list[int] = field(default_factory=list)
    digested: list[int] = field(default_factory=list)


def build_providers(settings: Settings) -> list[Provider]:
    providers: list[Provider] = []
    if key := get_secret("gemini"):
        providers.append(
            Provider(GeminiClient(key, settings.llm.gemini_model), settings.llm.gemini_daily_cap)
        )
    if key := get_secret("groq"):
        providers.append(
            Provider(GroqClient(key, settings.llm.groq_model), settings.llm.groq_daily_cap)
        )
    if not providers:
        logger.warning("Chưa có khóa Gemini/Groq (python -m app.setkey): cụm sẽ hiện tiêu đề gốc")
    return providers


def build_processor(settings: Settings, engine: AsyncEngine, writer: Writer) -> Processor:
    embedder = FastEmbedder(settings.dedup.embedding_model, app_home() / "models")
    return Processor(settings, engine, writer, embedder, build_providers(settings))


class Processor:
    """Một vòng: gán cụm (lọc trùng) -> lọc rác bằng luật -> tóm tắt LLM theo lô -> xếp hạng."""

    def __init__(
        self,
        settings: Settings,
        engine: AsyncEngine,
        writer: Writer,
        embedder: Embedder | None,
        providers: list[Provider],
    ) -> None:
        self._settings = settings
        self._engine = engine
        self._writer = writer
        self._embedder = embedder
        self._providers = providers
        self._prompt = load_prompt()
        self._deferred: dict[int, datetime] = {}
        self._calls_in_batch = 0

    async def _read(self, fn: Callable[[AsyncConnection], Awaitable[_T]]) -> _T:
        async with self._engine.connect() as conn:
            return await fn(conn)

    async def run(self) -> ProcessResult:
        result = ProcessResult()
        items = await self._read(load_unclustered)
        if items:
            vectors = await self._embed(items)
            result.touched = await self._writer.submit(
                lambda conn: self._assign_all(conn, items, vectors)
            )
            result.clustered = len(items)
        await self._backfill_embeddings()
        revived = await self._writer.submit(self._refresh_recent)
        result.touched = list(dict.fromkeys([*result.touched, *revived]))
        result.digested = await self._digest_pending()
        return result

    async def _backfill_embeddings(self) -> int:
        """Bù embedding cho bài đã gom trước khi có model (mỗi vòng một mẻ nhỏ).

        Bài cũ không bị gom lại; vector chỉ để so sánh với bài mới và để xuất cặp gán nhãn.
        """
        if self._embedder is None:
            return 0
        rows = await self._read(self._items_without_embedding)
        if not rows:
            return 0
        try:
            vectors = await self._embedder.embed([embedding_text(r.title, r.text) for r in rows])
        except Exception:
            logger.exception("Không bù được embedding cho bài cũ")
            return 0
        model = self._embedder.model_name
        try:
            await self._writer.submit(
                partial(self._store_embeddings, rows=rows, vectors=vectors, model=model)
            )
        except Exception:
            logger.exception("Không ghi được embedding bù; thử lại ở vòng sau")
            return 0
        return len(rows)

    async def _items_without_embedding(self, conn: AsyncConnection) -> list[Any]:
        stmt = (
            select(raw_items.c.id, raw_items.c.title, raw_items.c.text)
            .outerjoin(item_embeddings, item_embeddings.c.item_id == raw_items.c.id)
            .where(item_embeddings.c.item_id.is_(None))
            .order_by(raw_items.c.id.desc())
            .limit(BACKFILL_BATCH)
        )
        return list((await conn.execute(stmt)).all())

    async def _store_embeddings(
        self, conn: AsyncConnection, *, rows: list[Any], vectors: list[Vector], model: str
    ) -> None:
        values = [
            {"item_id": row.id, "model": model, "vector": to_bytes(vec)}
            for row, vec in zip(rows, vectors, strict=True)
        ]
        await conn.execute(sqlite_insert(item_embeddings).values(values).on_conflict_do_nothing())

    async def _refresh_recent(self, conn: AsyncConnection) -> list[int]:
        """Tính lại cờ rác và điểm của các cụm mới (trong cửa sổ lọc trùng).

        Số sao, trending, điểm HN đổi theo thời gian: repo lúc đầu dưới ngưỡng sao có thể lên hàng
        trăm sao sau đó. Trả về các cụm vừa hết bị coi là rác.
        """
        now = utcnow()
        since = now - timedelta(hours=self._settings.dedup.window_hours)
        before = {
            row.id: bool(row.is_noise)
            for row in (
                await conn.execute(
                    select(clusters.c.id, clusters.c.is_noise).where(clusters.c.first_seen >= since)
                )
            ).all()
        }
        for cluster_id in before:
            await refresh_cluster(
                conn, cluster_id, self._settings.noise, self._settings.ranking, now, touch=False
            )
        after = {
            row.id: bool(row.is_noise)
            for row in (
                await conn.execute(
                    select(clusters.c.id, clusters.c.is_noise).where(
                        clusters.c.id.in_(list(before))
                    )
                )
            ).all()
        }
        return [cid for cid, was_noise in before.items() if was_noise and not after.get(cid, True)]

    async def _embed(self, items: list[ItemRow]) -> list[Vector | None]:
        if self._embedder is None:
            return [None] * len(items)
        try:
            vectors = await self._embedder.embed([embedding_text(i.title, i.text) for i in items])
        except Exception:
            logger.exception("Không tạo được embedding; chỉ lọc trùng theo khóa chuẩn lượt này")
            return [None] * len(items)
        return list(vectors)

    async def _assign_all(
        self, conn: AsyncConnection, items: list[ItemRow], vectors: list[Vector | None]
    ) -> list[int]:
        now = utcnow()
        model = self._embedder.model_name if self._embedder else ""
        touched: dict[int, None] = {}
        for item, vector in zip(items, vectors, strict=True):
            cluster_id = await assign_item(conn, item, vector, model, self._settings.dedup, now)
            touched[cluster_id] = None
        alive = []
        for cluster_id in touched:
            await refresh_cluster(
                conn, cluster_id, self._settings.noise, self._settings.ranking, now, touch=True
            )
            if (
                await conn.execute(select(clusters.c.id).where(clusters.c.id == cluster_id))
            ).first():
                alive.append(cluster_id)
        return alive

    async def _digest_pending(self) -> list[int]:
        if not self._providers:
            return []
        digested: list[int] = []
        for _ in range(MAX_BATCHES_PER_RUN):
            batch = await self._read(self._pending_inputs)
            if not batch:
                break
            self._calls_in_batch = 0
            digests = await digest_batch(
                self._providers,
                batch,
                self._prompt,
                self._settings.llm.max_text_chars,
                self._quota_ok,
                self._record_call,
            )
            if digests:
                await self._writer.submit(partial(self._save_digests, digests=digests))
                digested.extend(d.cluster_id for d in digests if not d.is_noise)
            if self._calls_in_batch == 0:
                break  # hết quota hoặc không có nhà cung cấp: đợi hôm sau
            self._defer({c.cluster_id for c in batch} - {d.cluster_id for d in digests})
        return digested

    def _defer(self, cluster_ids: set[int]) -> None:
        """Cụm LLM không trả lời được: để sau, khỏi chặn hàng đợi và đốt quota mỗi 5 phút."""
        until = utcnow() + timedelta(minutes=DEFER_MINUTES)
        for cluster_id in cluster_ids:
            self._deferred[cluster_id] = until

    def _deferred_ids(self) -> list[int]:
        now = utcnow()
        self._deferred = {cid: t for cid, t in self._deferred.items() if t > now}
        return list(self._deferred)

    async def _pending_inputs(self, conn: AsyncConnection) -> list[ClusterInput]:
        ids = (
            (
                await conn.execute(
                    select(clusters.c.id)
                    .where(
                        clusters.c.is_noise.is_(False),
                        clusters.c.digest.is_(None),
                        clusters.c.id.not_in(self._deferred_ids()),
                    )
                    .order_by(clusters.c.importance.desc(), clusters.c.id.desc())
                    .limit(self._settings.llm.batch_size)
                )
            )
            .scalars()
            .all()
        )
        batch = []
        for cluster_id in ids:
            members = (
                await conn.execute(
                    select(raw_items.c.source, raw_items.c.title, raw_items.c.text)
                    .join(cluster_items, cluster_items.c.item_id == raw_items.c.id)
                    .where(cluster_items.c.cluster_id == cluster_id)
                    .order_by(raw_items.c.id)
                )
            ).all()
            batch.append(
                ClusterInput(
                    cluster_id=cluster_id,
                    sources=list(dict.fromkeys(m.source for m in members)),
                    titles=[m.title for m in members[:MAX_MEMBER_TITLES]],
                    text="\n".join(m.text for m in members if m.text),
                )
            )
        return batch

    async def _save_digests(self, conn: AsyncConnection, *, digests: list[Digest]) -> None:
        now = utcnow()
        for digest in digests:
            await conn.execute(
                update(clusters)
                .where(clusters.c.id == digest.cluster_id)
                .values(digest=digest.model_dump(mode="json"))
            )
            await refresh_cluster(
                conn,
                digest.cluster_id,
                self._settings.noise,
                self._settings.ranking,
                now,
                touch=False,
            )

    @staticmethod
    def _today() -> str:
        return utcnow().strftime("%Y-%m-%d")

    async def _quota_ok(self, provider: str, cap: int) -> bool:
        async def calls(conn: AsyncConnection) -> int:
            row = await conn.execute(
                select(llm_usage.c.calls).where(
                    llm_usage.c.day == self._today(), llm_usage.c.provider == provider
                )
            )
            return int(row.scalar_one_or_none() or 0)

        return await self._read(calls) < cap

    async def _record_call(self, provider: str) -> None:
        self._calls_in_batch += 1
        day = self._today()

        async def op(conn: AsyncConnection) -> None:
            stmt = sqlite_insert(llm_usage).values(day=day, provider=provider, calls=1)
            await conn.execute(
                stmt.on_conflict_do_update(
                    index_elements=["day", "provider"],
                    set_={"calls": llm_usage.c.calls + 1},
                )
            )

        await self._writer.submit(op)
