from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from sqlalchemy.ext.asyncio import AsyncEngine

from app.adapters import base
from app.adapters.base import SourceError
from app.adapters.bluesky import FEED_URL, BlueskyAdapter, build_post
from app.adapters.rss import RSSAdapter, plain_text
from app.config import (
    BlueskySettings,
    FeedSettings,
    NoiseSettings,
    RankingSettings,
    Settings,
)
from app.config import (
    feed_slug as slug,
)
from app.core import sources
from app.core.sources import SourceInfo, register
from app.pipeline.noise import noise_reason
from app.pipeline.ranking import item_heat
from app.scheduler import build_adapters
from app.storage.ui_queries import source_label
from app.ui import theme
from tests.helpers import all_clusters, item, make

FIXTURES = Path(__file__).parent / "fixtures"
HF_BLOG_URL = "https://huggingface.co/blog/feed.xml"
AINEWS_URL = "https://news.smol.ai/rss.xml"
BLUESKY_FEED = json.loads((FIXTURES / "bluesky_author_feed.json").read_text(encoding="utf-8"))


def feed_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(_seconds: float) -> None:
        return None

    monkeypatch.setattr(base, "_SLEEP", fake)


def rss(name: str = "hf_blog", url: str = HF_BLOG_URL, **kw: Any) -> RSSAdapter:
    return RSSAdapter(FeedSettings(name=name, url=url, **kw))


async def fetch(adapter: Any, router: respx.MockRouter) -> list[Any]:
    async with httpx.AsyncClient() as client:
        return await adapter.fetch(client)


# ---- RSS ------------------------------------------------------------------------------------


async def test_rss_parses_real_feed_newest_first_with_exact_utc_times() -> None:
    with respx.mock() as router:
        router.get(HF_BLOG_URL).respond(200, text=feed_text("rss_hf_blog.xml"))
        items = await fetch(rss(), router)
    assert len(items) == 4
    first = items[0]
    assert first.source == "rss_hf_blog" and first.title.startswith("LitPivot")
    assert first.url == "https://huggingface.co/blog/allenai/litpivot" == first.source_id
    assert first.published_at == datetime(2026, 10, 23, 16, 15, 50, tzinfo=UTC)
    assert [i.published_at for i in items] == sorted((i.published_at for i in items), reverse=True)
    assert first.links == [first.url] and first.metrics == {}


async def test_rss_html_summary_becomes_plain_text_and_links_stay_untrusted() -> None:
    with respx.mock() as router:
        router.get(AINEWS_URL).respond(200, text=feed_text("rss_ainews.xml"))
        (entry,) = await fetch(rss("ainews", AINEWS_URL), router)
    assert 0 < len(entry.text) <= 2000 and "<" not in entry.text and "&amp;" not in entry.text
    # bản tin tổng hợp trỏ ra rất nhiều repo/paper: không được đưa vào `links` (sẽ gộp cụm bậy)
    assert entry.links == [entry.url]


async def test_rss_keeps_only_the_newest_max_entries_of_a_huge_feed() -> None:
    entries = "\n".join(
        f"<item><title>Bài số {n:03d} về AI</title><link>https://x.test/{n}</link>"
        f"<pubDate>Mon, {1 + n % 28:02d} Sep 2026 10:00:00 GMT</pubDate></item>"
        for n in range(60)
    )
    body = f'<rss version="2.0"><channel><title>t</title>{entries}</channel></rss>'
    with respx.mock() as router:
        router.get("https://x.test/feed").respond(200, text=body)
        items = await fetch(rss("big", "https://x.test/feed", max_entries=5), router)
    assert len(items) == 5
    assert all(i.published_at.day >= 24 for i in items)  # 5 bài mới nhất là các ngày 24-28


async def test_rss_bad_entries_become_warnings_and_all_bad_is_an_error() -> None:
    mixed = (
        '<rss version="2.0"><channel><title>t</title>'
        "<item><link>https://x.test/no-title</link></item>"
        "<item><title>Bài tốt về LLM</title><link>https://x.test/ok</link></item>"
        "</channel></rss>"
    )
    adapter = rss("mixed", "https://x.test/f")
    with respx.mock() as router:
        router.get("https://x.test/f").respond(200, text=mixed)
        items = await fetch(adapter, router)
    assert [i.url for i in items] == ["https://x.test/ok"] and len(adapter.warnings) == 1
    allbad = '<rss version="2.0"><channel><title>t</title><item><link>https://x.test/a</link></item></channel></rss>'
    with respx.mock() as router:
        router.get("https://x.test/f").respond(200, text=allbad)
        with pytest.raises(SourceError, match="định dạng"):
            await fetch(rss("mixed", "https://x.test/f"), router)


