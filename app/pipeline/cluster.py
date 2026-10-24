from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import numpy as np
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from app.config import DedupSettings, NoiseSettings, RankingSettings
from app.core import sources
from app.pipeline.embeddings import Vector, from_bytes, to_bytes
from app.pipeline.noise import noise_reason
from app.pipeline.normalize import canonical_key, extract_links
from app.pipeline.ranking import importance_score, item_heat
from app.storage.tables import (
    cluster_items,
    clusters,
    item_embeddings,
    metric_snapshots,
    raw_items,
    user_state,
)
from app.storage.tables import (
    item_keys as item_keys_table,
)

STRONG_PREFIXES = ("github:", "arxiv:", "hf:")
LOAD_LIMIT = 500


@dataclass(frozen=True)
class ItemRow:
    id: int
    source: str
    source_id: str
    url: str
    title: str
    text: str
    links: list[str]
    fetched_at: datetime


def _strong(keys: list[str]) -> list[str]:
    return [k for k in keys if k.startswith(STRONG_PREFIXES)]


def storage_keys(item: ItemRow) -> list[str]:
    """Khóa dùng để gộp cụm: khóa của URL chính, cộng link repo/paper/model.

    - Link do adapter cung cấp (`links`) đáng tin nên giữ hết các khóa mạnh.
    - Link trích từ nội dung chỉ dùng khi bài chỉ nhắc đúng MỘT repo/paper/model; bài liệt kê
      nhiều (kiểu "awesome list") không bị coi là cùng tin với từng mục trong đó.
    - Link chung chung (trang chủ, blog) không dùng vì nhiều bài cùng trỏ về đó.
    """
    primary = canonical_key(item.url)
    keys = [primary]
    keys += [k for k in _strong([canonical_key(link) for link in item.links]) if k not in keys]
    mentioned = _strong([canonical_key(u) for u in extract_links(item.text)])
    mentioned = [k for k in dict.fromkeys(mentioned) if k not in keys]
    if len(mentioned) == 1:
        keys.append(mentioned[0])
    return keys


def strong_conflict(item_keys_: list[str], cluster_keys: set[str]) -> bool:
    """Hai bên đã có khóa cùng loại (repo với repo...) nhưng khác nhau: không phải cùng một thứ."""
    for prefix in STRONG_PREFIXES:
        mine = {k for k in item_keys_ if k.startswith(prefix)}
        theirs = {k for k in cluster_keys if k.startswith(prefix)}
        if mine and theirs and mine.isdisjoint(theirs):
            return True
    return False


async def load_unclustered(conn: AsyncConnection, limit: int = LOAD_LIMIT) -> list[ItemRow]:
    stmt = (
        select(raw_items)
        .outerjoin(cluster_items, cluster_items.c.item_id == raw_items.c.id)
        .where(cluster_items.c.item_id.is_(None))
        .order_by(raw_items.c.id)
        .limit(limit)
    )
    return [
        ItemRow(r.id, r.source, r.source_id, r.url, r.title, r.text, list(r.links), r.fetched_at)
        for r in (await conn.execute(stmt)).all()
    ]


async def latest_metrics(conn: AsyncConnection, item_ids: list[int]) -> dict[int, dict[str, float]]:
    if not item_ids:
        return {}
    stmt = (
        select(metric_snapshots.c.item_id, metric_snapshots.c.metric, metric_snapshots.c.value)
        .where(metric_snapshots.c.item_id.in_(item_ids))
        .order_by(metric_snapshots.c.captured_at, metric_snapshots.c.id)
    )
    out: dict[int, dict[str, float]] = {i: {} for i in item_ids}
    for item_id, metric, value in (await conn.execute(stmt)).all():
        out[item_id][metric] = value
    return out


async def _clusters_sharing_keys(conn: AsyncConnection, keys: list[str], item_id: int) -> list[int]:
    stmt = (
        select(cluster_items.c.cluster_id)
        .join(item_keys_table, item_keys_table.c.item_id == cluster_items.c.item_id)
        .where(item_keys_table.c.key.in_(keys), item_keys_table.c.item_id != item_id)
        .distinct()
        .order_by(cluster_items.c.cluster_id)
    )
    return [row[0] for row in (await conn.execute(stmt)).all()]


async def _cluster_strong_keys(conn: AsyncConnection, cluster_id: int) -> set[str]:
    stmt = (
        select(item_keys_table.c.key)
        .join(cluster_items, cluster_items.c.item_id == item_keys_table.c.item_id)
        .where(cluster_items.c.cluster_id == cluster_id)
    )
    return set(_strong([row[0] for row in (await conn.execute(stmt)).all()]))


async def _nearest_cluster(
    conn: AsyncConnection,
    vector: Vector,
    keys: list[str],
    model: str,
    settings: DedupSettings,
    now: datetime,
) -> int | None:
    """Cụm giống nghĩa nhất trong cửa sổ thời gian, bỏ qua cụm đã là repo/paper khác hẳn."""
    since = now - timedelta(hours=settings.window_hours)
    stmt = (
        select(cluster_items.c.cluster_id, item_embeddings.c.vector)
        .join(item_embeddings, item_embeddings.c.item_id == cluster_items.c.item_id)
        .join(clusters, clusters.c.id == cluster_items.c.cluster_id)
        .where(clusters.c.last_seen >= since, item_embeddings.c.model == model)
    )
    rows = (await conn.execute(stmt)).all()
    if not rows:
        return None
    matrix = np.stack([from_bytes(blob) for _, blob in rows])
    if matrix.shape[1] != vector.shape[0]:
        return None
    sims = matrix @ vector
    tried: set[int] = set()
    for index in np.argsort(-sims):
        if float(sims[index]) < settings.threshold:
            break
        cluster_id = int(rows[int(index)][0])
        if cluster_id in tried:
            continue
        tried.add(cluster_id)
        if not strong_conflict(keys, await _cluster_strong_keys(conn, cluster_id)):
            return cluster_id
    return None


