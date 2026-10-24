from __future__ import annotations

import queue
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from app.config import Settings
from app.pipeline.process import ProcessResult
from app.storage.db import make_engine
from app.storage.ui_queries import get_cluster, open_reader
from app.storage.writer import Writer
from app.ui.backend import Backend, UIEvent
from tests.helpers_ui import seed_db


class FakeRadar:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.fail_start = False

    def start(self) -> None:
        if self.fail_start:
            raise RuntimeError("scheduler chết")
        self.calls.append("start")

    async def run_now(self) -> None:
        self.calls.append("run_now")

    def pause(self) -> None:
        self.calls.append("pause")

    def resume(self) -> None:
        self.calls.append("resume")

    async def stop(self) -> None:
        self.calls.append("stop")


class FakeClient:
    async def aclose(self) -> None:
        return None


class FakeEngine:
    async def dispose(self) -> None:
        return None


class FakeWriter:
    async def stop(self) -> None:
        return None


class FakeRuntime:
    def __init__(self, writer: Any = None, engine: Any = None) -> None:
        self.radar = FakeRadar()
        self.client = FakeClient()
        self.writer = writer or FakeWriter()
        self.engine = engine or FakeEngine()


class Factory:
    def __init__(self, fail_times: int = 0, make: Callable[[], FakeRuntime] = FakeRuntime) -> None:
        self.fail_times = fail_times
        self.calls = 0
        self.runtimes: list[FakeRuntime] = []
        self.on_processed: Callable[[ProcessResult], None] | None = None
        self._make = make

    async def __call__(
        self, settings: Settings, on_new: object = None, on_processed: Any = None
    ) -> Any:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("không mở được DB")
        self.on_processed = on_processed
        runtime = self._make()
        self.runtimes.append(runtime)
        return runtime


def wait_for(condition: Callable[[], bool], timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False


def start_backend(factory: Factory, delay: float = 0.01) -> tuple[Backend, queue.Queue[UIEvent]]:
    events: queue.Queue[UIEvent] = queue.Queue()
    backend = Backend(Settings(), events, factory, restart_delay=delay)  # type: ignore[arg-type]
    backend.start()
    return backend, events


def test_start_runs_scheduler_and_stop_shuts_down_cleanly() -> None:
    factory = Factory()
    backend, _ = start_backend(factory)
    assert backend.wait_ready(5)
    assert factory.runtimes[0].radar.calls == ["start"]
    backend.stop()
    assert factory.runtimes[0].radar.calls[-1] == "stop"
    assert backend._thread is not None and not backend._thread.is_alive()


def test_processed_result_becomes_ui_event_with_unique_ids() -> None:
    factory = Factory()
    backend, events = start_backend(factory)
    assert backend.wait_ready(5) and factory.on_processed is not None
    factory.on_processed(ProcessResult(clustered=3, touched=[1, 2, 3], digested=[3, 1]))
    event = events.get(timeout=2)
    assert event.kind == "updated" and event.cluster_ids == (3, 1, 2)
    backend.stop()


def test_backend_restarts_after_a_crash_and_tells_the_ui() -> None:
    factory = Factory(fail_times=2)
    backend, events = start_backend(factory)
    assert backend.wait_ready(5)
    assert factory.calls == 3 and backend.restarts == 2
    kinds = [events.get(timeout=2).kind for _ in range(2)]
    assert kinds == ["restarted", "restarted"]
    backend.stop()


def test_crash_after_startup_also_restarts() -> None:
    def make() -> FakeRuntime:
        runtime = FakeRuntime()
        runtime.radar.fail_start = len(factory.runtimes) == 0  # lần đầu: scheduler chết
        return runtime

    factory = Factory(make=make)
    backend, events = start_backend(factory)
    assert backend.wait_ready(5)
    assert len(factory.runtimes) == 2 and backend.restarts == 1
    assert factory.runtimes[0].radar.calls == ["stop"]  # bản hỏng vẫn được đóng sạch
    assert events.get(timeout=2).kind == "restarted"
    backend.stop()


def test_stop_during_crash_loop_does_not_hang() -> None:
    factory = Factory(fail_times=10**6)
    backend, _ = start_backend(factory, delay=0.05)
    time.sleep(0.15)
    started = time.monotonic()
    backend.stop(timeout=3)
    assert time.monotonic() - started < 2
    assert backend._thread is not None and not backend._thread.is_alive()


def test_commands_reach_the_scheduler() -> None:
    factory = Factory()
    backend, _ = start_backend(factory)
    assert backend.wait_ready(5)
    backend.run_now()
    backend.pause()
    backend.resume()
    radar = factory.runtimes[0].radar
    assert wait_for(lambda: radar.calls[1:] == ["run_now", "pause", "resume"])
    backend.stop()


def test_commands_before_ready_are_ignored_not_crashing() -> None:
    events: queue.Queue[UIEvent] = queue.Queue()
    backend = Backend(Settings(), events, Factory())  # type: ignore[arg-type]
    backend.run_now()
    backend.pause()
    backend.mark_read(1)
    backend.set_bookmark(1, True)
    assert events.empty()


def test_read_and_bookmark_are_written_through_the_writer_and_announced(tmp_path: Path) -> None:
    path = tmp_path / "b.db"
    ids = seed_db(path)

    def make() -> FakeRuntime:
        engine = make_engine(path)
        writer = Writer(engine)
        writer.start()
        return FakeRuntime(writer=writer, engine=engine)

    factory = Factory(make=make)
    backend, events = start_backend(factory)
    assert backend.wait_ready(5)
    backend.mark_read(ids["plain"])
    backend.set_bookmark(ids["plain"], True)
    assert events.get(timeout=3).cluster_ids == (ids["plain"],)
    assert events.get(timeout=3).cluster_ids == (ids["plain"],)
    backend.stop()
    reader = open_reader(path)
    view = get_cluster(reader, ids["plain"])
    reader.close()
    assert view is not None and view.read and view.bookmarked
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT COUNT(*) FROM user_state").fetchone()[0] == 1
    conn.close()


@pytest.mark.parametrize("method", ["run_now", "pause", "resume"])
def test_methods_exist_on_the_controller_protocol(method: str) -> None:
    assert callable(getattr(Backend, method))
