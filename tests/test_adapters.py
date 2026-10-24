from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from app.adapters import base
from app.adapters.base import (
    RateLimited,
    SourceAdapter,
    SourceError,
    parse_retry_after,
    request,
)
from app.adapters.bluesky import BlueskyAdapter
from app.adapters.github import GitHubAdapter
from app.adapters.hackernews import HackerNewsAdapter, keyword_pattern
from app.adapters.huggingface import HFModelsAdapter, HFPapersAdapter
from app.adapters.rss import RSSAdapter
from app.config import (
    BlueskySettings,
    FeedSettings,
    GitHubSettings,
    HackerNewsSettings,
    HuggingFaceSettings,
)
from app.core.models import RawItem

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    recorded: list[float] = []

    async def fake(seconds: float) -> None:
        recorded.append(seconds)

    monkeypatch.setattr(base, "_SLEEP", fake)
    return recorded


GITHUB_URL = "https://api.github.com/search/repositories"
HF_PAPERS_URL = "https://huggingface.co/api/daily_papers"
HF_MODELS_URL = "https://huggingface.co/api/models"
HN_URL = "https://hn.algolia.com/api/v1/search_by_date"

# (tên, hàm tạo adapter, hàm khai báo route giả lập thành công, hàm khai báo route lỗi 500)
Factory = Callable[[], SourceAdapter]


def mock_github(router: respx.MockRouter) -> None:
    router.get(GITHUB_URL).respond(200, json=fixture("github_search.json"))


def mock_hf_papers(router: respx.MockRouter) -> None:
    router.get(HF_PAPERS_URL).respond(200, json=fixture("hf_daily_papers.json"))


def mock_hf_models(router: respx.MockRouter) -> None:
    router.get(HF_MODELS_URL).respond(200, json=fixture("hf_models.json"))


def mock_hn(router: respx.MockRouter) -> None:
    router.get(HN_URL).respond(200, json=fixture("hn_search.json"))


RSS_URL = "https://huggingface.co/blog/feed.xml"
BLUESKY_URL = "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed"


def mock_rss(router: respx.MockRouter) -> None:
    text = (FIXTURES / "rss_hf_blog.xml").read_text(encoding="utf-8")
    router.get(RSS_URL).respond(200, text=text)


def mock_bluesky(router: respx.MockRouter) -> None:
    router.get(BLUESKY_URL).respond(200, json=fixture("bluesky_author_feed.json"))


def fail_500(url: str) -> Callable[[respx.MockRouter], None]:
    def route(router: respx.MockRouter) -> None:
        router.get(url).respond(500)

    return route


CASES: list[tuple[str, Factory, Callable[[respx.MockRouter], None], str]] = [
    ("github", lambda: GitHubAdapter(GitHubSettings(topics=["llm"])), mock_github, GITHUB_URL),
    ("hf_papers", lambda: HFPapersAdapter(HuggingFaceSettings()), mock_hf_papers, HF_PAPERS_URL),
    ("hf_models", lambda: HFModelsAdapter(HuggingFaceSettings()), mock_hf_models, HF_MODELS_URL),
    (
        "hackernews",
        lambda: HackerNewsAdapter(HackerNewsSettings(keywords=["llm"], min_points=0)),
        mock_hn,
        HN_URL,
    ),
    (
        "rss_hf_blog",
        lambda: RSSAdapter(FeedSettings(name="hf_blog", url=RSS_URL)),
        mock_rss,
        RSS_URL,
    ),
    (
        "bluesky",
        lambda: BlueskyAdapter(BlueskySettings(handles=["simonwillison.net"])),
        mock_bluesky,
        BLUESKY_URL,
    ),
]


