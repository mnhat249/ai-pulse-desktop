from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings
from app.core.models import utcnow
from app.pipeline.embeddings import from_bytes
from app.storage.ops import ingest_items
from app.storage.tables import clusters, item_embeddings, user_state
from tests.helpers import (
    DIM,
    NOW,
    BrokenEmbedder,
    FakeEmbedder,
    all_clusters,
    gh,
    item,
    make,
    member_count,
)


async def test_same_repo_from_two_sources_is_one_cluster(engine: AsyncEngine) -> None:
    items = [
        gh("1", "Acme/Tool"),
        item(
            "hackernews",
            "9",
            "https://github.com/acme/tool/tree/main?utm_source=hn",
            "Show HN: Tool a new AI agent runner",
            points=300.0,
        ),
    ]
    proc, writer = await make(engine, items)
    result = await proc.run()
    await writer.stop()
    (cluster,) = await all_clusters(engine)
    assert result.clustered == 2 and member_count(cluster) == 2
    assert cluster["primary_url"] == "https://github.com/Acme/Tool"
    assert cluster["importance"] > 0


async def test_paper_with_repo_link_joins_repo_and_arxiv_clusters(engine: AsyncEngine) -> None:
    items = [
        gh("1", "acme/tool"),
        item(
            "hf_papers",
            "2401.00001",
            "https://huggingface.co/papers/2401.00001",
            "Paper về Tool agent runner",
            links=["https://arxiv.org/abs/2401.00001", "https://github.com/acme/tool"],
            upvotes=40.0,
        ),
        item(
            "hackernews",
            "5",
            "https://arxiv.org/abs/2401.00001v2",
            "Tool agent runner paper on arXiv",
            points=200.0,
        ),
    ]
    proc, writer = await make(engine, items)
    await proc.run()
    await writer.stop()
    (cluster,) = await all_clusters(engine)
    assert member_count(cluster) == 3


async def test_bridging_item_merges_clusters_and_keeps_bookmark(engine: AsyncEngine) -> None:
    first_items = [
        gh("1", "acme/tool"),
        item(
            "hackernews",
            "5",
            "https://arxiv.org/abs/2401.00001",
            "Bài paper khác hẳn",
            points=200.0,
        ),
    ]
    proc, writer = await make(engine, first_items)
    await proc.run()
    before = await all_clusters(engine)
    assert len(before) == 2
    drop_id = before[1]["id"]
    await writer.submit(
        lambda c: c.execute(user_state.insert().values(cluster_id=drop_id, bookmarked=True))
    )
    bridge = item(
        "hf_papers",
        "2401.00001",
        "https://huggingface.co/papers/2401.00001",
        "Cầu nối giữa repo và paper",
        links=["https://github.com/acme/tool"],
        upvotes=10.0,
    )
    await writer.submit(lambda c: ingest_items(c, [bridge], NOW))
    await proc.run()
    await writer.stop()
    (merged,) = await all_clusters(engine)
    assert member_count(merged) == 3
    async with engine.connect() as conn:
        state = (await conn.execute(select(user_state))).mappings().all()
    assert [(s["cluster_id"], s["bookmarked"]) for s in state] == [(merged["id"], True)]


async def test_similar_titles_join_via_embeddings_but_other_topics_do_not(
    engine: AsyncEngine,
) -> None:
    items = [
        item(
            "hackernews",
            "1",
            "https://blog.a.com/p1",
            "OpenAI releases new reasoning model o5 today",
            points=200.0,
        ),
        item(
            "hackernews",
            "2",
            "https://news.b.com/p2",
            "OpenAI releases new reasoning model o5",
            points=150.0,
        ),
        item(
            "hackernews",
            "3",
            "https://blog.c.com/p3",
            "Rust async runtime benchmark results compared",
            points=150.0,
        ),
    ]
    proc, writer = await make(engine, items, embedder=FakeEmbedder())
    await proc.run()
    await writer.stop()
    assert sorted(member_count(c) for c in await all_clusters(engine)) == [1, 2]
    async with engine.connect() as conn:
        stored = (await conn.execute(select(item_embeddings))).mappings().all()
    assert len(stored) == 3 and stored[0]["model"] == "fake-bow"
    assert from_bytes(stored[0]["vector"]).shape == (DIM,)


