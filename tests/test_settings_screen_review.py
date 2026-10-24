from __future__ import annotations

import threading
from pathlib import Path

from app.config import Settings
from app.ui.settings_window import SettingsWindow
from tests.tk_env import Env, pump_until


def wait_for_calls(window: SettingsWindow, applied: list[bool], count: int) -> None:
    pump_until(window, lambda: len(applied) >= count and not window._startup_busy)


def open_window(fresh: Env, path: Path, applied: list[bool], result: bool = True) -> SettingsWindow:
    return SettingsWindow(
        fresh.widget,
        Settings(),
        path,
        fresh.widget._fonts,
        apply_startup=lambda enabled: applied.append(enabled) or result,
    )


def test_enable_then_disable_in_the_same_window_removes_the_shortcut(
    fresh: Env, tmp_path: Path
) -> None:
    applied: list[bool] = []
    window = open_window(fresh, tmp_path / "settings.toml", applied)
    try:
        window._startup.set(True)
        assert window.save() is True
        wait_for_calls(window, applied, 1)
        window._startup.set(False)  # đổi ý mà không đóng cửa sổ
        assert window.save() is True
        wait_for_calls(window, applied, 2)
        assert applied == [True, False]  # trước đây lần lưu thứ hai bị coi là "không đổi"
    finally:
        window.destroy()


def test_saving_twice_without_changes_touches_the_shortcut_once(fresh: Env, tmp_path: Path) -> None:
    applied: list[bool] = []
    window = open_window(fresh, tmp_path / "settings.toml", applied)
    try:
        window._startup.set(True)
        window.save()
        wait_for_calls(window, applied, 1)
        window.save()
        for _ in range(10):
            window.update()
        assert applied == [True]
    finally:
        window.destroy()


def open_blocking_window(
    fresh: Env, path: Path, applied: list[bool], release: threading.Event
) -> SettingsWindow:
    def apply(enabled: bool) -> bool:
        release.wait(5)
        applied.append(enabled)
        return True

    return SettingsWindow(fresh.widget, Settings(), path, fresh.widget._fonts, apply_startup=apply)


def test_saving_again_while_the_shortcut_job_runs_does_not_start_a_second_job(
    fresh: Env, tmp_path: Path
) -> None:
    applied: list[bool] = []
    release = threading.Event()
    window = open_blocking_window(fresh, tmp_path / "settings.toml", applied, release)
    try:
        window._startup.set(True)
        window.save()
        window.save()  # PowerShell lần trước chưa xong
        release.set()
        wait_for_calls(window, applied, 1)
        assert applied == [True]
    finally:
        window.destroy()


def test_changing_mind_while_the_shortcut_job_runs_applies_the_latest_value_after_it(
    fresh: Env, tmp_path: Path
) -> None:
    applied: list[bool] = []
    release = threading.Event()
    window = open_blocking_window(fresh, tmp_path / "settings.toml", applied, release)
    try:
        window._startup.set(True)
        window.save()
        window._startup.set(False)
        window.save()
        release.set()
        wait_for_calls(window, applied, 2)
        assert applied == [True, False]
    finally:
        window.destroy()


def test_a_failed_shortcut_change_is_retried_on_the_next_save(fresh: Env, tmp_path: Path) -> None:
    applied: list[bool] = []
    window = open_window(fresh, tmp_path / "settings.toml", applied, result=False)
    try:
        window._startup.set(True)
        window.save()
        wait_for_calls(window, applied, 1)
        window.save()
        wait_for_calls(window, applied, 2)
        assert applied == [True, True]  # lần đầu thất bại nên lần lưu sau thử lại
    finally:
        window.destroy()


def test_corrupt_settings_file_is_reported_in_the_window_not_raised(
    fresh: Env, tmp_path: Path
) -> None:
    path = tmp_path / "settings.toml"
    path.write_text("[github\nenabled = ", encoding="utf-8")  # TOML hỏng
    window = open_window(fresh, path, [])
    try:
        assert window.save() is False
        assert "đang hỏng" in window._message.cget("text")
    finally:
        window.destroy()


def test_closing_the_window_while_waiting_for_the_shortcut_is_harmless(
    fresh: Env, tmp_path: Path
) -> None:
    window = open_window(fresh, tmp_path / "settings.toml", [])
    window._startup.set(True)
    window.save()
    window.destroy()
    window._poll_startup()  # không ném lỗi Tcl dù cửa sổ đã đóng
