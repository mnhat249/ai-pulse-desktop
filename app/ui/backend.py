from __future__ import annotations

import asyncio
import logging
import queue
import threading
from collections.abc import Awaitable, Callable
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import Any

from app.config import Settings
from app.core.models import utcnow
from app.pipeline.process import ProcessResult
from app.runtime import Runtime, close_runtime, open_runtime
from app.storage.ops import set_cluster_bookmark, set_cluster_read

logger = logging.getLogger(__name__)

RESTART_DELAY_SECONDS = 5.0
STOP_TIMEOUT_SECONDS = 45.0

RuntimeFactory = Callable[..., Awaitable[Runtime]]


@dataclass(frozen=True)
class UIEvent:
    """Luồng nền báo cho giao diện; giao diện tự đọc DB để lấy dữ liệu mới."""

    kind: str  # "updated" (tin mới xử lý xong) | "state" (đã đọc/bookmark) | "restarted"
    cluster_ids: tuple[int, ...] = field(default_factory=tuple)


class Backend:
    """Luồng nền: asyncio + scheduler + task ghi DB. Lỗi thì ghi log và tự khởi động lại.

    Giao diện chỉ nói chuyện với lớp này qua các phương thức không chặn và `events`.
    """

    def __init__(
        self,
        settings: Settings,
        events: queue.Queue[UIEvent],
        runtime_factory: RuntimeFactory = open_runtime,
        restart_delay: float = RESTART_DELAY_SECONDS,
    ) -> None:
        self._settings = settings
        self._events = events
        self._factory = runtime_factory
        self._restart_delay = restart_delay
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_async: asyncio.Event | None = None
        self._runtime: Runtime | None = None
        self._ready = threading.Event()
        self._paused = (
            False  # ý muốn của người dùng; áp lại cho scheduler mới sau khi khởi động lại
        )
        self.restarts = 0

    def start(self) -> None:
        self._thread = threading.Thread(target=self._thread_main, name="backend", daemon=True)
        self._thread.start()

    def wait_ready(self, timeout: float) -> bool:
        return self._ready.wait(timeout)

    def stop(self, timeout: float = STOP_TIMEOUT_SECONDS) -> None:
        """Thoát sạch: dừng scheduler, chờ task ghi xong, đóng DB."""
        self._stopping.set()
        loop, stop_async = self._loop, self._stop_async
        if loop is not None and stop_async is not None and not loop.is_closed():
            loop.call_soon_threadsafe(stop_async.set)
        if self._thread is not None:
            self._thread.join(timeout)
            if self._thread.is_alive():
                logger.warning("Luồng nền chưa dừng sau %.0f giây", timeout)

    def _thread_main(self) -> None:
        while not self._stopping.is_set():
            try:
                asyncio.run(self._serve())
            except Exception:
                logger.exception("Luồng nền gặp lỗi, sẽ khởi động lại")
            if self._stopping.wait(self._restart_delay):
                break
            self.restarts += 1
            self._events.put(UIEvent("restarted"))

    async def _serve(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._stop_async = asyncio.Event()
        runtime = await self._factory(self._settings, on_processed=self._on_processed)
        self._runtime = runtime
        try:
            runtime.radar.start()
            if self._paused:
                runtime.radar.pause()
            self._ready.set()
            if self._stopping.is_set():
                self._stop_async.set()
            await self._stop_async.wait()
        finally:
            self._runtime = None
            await close_runtime(runtime)

    def _on_processed(self, result: ProcessResult) -> None:
        ids = tuple(dict.fromkeys([*result.digested, *result.touched]))
        self._events.put(UIEvent("updated", ids))

    def _submit(self, coro_factory: Callable[[Runtime], Awaitable[Any]]) -> Future[Any] | None:
        loop, runtime = self._loop, self._runtime
        if loop is None or runtime is None or loop.is_closed():
            logger.warning("Luồng nền chưa sẵn sàng, bỏ qua yêu cầu")
            return None
        return asyncio.run_coroutine_threadsafe(_as_coroutine(coro_factory(runtime)), loop)

    def run_now(self) -> None:
        self._submit(lambda rt: rt.radar.run_now())

    def pause(self) -> None:
        self._paused = True
        self._submit(_call_sync(lambda rt: rt.radar.pause()))

    def resume(self) -> None:
        self._paused = False
        self._submit(_call_sync(lambda rt: rt.radar.resume()))

    def mark_read(self, cluster_id: int, read: bool = True) -> None:
        now = utcnow()

        async def write(rt: Runtime) -> None:
            await rt.writer.submit(lambda c: set_cluster_read(c, cluster_id, read, now))
            self._events.put(UIEvent("state", (cluster_id,)))

        self._submit(write)

    def set_bookmark(self, cluster_id: int, bookmarked: bool) -> None:
        async def write(rt: Runtime) -> None:
            await rt.writer.submit(lambda c: set_cluster_bookmark(c, cluster_id, bookmarked))
            self._events.put(UIEvent("state", (cluster_id,)))

        self._submit(write)


async def _as_coroutine(awaitable: Awaitable[Any]) -> Any:
    return await awaitable


def _call_sync(fn: Callable[[Runtime], None]) -> Callable[[Runtime], Awaitable[None]]:
    async def run(runtime: Runtime) -> None:
        fn(runtime)

    return run