@pytest.mark.parametrize(("name", "factory", "ok_route", "url"), CASES, ids=[c[0] for c in CASES])
class TestAdapterContract:
    async def test_returns_valid_raw_items(
        self,
        name: str,
        factory: Factory,
        ok_route: Callable[[respx.MockRouter], None],
        url: str,
        sleeps: list[float],
    ) -> None:
        adapter = factory()
        assert adapter.name == name and adapter.interval_minutes > 0
        with respx.mock(assert_all_called=False) as router:
            ok_route(router)
            async with httpx.AsyncClient() as client:
                items = await adapter.fetch(client)
        assert items, "fixture phải cho ra ít nhất một bài"
        assert all(isinstance(i, RawItem) for i in items)
        assert all(i.source == name and i.source_id and i.url and i.title for i in items)
        assert all(i.published_at.tzinfo is not None for i in items)
        assert len({i.source_id for i in items}) == len(items)

    async def test_network_failure_raises_source_error_after_three_attempts(
        self,
        name: str,
        factory: Factory,
        ok_route: Callable[[respx.MockRouter], None],
        url: str,
        sleeps: list[float],
    ) -> None:
        with respx.mock() as router:
            route = router.get(url).mock(side_effect=httpx.ConnectError("mất mạng"))
            async with httpx.AsyncClient() as client:
                with pytest.raises(SourceError) as info:
                    await factory().fetch(client)
        assert info.value.source == name
        assert sleeps[:2] == [1.0, 4.0]
        assert sleeps[:3] == [1.0, 4.0, 16.0]
        assert route.call_count >= 4 and route.call_count % 4 == 0  # mỗi truy vấn gọi 4 lần

    async def test_http_500_raises_source_error(
        self,
        name: str,
        factory: Factory,
        ok_route: Callable[[respx.MockRouter], None],
        url: str,
        sleeps: list[float],
    ) -> None:
        with respx.mock() as router:
            router.get(url).respond(500)
            async with httpx.AsyncClient() as client:
                with pytest.raises(SourceError):
                    await factory().fetch(client)

    async def test_changed_format_raises_named_source_error(
        self,
        name: str,
        factory: Factory,
        ok_route: Callable[[respx.MockRouter], None],
        url: str,
        sleeps: list[float],
    ) -> None:
        with respx.mock() as router:
            router.get(url).respond(200, json={"khong": "dung dinh dang"})
            async with httpx.AsyncClient() as client:
                with pytest.raises(SourceError) as info:
                    await factory().fetch(client)
        assert info.value.source == name


async def test_request_retries_1_4_then_succeeds(sleeps: list[float]) -> None:
    with respx.mock() as router:
        route = router.get("https://x.test/a").mock(
            side_effect=[httpx.Response(503), httpx.Response(502), httpx.Response(200, json={})]
        )
        async with httpx.AsyncClient() as client:
            response = await request(client, "x", "https://x.test/a")
    assert response.status_code == 200 and route.call_count == 3
    assert sleeps == [1.0, 4.0]


async def test_request_succeeds_on_the_fourth_call_after_1_4_16(sleeps: list[float]) -> None:
    with respx.mock() as router:
        route = router.get("https://x.test/a").mock(
            side_effect=[httpx.Response(500)] * 3 + [httpx.Response(200)]
        )
        async with httpx.AsyncClient() as client:
            response = await request(client, "x", "https://x.test/a")
    assert response.status_code == 200 and route.call_count == 4
    assert sleeps == [1.0, 4.0, 16.0]


async def test_request_long_rate_limit_raises_without_sleeping(sleeps: list[float]) -> None:
    with respx.mock() as router:
        route = router.get("https://x.test/a").respond(429, headers={"Retry-After": "3600"})
        async with httpx.AsyncClient() as client:
            with pytest.raises(RateLimited) as info:
                await request(client, "x", "https://x.test/a")
    assert route.call_count == 1 and sleeps == []
    assert info.value.retry_after == 3600 and info.value.source == "x"


