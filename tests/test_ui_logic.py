from __future__ import annotations

import json
import socket
import time
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import UISettings
from app.core.models import utcnow
from app.storage import ui_queries
from app.storage.ops import record_source_run, set_cluster_bookmark, set_cluster_read
from app.storage.ui_queries import ClusterView, open_reader
from app.storage.writer import Writer
from app.ui.model import ALL_SOURCES, UIModel
from app.ui.notifier import Notifier, ToastPolicy, toast_text
from app.ui.single_instance import Acquire, SingleInstance
from app.ui.state import WindowState, load_state, save_state
from tests.helpers import NOW
from tests.helpers_ui import seed_db


@pytest.fixture
def seeded(tmp_path: Path):  # type: ignore[no-untyped-def]
    path = tmp_path / "ui.db"
    ids = seed_db(path)
    reader = open_reader(path)
    yield path, ids, reader
    reader.close()


def test_clusters_sorted_by_importance_and_noise_hidden(seeded) -> None:  # type: ignore[no-untyped-def]
    _, ids, reader = seeded
    views = ui_queries.list_clusters(reader)
    assert [v.id for v in views] == [ids["hot"], ids["plain"], ids["paper"]]


def test_summarized_cluster_shows_vietnamese_title_and_source_badges(seeded) -> None:  # type: ignore[no-untyped-def]
    _, ids, reader = seeded
    hot = ui_queries.get_cluster(reader, ids["hot"])
    assert hot is not None and hot.summarized
    assert hot.title == "Công cụ agent mới" and hot.original_title == "acme/agent"
    assert hot.source_text == "GitHub · HN · HF"
    assert hot.primary_url == "https://github.com/acme/agent" and len(hot.urls) == 3


def test_unsummarized_cluster_falls_back_to_original_title(seeded) -> None:  # type: ignore[no-untyped-def]
    _, ids, reader = seeded
    plain = ui_queries.get_cluster(reader, ids["plain"])
    assert plain is not None and not plain.summarized
    assert plain.title == "Rust 2.0 released" and plain.innovation is None


def test_noise_cluster_is_not_returned_by_id(seeded) -> None:  # type: ignore[no-untyped-def]
    _, ids, reader = seeded
    assert ui_queries.get_cluster(reader, ids["spam"]) is None


def test_filter_by_source(seeded) -> None:  # type: ignore[no-untyped-def]
    _, ids, reader = seeded
    hn = ui_queries.list_clusters(reader, source="hackernews")
    assert {v.id for v in hn} == {ids["hot"], ids["plain"]}
    assert ui_queries.list_sources(reader) == ["github", "hackernews", "hf_models", "hf_papers"]


def test_limit_is_respected(seeded) -> None:  # type: ignore[no-untyped-def]
    _, _, reader = seeded
    assert len(ui_queries.list_clusters(reader, limit=2)) == 2


async def test_read_and_bookmark_state_through_the_single_writer(
    engine: AsyncEngine, tmp_path: Path
) -> None:
    path = Path(engine.url.database or "")
    ids = seed_db_on(path)
    writer = Writer(engine)
    writer.start()
    reader = open_reader(path)
    await writer.submit(lambda c: set_cluster_bookmark(c, ids["plain"], True))
    await writer.submit(lambda c: set_cluster_read(c, ids["plain"], True, utcnow()))
    await writer.submit(lambda c: set_cluster_read(c, ids["hot"], True, utcnow()))
    plain = ui_queries.get_cluster(reader, ids["plain"])
    assert plain is not None and plain.read and plain.bookmarked
    assert {v.id for v in ui_queries.list_clusters(reader, view="unread")} == {ids["paper"]}
    assert [v.id for v in ui_queries.list_clusters(reader, view="bookmarked")] == [ids["plain"]]
    assert ui_queries.count_unread(reader) == 1
    await writer.submit(lambda c: set_cluster_read(c, ids["plain"], False, utcnow()))
    await writer.submit(lambda c: set_cluster_bookmark(c, ids["plain"], False))
    again = ui_queries.get_cluster(reader, ids["plain"])
    assert again is not None and not again.read and not again.bookmarked
    await writer.stop()
    reader.close()


