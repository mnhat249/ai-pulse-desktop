from __future__ import annotations

import sqlite3
import time
import tkinter
from dataclasses import replace
from pathlib import Path
from typing import Any

import customtkinter as ctk
import pytest

from app.storage.ui_queries import ClusterView, cluster_details, plain_excerpt
from app.ui import tray as cmd
from app.ui.backend import UIEvent
from app.ui.state import load_state
from app.ui.widget import FloatingWidget, open_link
from tests.helpers_ui import ISO
from tests.tk_env import Env, card_texts, pump_until


def test_cards_are_listed_by_score_with_sources_and_unread_count(fresh: Env) -> None:
    fresh.widget.refresh()
    texts = " | ".join(card_texts(fresh.widget))
    assert texts.index("Công cụ agent mới") < texts.index("Rust 2.0 released")
    assert all(chip in texts for chip in ("GitHub", "HN", "HF")) and "Free course" not in texts
    assert fresh.widget._unread_label.cget("text") == "3 tin chưa đọc"


def test_clicking_a_card_expands_it_to_the_three_points(fresh: Env) -> None:
    fresh.widget.refresh()
    assert "Chạy agent cục bộ" not in " ".join(card_texts(fresh.widget))
    fresh.widget.toggle_card(fresh.ids["hot"])
    texts = " | ".join(card_texts(fresh.widget))
    assert all(
        t in texts for t in ("Cái mới", "Chạy agent cục bộ", "Dùng để", "Dev tiết kiệm thời gian")
    )
    assert "Mở link" in texts and "Bookmark" in texts and "Đã đọc" in texts


def test_unsummarized_cluster_shows_original_title_and_pending_note(fresh: Env) -> None:
    fresh.widget.toggle_card(fresh.ids["plain"])
    texts = " | ".join(card_texts(fresh.widget))
    assert "Rust 2.0 released" in texts and "Chờ tóm tắt" in texts


def test_filters_change_the_list(fresh: Env) -> None:
    fresh.widget._on_source("github")
    texts = " | ".join(card_texts(fresh.widget))
    assert "Công cụ agent mới" in texts and "Rust 2.0 released" not in texts
    fresh.widget._on_source("Mọi nguồn")
    fresh.widget._on_filter("Bookmark")
    assert "Chưa có tin nào" in " ".join(card_texts(fresh.widget))


def test_buttons_call_the_controller(fresh: Env) -> None:
    view = fresh.widget._model.cluster(fresh.ids["hot"])
    assert view is not None
    fresh.widget.toggle_bookmark(view)
    fresh.widget.toggle_read(view)
    assert fresh.controller.calls == [
        ("set_bookmark", (view.id, True)),
        ("mark_read", (view.id, True)),
    ]


