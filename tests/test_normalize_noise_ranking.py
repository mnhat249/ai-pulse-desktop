from __future__ import annotations

import pytest

from app.config import NoiseSettings, RankingSettings
from app.pipeline.noise import noise_reason
from app.pipeline.normalize import canonical_key, extract_links, item_keys, strip_tracking
from app.pipeline.ranking import importance_score, item_heat


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://www.Example.com/post/?utm_source=x&id=7&fbclid=abc#top",
            "https://example.com/post?id=7",
        ),
        ("https://example.com/a/", "https://example.com/a"),
        ("http://example.com", "http://example.com"),
    ],
)
def test_strip_tracking(url: str, expected: str) -> None:
    assert strip_tracking(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/Owner/Repo",
        "https://www.github.com/owner/repo/",
        "https://github.com/owner/repo.git",
        "https://github.com/owner/repo/tree/main/src?tab=readme#install",
        "https://github.com/OWNER/REPO/issues/12",
    ],
)
def test_github_urls_share_one_key(url: str) -> None:
    assert canonical_key(url) == "github:owner/repo"


def test_github_non_repo_pages_are_not_repo_keys() -> None:
    assert (
        canonical_key("https://github.com/orgs/acme/people")
        == "https://github.com/orgs/acme/people"
    )
    assert canonical_key("https://github.com/topics/llm").startswith("https://")


@pytest.mark.parametrize(
    "url",
    [
        "https://arxiv.org/abs/2401.01234",
        "http://arxiv.org/abs/2401.01234v2",
        "https://arxiv.org/pdf/2401.01234v3.pdf",
        "https://export.arxiv.org/abs/2401.01234",
        "https://huggingface.co/papers/2401.01234",
    ],
)
def test_paper_urls_share_one_arxiv_key(url: str) -> None:
    assert canonical_key(url) == "arxiv:2401.01234"


def test_huggingface_model_key_ignores_subpages_and_non_model_paths() -> None:
    assert canonical_key("https://huggingface.co/Org/Model/blob/main/README.md") == "hf:org/model"
    assert canonical_key("https://huggingface.co/org/model") == "hf:org/model"
    assert not canonical_key("https://huggingface.co/datasets/org/data").startswith("hf:")
    assert not canonical_key("https://huggingface.co/blog/some-post").startswith("hf:")


def test_extract_links_trims_punctuation_and_dedupes() -> None:
    text = "Xem https://github.com/a/b, và (https://arxiv.org/abs/2401.01234). Lại https://github.com/a/b!"
    assert extract_links(text) == ["https://github.com/a/b", "https://arxiv.org/abs/2401.01234"]


def test_item_keys_puts_primary_first_and_dedupes() -> None:
    keys = item_keys(
        "https://news.ycombinator.com/item?id=1",
        ["https://github.com/a/b"],
        "code ở https://github.com/A/B/tree/main",
    )
    assert keys[0].startswith("https://news.ycombinator.com")
    assert keys.count("github:a/b") == 1


NOISE = NoiseSettings()


def test_noise_spam_keyword_whole_word() -> None:
    assert "quảng cáo" in (
        noise_reason("hackernews", "Free AI course giveaway today", "", {"points": 500}, NOISE)
        or ""
    )
    assert (
        noise_reason("hackernews", "Discounted GPUs are scarce", "", {"points": 500}, NOISE) is None
    )


def test_noise_short_title() -> None:
    assert noise_reason("hf_papers", "AI", "", {}, NOISE) == "tiêu đề quá ngắn"


@pytest.mark.parametrize(
    ("source", "metrics", "is_noise"),
    [
        ("github", {"stars": 5}, True),
        ("github", {"stars": 500}, False),
        ("hf_models", {"likes": 1}, True),
        ("hf_models", {"likes": 50}, False),
        ("hackernews", {"points": 10}, True),
        ("hackernews", {"points": 120}, False),
        ("hf_papers", {}, False),
    ],
)
def test_noise_thresholds_per_source(
    source: str, metrics: dict[str, float], is_noise: bool
) -> None:
    assert (noise_reason(source, "Một tiêu đề đủ dài", "", metrics, NOISE) is not None) is is_noise


RANK = RankingSettings()


def test_item_heat_is_scaled_per_source_and_clamped() -> None:
    assert item_heat("github", {"stars_per_24h": 50}, RANK) == pytest.approx(0.5)
    assert item_heat("github", {"stars_per_24h": 9999}, RANK) == 1.0
    assert item_heat("hf_models", {"trendingScore": 500}, RANK) == pytest.approx(0.5)
    assert item_heat("hackernews", {"points": 150}, RANK) == pytest.approx(0.5)
    assert item_heat("hf_papers", {"upvotes": 25}, RANK) == pytest.approx(0.5)
    assert item_heat("hf_models", {"trendingScore": -5}, RANK) == 0.0
    assert item_heat("unknown", {"points": 1}, RANK) == 0.0


def test_importance_combines_heat_spread_and_llm() -> None:
    low = importance_score([0.0], 1, 1, RANK)
    high = importance_score([1.0], 3, 5, RANK)
    assert low == 0.0 and high == 100.0
    mid = importance_score([0.5], 2, 3, RANK)
    assert 0 < mid < 100


def test_importance_without_llm_renormalizes_weights() -> None:
    assert importance_score([1.0], 3, None, RANK) == 100.0
    assert importance_score([1.0], 1, None, RANK) == pytest.approx(100 * 0.4 / 0.7, abs=0.01)


def test_more_sources_rank_higher_all_else_equal() -> None:
    assert importance_score([0.2], 3, 3, RANK) > importance_score([0.2], 1, 3, RANK)


def test_weights_come_from_settings() -> None:
    only_llm = RankingSettings(heat_weight=0, spread_weight=0, llm_weight=1)
    assert importance_score([1.0], 3, 1, only_llm) == 0.0
    assert importance_score([0.0], 1, 5, only_llm) == 100.0
