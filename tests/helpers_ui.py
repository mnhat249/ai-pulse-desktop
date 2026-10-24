from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.storage.db import migrate

ISO = "2026-10-23 12:00:00.000000"


def seed_db(path: Path) -> dict[str, int]:
    """DB nhỏ cho test giao diện: 3 cụm hiện được (1 đã tóm tắt) và 1 cụm rác."""
    migrate(path)
    conn = sqlite3.connect(path)
    ids: dict[str, int] = {}

    def add_cluster(
        name: str,
        importance: float,
        digest: dict[str, object] | None,
        noise: bool,
        members: list[tuple[str, str, str]],
    ) -> None:
        cur = conn.execute(
            "INSERT INTO clusters (first_seen, last_seen, importance, is_noise, digest,"
            " primary_url) VALUES (?, ?, ?, ?, ?, ?)",
            (ISO, ISO, importance, noise, json.dumps(digest) if digest else None, members[0][2]),
        )
        cluster_id = int(cur.lastrowid or 0)
        ids[name] = cluster_id
        for source, title, url in members:
            item = conn.execute(
                "INSERT INTO raw_items (source, source_id, url, title, text, published_at,"
                " fetched_at, links) VALUES (?, ?, ?, ?, '', ?, ?, '[]')",
                (source, f"{name}-{source}", url, title, ISO, ISO),
            )
            conn.execute(
                "INSERT INTO cluster_items (cluster_id, item_id) VALUES (?, ?)",
                (cluster_id, item.lastrowid),
            )

    add_cluster(
        "hot",
        80.0,
        {
            "title_vi": "Công cụ agent mới",
            "innovation": "Chạy agent cục bộ",
            "impact": "Dev tiết kiệm thời gian",
            "importance": 4,
            "is_noise": False,
            "noise_reason": None,
            "cluster_id": 1,
        },
        False,
        [
            ("github", "acme/agent", "https://github.com/acme/agent"),
            ("hackernews", "Show HN: agent", "https://news.ycombinator.com/item?id=1"),
            ("hf_models", "acme/agent-7b", "https://huggingface.co/acme/agent-7b"),
        ],
    )
    add_cluster(
        "plain", 50.0, None, False, [("hackernews", "Rust 2.0 released", "https://rust.dev/2")]
    )
    add_cluster(
        "paper",
        30.0,
        None,
        False,
        [("hf_papers", "A paper", "https://huggingface.co/papers/2401.1")],
    )
    add_cluster("spam", 90.0, None, True, [("hackernews", "Free course", "https://spam.example/x")])
    conn.commit()
    conn.close()
    return ids