@pytest.mark.parametrize(
    ("status", "body"),
    [(200, "<html><body>Không phải feed</body></html>"), (200, ""), (404, "x"), (500, "x")],
)
async def test_rss_non_feed_or_http_errors_raise_named_source_error(status: int, body: str) -> None:
    with respx.mock() as router:
        router.get(HF_BLOG_URL).respond(status, text=body)
        with pytest.raises(SourceError) as info:
            await fetch(rss(), router)
    assert info.value.source == "rss_hf_blog"


def test_rss_names_labels_and_prefix_fallback() -> None:
    assert slug("Google AI") == "google_ai" and slug("!!!") == "feed"
    assert slug("Chỉ một Đồng") == "chi_mot_dong"
    adapter = rss("Google AI", "https://x.test/f")
    assert adapter.name == "rss_google_ai"
    assert sources.info("rss_google_ai").label == "Google AI"
    assert sources.info("rss_chua_dang_ky").label == "RSS"  # nguồn RSS lạ vẫn có chip hợp lý


def test_plain_text_strips_tags_entities_and_whitespace() -> None:
    assert (
        plain_text("<p>Xin  chào&nbsp;<b>thế giới</b> &amp; AI</p>\n") == "Xin chào thế giới & AI"
    )


# ---- Bluesky --------------------------------------------------------------------------------


def bsky(handles: list[str] | None = None, **kw: Any) -> BlueskyAdapter:
    return BlueskyAdapter(BlueskySettings(handles=handles or ["simonwillison.net"], **kw))


async def test_bluesky_keeps_only_ai_posts_with_correct_fields() -> None:
    with respx.mock() as router:
        router.get(FEED_URL).respond(200, json=BLUESKY_FEED)
        items = await fetch(bsky(), router)
    assert 1 <= len(items) < len(BLUESKY_FEED["feed"])  # lọc theo từ khóa AI
    for it in items:
        assert it.source == "bluesky" and it.author == "simonwillison.net"
        assert re.fullmatch(r"https://bsky\.app/profile/simonwillison\.net/post/\w+", it.url)
        assert it.metrics["likes"] >= 0 and it.published_at.tzinfo is not None
        assert it.title and len(it.title) <= 300
        assert not it.title.endswith(("...", "…"))  # chữ link rút gọn bị bỏ


async def test_bluesky_reposts_are_skipped() -> None:
    feed = json.loads(json.dumps(BLUESKY_FEED))
    for entry in feed["feed"]:
        entry["reason"] = {"$type": "app.bsky.feed.defs#reasonRepost"}
    with respx.mock() as router:
        router.get(FEED_URL).respond(200, json=feed)
        assert await fetch(bsky(keywords=["claude", "anthropic", "python"]), router) == []


async def test_bluesky_one_bad_handle_is_a_warning_all_bad_is_an_error() -> None:
    adapter = bsky(["khong-ton-tai.example", "simonwillison.net"])
    bad = httpx.Response(400, json={"error": "InvalidRequest", "message": "Profile not found"})
    ok = httpx.Response(200, json=BLUESKY_FEED)
    with respx.mock() as router:
        router.get(FEED_URL).mock(side_effect=[bad, ok])
        items = await fetch(adapter, router)
    assert items and len(adapter.warnings) == 1 and "khong-ton-tai" in adapter.warnings[0]
    with respx.mock() as router:
        router.get(FEED_URL).respond(400)
        with pytest.raises(SourceError):
            await fetch(bsky(["a.example", "b.example"]), router)


def test_bluesky_post_with_external_link_embed() -> None:
    post = {
        "uri": "at://did:plc:x/app.bsky.feed.post/3kabc",
        "author": {"handle": "a.example"},
        "record": {"text": "Repo mới về agent", "createdAt": "2026-10-23T10:00:00.000Z"},
        "embed": {
            "external": {
                "uri": "https://github.com/acme/tool",
                "title": "acme/tool",
                "description": "Runner",
            }
        },
        "likeCount": 7,
    }
    result = build_post(post)
    assert result.links == ["https://github.com/acme/tool"]
    assert "acme/tool" in result.text and result.url.endswith("/post/3kabc")
    assert result.metrics == {"likes": 7.0, "reposts": 0.0, "replies": 0.0}


def _post_with_link(text: str, link_text: str) -> dict[str, object]:
    start = text.encode("utf-8").index(link_text.encode("utf-8"))
    return {
        "uri": "at://did:plc:x/app.bsky.feed.post/3kl",
        "author": {"handle": "a.example"},
        "record": {
            "text": text,
            "createdAt": "2026-10-23T10:00:00Z",
            "facets": [
                {
                    "index": {"byteStart": start, "byteEnd": start + len(link_text.encode())},
                    "features": [
                        {"$type": "app.bsky.richtext.facet#link", "uri": "https://a.example/x"}
                    ],
                }
            ],
        },
    }


