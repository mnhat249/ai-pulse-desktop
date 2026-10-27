from __future__ import annotations

from typing import Any

import customtkinter as ctk
import pytest

from app.storage.ui_queries import ClusterView
from app.ui import tray as cmd
from app.ui.backend import UIEvent
from app.ui.state import load_state
from app.ui.widget import open_link
from tests.tk_env import Env, card_texts


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


def status_window_texts(fresh: Env) -> list[str]:
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
    return texts


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
    texts = status_window_texts(fresh)
    joined = " | ".join(texts)
    assert "GitHub" in joined and "9 bài" in joined and "HTTP 500" in joined
    assert "github —" not in joined  # tên đã được làm đẹp
    assert "chỉ lấy được" not in joined  # lần quét cuối đủ, không có cảnh báo


def test_status_window_shows_partial_run_warning(fresh: Env) -> None:
    import sqlite3

    conn = sqlite3.connect(fresh.path.parent / "ui.db")
    conn.execute(
        "INSERT INTO source_runs (source, started_at, ok, item_count, error) "
        "VALUES ('hf_models', '2026-10-23 11:00:00', 1, 3, "
        "'một phần: bỏ 97/100 phần tử hỏng (lỗi đầu: KeyError(''id''))')"
    )
    conn.commit()
    conn.close()
    texts = status_window_texts(fresh)
    assert any(t.startswith("✓ HuggingFace · model") for t in texts)
    assert any("chỉ lấy được một phần: bỏ 97/100 phần tử hỏng" in t for t in texts)


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