def seed_db_on(path: Path) -> dict[str, int]:
    """Gieo dữ liệu vào DB mà fixture `engine` đã migrate sẵn."""
    import sqlite3

    from tests.helpers_ui import ISO

    conn = sqlite3.connect(path)
    ids: dict[str, int] = {}
    for name, importance, noise in (("hot", 80.0, 0), ("plain", 50.0, 0), ("paper", 30.0, 0)):
        cur = conn.execute(
            "INSERT INTO clusters (first_seen, last_seen, importance, is_noise, primary_url)"
            " VALUES (?, ?, ?, ?, 'https://x.dev')",
            (ISO, ISO, importance, noise),
        )
        ids[name] = int(cur.lastrowid or 0)
        item = conn.execute(
            "INSERT INTO raw_items (source, source_id, url, title, text, published_at, fetched_at,"
            " links) VALUES ('github', ?, 'https://x.dev', ?, '', ?, ?, '[]')",
            (name, name, ISO, ISO),
        )
        conn.execute(
            "INSERT INTO cluster_items (cluster_id, item_id) VALUES (?, ?)",
            (ids[name], item.lastrowid),
        )
    conn.commit()
    conn.close()
    return ids


async def test_source_status_and_last_error(engine: AsyncEngine) -> None:
    path = Path(engine.url.database or "")
    writer = Writer(engine)
    writer.start()
    await writer.submit(lambda c: record_source_run(c, "github", NOW, False, 0, "HTTP 500"))
    await writer.submit(lambda c: record_source_run(c, "github", NOW, True, 7, None))
    await writer.submit(lambda c: record_source_run(c, "hackernews", NOW, False, 0, "timeout"))
    await writer.stop()
    reader = open_reader(path)
    statuses = {s.source: s for s in ui_queries.source_statuses(reader)}
    assert statuses["github"].ok and statuses["github"].item_count == 7
    assert not statuses["hackernews"].ok and statuses["hackernews"].error == "timeout"
    assert ui_queries.last_error(reader, "github") == "HTTP 500"
    assert ui_queries.last_error(reader, "hf_models") is None
    reader.close()


def test_reader_is_query_only(seeded) -> None:  # type: ignore[no-untyped-def]
    import sqlite3

    _, _, reader = seeded
    with pytest.raises(sqlite3.OperationalError):
        reader.execute("DELETE FROM clusters")


def test_model_filters_and_expanded_state(seeded) -> None:  # type: ignore[no-untyped-def]
    _, ids, reader = seeded
    model = UIModel(reader)
    model.set_filter_label("Chưa đọc")
    assert model.view == "unread"
    model.set_source_label("github")
    assert [c.id for c in model.clusters()] == [ids["hot"]]
    model.set_source_label(ALL_SOURCES)
    assert model.source is None and model.source_choices()[0] == ALL_SOURCES
    model.set_filter_label("không có")
    assert model.view == "all"
    assert model.toggle_expanded(5) is True and model.toggle_expanded(5) is False


# ---- trạng thái cửa sổ ----------------------------------------------------------------------


def test_window_state_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "s.json"
    save_state(path, WindowState(x=10, y=20, width=500, height=600, always_on_top=False))
    state = load_state(path)
    assert (state.x, state.y, state.width, state.height, state.always_on_top) == (
        10,
        20,
        500,
        600,
        False,
    )
    assert state.geometry == "500x600+10+20"


def test_window_state_missing_or_corrupt_uses_defaults(tmp_path: Path) -> None:
    assert load_state(tmp_path / "none.json", default_on_top=False).always_on_top is False
    bad = tmp_path / "bad.json"
    bad.write_text("{không phải json", encoding="utf-8")
    assert load_state(bad).width == WindowState().width
    bad.write_text(json.dumps({"width": "abc"}), encoding="utf-8")
    assert load_state(bad).width == WindowState().width


