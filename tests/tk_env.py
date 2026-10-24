"""Cửa sổ Tk dùng chung cho các test giao diện (một root duy nhất cho cả phiên test)."""

from __future__ import annotations

import queue
import tkinter
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.config import Settings
from app.storage.ui_queries import ClusterView, open_reader
from app.ui.backend import UIEvent
from app.ui.model import UIModel
from app.ui.widget import FloatingWidget
from tests.helpers_ui import seed_db


class FakeController:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def run_now(self) -> None:
        self.calls.append(("run_now", ()))

    def pause(self) -> None:
        self.calls.append(("pause", ()))

    def resume(self) -> None:
        self.calls.append(("resume", ()))

    def mark_read(self, cluster_id: int, read: bool = True) -> None:
        self.calls.append(("mark_read", (cluster_id, read)))

    def set_bookmark(self, cluster_id: int, bookmarked: bool) -> None:
        self.calls.append(("set_bookmark", (cluster_id, bookmarked)))


class FakeNotifier:
    def __init__(self) -> None:
        self.shown: list[int] = []

    def notify(self, cluster: ClusterView) -> bool:
        self.shown.append(cluster.id)
        return True


class Env:
    def __init__(self, widget: FloatingWidget, path: Path, ids: dict[str, int]) -> None:
        self.widget = widget
        self.path = path
        self.ids = ids
        self.controller = FakeController()
        self.notifier = FakeNotifier()
        self.events: queue.Queue[UIEvent] = queue.Queue()
        self.commands: queue.SimpleQueue[str] = queue.SimpleQueue()
        widget._controller = self.controller
        widget._notifier = self.notifier  # type: ignore[assignment]
        widget._events = self.events
        widget._commands = self.commands

    def reset(self) -> None:
        self.widget._notifier = self.notifier  # type: ignore[assignment]
        self.controller.calls.clear()
        self.notifier.shown.clear()
        self.widget._model.set_filter_label("Tất cả")
        self.widget._model.set_source_label("Mọi nguồn")
        self.widget._model.expanded.clear()
        self.widget._closed = False
        self.widget._tray_ok = False
        self.widget._paused = False
        self.widget.quit_requested = False


@pytest.fixture(scope="session")
def env(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Env]:
    """Một cửa sổ Tk cho cả phiên test: dựng lại Tk root trong cùng tiến trình hay gây lỗi."""
    base = tmp_path_factory.mktemp("widget")
    db = base / "ui.db"
    ids = seed_db(db)
    reader = open_reader(db)
    try:
        widget = FloatingWidget(
            Settings(),
            UIModel(reader),
            FakeController(),
            queue.Queue(),
            queue.SimpleQueue(),
            None,
            base / "ui_state.json",
        )
    except tkinter.TclError:
        reader.close()
        pytest.skip("không có màn hình để dựng Tk")
    yield Env(widget, base / "ui_state.json", ids)
    try:
        widget.destroy()
    except tkinter.TclError:
        pass
    reader.close()


@pytest.fixture
def fresh(env: Env) -> Env:
    env.reset()
    return env


def card_texts(widget: FloatingWidget) -> list[str]:
    texts: list[str] = []

    def walk(w: tkinter.Misc) -> None:
        for child in w.winfo_children():
            walk(child)
            try:
                value = child.cget("text")
            except (tkinter.TclError, AttributeError, ValueError):
                continue
            if isinstance(value, str) and value:
                texts.append(value)

    walk(widget._feed)
    return texts