async def test_request_github_quota_reset_in_an_hour_raises_without_sleeping(
    sleeps: list[float],
) -> None:
    from app.core.models import utcnow

    reset = str(int(utcnow().timestamp()) + 3000)
    with respx.mock() as router:
        route = router.get("https://x.test/a").respond(
            403, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": reset}
        )
        async with httpx.AsyncClient() as client:
            with pytest.raises(RateLimited):
                await request(client, "x", "https://x.test/a")
    assert route.call_count == 1 and sleeps == []


async def test_github_stops_remaining_queries_when_rate_limited(sleeps: list[float]) -> None:
    adapter = GitHubAdapter(GitHubSettings())  # 5 topic = 10 truy vấn
    ok = httpx.Response(200, json=fixture("github_search.json"))
    limited = httpx.Response(429, headers={"Retry-After": "3600"})
    with respx.mock() as router:
        route = router.get(GITHUB_URL).mock(side_effect=[ok, ok, limited])
        async with httpx.AsyncClient() as client:
            items = await adapter.fetch(client)
    assert route.call_count == 3 and sleeps == []
    assert items
    assert len(adapter.warnings) == 1 and "hết quota" in adapter.warnings[0]
    assert "8 truy vấn" in adapter.warnings[0]


async def test_github_partial_failure_is_reported_in_warnings(sleeps: list[float]) -> None:
    adapter = GitHubAdapter(GitHubSettings(topics=["llm"]))
    with respx.mock() as router:
        router.get(GITHUB_URL).mock(
            side_effect=[
                httpx.Response(404),
                httpx.Response(200, json=fixture("github_search.json")),
            ]
        )
        async with httpx.AsyncClient() as client:
            assert await adapter.fetch(client)
    assert len(adapter.warnings) == 1 and "HTTP 404" in adapter.warnings[0]


async def test_github_warnings_are_reset_on_every_fetch(sleeps: list[float]) -> None:
    adapter = GitHubAdapter(GitHubSettings(topics=["llm"]))
    with respx.mock() as router:
        router.get(GITHUB_URL).mock(
            side_effect=[
                httpx.Response(404),
                httpx.Response(200, json=fixture("github_search.json")),
                httpx.Response(200, json=fixture("github_search.json")),
                httpx.Response(200, json=fixture("github_search.json")),
            ]
        )
        async with httpx.AsyncClient() as client:
            await adapter.fetch(client)
            await adapter.fetch(client)
    assert adapter.warnings == []


async def test_github_all_queries_failing_raises(sleeps: list[float]) -> None:
    adapter = GitHubAdapter(GitHubSettings(topics=["llm"]))
    with respx.mock() as router:
        router.get(GITHUB_URL).respond(404)
        async with httpx.AsyncClient() as client:
            with pytest.raises(SourceError):
                await adapter.fetch(client)


async def test_hackernews_one_failing_keyword_keeps_the_others(sleeps: list[float]) -> None:
    hits = fixture("hn_search.json")["hits"]
    word = hits[0]["title"].split()[0].lower().strip("'\"")
    adapter = HackerNewsAdapter(HackerNewsSettings(keywords=["zzzz", word], min_points=0))
    with respx.mock() as router:
        router.get(HN_URL).mock(
            side_effect=[httpx.Response(404), httpx.Response(200, json=fixture("hn_search.json"))]
        )
        async with httpx.AsyncClient() as client:
            items = await adapter.fetch(client)
    assert any(i.title == hits[0]["title"] for i in items)
    assert len(adapter.warnings) == 1 and "zzzz" in adapter.warnings[0]


async def test_hackernews_all_keywords_failing_raises(sleeps: list[float]) -> None:
    adapter = HackerNewsAdapter(HackerNewsSettings(keywords=["a1", "b2"], min_points=0))
    with respx.mock() as router:
        router.get(HN_URL).respond(404)
        async with httpx.AsyncClient() as client:
            with pytest.raises(SourceError):
                await adapter.fetch(client)