def test_bluesky_title_drops_shortened_link_text() -> None:
    mid = _post_with_link("New tool a.example/x... is great", "a.example/x...")
    assert build_post(mid).title == "New tool is great"  # không còn hai dấu cách liền nhau
    # chữ nhiều byte (tiếng Việt, emoji) đứng trước link: offset tính theo byte UTF-8
    viet = _post_with_link("Công cụ mới 🚀 cho LLM a.example/x...", "a.example/x...")
    assert build_post(viet).title == "Công cụ mới 🚀 cho LLM"
    only = _post_with_link("a.example/x...", "a.example/x...")
    assert build_post(only).title == "a.example/x..."  # bài chỉ có link: không để tiêu đề rỗng


def test_bluesky_long_first_line_is_kept_whole_for_the_title() -> None:
    line = "word " * 59 + "end"
    post = {
        "uri": "at://did:plc:x/app.bsky.feed.post/3k1",
        "author": {"handle": "a.example"},
        "record": {"text": f"{line}\nsecond line", "createdAt": "2026-10-23T10:00:00Z"},
    }
    title = build_post(post).title
    assert title == line and not title.endswith("…")


# ---- cài đặt: bật/tắt nguồn và thêm feed -------------------------------------------------


def test_build_adapters_includes_rss_and_bluesky_and_respects_enabled_flags(app_home: Path) -> None:
    names = [a.name for a in build_adapters(Settings())]
    assert names[:4] == ["github", "hf_papers", "hf_models", "hackernews"]
    assert {"rss_ainews", "rss_hf_blog", "rss_openai", "rss_deepmind", "bluesky"} <= set(names)
    off = Settings.model_validate(
        {
            "github": {"enabled": False},
            "huggingface": {"enabled": False},
            "hackernews": {"enabled": False},
            "bluesky": {"enabled": False},
            "rss": [
                {"name": "Chỉ một", "url": "https://x.test/f"},
                {"name": "Tắt", "url": "https://x.test/g", "enabled": False},
            ],
        }
    )
    assert [a.name for a in build_adapters(off)] == ["rss_chi_mot"]


def test_toml_can_add_a_feed_with_one_block(app_home: Path) -> None:
    app_home.mkdir(parents=True)
    toml = (
        "[[rss]]\n"
        'name = "Blog riêng"\n'
        'url = "https://blog.example/feed.xml"\n'
        "interval_minutes = 45\n"
    )
    (app_home / "settings.toml").write_text(toml, encoding="utf-8")
    from app.config import load_settings

    feeds = load_settings().rss
    assert [(f.name, f.interval_minutes, f.max_entries) for f in feeds] == [("Blog riêng", 45, 30)]


# ---- cổng giai đoạn 4: thêm nguồn không phải sửa pipeline/ui ---------------------------------


async def test_a_brand_new_source_works_end_to_end_with_only_a_registration(
    engine: AsyncEngine,
) -> None:
    register(SourceInfo("mastodon", "Mastodon", "#5A3E8C", rank=5, heat_metric="boosts"))
    assert source_label("mastodon") == "Mastodon" and theme.source_color("mastodon") == "#5A3E8C"
    ranking = RankingSettings.model_validate({"heat_scales": {"mastodon": 50.0}})
    assert item_heat("mastodon", {"boosts": 25.0}, ranking) == pytest.approx(0.5)
    noise = NoiseSettings.model_validate({"thresholds": {"mastodon": {"boosts": 10}}})
    assert noise_reason("mastodon", "Một bài đủ dài về AI", "", {"boosts": 3}, noise) is not None
    assert noise_reason("mastodon", "Một bài đủ dài về AI", "", {"boosts": 30}, noise) is None
    post = item(
        "mastodon", "1", "https://m.example/@a/1", "Bài mới về mô hình ngôn ngữ", boosts=40.0
    )
    settings = Settings.model_validate(
        {
            "noise": {"thresholds": {"mastodon": {"boosts": 10}}},
            "ranking": {"heat_scales": {"mastodon": 50.0}},
        }
    )
    proc, writer = await make(engine, [post], settings=settings)
    await proc.run()
    await writer.stop()
    (cluster,) = await all_clusters(engine)
    assert cluster["is_noise"] is False and cluster["importance"] > 0


def test_unregistered_source_gets_safe_defaults() -> None:
    info = sources.info("nguon-la-hoan-toan")
    assert info.label == "nguon-la-hoan-toan" and info.heat_metric is None
    assert theme.source_color("nguon-la-hoan-toan") == theme.DEFAULT_SOURCE_COLOR
    assert item_heat("nguon-la-hoan-toan", {"x": 1e9}, RankingSettings()) == 0.0


def test_pipeline_and_ui_contain_no_per_source_code() -> None:
    root = Path(__file__).parent.parent / "app"
    pattern = re.compile(r"""\bsource\s*(==|!=|in)\s*[("'\[]|\.source\s*(==|!=)\s*["']""")
    offenders = [
        f"{path.relative_to(root)}:{n}"
        for folder in ("pipeline", "ui")
        for path in (root / folder).rglob("*.py")
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if pattern.search(line)
    ]
    assert offenders == []
