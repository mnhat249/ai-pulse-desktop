from __future__ import annotations

import tkinter
from pathlib import Path

import pytest

from app.config import Settings, load_settings
from app.settings_store import deep_merge, read_settings_file, update_settings_file
from app.ui.settings_form import SettingsDraft
from app.ui.settings_window import SettingsWindow
from tests.tk_env import Env, card_texts


def test_deep_merge_merges_tables_and_replaces_lists() -> None:
    base = {"github": {"enabled": True, "topics": ["a"]}, "rss": [{"name": "x"}], "k": 1}
    merged = deep_merge(base, {"github": {"enabled": False}, "rss": [{"name": "y"}]})
    assert merged == {"github": {"enabled": False, "topics": ["a"]}, "rss": [{"name": "y"}], "k": 1}
    assert base["github"]["enabled"] is True  # không sửa đối tượng gốc


def test_update_settings_file_keeps_unrelated_keys_and_is_atomic(tmp_path: Path) -> None:
    path = tmp_path / "settings.toml"
    path.write_text(
        "request_timeout_seconds = 5\n[hackernews]\nmin_points = 80\n", encoding="utf-8"
    )
    update_settings_file(path, {"hackernews": {"interval_minutes": 10}, "start_with_windows": True})
    data = read_settings_file(path)
    assert data["request_timeout_seconds"] == 5 and data["start_with_windows"] is True
    assert data["hackernews"] == {"min_points": 80, "interval_minutes": 10}
    assert not list(tmp_path.glob("*.tmp"))


def test_read_missing_file_is_empty(tmp_path: Path) -> None:
    assert read_settings_file(tmp_path / "none.toml") == {}


def test_draft_roundtrips_current_settings() -> None:
    settings = Settings()
    draft = SettingsDraft.from_settings(settings)
    assert draft.errors() == []
    assert draft.enabled["github"] and draft.enabled["rss:ainews"]
    assert draft.intervals["hackernews"] == "15" and draft.toast_min_importance == "70"
    updates = draft.to_updates(settings)
    assert updates["github"] == {"enabled": True, "interval_minutes": 30}
    assert [f["name"] for f in updates["rss"]] == [f.name for f in settings.rss]
    assert updates["ui"] == {"toast_min_importance": 70.0, "toast_max_per_hour": 4}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("intervals", {"github": "0"}),
        ("intervals", {"github": "abc"}),
        ("intervals", {"hackernews": "999999"}),
        ("intervals", {"bluesky": ""}),
        ("toast_min_importance", "150"),
        ("toast_min_importance", "cao"),
        ("toast_max_per_hour", "0"),
        ("toast_max_per_hour", "-3"),
    ],
)
def test_draft_rejects_bad_input_and_refuses_to_build_updates(field: str, value: object) -> None:
    draft = SettingsDraft.from_settings(Settings())
    if field == "intervals":
        assert isinstance(value, dict)
        draft.intervals.update(value)
    else:
        setattr(draft, field, value)
    assert draft.errors()
    with pytest.raises(ValueError):
        draft.to_updates(Settings())


def test_draft_accepts_decimal_comma_for_importance() -> None:
    draft = SettingsDraft.from_settings(Settings())
    draft.toast_min_importance = "65,5"
    assert draft.to_updates(Settings())["ui"]["toast_min_importance"] == 65.5


def test_toggling_a_feed_only_changes_its_enabled_flag() -> None:
    settings = Settings()
    draft = SettingsDraft.from_settings(settings)
    draft.enabled["rss:openai"] = False
    feeds = {f["name"]: f for f in draft.to_updates(settings)["rss"]}
    assert feeds["openai"]["enabled"] is False and feeds["ainews"]["enabled"] is True
    assert feeds["openai"]["url"] == next(f.url for f in settings.rss if f.name == "openai")


