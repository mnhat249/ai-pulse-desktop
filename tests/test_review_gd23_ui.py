from __future__ import annotations

import socket
import threading
import time
import unicodedata
from typing import Any

import pytest

from app.config import UISettings
from app.storage.ui_queries import ClusterView
from app.ui.notifier import Notifier, ToastPolicy, safe_toast_url, sanitize_toast_text, toast_text
from app.ui.single_instance import Acquire, SingleInstance
from tests.test_backend import Factory, FakeRuntime, start_backend, wait_for
from tests.test_ui_logic import free_port, view


def cluster(**override: Any) -> ClusterView:
    base = view(1)
    return ClusterView(**{**base.__dict__, **override})


# ---- 1. toast: không chèn được lệnh PowerShell / XML ----------------------------------------

EVIL = (
    'Show HN: $(2+3) marker `calc` "x" <b>bold</b> ]]> @" $env:USERNAME ${x}\n@"\nrm -rf',
    "$(Start-Process calc)",
    '"@\nStart-Process calc\n$h=@"',
    "]]></text><actions><action content='x' arguments='file:///c:/windows/calc.exe'/></actions>",
)


@pytest.mark.parametrize("evil", EVIL)
def test_sanitized_text_has_no_powershell_or_xml_metacharacters(evil: str) -> None:
    clean = sanitize_toast_text(evil)
    for char in '$`"<>[]{}@\\\n\r\t&':
        assert char not in clean, f"{char!r} còn trong {clean!r}"
    assert "'" not in clean


def test_sanitize_keeps_vietnamese_and_normalizes_decomposed_text() -> None:
    assert sanitize_toast_text("Công cụ agent mới: 3 tin (HN), 50% nhanh hơn!") == (
        "Công cụ agent mới: 3 tin (HN), 50% nhanh hơn!"
    )
    decomposed = unicodedata.normalize("NFD", "Tóm tắt ngắn gọn")
    assert sanitize_toast_text(decomposed) == "Tóm tắt ngắn gọn"
    assert sanitize_toast_text("it's") == "it’s"


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "file:///c:/windows/system32/calc.exe",
        'https://x.dev/a"onmouseover="x',
        "https://x.dev/$(calc)",
        "https://x.dev/a`b",
        "https://x.dev/a b",
        "https://x.dev/a'b",
        "https://x.dev/<script>",
        "ms-settings:network",
        "",
        None,
    ],
)
def test_unsafe_urls_get_no_action_button(url: str | None) -> None:
    assert safe_toast_url(url) is None


def test_safe_url_is_kept_and_ampersand_is_xml_escaped() -> None:
    assert safe_toast_url("https://github.com/acme/tool") == "https://github.com/acme/tool"
    assert safe_toast_url("https://x.dev/a?b=1&c=2") == "https://x.dev/a?b=1&amp;c=2"


def test_toast_text_is_sanitized_for_title_and_body() -> None:
    evil = cluster(title="Show HN: $(2+3) marker", innovation='a "$(calc)" b', impact="c`d`")
    title, body = toast_text(evil)
    assert title == "Show HN: 2+3 marker" or "$" not in title
    assert "$" not in body and '"' not in body and "`" not in body


def test_notifier_passes_only_sanitized_text_and_safe_url() -> None:
    seen: list[Any] = []

    class FakeToast:
        def __init__(self, app_id: str, title: str, msg: str) -> None:
            self.title, self.msg, self.links = title, msg, []
            seen.append(self)

        def add_actions(self, label: str, launch: str) -> None:
            self.links.append(launch)

        def show(self) -> None:
            pass

    notifier = Notifier(ToastPolicy(UISettings()))
    notifier._factory = FakeToast
    assert notifier.notify(cluster(id=1, title="$(calc)", primary_url="javascript:alert(1)"))
    assert notifier.notify(cluster(id=2, title="ok", primary_url="https://github.com/a/b"))
    assert "$" not in seen[0].title and seen[0].links == []
    assert seen[1].links == ["https://github.com/a/b"]