def test_open_link_only_opens_http_and_marks_read(
    fresh: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[str] = []
    monkeypatch.setattr("app.ui.widget.webbrowser.open", opened.append)
    view = fresh.widget._model.cluster(fresh.ids["hot"])
    assert view is not None
    fresh.widget.open_cluster_link(view)
    pump_until(fresh.widget, lambda: bool(opened))
    assert opened == ["https://github.com/acme/agent"]
    assert fresh.controller.calls == [("mark_read", (view.id, True))]
    assert open_link("file:///c:/windows/system32/calc.exe") is False
    assert open_link(None) is False and opened == ["https://github.com/acme/agent"]


def test_events_refresh_the_list_and_trigger_toasts_for_changed_clusters(fresh: Env) -> None:
    fresh.events.put(UIEvent("updated", (fresh.ids["hot"], fresh.ids["plain"])))
    fresh.events.put(UIEvent("updated", (fresh.ids["hot"],)))
    fresh.widget.process_events()
    assert fresh.notifier.shown == [fresh.ids["hot"], fresh.ids["plain"]]
    fresh.widget.process_events()  # không có sự kiện mới thì không làm gì thêm
    assert len(fresh.notifier.shown) == 2


def test_drain_keeps_polling_even_when_processing_raises(
    fresh: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom() -> None:
        raise RuntimeError("lỗi giả")

    scheduled: list[int] = []
    monkeypatch.setattr(fresh.widget, "process_events", boom)
    monkeypatch.setattr(fresh.widget, "after", lambda ms, fn=None: scheduled.append(ms))
    fresh.widget._drain()
    assert scheduled == [500]


def test_toast_failure_does_not_lose_the_refresh(fresh: Env) -> None:
    class Exploding:
        def notify(self, cluster: ClusterView) -> bool:
            raise RuntimeError("không có backend toast")

    fresh.widget._notifier = Exploding()  # type: ignore[assignment]
    fresh.events.put(UIEvent("updated", (fresh.ids["hot"],)))
    with pytest.raises(RuntimeError):
        fresh.widget.process_events()
    # vòng _drain bắt lỗi này và vẫn đặt lịch lại (xem test trước); danh sách đã được làm mới
    assert "Công cụ agent mới" in " ".join(card_texts(fresh.widget))


def test_tray_commands_are_handled_on_the_ui_thread(
    fresh: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(fresh.widget, "withdraw", lambda: calls.append("withdraw"))
    monkeypatch.setattr(fresh.widget, "deiconify", lambda: calls.append("deiconify"))
    monkeypatch.setattr(fresh.widget, "state", lambda: "normal")
    fresh.commands.put(cmd.TOGGLE)
    fresh.commands.put(cmd.RUN_NOW)
    fresh.commands.put(cmd.PAUSE)
    fresh.commands.put(cmd.RESUME)
    fresh.widget.process_commands()
    assert calls == ["withdraw"]
    assert [c[0] for c in fresh.controller.calls] == ["run_now", "pause", "resume"]
    assert fresh.widget.paused is False


def test_show_command_brings_window_back(fresh: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(fresh.widget, "deiconify", lambda: calls.append("deiconify"))
    monkeypatch.setattr(fresh.widget, "lift", lambda: calls.append("lift"))
    monkeypatch.setattr(fresh.widget, "focus_force", lambda: calls.append("focus"))
    fresh.commands.put(cmd.SHOW)
    fresh.widget.process_commands()
    assert calls == ["deiconify", "lift", "focus"]


def test_quit_command_shuts_down_cleanly(fresh: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    destroyed: list[bool] = []
    monkeypatch.setattr(fresh.widget, "destroy", lambda: destroyed.append(True))
    fresh.commands.put(cmd.QUIT)
    fresh.commands.put(cmd.RUN_NOW)  # lệnh sau QUIT bị bỏ
    fresh.widget.process_commands()
    assert fresh.widget.quit_requested and destroyed == [True]
    assert fresh.controller.calls == []
    fresh.widget.shutdown()  # gọi lần hai không destroy thêm
    assert destroyed == [True]


def test_close_button_hides_when_tray_works_and_quits_when_not(
    fresh: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(fresh.widget, "withdraw", lambda: calls.append("withdraw"))
    monkeypatch.setattr(fresh.widget, "destroy", lambda: calls.append("destroy"))
    fresh.widget.mark_tray_ready()
    fresh.widget._on_close()
    assert calls == ["withdraw"] and not fresh.widget.quit_requested
    fresh.widget._tray_ok = False
    fresh.widget._on_close()
    assert calls == ["withdraw", "destroy"] and fresh.widget.quit_requested


def test_always_on_top_toggle_is_remembered(fresh: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fresh.widget, "state", lambda: "normal")
    before = fresh.widget._state.always_on_top
    fresh.widget.toggle_always_on_top()
    saved = load_state(fresh.path)
    assert saved.always_on_top is (not before)
    assert saved.width >= 320 and saved.height >= 300
    fresh.widget.toggle_always_on_top()
    assert load_state(fresh.path).always_on_top is before


def test_window_position_and_size_are_saved_on_resize(fresh: Env) -> None:
    fresh.widget.geometry("450x520+120+90")
    fresh.widget.update()
    fresh.widget._save_now()
    saved = load_state(fresh.path)
    assert (saved.width, saved.height) == (450, 520)


def test_status_window_lists_sources_and_last_error(fresh: Env) -> None:
    import sqlite3

    conn = sqlite3.connect(fresh.path.parent / "ui.db")
    conn.execute(
        "INSERT INTO source_runs (source, started_at, ok, item_count, error) "
        "VALUES ('github', '2026-10-23 10:00:00', 0, 0, 'HTTP 500')"
    )
    conn.execute(
        "INSERT INTO source_runs (source, started_at, ok, item_count, error) "
        "VALUES ('github', '2026-10-23 11:00:00', 1, 9, NULL)"
    )
    conn.commit()
    conn.close()
    before = set(fresh.widget.winfo_children())
    fresh.widget.show_statuses()
    window = (set(fresh.widget.winfo_children()) - before).pop()
    texts: list[str] = []

    def collect(parent: Any) -> None:
        for child in parent.winfo_children():
            if isinstance(child, ctk.CTkLabel):
                texts.append(str(child.cget("text")))
            collect(child)

    collect(window)
    window.destroy()
    joined = " | ".join(texts)
    assert "GitHub" in joined and "9 bài" in joined and "HTTP 500" in joined
    assert "github —" not in joined  # tên đã được làm đẹp


def test_paused_state_shows_message_and_updates_tray(fresh: Env) -> None:
    updates: list[bool] = []

    class FakeTray:
        def update(self) -> None:
            updates.append(True)

    fresh.widget._tray = FakeTray()  # type: ignore[assignment]
    fresh.widget.set_paused(True)
    assert fresh.widget.paused and "tạm dừng" in fresh.widget._status_label.cget("text")
    assert fresh.controller.calls[-1][0] == "pause" and updates == [True]
    fresh.widget.set_paused(False)
    assert (
        fresh.widget._status_label.cget("text") == "" and fresh.controller.calls[-1][0] == "resume"
    )
    fresh.widget._tray = None


def test_state_events_refresh_the_list_but_never_toast(fresh: Env) -> None:
    fresh.events.put(UIEvent("state", (fresh.ids["hot"], fresh.ids["plain"])))
    fresh.widget.process_events()
    assert fresh.notifier.shown == []
    assert "Công cụ agent mới" in " ".join(card_texts(fresh.widget))
    fresh.events.put(UIEvent("updated", (fresh.ids["hot"],)))
    fresh.widget.process_events()
    assert fresh.notifier.shown == [fresh.ids["hot"]]


def _tree(root: tkinter.Misc) -> set[str]:
    names: set[str] = set()
    for child in root.winfo_children():
        names.add(str(child))
        names |= _tree(child)
    return names


def _shown_ids(widget: FloatingWidget) -> list[int]:
    ids = {str(card): cid for cid, card in widget._cards.items()}
    return [ids[str(card)] for card in widget._feed.pack_slaves()]


def card_texts_of(card: tkinter.Misc) -> list[str]:
    texts: list[str] = []
    for name in sorted(_tree(card)):
        try:
            value = card.nametowidget(name).cget("text")
        except (tkinter.TclError, AttributeError, ValueError, KeyError):
            continue
        if isinstance(value, str) and value:
            texts.append(value)
    return texts


def _set_user_state(fresh: Env, cluster_id: int, *, bookmarked: bool, read: bool) -> None:
    conn = sqlite3.connect(fresh.path.parent / "ui.db")
    conn.execute(
        "INSERT INTO user_state (cluster_id, read_at, bookmarked) VALUES (?, ?, ?)"
        " ON CONFLICT(cluster_id) DO UPDATE SET read_at = excluded.read_at,"
        " bookmarked = excluded.bookmarked",
        (cluster_id, "2026-10-24 08:00:00" if read else None, bookmarked),
    )
    conn.commit()
    conn.close()


def test_toggling_a_card_destroys_only_that_card(fresh: Env) -> None:
    widget = fresh.widget
    widget.refresh()
    order = [str(card) for card in widget._feed.pack_slaves()]
    hot_card = widget._cards[fresh.ids["hot"]]
    hot_widgets = {str(hot_card)} | _tree(hot_card)
    before = _tree(widget._feed)

    widget.toggle_card(fresh.ids["hot"])
    destroyed = before - _tree(widget._feed)
    assert destroyed == hot_widgets
    new_hot = widget._cards[fresh.ids["hot"]]
    assert [str(c) for c in widget._feed.pack_slaves()] == [
        str(new_hot) if name == str(hot_card) else name for name in order
    ]
    assert "Chạy agent cục bộ" in " ".join(card_texts(widget))

    expanded = _tree(widget._feed)
    expanded_hot = {str(new_hot)} | _tree(new_hot)
    widget.toggle_card(fresh.ids["hot"])
    assert expanded - _tree(widget._feed) == expanded_hot
    assert "Chạy agent cục bộ" not in " ".join(card_texts(widget))
    assert widget._unread_label.cget("text") == "3 tin chưa đọc"


def test_toggling_a_middle_card_keeps_card_order(fresh: Env) -> None:
    widget = fresh.widget
    widget.refresh()
    expected = [fresh.ids[name] for name in ("hot", "plain", "paper")]
    assert _shown_ids(widget) == expected
    for _ in range(2):
        widget.toggle_card(fresh.ids["plain"])
        assert _shown_ids(widget) == expected


def test_state_event_rebuilds_only_the_changed_card(fresh: Env) -> None:
    widget = fresh.widget
    widget.refresh()
    hot_card = widget._cards[fresh.ids["hot"]]
    hot_widgets = {str(hot_card)} | _tree(hot_card)
    before = _tree(widget._feed)
    try:
        _set_user_state(fresh, fresh.ids["hot"], bookmarked=True, read=True)
        fresh.events.put(UIEvent("state", (fresh.ids["hot"],)))
        widget.process_events()
        assert before - _tree(widget._feed) == hot_widgets
        assert any("★" in t for t in card_texts_of(widget._cards[fresh.ids["hot"]]))
        assert widget._unread_label.cget("text") == "2 tin chưa đọc"

        fresh.events.put(UIEvent("state", (fresh.ids["plain"],)))
        unchanged = _tree(widget._feed)
        widget.process_events()  # dữ liệu không đổi thì không hủy widget nào
        assert unchanged - _tree(widget._feed) == set()
    finally:
        _set_user_state(fresh, fresh.ids["hot"], bookmarked=False, read=False)
        widget.refresh()


def test_card_leaving_the_filter_triggers_full_rebuild(fresh: Env) -> None:
    widget = fresh.widget
    widget._on_filter("Chưa đọc")
    assert len(widget._feed.pack_slaves()) == 3
    try:
        _set_user_state(fresh, fresh.ids["plain"], bookmarked=False, read=True)
        fresh.events.put(UIEvent("state", (fresh.ids["plain"],)))
        widget.process_events()
        assert fresh.ids["plain"] not in widget._cards
        assert "Rust 2.0 released" not in " ".join(card_texts(widget))
        assert len(widget._feed.pack_slaves()) == 2
    finally:
        _set_user_state(fresh, fresh.ids["plain"], bookmarked=False, read=False)
        widget._on_filter("Tất cả")


def test_toggle_after_filter_change_without_refresh_rebuilds_everything(fresh: Env) -> None:
    widget = fresh.widget
    widget._on_filter("Bookmark")
    widget._model.set_filter_label("Tất cả")  # bộ lọc đổi nhưng chưa dựng lại
    widget.toggle_card(fresh.ids["plain"])
    texts = " | ".join(card_texts(widget))
    assert "Rust 2.0 released" in texts and "Công cụ agent mới" in texts


def _insert_item(path: Path, cluster_id: int, source: str, title: str, text: str, url: str) -> None:
    conn = sqlite3.connect(path)
    item = conn.execute(
        "INSERT INTO raw_items (source, source_id, url, title, text, published_at, fetched_at,"
        " links) VALUES (?, ?, ?, ?, ?, ?, ?, '[]')",
        (source, f"x-{title}", url, title, text, ISO, ISO),
    )
    conn.execute(
        "INSERT INTO cluster_items (cluster_id, item_id) VALUES (?, ?)",
        (cluster_id, item.lastrowid),
    )
    conn.commit()
    conn.close()


def _arrow(card: tkinter.Misc) -> ctk.CTkButton:
    for name in sorted(_tree(card)):
        w = card.nametowidget(name)
        if isinstance(w, ctk.CTkButton) and w.cget("text") == "↗":
            return w
    raise AssertionError("không có nút ↗")


def test_opening_a_card_keeps_the_other_cards(fresh: Env) -> None:
    widget = fresh.widget
    widget.refresh()
    others = {cid: widget._cards[cid] for cid in (fresh.ids["hot"], fresh.ids["paper"])}
    widget.toggle_card(fresh.ids["plain"])
    for cid, card in others.items():
        assert widget._cards[cid] is card and card.winfo_exists()
    widget.toggle_card(fresh.ids["plain"])


def test_full_refresh_keeps_scroll_position(fresh: Env) -> None:
    widget = fresh.widget
    conn = sqlite3.connect(fresh.path.parent / "ui.db")
    ids = []
    for i in range(14):
        cur = conn.execute(
            "INSERT INTO clusters (first_seen, last_seen, importance, is_noise, primary_url)"
            " VALUES (?, ?, ?, 0, 'https://x.example/')",
            (ISO, ISO, 10.0 - i * 0.1),
        )
        ids.append(cur.lastrowid)
        item = conn.execute(
            "INSERT INTO raw_items (source, source_id, url, title, text, published_at,"
            " fetched_at, links) VALUES ('hackernews', ?, 'https://x.example/', ?, '', ?, ?, '[]')",
            (f"pad{i}", f"Padding {i}", ISO, ISO),
        )
        conn.execute("INSERT INTO cluster_items VALUES (?, ?)", (cur.lastrowid, item.lastrowid))
    conn.commit()
    widget._model.page_size = 20  # một trang đủ dài để cuộn
    try:
        widget.refresh()
        widget.update()
        canvas = widget._feed._parent_canvas
        canvas.yview_moveto(0.5)
        widget.update()
        before = canvas.yview()[0]
        assert before > 0.1
        widget.refresh()
        widget.update()
        assert canvas.yview()[0] == pytest.approx(before, abs=0.02)
    finally:
        for cid in ids:
            conn.execute("DELETE FROM cluster_items WHERE cluster_id = ?", (cid,))
            conn.execute("DELETE FROM clusters WHERE id = ?", (cid,))
        conn.execute("DELETE FROM raw_items WHERE source_id LIKE 'pad%'")
        conn.commit()
        conn.close()
        widget._model.page_size = 6
        widget.refresh()


def test_arrow_button_opens_link_without_toggling_card(
    fresh: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[str] = []
    monkeypatch.setattr("app.ui.widget.webbrowser.open", opened.append)
    widget = fresh.widget
    widget.refresh()
    _arrow(widget._cards[fresh.ids["plain"]]).invoke()
    pump_until(widget, lambda: bool(opened))
    assert opened == ["https://rust.dev/2"]
    assert fresh.ids["plain"] not in widget._model.expanded
    assert fresh.controller.calls == [("mark_read", (fresh.ids["plain"], True))]


def test_arrow_falls_back_to_first_url_when_primary_url_is_missing(
    fresh: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[str] = []
    monkeypatch.setattr("app.ui.widget.webbrowser.open", opened.append)
    view = fresh.widget._model.cluster(fresh.ids["paper"])
    assert view is not None
    fresh.widget.open_cluster_link(replace(view, primary_url=None))
    pump_until(fresh.widget, lambda: bool(opened))
    assert opened == ["https://huggingface.co/papers/2401.1"]
    fresh.widget.open_cluster_link(replace(view, primary_url=None, urls=()))
    fresh.widget.open_cluster_link(replace(view, primary_url="file:///c:/x"))
    time.sleep(0.2)
    assert opened == ["https://huggingface.co/papers/2401.1"]


def test_unsummarized_card_shows_hint_excerpt_and_sources(
    fresh: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[str] = []
    monkeypatch.setattr("app.ui.widget.webbrowser.open", opened.append)
    widget = fresh.widget
    cid = fresh.ids["plain"]
    db = fresh.path.parent / "ui.db"
    _insert_item(db, cid, "github", "rust-lang/rust", "", "https://gh/r")
    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE raw_items SET text = ? WHERE title = 'Rust 2.0 released'",
        ("<p>Rust   <b>2.0</b> ra mắt</p>\n<i>x</i>&amp; hơn",),
    )
    conn.commit()
    conn.close()
    try:
        widget.refresh()
        widget.toggle_card(cid)
        texts = card_texts_of(widget._cards[cid])
        assert any("python -m app.setkey gemini" in t for t in texts)
        assert "Nguồn" in texts and "Rust 2.0 ra mắt x & hơn" in texts
        assert "Nội dung gốc" not in texts  # đoạn mở đầu dưới tiêu đề đã là nội dung gốc
        assert any(t.endswith("· Rust 2.0 released") for t in texts)
        assert any(t.endswith("· rust-lang/rust") for t in texts)
        widget.open_url(widget._views[cid], "https://gh/r")
        pump_until(widget, lambda: bool(opened))
        assert opened == ["https://gh/r"]
    finally:
        widget._model.expanded.discard(cid)
        conn = sqlite3.connect(db)
        conn.execute(
            "DELETE FROM cluster_items WHERE item_id IN"
            " (SELECT id FROM raw_items WHERE source_id = 'x-rust-lang/rust')"
        )
        conn.execute("DELETE FROM raw_items WHERE source_id = 'x-rust-lang/rust'")
        conn.execute("UPDATE raw_items SET text = '' WHERE title = 'Rust 2.0 released'")
        conn.commit()
        conn.close()
        widget.refresh()


def test_summarized_card_lists_sources_too(fresh: Env) -> None:
    widget = fresh.widget
    widget.refresh()
    widget.toggle_card(fresh.ids["hot"])
    try:
        texts = card_texts_of(widget._cards[fresh.ids["hot"]])
        assert "Chạy agent cục bộ" in " ".join(texts)
        assert not any("python -m app.setkey" in t for t in texts)
        assert "Nguồn" in texts
        ends = ("· acme/agent", "· Show HN: agent", "· acme/agent-7b")
        assert len({t for t in texts if t.endswith(ends)}) == 3
    finally:
        widget.toggle_card(fresh.ids["hot"])


def test_plain_excerpt_strips_html_collapses_spaces_and_truncates() -> None:
    assert plain_excerpt("<div>a\n\n  <i>b</i>&nbsp;c &lt;3</div>") == "a b c <3"
    assert plain_excerpt(None) == ""
    long = plain_excerpt("<p>" + "chữ " * 200 + "</p>")
    assert len(long) <= 301 and long.endswith("…")


def test_cluster_details_reads_excerpt_and_items(fresh: Env) -> None:
    conn = sqlite3.connect(fresh.path.parent / "ui.db")
    conn.row_factory = sqlite3.Row
    details = cluster_details(conn, fresh.ids["hot"])
    assert details.excerpt == ""
    first = details.items[0]
    assert (first.source, first.label, first.title, first.url) == (
        "github",
        "GitHub",
        "acme/agent",
        "https://github.com/acme/agent",
    )
    assert len(details.items) == 3
    assert cluster_details(conn, 999999).items == ()
    conn.close()