def test_saved_settings_load_back_through_the_real_settings_loader(
    tmp_path: Path, app_home: Path
) -> None:
    settings = Settings()
    draft = SettingsDraft.from_settings(settings)
    draft.enabled["github"] = False
    draft.enabled["rss:deepmind"] = False
    draft.intervals["hackernews"] = "20"
    draft.toast_max_per_hour = "2"
    update_settings_file(app_home / "settings.toml", draft.to_updates(settings))
    loaded = load_settings()
    assert loaded.github.enabled is False and loaded.hackernews.interval_minutes == 20
    assert loaded.ui.toast_max_per_hour == 2
    assert {f.name: f.enabled for f in loaded.rss}["deepmind"] is False
    assert loaded.huggingface.enabled is True and loaded.github.topics == settings.github.topics


# ---- cửa sổ Tk thật -------------------------------------------------------------------------


def open_window(fresh: Env, path: Path, applied: list[bool]) -> SettingsWindow:
    return SettingsWindow(
        fresh.widget,
        Settings(),
        path,
        fresh.widget._fonts,
        apply_startup=lambda enabled: applied.append(enabled) or True,
    )


def test_window_saves_valid_changes_to_the_toml_file(fresh: Env, tmp_path: Path) -> None:
    applied: list[bool] = []
    window = open_window(fresh, tmp_path / "settings.toml", applied)
    try:
        window._enabled["github"].set(False)
        window._intervals["hackernews"].set("25")
        window._startup.set(True)
        assert window.save() is True
        data = read_settings_file(tmp_path / "settings.toml")
        assert data["github"]["enabled"] is False and data["hackernews"]["interval_minutes"] == 25
        assert data["start_with_windows"] is True
        assert "Đã lưu" in window._message.cget("text")
        for _ in range(40):  # luồng nền áp dụng shortcut Startup
            window.update()
            if applied:
                break
        assert applied == [True]
    finally:
        window.destroy()


def test_window_blocks_invalid_input_and_writes_nothing(fresh: Env, tmp_path: Path) -> None:
    path = tmp_path / "settings.toml"
    applied: list[bool] = []
    window = open_window(fresh, path, applied)
    try:
        window._intervals["github"].set("không")
        window._importance.set("500")
        assert window.save() is False
        message = window._message.cget("text")
        assert "GitHub" in message and "0 đến 100" in message
        assert not path.exists() and applied == []
    finally:
        window.destroy()


def test_startup_shortcut_is_only_touched_when_the_choice_changed(
    fresh: Env, tmp_path: Path
) -> None:
    applied: list[bool] = []
    window = open_window(fresh, tmp_path / "settings.toml", applied)
    try:
        assert window.save() is True  # không đổi gì: start_with_windows vẫn False
        for _ in range(5):
            window.update()
        assert applied == []
    finally:
        window.destroy()


def test_window_reports_a_failed_startup_change(fresh: Env, tmp_path: Path) -> None:
    window = SettingsWindow(
        fresh.widget,
        Settings(),
        tmp_path / "settings.toml",
        fresh.widget._fonts,
        apply_startup=lambda enabled: False,
    )
    try:
        window._startup.set(True)
        window.save()
        for _ in range(40):
            window.update()
            if "shortcut" in window._message.cget("text"):
                break
        assert "shortcut" in window._message.cget("text")
    finally:
        window.destroy()


def test_widget_has_a_settings_button_that_opens_the_window(
    fresh: Env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[object] = []
    monkeypatch.setattr(
        "app.ui.widget.SettingsWindow", lambda *args, **kw: opened.append(args) or None
    )
    fresh.widget._settings_path = tmp_path / "settings.toml"
    assert "Cài đặt" in " ".join(_all_button_texts(fresh.widget))
    fresh.widget.show_settings()
    assert len(opened) == 1 and opened[0][2] == tmp_path / "settings.toml"  # type: ignore[index]


def _all_button_texts(widget: tkinter.Misc) -> list[str]:
    texts: list[str] = []

    def walk(w: tkinter.Misc) -> None:
        for child in w.winfo_children():
            walk(child)
            try:
                texts.append(str(child.cget("text")))
            except (tkinter.TclError, AttributeError, ValueError):
                continue

    walk(widget)
    return texts


def test_card_texts_helper_still_importable() -> None:
    assert callable(card_texts)
