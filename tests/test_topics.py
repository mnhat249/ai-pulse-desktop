"""Chủ đề tin: so khớp tiêu đề thật từ tests/fixtures, truy vấn lọc, model, menu, cài đặt."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from app.config import Settings, TopicOverride, TopicSettings
from app.core.topics import DEFAULT_RULES, TopicRule, match_topics
from app.storage import ui_queries
from app.storage.db import migrate
from app.storage.ui_queries import open_reader
from app.ui.model import ALL_TOPICS, MY_TOPICS, UIModel
from app.ui.state import WindowState, load_state, save_state
from tests.helpers_ui import ISO, seed_db
from tests.tk_env import Env, card_texts, env, fresh, pump_until  # noqa: F401

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def rss_titles(name: str) -> list[str]:
    xml = (FIXTURES / name).read_text(encoding="utf-8")
    return re.findall(r"<item>.*?<title>(.*?)</title>", xml, re.S)


def _real_titles() -> dict[str, str]:
    """Tiêu đề thật từ fixtures, khóa = 'nguồn:tiêu đề'."""
    out = [("github", i["full_name"]) for i in load("github_search.json")["items"]]
    out += [("hf", m["id"]) for m in load("hf_models.json")]
    out += [("hn", h["title"]) for h in load("hn_search.json")["hits"]]
    for name in ("rss_ainews", "rss_deepmind", "rss_hf_blog"):
        out += [("rss", t) for t in rss_titles(name + ".xml")]
    out += [("bsky", p["post"]["record"]["text"]) for p in load("bluesky_author_feed.json")["feed"]]
    return {f"{src}:{title}": title for src, title in out}


REAL = _real_titles()


def real(prefix: str) -> str:
    return next(title for key, title in REAL.items() if key.startswith(prefix))


def test_fixture_titles_are_loaded() -> None:
    assert len(REAL) > 20


@pytest.mark.parametrize(
    ("prefix", "topic"),
    [
        ("hf:deepseek-ai/DeepSeek", "models"),
        ("rss:Developing Gemini 4", "models"),
        ("bsky:Notes on Kimi", "models"),
        ("hf:black-forest-labs/flux-3", "aigi"),
        ("bsky:I built a Command", "claude"),
        ("bsky:I built a Command", "models"),  # "Claude Opus 5.5" là tên model
        ('bsky:"Anthropic told', "claude"),
    ],
)
def test_real_titles_match_topic(prefix: str, topic: str) -> None:
    assert topic in match_topics(real(prefix), DEFAULT_RULES)


@pytest.mark.parametrize(
    "prefix",
    [
        "hn:UN says breaching",
        "hn:LLMs are making formal",
        "hn:Using LLM for confidence",
        "rss:not much happened",
        "rss:Beyond tree cover",
        "rss:Accelerating the search",
        "rss:Ensemble forecasting",
        "bsky:Shared some notes on Python",
        "bsky:Anyone else's TikTok",
        "bsky:Spotted a familiar",
        "github:firecrawl/firecrawl",
        "github:morluto/rea",
    ],
)
def test_real_titles_do_not_match(prefix: str) -> None:
    assert match_topics(real(prefix), DEFAULT_RULES) == ()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Fluxion is a new chemistry kit", ()),
        ("Flux 2 is out", ("aigi",)),
        ("Overview of video games", ()),
        ("Veo 3 launches", ("aigi",)),
        ("DALL·E 4 and DALL-E 3", ("aigi",)),
        ("Stable Diffusion XL", ("aigi",)),
        ("New text-to-video model", ("aigi",)),
        ("Airport runway closed", ()),
        ("Runway Gen-4 released", ("aigi",)),
        ("A 7B model", ("models",)),
        ("Llama 70B weights", ("models",)),
        ("Raised $5B in funding", ()),
        ("GPT-5 hits benchmark", ("models",)),
        ("CHATGPT is popular", ()),
        ("Haiku poems", ()),
        ("Haiku 4 is fast", ("models", "claude")),
        ("Opus codec 1.5", ()),
        ("Claude Code adds MCP", ("claude",)),
        ("open-weights release", ("models",)),
        ("OPEN WEIGHT", ("models",)),
        ("Claude drives Stable Diffusion", ("claude", "aigi")),
        ("Writing Agent Skills and subagents for your repo", ("claude",)),
        ("My CLAUDE.md workflow", ("claude",)),
        ("New slash commands in the agent SDK", ("claude",)),
        ("Hooks for your build pipeline", ()),  # "hook"/"workflow" đứng một mình không tính
        ("Gemma 4 model card", ("models",)),
        ("Phi-5 and o3-mini pricing", ("models",)),
        ("Grok 5 is out", ("models",)),
        ("Photo3D and phinance apps", ()),
        ("Version 0.4.3 of foo", ()),
    ],
)
def test_match_topics_edge_cases(text: str, expected: tuple[str, ...]) -> None:
    assert match_topics(text, DEFAULT_RULES) == expected


def test_hf_models_source_always_models() -> None:
    assert match_topics("acme/zzz", DEFAULT_RULES, ["hf_models"]) == ("models",)
    assert match_topics("acme/zzz", DEFAULT_RULES, ["github"]) == ()


def test_rule_without_keywords_matches_nothing() -> None:
    assert match_topics("anything", [TopicRule("x", "X", ())]) == ()


# ---- cài đặt -----------------------------------------------------------------------------


def test_settings_overrides_from_toml(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("NEURALRADAR_HOME", str(tmp_path))
    (tmp_path / "settings.toml").write_text(
        '[topics]\nenabled = ["claude", "chip", "nope"]\n'
        '[topics.rules.claude]\nlabel = "Cờ-lốt"\nkeywords = ["cloud"]\n'
        '[topics.rules.chip]\nlabel = "Chip"\nkeywords = ["gpu", "nvidia"]\n'
        '[topics.rules.empty]\nlabel = "Rỗng"\n',
        encoding="utf-8",
    )
    topics = Settings().topics
    rules = {r.key: r for r in topics.resolved_rules()}
    assert rules["claude"].label == "Cờ-lốt" and rules["claude"].keywords == ("cloud",)
    assert rules["claude"].patterns == ()
    assert rules["models"].label == "Model mới"
    assert rules["chip"].keywords == ("gpu", "nvidia")
    assert "empty" not in rules
    assert topics.enabled_keys() == ("claude", "chip")
    assert match_topics("Nvidia GPU", topics.resolved_rules()) == ("chip",)


def test_settings_defaults_enable_all_three() -> None:
    assert TopicSettings().enabled_keys() == ("models", "claude", "aigi")
    only_label = TopicSettings(rules={"claude": TopicOverride(label="C")})
    claude = next(r for r in only_label.resolved_rules() if r.key == "claude")
    assert claude.label == "C" and "anthropic" in claude.keywords and claude.patterns


# ---- truy vấn ---------------------------------------------------------------------------


@pytest.fixture
def seeded(tmp_path: Path):  # type: ignore[no-untyped-def]
    path = tmp_path / "ui.db"
    ids = seed_db(path)
    reader = open_reader(path)
    yield path, ids, reader
    reader.close()


def test_list_clusters_topic_filter(seeded) -> None:  # type: ignore[no-untyped-def]
    _, ids, reader = seeded
    assert [c.id for c in ui_queries.list_clusters(reader, topics=("models",))] == [ids["hot"]]
    assert ui_queries.list_clusters(reader, topics=("claude",)) == []
    hot = ui_queries.list_clusters(reader, topics=("models", "claude"))[0]
    assert hot.topics == ("models",)
    everything = ui_queries.list_clusters(reader)
    assert len(everything) == 3 and everything[1].topics == ()


def add_cluster(
    path: Path,
    importance: float,
    title: str,
    digest: dict[str, Any] | None = None,
    extra_titles: tuple[str, ...] = (),
) -> int:
    conn = sqlite3.connect(path)
    cur = conn.execute(
        "INSERT INTO clusters (first_seen, last_seen, importance, is_noise, digest, primary_url)"
        " VALUES (?, ?, ?, 0, ?, 'https://x.example')",
        (ISO, ISO, importance, json.dumps(digest) if digest else None),
    )
    cid = int(cur.lastrowid or 0)
    for n, item_title in enumerate((title, *extra_titles)):
        item = conn.execute(
            "INSERT INTO raw_items (source, source_id, url, title, text, published_at,"
            " fetched_at, links) VALUES ('hackernews', ?, 'https://x.example', ?, '', ?, ?, '[]')",
            (f"id-{cid}-{n}", item_title, ISO, ISO),
        )
        conn.execute(
            "INSERT INTO cluster_items (cluster_id, item_id) VALUES (?, ?)", (cid, item.lastrowid)
        )
    conn.commit()
    conn.close()
    return cid


def digest(title_vi: str, innovation: str = "", impact: str = "") -> dict[str, Any]:
    return {
        "title_vi": title_vi,
        "innovation": innovation,
        "impact": impact,
        "importance": 3,
        "is_noise": False,
        "noise_reason": None,
        "cluster_id": 1,
    }


def test_topic_match_uses_every_text_field(tmp_path: Path) -> None:
    path = tmp_path / "t.db"
    migrate(path)
    by_vi = add_cluster(path, 10, "zzz one", digest("Ra mắt Claude mới"))
    by_idea = add_cluster(path, 9, "zzz two", digest("Tin hai", innovation="Dùng Midjourney"))
    by_impact = add_cluster(path, 8, "zzz three", digest("Tin ba", impact="Chạy Qwen cục bộ"))
    by_original = add_cluster(path, 7, "Sora is here", digest("Tin bốn"))
    by_member = add_cluster(path, 6, "Boring first", None, extra_titles=("Kling 2 arrives",))
    add_cluster(path, 5, "Nothing relevant", digest("Không liên quan"))
    reader = open_reader(path)
    got = ui_queries.list_clusters(reader, topics=("models", "claude", "aigi"))
    assert [c.id for c in got] == [by_vi, by_idea, by_impact, by_original, by_member]
    assert [c.topics for c in got] == [
        ("claude",),
        ("aigi",),
        ("models",),
        ("aigi",),
        ("aigi",),
    ]
    reader.close()


def test_topic_filter_pages_until_limit_and_caps_scan(tmp_path: Path) -> None:
    path = tmp_path / "t.db"
    migrate(path)
    conn = sqlite3.connect(path)
    matching: list[int] = []
    for n in range(600):  # chỉ cụm 120 và các cụm từ 560 trở đi (điểm thấp) mới khớp
        title = "Claude news" if n >= 560 or n == 120 else f"filler {n}"
        cur = conn.execute(
            "INSERT INTO clusters (first_seen, last_seen, importance, is_noise, primary_url)"
            " VALUES (?, ?, ?, 0, 'https://x.example')",
            (ISO, ISO, 1000.0 - n),
        )
        cid = int(cur.lastrowid or 0)
        item = conn.execute(
            "INSERT INTO raw_items (source, source_id, url, title, text, published_at,"
            " fetched_at, links) VALUES ('hackernews', ?, 'https://x.example', ?, '', ?, ?, '[]')",
            (f"i{n}", title, ISO, ISO),
        )
        conn.execute(
            "INSERT INTO cluster_items (cluster_id, item_id) VALUES (?, ?)", (cid, item.lastrowid)
        )
        if title == "Claude news":
            matching.append(cid)
    conn.commit()
    conn.close()
    reader = open_reader(path)
    # cụm khớp đầu tiên nằm sau hàng trăm cụm không khớp, vẫn phải tìm ra
    got = ui_queries.list_clusters(reader, topics=("claude",), limit=1)
    assert [c.id for c in got] == [matching[0]]
    # các cụm từ vị trí 560 nằm ngoài giới hạn quét 500 dòng
    assert [c.id for c in ui_queries.list_clusters(reader, topics=("claude",), limit=30)] == [
        matching[0]
    ]
    assert len(ui_queries.list_clusters(reader, limit=30)) == 30
    reader.close()


def test_topic_filter_combines_with_view_and_source(seeded) -> None:  # type: ignore[no-untyped-def]
    _, ids, reader = seeded
    got = ui_queries.list_clusters(reader, view="unread", source="github", topics=("models",))
    assert [c.id for c in got] == [ids["hot"]]
    assert ui_queries.list_clusters(reader, source="hf_papers", topics=("models",)) == []
    assert ui_queries.list_clusters(reader, view="bookmarked", topics=("models",)) == []


# ---- model ------------------------------------------------------------------------------


def test_model_topic_choices_and_filtering(seeded) -> None:  # type: ignore[no-untyped-def]
    _, ids, reader = seeded
    model = UIModel(reader)
    assert model.topic == MY_TOPICS
    assert model.topic_choices() == [
        MY_TOPICS,
        ALL_TOPICS,
        "Model mới",
        "Dùng Claude",
        "Ảnh/video AI",
    ]
    assert [c.id for c in model.clusters()] == [ids["hot"]]
    model.set_topic_label(ALL_TOPICS)
    assert len(model.clusters()) == 3
    model.set_topic_label("Dùng Claude")
    assert model.topic_keys() == ("claude",) and model.clusters() == []
    model.set_topic_label("Model mới")
    assert [c.id for c in model.clusters()] == [ids["hot"]]
    model.set_topic_label("không có chủ đề này")
    assert model.topic == MY_TOPICS


def test_model_respects_enabled_topics(seeded) -> None:  # type: ignore[no-untyped-def]
    _, _, reader = seeded
    model = UIModel(reader, enabled_topics=("claude",))
    assert model.topic_choices() == [MY_TOPICS, ALL_TOPICS, "Dùng Claude"]
    assert model.topic_keys() == ("claude",) and model.clusters() == []
    model.set_topic_label("Model mới")  # đã tắt nên quay về mặc định
    assert model.topic == MY_TOPICS
    assert UIModel(reader, enabled_topics=()).topic_keys() is None


# ---- nhớ lựa chọn ------------------------------------------------------------------------


def test_topic_persisted_in_window_state(tmp_path: Path) -> None:
    path = tmp_path / "s.json"
    save_state(path, WindowState(topic="Claude"))
    assert load_state(path).topic == "Claude"
    path.write_text('{"x": 1}', encoding="utf-8")
    assert load_state(path).topic == ""


# ---- menu trên widget --------------------------------------------------------------------


def test_topic_menu_filters_and_remembers(fresh: Env) -> None:  # noqa: F811
    widget = fresh.widget
    widget._model.set_topic_label(MY_TOPICS)
    widget.refresh()
    assert any("Công cụ agent mới" in t for t in card_texts(widget))
    assert not any("Rust 2.0" in t for t in card_texts(widget))
    widget._on_topic("Dùng Claude")
    pump_until(widget, lambda: fresh.path.exists())
    assert load_state(fresh.path).topic == "Dùng Claude"
    assert widget._topic_bar.get() == "Dùng Claude"
    assert any("Chưa có tin nào khớp" in t for t in card_texts(widget))
    widget._on_topic(ALL_TOPICS)
    assert any("Rust 2.0" in t for t in card_texts(widget))
    assert widget._model.topic == ALL_TOPICS and widget._topic_bar.get() == ALL_TOPICS