def test_toast_counts_distinct_source_families_not_raw_sources() -> None:
    policy = ToastPolicy(UISettings(toast_min_importance=101, toast_min_sources=2))
    hf_only = cluster(
        id=1, importance=10, sources=("hf_models", "hf_papers"), labels=("HF",), read=False
    )
    two_families = cluster(
        id=2, importance=10, sources=("github", "hf_models"), labels=("GitHub", "HF"), read=False
    )
    assert not policy.allow(hf_only)
    assert policy.allow(two_families)


# ---- 10. tạm dừng được giữ sau khi luồng nền khởi động lại ---------------------------------


def test_pause_chosen_before_a_restart_is_applied_to_the_new_scheduler() -> None:
    factory = Factory(fail_times=1)
    backend, _ = start_backend(factory, delay=0.3)  # lần dựng đầu thất bại, 0,3s sau mới dựng lại
    backend.pause()  # người dùng bấm tạm dừng trong lúc luồng nền đang khởi động lại
    assert backend.wait_ready(5)
    assert factory.runtimes[0].radar.calls == ["start", "pause"]
    backend.stop()


def test_resume_clears_the_remembered_pause() -> None:
    factory = Factory()
    backend, _ = start_backend(factory)
    assert backend.wait_ready(5)
    backend.pause()
    backend.resume()
    assert backend._paused is False
    assert wait_for(lambda: factory.runtimes[0].radar.calls[-2:] == ["pause", "resume"])
    backend.stop()


# ---- 11. single instance: cổng bị chương trình khác chiếm ------------------------------------


def test_port_held_by_another_program_is_reported_not_silently_ignored() -> None:
    port = free_port()
    foreign = socket.socket()
    foreign.bind(("127.0.0.1", port))
    foreign.listen(1)

    def silent_server() -> None:
        try:
            conn, _ = foreign.accept()
            time.sleep(0.2)
            conn.close()
        except OSError:
            pass

    threading.Thread(target=silent_server, daemon=True).start()
    try:
        assert SingleInstance(lambda: None, port).acquire() is Acquire.PORT_BUSY
    finally:
        foreign.close()


def test_port_held_by_a_closed_listener_is_also_port_busy() -> None:
    port = free_port()
    foreign = socket.socket()
    foreign.bind(("127.0.0.1", port))  # không listen: kết nối bị từ chối
    try:
        assert SingleInstance(lambda: None, port).acquire() is Acquire.PORT_BUSY
    finally:
        foreign.close()


def test_real_running_instance_replies_so_second_one_knows() -> None:
    port, shown = free_port(), []
    first = SingleInstance(lambda: shown.append(1), port)
    assert first.acquire() is Acquire.ACQUIRED
    try:
        assert SingleInstance(lambda: None, port).acquire() is Acquire.ALREADY_RUNNING
        assert wait_for(lambda: shown == [1])
    finally:
        first.close()


# ---- 12. đã đọc / bookmark không kích hoạt toast; backend phát sự kiện "state" ----------------


def test_user_actions_emit_state_events_not_processing_events(tmp_path: Any) -> None:
    from pathlib import Path

    from app.storage.db import make_engine
    from app.storage.writer import Writer
    from tests.helpers_ui import seed_db

    path = Path(tmp_path) / "b.db"
    ids = seed_db(path)

    def make() -> FakeRuntime:
        engine = make_engine(path)
        writer = Writer(engine)
        writer.start()
        return FakeRuntime(writer=writer, engine=engine)

    backend, events = start_backend(Factory(make=make))
    assert backend.wait_ready(5)
    backend.mark_read(ids["hot"])
    backend.set_bookmark(ids["hot"], True)
    kinds = [events.get(timeout=3).kind for _ in range(2)]
    backend.stop()
    assert kinds == ["state", "state"]
