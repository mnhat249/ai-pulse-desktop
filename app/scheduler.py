from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.adapters.base import SourceAdapter, SourceError
from app.adapters.github import GitHubAdapter
from app.adapters.hackernews import HackerNewsAdapter
from app.adapters.huggingface import HFModelsAdapter, HFPapersAdapter
from app.config import Settings, get_secret
from app.core.models import RawItem, utcnow
from app.pipeline.process import Processor, ProcessResult
from app.storage.ops import ingest_new_items, record_source_run
from app.storage.writer import Writer

logger = logging.getLogger(__name__)

NewItemsCallback = Callable[[str, list[RawItem]], None]
ProcessedCallback = Callable[[ProcessResult], None]
PROCESS_FIRST_RUN_DELAY_SECONDS = 45
SHUTDOWN_TIMEOUT_SECONDS = 30.0


@dataclass
class SourceState:
    consecutive_failures: int = 0
    suspended_until: datetime | None = None


@dataclass(frozen=True)
class RunOutcome:
    source: str
    ok: bool
    new_items: list[RawItem]
    error: str | None = None
    skipped: bool = False
    warnings: list[str] = field(default_factory=list)


def build_adapters(settings: Settings) -> list[SourceAdapter]:
    return [
        GitHubAdapter(settings.github, token=get_secret("github")),
        HFPapersAdapter(settings.huggingface),
        HFModelsAdapter(settings.huggingface),
        HackerNewsAdapter(settings.hackernews),
    ]