async def test_request_429_waits_retry_after(sleeps: list[float]) -> None:
    with respx.mock() as router:
        router.get("https://x.test/a").mock(
            side_effect=[httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200)]
        )
        async with httpx.AsyncClient() as client:
            await request(client, "x", "https://x.test/a")
    assert sleeps == [7.0]


async def test_request_gives_up_after_three_attempts(sleeps: list[float]) -> None:
    with respx.mock() as router:
        route = router.get("https://x.test/a").respond(500)
        async with httpx.AsyncClient() as client:
            with pytest.raises(SourceError):
                await request(client, "x", "https://x.test/a")
    assert route.call_count == 4 and sleeps == [1.0, 4.0, 16.0]


async def test_request_4xx_is_not_retried(sleeps: list[float]) -> None:
    with respx.mock() as router:
        route = router.get("https://x.test/a").respond(404)
        async with httpx.AsyncClient() as client:
            with pytest.raises(SourceError):
                await request(client, "x", "https://x.test/a")
    assert route.call_count == 1 and sleeps == []


async def test_request_github_style_rate_limit_waits_until_reset(
    sleeps: list[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.models import utcnow

    reset = str(int(utcnow().timestamp()) + 30)
    with respx.mock() as router:
        router.get("https://x.test/a").mock(
            side_effect=[
                httpx.Response(
                    403, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": reset}
                ),
                httpx.Response(200),
            ]
        )
        async with httpx.AsyncClient() as client:
            await request(client, "x", "https://x.test/a")
    assert 25 <= sleeps[0] <= 31


async def test_request_plain_403_is_not_retried(sleeps: list[float]) -> None:
    with respx.mock() as router:
        route = router.get("https://x.test/a").respond(403)
        async with httpx.AsyncClient() as client:
            with pytest.raises(SourceError):
                await request(client, "x", "https://x.test/a")
    assert route.call_count == 1


def test_parse_retry_after() -> None:
    assert parse_retry_after("12") == 12.0
    assert parse_retry_after(None) is None
    assert parse_retry_after("không phải số") is None
    assert parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT") == 0.0


async def test_github_parses_fixture_fields(sleeps: list[float]) -> None:
    with respx.mock() as router:
        mock_github(router)
        async with httpx.AsyncClient() as client:
            items = await GitHubAdapter(GitHubSettings(topics=["llm"])).fetch(client)
    first = fixture("github_search.json")["items"][0]
    item = next(i for i in items if i.source_id == str(first["id"]))
    assert item.title == first["full_name"] and item.author == first["owner"]["login"]
    assert item.metrics["stars"] == first["stargazers_count"]
    assert item.metrics["age_hours"] > 0
    assert item.url in item.links


async def test_github_sends_token_and_reuses_etag(sleeps: list[float]) -> None:
    adapter = GitHubAdapter(GitHubSettings(topics=["llm"]), token="tok")
    with respx.mock() as router:
        route = router.get(GITHUB_URL).mock(
            side_effect=[
                httpx.Response(200, json=fixture("github_search.json"), headers={"etag": 'W/"1"'}),
                httpx.Response(200, json=fixture("github_search.json"), headers={"etag": 'W/"2"'}),
                httpx.Response(304),
                httpx.Response(304),
            ]
        )
        async with httpx.AsyncClient() as client:
            first = await adapter.fetch(client)
            second = await adapter.fetch(client)
    assert first and second == []
    assert route.calls[0].request.headers["authorization"] == "Bearer tok"
    assert "if-none-match" not in route.calls[0].request.headers
    assert route.calls[2].request.headers["if-none-match"] == 'W/"1"'
    assert route.calls[3].request.headers["if-none-match"] == 'W/"2"'


async def test_github_one_failing_query_does_not_lose_the_others(sleeps: list[float]) -> None:
    adapter = GitHubAdapter(GitHubSettings(topics=["llm"]))
    with respx.mock() as router:
        router.get(GITHUB_URL).mock(
            side_effect=[
                httpx.Response(404),
                httpx.Response(200, json=fixture("github_search.json")),
            ]
        )
        async with httpx.AsyncClient() as client:
            items = await adapter.fetch(client)
    assert items


async def test_github_deduplicates_repos_across_queries(sleeps: list[float]) -> None:
    with respx.mock() as router:
        mock_github(router)
        async with httpx.AsyncClient() as client:
            items = await GitHubAdapter(GitHubSettings(topics=["llm", "mcp"])).fetch(client)
    ids = [i.source_id for i in items]
    assert len(ids) == len(set(ids)) == len(fixture("github_search.json")["items"])


async def test_hf_paper_fields(sleeps: list[float]) -> None:
    with respx.mock() as router:
        mock_hf_papers(router)
        async with httpx.AsyncClient() as client:
            items = await HFPapersAdapter(HuggingFaceSettings()).fetch(client)
    first = fixture("hf_daily_papers.json")[0]["paper"]
    assert items[0].source_id == first["id"]
    assert items[0].url == f"https://huggingface.co/papers/{first['id']}"
    assert f"https://arxiv.org/abs/{first['id']}" in items[0].links


async def test_hf_model_fields(sleeps: list[float]) -> None:
    with respx.mock() as router:
        mock_hf_models(router)
        async with httpx.AsyncClient() as client:
            items = await HFModelsAdapter(HuggingFaceSettings()).fetch(client)
    first = fixture("hf_models.json")[0]
    assert items[0].source_id == first["id"] and items[0].author == first["id"].split("/")[0]
    assert items[0].metrics["trendingScore"] == first["trendingScore"]


async def test_hackernews_filters_by_keyword_in_title(sleeps: list[float]) -> None:
    hits = fixture("hn_search.json")["hits"]
    title = hits[0]["title"]
    word = title.split()[0].lower().strip("'\"")
    other = "zzzzqqqq"
    with respx.mock() as router:
        mock_hn(router)
        async with httpx.AsyncClient() as client:
            matched = await HackerNewsAdapter(
                HackerNewsSettings(keywords=[word], min_points=0)
            ).fetch(client)
            none = await HackerNewsAdapter(
                HackerNewsSettings(keywords=[other], min_points=0)
            ).fetch(client)
    assert any(i.title == title for i in matched)
    assert none == []


async def test_hackernews_sends_min_points_and_story_tag(sleeps: list[float]) -> None:
    with respx.mock() as router:
        route = router.get(HN_URL).respond(200, json=fixture("hn_search.json"))
        async with httpx.AsyncClient() as client:
            await HackerNewsAdapter(HackerNewsSettings(keywords=["llm"], min_points=80)).fetch(
                client
            )
    params = route.calls[0].request.url.params
    assert params["tags"] == "story" and "points>=80" in params["numericFilters"]


def test_keyword_pattern_matches_whole_words_only() -> None:
    pattern = keyword_pattern(["ai", "machine learning"])
    assert pattern.search("Show HN: an AI tool")
    assert pattern.search("Machine Learning at scale")
    assert not pattern.search("Rain in Spain")
    assert not pattern.search("Maintaining the maintainers")


async def test_hackernews_story_without_url_falls_back_to_hn_link(sleeps: list[float]) -> None:
    body = {
        "hits": [
            {
                "objectID": "42",
                "title": "Ask HN: best LLM for coding?",
                "author": "a",
                "created_at_i": 1792712270,
                "points": 90,
                "num_comments": 12,
                "story_text": "xin chào",
            }
        ]
    }
    with respx.mock() as router:
        router.get(HN_URL).respond(200, json=body)
        async with httpx.AsyncClient() as client:
            (item,) = await HackerNewsAdapter(
                HackerNewsSettings(keywords=["llm"], min_points=0)
            ).fetch(client)
    assert item.url == "https://news.ycombinator.com/item?id=42"
    assert item.text == "xin chào" and item.metrics["points"] == 90