async def test_embedding_match_ignores_clusters_older_than_the_window(engine: AsyncEngine) -> None:
    first = item(
        "hackernews",
        "1",
        "https://blog.a.com/p1",
        "OpenAI releases new reasoning model o5",
        points=200.0,
    )
    proc, writer = await make(engine, [first], embedder=FakeEmbedder())
    await proc.run()
    old = utcnow() - timedelta(hours=100)
    await writer.submit(lambda c: c.execute(update(clusters).values(last_seen=old)))
    second = item(
        "hackernews",
        "2",
        "https://news.b.com/p2",
        "OpenAI releases new reasoning model o5",
        points=200.0,
    )
    await writer.submit(lambda c: ingest_items(c, [second], NOW))
    await proc.run()
    await writer.stop()
    assert len(await all_clusters(engine)) == 2


async def test_threshold_comes_from_settings(engine: AsyncEngine) -> None:
    items = [
        item(
            "hackernews",
            "1",
            "https://blog.a.com/p1",
            "OpenAI releases new reasoning model o5 today",
            points=200.0,
        ),
        item(
            "hackernews",
            "2",
            "https://news.b.com/p2",
            "OpenAI releases new reasoning model o5",
            points=150.0,
        ),
    ]
    settings = Settings.model_validate({"dedup": {"threshold": 0.9999}})
    proc, writer = await make(engine, items, embedder=FakeEmbedder(), settings=settings)
    await proc.run()
    await writer.stop()
    assert len(await all_clusters(engine)) == 2


async def test_embedder_failure_falls_back_to_key_only_dedup(engine: AsyncEngine) -> None:
    items = [
        gh("1", "acme/tool"),
        item(
            "hackernews",
            "9",
            "https://github.com/acme/tool",
            "Show HN: Tool runner agent",
            points=200.0,
        ),
    ]
    proc, writer = await make(engine, items, embedder=BrokenEmbedder())
    result = await proc.run()
    await writer.stop()
    assert result.clustered == 2 and len(await all_clusters(engine)) == 1


async def test_second_run_does_not_recluster_and_no_cluster_repeats(engine: AsyncEngine) -> None:
    proc, writer = await make(
        engine,
        [
            gh("1", "acme/tool"),
            item(
                "github",
                "2",
                "https://github.com/acme/other",
                "acme/other",
                "Compiler fuzzing harness for Rust crates",
                stars=500.0,
                stars_per_24h=40.0,
            ),
        ],
        embedder=FakeEmbedder(),
    )
    await proc.run()
    again = await proc.run()
    await writer.stop()
    assert again.clustered == 0 and again.touched == []
    urls = [c["primary_url"] for c in await all_clusters(engine)]
    assert len(urls) == len(set(urls)) == 2


async def test_rule_noise_marks_cluster_but_a_good_member_saves_it(engine: AsyncEngine) -> None:
    spam = item(
        "hackernews", "1", "https://x.com/a", "Free AI course giveaway for everyone", points=500.0
    )
    weak = gh("2", "nobody/tiny", stars=3.0)
    good = gh("3", "acme/real")
    spam_on_good_repo = item(
        "hackernews", "4", "https://github.com/acme/real", "Discount code for hosting", points=400.0
    )
    proc, writer = await make(engine, [spam, weak, good, spam_on_good_repo])
    await proc.run()
    await writer.stop()
    by_first = {c["members"][0]: c for c in await all_clusters(engine)}  # type: ignore[index]
    assert by_first[("hackernews", "1")]["is_noise"] is True
    assert "quảng cáo" in str(by_first[("hackernews", "1")]["noise_reason"])
    assert by_first[("github", "2")]["is_noise"] is True
    assert by_first[("github", "3")]["is_noise"] is False
    assert member_count(by_first[("github", "3")]) == 2