async def _merge_user_state(conn: AsyncConnection, keep: int, drop: int) -> None:
    """Bookmark giữ nếu bên nào cũng có; "đã đọc" chỉ giữ khi cả hai bên đã đọc (có tin mới)."""
    rows = {
        r.cluster_id: r
        for r in (
            await conn.execute(select(user_state).where(user_state.c.cluster_id.in_([keep, drop])))
        ).all()
    }
    if drop not in rows:
        return
    mine, other = rows.get(keep), rows[drop]
    if mine is None:
        await conn.execute(
            update(user_state).where(user_state.c.cluster_id == drop).values(cluster_id=keep)
        )
        return
    read_at = max(mine.read_at, other.read_at) if mine.read_at and other.read_at else None
    await conn.execute(
        update(user_state)
        .where(user_state.c.cluster_id == keep)
        .values(read_at=read_at, bookmarked=bool(mine.bookmarked or other.bookmarked))
    )
    await conn.execute(delete(user_state).where(user_state.c.cluster_id == drop))


async def merge_clusters(conn: AsyncConnection, keep: int, drop: int) -> None:
    await conn.execute(
        update(cluster_items).where(cluster_items.c.cluster_id == drop).values(cluster_id=keep)
    )
    await _merge_user_state(conn, keep, drop)
    first_seen = (
        await conn.execute(select(clusters.c.first_seen).where(clusters.c.id == drop))
    ).scalar_one_or_none()
    if first_seen is not None:
        await conn.execute(
            update(clusters)
            .where(clusters.c.id == keep, clusters.c.first_seen > first_seen)
            .values(first_seen=first_seen)
        )
    await conn.execute(delete(clusters).where(clusters.c.id == drop))


async def assign_item(
    conn: AsyncConnection,
    item: ItemRow,
    vector: Vector | None,
    model: str,
    settings: DedupSettings,
    now: datetime,
) -> int:
    """Gán bài vào cụm: trùng khóa chuẩn (tầng 1), trùng nghĩa (tầng 2), không thì tạo cụm mới."""
    keys = storage_keys(item)
    await conn.execute(update(raw_items).where(raw_items.c.id == item.id).values(url_norm=keys[0]))
    await conn.execute(
        sqlite_insert(item_keys_table)
        .values([{"item_id": item.id, "key": k} for k in keys])
        .on_conflict_do_nothing()
    )
    if vector is not None:
        await conn.execute(
            sqlite_insert(item_embeddings)
            .values(item_id=item.id, model=model, vector=to_bytes(vector))
            .on_conflict_do_nothing()
        )
    shared = await _clusters_sharing_keys(conn, keys, item.id)
    target: int | None = None
    if shared:
        target = shared[0]
        for other in shared[1:]:
            await merge_clusters(conn, target, other)
    elif vector is not None:
        target = await _nearest_cluster(conn, vector, keys, model, settings, now)
    if target is None:
        result = await conn.execute(
            clusters.insert().values(
                first_seen=now, last_seen=now, importance=0.0, is_noise=False, primary_url=item.url
            )
        )
        target = int(result.inserted_primary_key[0])  # type: ignore[index]
    await conn.execute(
        sqlite_insert(cluster_items)
        .values(cluster_id=target, item_id=item.id)
        .on_conflict_do_nothing()
    )
    return target


async def refresh_cluster(
    conn: AsyncConnection,
    cluster_id: int,
    noise: NoiseSettings,
    ranking: RankingSettings,
    now: datetime,
    *,
    touch: bool,
) -> None:
    """Tính lại điểm, cờ rác và link chính của cụm từ các bài hiện có."""
    members = (
        await conn.execute(
            select(raw_items.c.id, raw_items.c.source, raw_items.c.title, raw_items.c.text)
            .join(cluster_items, cluster_items.c.item_id == raw_items.c.id)
            .where(cluster_items.c.cluster_id == cluster_id)
        )
    ).all()
    if not members:
        await conn.execute(delete(clusters).where(clusters.c.id == cluster_id))
        return
    metrics = await latest_metrics(conn, [m.id for m in members])
    reasons = [noise_reason(m.source, m.title, m.text, metrics[m.id], noise) for m in members]
    rule_noise = all(r is not None for r in reasons)
    row = (await conn.execute(select(clusters).where(clusters.c.id == cluster_id))).one()
    digest: dict[str, Any] | None = row.digest
    llm_noise = bool(digest and digest.get("is_noise"))
    reason: str | None = None
    if rule_noise:
        reason = "; ".join(dict.fromkeys(r for r in reasons if r))
    elif llm_noise and digest:
        reason = digest.get("noise_reason")
    best = min(members, key=lambda m: (sources.info(m.source).rank, m.id))
    best_url = (
        await conn.execute(select(raw_items.c.url).where(raw_items.c.id == best.id))
    ).scalar_one()
    heats = [item_heat(m.source, metrics[m.id], ranking) for m in members]
    score = importance_score(
        heats,
        len({m.source for m in members}),
        int(digest["importance"]) if digest else None,
        ranking,
    )
    values: dict[str, Any] = {
        "is_noise": rule_noise or llm_noise,
        "noise_reason": reason,
        "primary_url": best_url,
        "importance": score,
    }
    if touch:
        values["last_seen"] = now
    await conn.execute(update(clusters).where(clusters.c.id == cluster_id).values(**values))