def test_window_state_clamps_absurd_values(tmp_path: Path) -> None:
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"width": 1, "height": 10**9, "x": 10**9}), encoding="utf-8")
    state = load_state(path)
    assert state.width == 320 and state.height == 4000 and state.x == 10000


# ---- toast ----------------------------------------------------------------------------------


def view(cid: int, importance: float = 80.0, sources: int = 1, read: bool = False) -> ClusterView:
    names = ("github", "hackernews", "hf_models", "hf_papers")[:sources]
    return ClusterView(
        id=cid,
        title=f"Tin {cid}",
        original_title="o",
        innovation="Cái mới",
        impact="Để dùng",
        importance=importance,
        sources=names,
        primary_url="https://github.com/a/b",
        urls=(),
        read=read,
        bookmarked=False,
        summarized=True,
        last_seen=NOW,
        labels=tuple(n.upper() for n in names),
    )


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_toast_policy_thresholds() -> None:
    policy = ToastPolicy(UISettings(toast_min_importance=70, toast_min_sources=3))
    assert policy.allow(view(1, importance=75))
    assert not policy.allow(view(2, importance=40, sources=2))
    assert policy.allow(view(3, importance=40, sources=3))


def test_toast_policy_once_per_cluster_and_never_for_read() -> None:
    policy = ToastPolicy(UISettings())
    assert policy.allow(view(1)) and not policy.allow(view(1))
    assert not policy.allow(view(2, read=True))


def test_toast_policy_hourly_cap_then_resets() -> None:
    clock = Clock()
    policy = ToastPolicy(UISettings(toast_max_per_hour=2), clock)
    assert policy.allow(view(1)) and policy.allow(view(2))
    assert not policy.allow(view(3))
    clock.now += 3601
    assert policy.allow(view(3))


def test_toast_text_is_truncated_and_has_sources() -> None:
    long = view(1)
    long = ClusterView(**{**long.__dict__, "title": "T" * 200, "innovation": "x" * 500})
    title, body = toast_text(long)
    assert len(title) == 64 and len(body) <= 200 and body.startswith("GITHUB")


def test_notifier_shows_toast_with_link_and_survives_errors() -> None:
    shown: list[tuple[str, str, str | None]] = []

    class FakeToast:
        def __init__(self, app_id: str, title: str, msg: str) -> None:
            self.title, self.msg, self.link = title, msg, None

        def add_actions(self, label: str, launch: str) -> None:
            self.link = launch

        def show(self) -> None:
            shown.append((self.title, self.msg, self.link))

    notifier = Notifier(ToastPolicy(UISettings()))
    notifier._factory = FakeToast
    assert notifier.notify(view(1)) is True
    assert shown[0][2] == "https://github.com/a/b"

    class Boom(FakeToast):
        def show(self) -> None:
            raise OSError("không có thông báo")

    broken = Notifier(ToastPolicy(UISettings()))
    broken._factory = Boom
    assert broken.notify(view(2)) is False


# ---- chỉ một bản ----------------------------------------------------------------------------


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_second_instance_asks_first_to_show_and_exits() -> None:
    port, shown = free_port(), []
    first = SingleInstance(lambda: shown.append(1), port)
    second = SingleInstance(lambda: shown.append(2), port)
    try:
        assert first.acquire() is Acquire.ACQUIRED
        assert second.acquire() is Acquire.ALREADY_RUNNING
        deadline = time.monotonic() + 3
        while not shown and time.monotonic() < deadline:
            time.sleep(0.02)
        assert shown == [1]
    finally:
        first.close()
        second.close()


def test_port_is_released_after_close() -> None:
    port = free_port()
    first = SingleInstance(lambda: None, port)
    assert first.acquire() is Acquire.ACQUIRED
    first.close()
    again = SingleInstance(lambda: None, port)
    try:
        assert again.acquire() is Acquire.ACQUIRED
    finally:
        again.close()
