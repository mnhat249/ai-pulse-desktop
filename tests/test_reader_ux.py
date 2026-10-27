"""Đọc tin dễ hơn: phân trang, đoạn giới thiệu, tiêu đề đầy đủ, chữ xuống dòng theo độ rộng."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings, UISettings
from app.core.models import Digest
from app.pipeline.digest import load_prompt
from app.storage import ui_queries
from app.storage.db import migrate
from app.storage.ui_queries import open_reader, plain_excerpt
from app.ui.model import ALL_TOPICS, MY_TOPICS, UIModel
from tests.helpers import digest_json
from tests.helpers_ui import ISO
from tests.test_widget import card_texts_of
from tests.tk_env import Env, card_texts, env, fresh  # noqa: F401


def _add(
    conn: sqlite3.Connection,
    importance: float,
    title: str,
    digest: dict[str, object] | None = None,
    text: str = "",
) -> int:
    cur = conn.execute(
        "INSERT INTO clusters (first_seen, last_seen, importance, is_noise, digest, primary_url)"
        " VALUES (?, ?, ?, 0, ?, 'https://x.example')",
        (ISO, ISO, importance, json.dumps(digest) if digest else None),
    )
    cid = int(cur.lastrowid or 0)
    item = conn.execute(
        "INSERT INTO raw_items (source, source_id, url, title, text, published_at, fetched_at,"
        " links) VALUES ('hackernews', ?, 'https://x.example', ?, ?, ?, ?, '[]')",
        (f"i{cid}", title, text, ISO, ISO),
    )
    conn.execute(
        "INSERT INTO cluster_items (cluster_id, item_id) VALUES (?, ?)", (cid, item.lastrowid)
    )
    return cid


@pytest.fixture
def many(tmp_path: Path):  # type: ignore[no-untyped-def]
    """14 cụm điểm giảm dần; cụm chẵn nói về Claude."""
    path = tmp_path / "many.db"
    migrate(path)
    conn = sqlite3.connect(path)
    ids = [
        _add(conn, 100.0 - n, "Claude Code tips" if n % 2 == 0 else f"filler {n}")
        for n in range(14)
    ]
    conn.commit()
    conn.close()
    reader = open_reader(path)
    yield ids, reader
    reader.close()


# ---- truy vấn: offset và đếm --------------------------------------------------------------


def test_offset_pages_are_disjoint_and_in_order(many) -> None:  # type: ignore[no-untyped-def]
    ids, reader = many
    pages = [
        [c.id for c in ui_queries.list_clusters(reader, limit=6, offset=o)] for o in (0, 6, 12)
    ]
    assert pages == [ids[0:6], ids[6:12], ids[12:14]]
    assert ui_queries.count_clusters(reader) == 14


def test_offset_and_count_with_topic_filter(many) -> None:  # type: ignore[no-untyped-def]
    ids, reader = many
    claude = ids[0::2]
    first = ui_queries.list_clusters(reader, topics=("claude",), limit=3)
    second = ui_queries.list_clusters(reader, topics=("claude",), limit=3, offset=3)
    assert [c.id for c in first] == claude[0:3] and [c.id for c in second] == claude[3:6]
    assert all("claude" in c.topics for c in first + second)
    assert ui_queries.count_clusters(reader, topics=("claude",)) == len(claude)
    assert ui_queries.list_clusters(reader, topics=("claude",), offset=99) == []
    assert ui_queries.count_clusters(reader, topics=("aigi",)) == 0


# ---- model: phân trang --------------------------------------------------------------------


def test_model_pages_and_resets_page_on_filter_change(many) -> None:  # type: ignore[no-untyped-def]
    ids, reader = many
    model = UIModel(reader, limit=30, page_size=6)
    model.set_topic_label(ALL_TOPICS)
    assert model.page_count() == 3 and [c.id for c in model.clusters()] == ids[0:6]
    assert model.next_page() and model.next_page() and not model.next_page()
    assert [c.id for c in model.clusters()] == ids[12:14]
    assert model.prev_page() and model.page == 1
    model.set_filter_label("Chưa đọc")
    assert model.page == 0
    model.page = 2
    model.set_source_label("hackernews")
    assert model.page == 0
    model.page = 2
    model.set_topic_label("Dùng Claude")
    assert model.page == 0 and model.page_count() == 2
    assert not model.prev_page()


def test_model_caps_total_and_clamps_page_past_the_end(many) -> None:  # type: ignore[no-untyped-def]
    ids, reader = many
    model = UIModel(reader, limit=8, page_size=6)
    model.set_topic_label(ALL_TOPICS)
    assert model.total() == 8 and model.page_count() == 2
    model.page = 1
    assert [c.id for c in model.clusters()] == ids[6:8]  # chỉ tới tin thứ 8
    model.page = 9  # ví dụ vừa đọc hết trang cuối ở chế độ "Chưa đọc"
    assert [c.id for c in model.clusters()] == ids[6:8] and model.page == 1


def test_empty_db_has_one_page(tmp_path: Path) -> None:
    path = tmp_path / "e.db"
    migrate(path)
    reader = open_reader(path)
    model = UIModel(reader)
    assert model.page_count() == 1 and model.clusters() == [] and not model.next_page()
    reader.close()


def test_page_size_setting() -> None:
    assert UISettings().page_size == 6 and Settings().ui.page_size == 6
    with pytest.raises(ValidationError):
        UISettings(page_size=0)
    with pytest.raises(ValidationError):
        UISettings(page_size=31)


# ---- đoạn giới thiệu ----------------------------------------------------------------------


def test_digest_intro_is_optional_and_link_free() -> None:
    assert Digest.model_validate(digest_json()).intro is None  # tóm tắt cũ vẫn hợp lệ
    assert Digest.model_validate(digest_json(intro="Nhóm A ra công cụ B.")).intro
    # giới thiệu có link: chỉ bỏ giới thiệu, bản tóm tắt vẫn giữ (không tốn thêm quota)
    linked = Digest.model_validate(digest_json(intro="Đọc thêm ở github.com/acme/tool nhé"))
    assert linked.intro is None and linked.innovation == "a"


def test_prompt_asks_for_intro_and_full_title() -> None:
    prompt = load_prompt()
    assert "intro" in prompt and '"intro": "..."' in prompt
    assert "12 từ" not in prompt and "không lược bớt" in prompt


def test_cluster_view_lead_text_prefers_intro_then_excerpt(tmp_path: Path) -> None:
    path = tmp_path / "i.db"
    migrate(path)
    conn = sqlite3.connect(path)
    with_intro = _add(
        conn, 9, "A", digest_json(title_vi="Tin A", intro="Giới thiệu A."), text="Gốc A"
    )
    old = _add(conn, 8, "B", digest_json(title_vi="Tin B"), text="<p>Nội dung <b>gốc</b> B</p>")
    bare = _add(conn, 7, "C")
    conn.commit()
    conn.close()
    reader = open_reader(path)
    views = {c.id: c for c in ui_queries.list_clusters(reader)}
    assert (
        views[with_intro].intro == "Giới thiệu A."
        and views[with_intro].lead_text == "Giới thiệu A."
    )
    assert views[old].intro is None and views[old].lead_text == "Nội dung gốc B"
    assert views[bare].lead_text == ""
    reader.close()


def test_plain_excerpt_cuts_at_sentence_end_when_possible() -> None:
    text = "Câu một khá dài để vượt nửa giới hạn. Câu hai " + "rất dài " * 30
    assert plain_excerpt(text, 60) == "Câu một khá dài để vượt nửa giới hạn."
    # "e.g." hay "vs." giữa câu (sau đó là chữ thường) không phải hết câu
    abbrev = "Nhiều công cụ tốt, e.g. ruff và mypy chạy rất nhanh trên dự án lớn " + "nữa " * 30
    assert not plain_excerpt(abbrev, 60).endswith("e.g.")
    words = plain_excerpt("chữ " * 100, 50)
    assert words.endswith("…") and not words[:-1].endswith(" ") and len(words) <= 51


# ---- widget ------------------------------------------------------------------------------


def test_widget_shows_one_page_and_pager(fresh: Env) -> None:  # noqa: F811
    widget = fresh.widget
    widget._model.page_size = 2
    try:
        widget.refresh()
        assert len(widget._cards) == 2
        assert widget._page_label.cget("text") == "Trang 1/2"
        assert widget._prev_button.cget("state") == "disabled"
        widget.next_page()
        assert len(widget._cards) == 1 and widget._page_label.cget("text") == "Trang 2/2"
        assert widget._next_button.cget("state") == "disabled"
        widget.prev_page()
        assert widget._model.page == 0 and len(widget._cards) == 2
    finally:
        widget._model.page_size = 6
        widget._model.page = 0
        widget.refresh()


def test_card_shows_full_long_title_and_original_title(fresh: Env) -> None:  # noqa: F811
    widget = fresh.widget
    long_title = "Rust 2.0 released " + " ".join(f"với tính năng số {n}" for n in range(25))
    db = fresh.path.parent / "ui.db"
    conn = sqlite3.connect(db)
    conn.execute("UPDATE raw_items SET title = ? WHERE title = 'Rust 2.0 released'", (long_title,))
    conn.commit()
    try:
        widget.refresh()
        texts = card_texts(widget)
        assert long_title in texts  # nguyên vẹn, không cắt, không "…"
        assert "acme/agent" in texts  # tiêu đề gốc dưới tiêu đề tiếng Việt
        assert widget._fonts["card_title"].cget("size") == 18
    finally:
        conn.execute(
            "UPDATE raw_items SET title = 'Rust 2.0 released' WHERE title = ?", (long_title,)
        )
        conn.commit()
        conn.close()
        widget.refresh()


def test_card_shows_topic_chip(fresh: Env) -> None:  # noqa: F811
    widget = fresh.widget
    widget.refresh()
    hot = widget._views[fresh.ids["hot"]]
    assert "models" in hot.topics
    assert "Model mới" in card_texts_of(widget._cards[hot.id])


def test_wrap_follows_feed_width(fresh: Env) -> None:  # noqa: F811
    widget = fresh.widget
    widget.refresh()
    wrap = widget._wrap
    scaling = widget._feed._get_widget_scaling()
    wrap.resize(round(700 * scaling))
    assert wrap.width == 700 - 44
    title = next(w for w, _ in wrap._labels if w.cget("text").startswith("Công cụ agent mới"))
    assert title.cget("wraplength") == 700 - 44
    wrap.resize(round(705 * scaling))  # đổi quá ít thì giữ nguyên
    assert wrap.width == 700 - 44
    wrap.resize(10)
    assert wrap.width == 200  # không nhỏ hơn mức tối thiểu


# ---- lọc chủ đề không làm đứng giao diện (review: 1,8 s mỗi lần làm mới) --------------------


def test_topic_scan_stops_early_and_runs_once_per_refresh(tmp_path: Path) -> None:
    path = tmp_path / "scan.db"
    migrate(path)
    conn = sqlite3.connect(path)
    for n in range(400):  # cụm nào cũng khớp "Dùng Claude"
        _add(conn, 1000.0 - n, f"Claude Code tip {n}")
    conn.commit()
    conn.close()
    reader = open_reader(path)
    ui_queries._row_topics.cache_clear()
    model = UIModel(reader, limit=30, page_size=6)
    assert model.topic == MY_TOPICS
    assert len(model.clusters()) == 6 and model.page_count() == 5
    # dừng khi đủ 30 tin, không dò regex cả 400 cụm; thanh trang không quét lại
    assert ui_queries._row_topics.cache_info().misses == 30
    model.clusters()
    model.page_count()
    assert ui_queries._row_topics.cache_info().misses == 30  # lần sau dùng kết quả đã nhớ
    reader.close()


def test_count_clusters_is_capped(many) -> None:  # type: ignore[no-untyped-def]
    _, reader = many
    assert ui_queries.count_clusters(reader, cap=5) == 5
    assert ui_queries.count_clusters(reader, topics=("claude",), cap=3) == 3


# ---- "Nội dung gốc" không lặp đoạn mở đầu với bài dài ----------------------------------------


def test_long_unsummarized_card_does_not_repeat_the_excerpt(fresh: Env) -> None:  # noqa: F811
    widget = fresh.widget
    cid = fresh.ids["plain"]
    db = fresh.path.parent / "ui.db"
    long_text = "Rust 2.0 mang tới nhiều thay đổi lớn cho trình biên dịch. " * 12
    conn = sqlite3.connect(db)
    conn.execute("UPDATE raw_items SET text = ? WHERE title = 'Rust 2.0 released'", (long_text,))
    conn.commit()
    try:
        widget.refresh()
        widget.toggle_card(cid)
        texts = card_texts_of(widget._cards[cid])
        assert "Nội dung gốc" not in texts
        assert len({t for t in texts if t.startswith("Rust 2.0 mang tới")}) == 1
    finally:
        widget._model.expanded.discard(cid)
        conn.execute("UPDATE raw_items SET text = '' WHERE title = 'Rust 2.0 released'")
        conn.commit()
        conn.close()
        widget.refresh()


def test_glossary_tab_is_built_only_when_opened(fresh: Env) -> None:  # noqa: F811
    widget = fresh.widget
    widget.glossary.rendered = False
    for child in widget.glossary._list.winfo_children():
        child.destroy()
    widget.refresh()
    assert not widget.glossary.rendered
    widget._tabs.set("Thuật ngữ")
    widget._on_tab()
    assert widget.glossary.rendered and widget.glossary.shown
    widget._tabs.set("Tin tức")


def test_glossary_file_ships_in_the_package() -> None:
    import tomllib

    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert "glossary/*.toml" in data["tool"]["setuptools"]["package-data"]["app"]
