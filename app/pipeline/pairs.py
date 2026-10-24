from __future__ import annotations

import csv
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from sqlalchemy import select

from app.config import Settings
from app.pipeline.embeddings import from_bytes
from app.storage.db import make_engine, migrate
from app.storage.tables import item_embeddings, raw_items

LOW_COSINE = 0.45
TEXT_CHARS = 300
CSV_COLUMNS = [
    "pair_id",
    "cosine",
    "a_id",
    "a_source",
    "a_title",
    "a_text",
    "a_url",
    "b_id",
    "b_source",
    "b_title",
    "b_text",
    "b_url",
    "label",
]


@dataclass(frozen=True)
class PairItem:
    id: int
    source: str
    title: str
    text: str
    url: str
    url_norm: str


def candidate_pairs(
    items: list[PairItem], vectors: np.ndarray, count: int, low: float = LOW_COSINE
) -> list[tuple[int, int, float]]:
    """Chọn các cặp "có thể trùng" rải đều theo độ giống, bỏ cặp đã trùng khóa chuẩn.

    Rải đều (không chỉ lấy cặp giống nhất) để tập gán nhãn có cả cặp khó, dùng chọn ngưỡng.
    """
    if len(items) < 2:
        return []
    sims = vectors @ vectors.T
    rows, cols = np.triu_indices(len(items), k=1)
    values = sims[rows, cols]
    keep = values >= low
    found = [
        (int(i), int(j), float(v))
        for i, j, v in zip(rows[keep], cols[keep], values[keep], strict=True)
        if items[i].url_norm != items[j].url_norm
    ]
    found.sort(key=lambda p: p[2], reverse=True)
    if len(found) <= count:
        return found
    picks = np.linspace(0, len(found) - 1, count).round().astype(int)
    return [found[k] for k in dict.fromkeys(picks.tolist())]


async def export_pairs(settings: Settings, out: Path, count: int) -> int:
    migrate(settings.db_path, settings.backup_dir)
    engine = make_engine(settings.db_path)
    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    select(
                        raw_items.c.id,
                        raw_items.c.source,
                        raw_items.c.title,
                        raw_items.c.text,
                        raw_items.c.url,
                        raw_items.c.url_norm,
                        item_embeddings.c.vector,
                    )
                    .join(item_embeddings, item_embeddings.c.item_id == raw_items.c.id)
                    .where(item_embeddings.c.model == settings.dedup.embedding_model)
                    .order_by(raw_items.c.id)
                )
            ).all()
    finally:
        await engine.dispose()
    if len(rows) < 2:
        sys.stderr.write(
            "Chưa có embedding nào. Chạy `python -m app.cli run-once` (cần tải model lần đầu) "
            "để có dữ liệu rồi xuất lại.\n"
        )
        return 1
    items = [PairItem(r.id, r.source, r.title, r.text, r.url, r.url_norm or r.url) for r in rows]
    vectors = np.stack([from_bytes(r.vector) for r in rows])
    pairs = candidate_pairs(items, vectors, count)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(CSV_COLUMNS)
        for n, (i, j, cosine) in enumerate(pairs, start=1):
            a, b = items[i], items[j]
            writer.writerow(
                [n, f"{cosine:.4f}"]
                + [a.id, a.source, a.title, a.text[:TEXT_CHARS], a.url]
                + [b.id, b.source, b.title, b.text[:TEXT_CHARS], b.url]
                + [""]
            )
    sys.stdout.write(
        f"Đã ghi {len(pairs)} cặp vào {out}. Điền cột label: 1 = cùng tin, 0 = khác tin.\n"
    )
    return 0