class Radar:
    """Chạy các nguồn: mỗi nguồn một job riêng, lỗi nguồn nào chỉ ảnh hưởng nguồn đó."""

    def __init__(
        self,
        settings: Settings,
        writer: Writer,
        client: httpx.AsyncClient,
        adapters: list[SourceAdapter],
        on_new: NewItemsCallback | None = None,
        processor: Processor | None = None,
        on_processed: ProcessedCallback | None = None,
    ) -> None:
        self._processor = processor
        self._on_processed = on_processed
        self._process_lock = asyncio.Lock()
        self._paused = False
        self._settings = settings
        self._writer = writer
        self._client = client
        self._adapters = adapters
        self._on_new = on_new
        self._states = {a.name: SourceState() for a in adapters}
        self._scheduler: AsyncIOScheduler | None = None
        self._inflight: set[asyncio.Task[Any]] = set()

    async def run_source(self, adapter: SourceAdapter) -> RunOutcome:
        state = self._states[adapter.name]
        started = utcnow()
        if state.suspended_until is not None:
            if started < state.suspended_until:
                logger.info("Nguồn %s đang tạm ngưng đến %s", adapter.name, state.suspended_until)
                return RunOutcome(adapter.name, ok=False, new_items=[], skipped=True)
            state.suspended_until = None
        try:
            items = await adapter.fetch(self._client)
            new_items: list[RawItem] = await self._writer.submit(
                lambda conn: ingest_new_items(conn, items, started)
            )
        except SourceError as exc:
            return await self._failed(adapter.name, state, started, exc.reason)
        except Exception as exc:
            logger.exception("Nguồn %s lỗi không lường trước", adapter.name)
            return await self._failed(adapter.name, state, started, repr(exc))
        state.consecutive_failures = 0
        warnings = list(adapter.warnings)
        note = f"một phần: {'; '.join(warnings)}" if warnings else None
        await self._record(adapter.name, started, True, len(items), note)
        logger.info("Nguồn %s: %d bài, %d mới", adapter.name, len(items), len(new_items))
        if note:
            logger.warning("Nguồn %s chỉ lấy được %s", adapter.name, note)
        if new_items and self._on_new is not None:
            self._notify(adapter.name, new_items)
        return RunOutcome(adapter.name, ok=True, new_items=new_items, warnings=warnings)

    def _notify(self, source: str, items: list[RawItem]) -> None:
        assert self._on_new is not None
        try:
            self._on_new(source, items)
        except Exception:
            logger.exception("Callback tin mới lỗi")

    async def _failed(
        self, source: str, state: SourceState, started: datetime, reason: str
    ) -> RunOutcome:
        state.consecutive_failures += 1
        logger.warning("Nguồn %s lỗi (%d lần liền): %s", source, state.consecutive_failures, reason)
        if state.consecutive_failures >= self._settings.failure_pause_threshold:
            state.suspended_until = utcnow() + timedelta(
                minutes=self._settings.failure_pause_minutes
            )
            state.consecutive_failures = 0
            logger.warning("Tạm ngưng nguồn %s đến %s", source, state.suspended_until)
        await self._record(source, started, False, 0, reason)
        return RunOutcome(source, ok=False, new_items=[], error=reason)

    async def _record(
        self, source: str, started: datetime, ok: bool, count: int, error: str | None
    ) -> None:
        try:
            await self._writer.submit(
                lambda conn: record_source_run(conn, source, started, ok, count, error)
            )
        except Exception:
            logger.exception("Không ghi được source_runs cho %s", source)

    async def run_once(self) -> list[RunOutcome]:
        return list(await asyncio.gather(*(self.run_source(a) for a in self._adapters)))

    async def _job(self, adapter: SourceAdapter) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._inflight.add(task)
        try:
            await self.run_source(adapter)
        finally:
            if task is not None:
                self._inflight.discard(task)

    async def process(self) -> ProcessResult | None:
        """Gán cụm, lọc rác, tóm tắt các bài mới. Mỗi lúc chỉ chạy một vòng; lỗi chỉ được log."""
        if self._processor is None:
            return None
        async with self._process_lock:
            try:
                result = await self._processor.run()
            except Exception:
                logger.exception("Vòng xử lý tin lỗi; thử lại ở chu kỳ sau")
                return None
        if self._on_processed is not None and (result.touched or result.digested):
            try:
                self._on_processed(result)
            except Exception:
                logger.exception("Callback xử lý xong lỗi")
        return result

    async def _process_job(self) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._inflight.add(task)
        try:
            await self.process()
        finally:
            if task is not None:
                self._inflight.discard(task)

    async def run_now(self) -> ProcessResult | None:
        """Quét mọi nguồn ngay rồi xử lý (nút "Chạy ngay" của tray)."""
        await self.run_once()
        return await self.process()

    @property
    def paused(self) -> bool:
        return self._paused

    def pause(self) -> None:
        if self._scheduler is not None:
            self._scheduler.pause()
        self._paused = True

    def resume(self) -> None:
        if self._scheduler is not None:
            self._scheduler.resume()
        self._paused = False

    def start(self) -> None:
        scheduler = AsyncIOScheduler()
        for adapter in self._adapters:
            scheduler.add_job(
                self._job,
                "interval",
                args=[adapter],
                minutes=adapter.interval_minutes,
                id=adapter.name,
                next_run_time=utcnow(),
                max_instances=1,
                coalesce=True,
            )
        if self._processor is not None:
            scheduler.add_job(
                self._process_job,
                "interval",
                minutes=self._settings.ui.process_interval_minutes,
                id="process",
                next_run_time=utcnow() + timedelta(seconds=PROCESS_FIRST_RUN_DELAY_SECONDS),
                max_instances=1,
                coalesce=True,
            )
        scheduler.start()
        self._scheduler = scheduler
        self._paused = False

    async def stop(self, grace_seconds: float = SHUTDOWN_TIMEOUT_SECONDS) -> None:
        """Ngừng lên lịch, chờ các job đang chạy xong (tối đa `grace_seconds`) rồi mới hủy."""
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
        pending = {t for t in self._inflight if not t.done()}
        if not pending:
            return
        logger.info("Chờ %d job đang chạy xong trước khi thoát", len(pending))
        _, still_running = await asyncio.wait(pending, timeout=grace_seconds)
        for task in still_running:
            task.cancel()
        if still_running:
            await asyncio.gather(*still_running, return_exceptions=True)
            logger.warning("Đã hủy %d job quá hạn khi thoát", len(still_running))
