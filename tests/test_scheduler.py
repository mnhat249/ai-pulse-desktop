from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.adapters.base import SourceAdapter, SourceError
from app.config import Settings
from app.core.models import RawItem
from app.scheduler import Radar, build_adapters
from app.storage.queries import count_raw_items, source_statuses
from app.storage.writer import Writer

NOW = datetime(2026, 10, 23, tzinfo=UTC)


def raw(n: int, source: str = "fake") -> RawItem:
    return RawItem(
        source=source, source_id=str(n), url=f"https://x.test/{n}", title=f"t{n}", published_at=NOW
    )


class Fake:
    interval_minutes = 5

    def __init__(self, name: str, items: list[RawItem] | None = None, error: str | None = None):
        self.name = name
        self.items = items or []
        self.error = error
        self.calls = 0
        self.warnings: list[str] = []
        self.gate: asyncio.Event | None = None
        self.started = asyncio.Event()

    async def fetch(self, client: httpx.AsyncClient) -> list[RawItem]:
        self.calls += 1
        self.started.set()
        if self.gate is not None:
            await self.gate.wait()
        if self.error == "boom":
            raise RuntimeError("lỗi lạ")
        if self.error:
            raise SourceError(self.name, self.error)
        return self.items


async def make_radar(
    engine: AsyncEngine,
    adapters: list[Fake],
    settings: Settings | None = None,
    on_new: object = None,
) -> tuple[Radar, Writer]:
    writer = Writer(engine)
    writer.start()
    radar = Radar(
        settings or Settings(),
        writer,
        httpx.AsyncClient(),
        [a for a in adapters],  # type: ignore[misc]
        on_new,  # type: ignore[arg-type]
    )
    return radar, writer


async def test_one_failing_source_does_not_stop_the_others(engine: AsyncEngine) -> None:
    good, bad, weird = (
        Fake("good", [raw(1), raw(2)]),
        Fake("bad", error="HTTP 500"),
        Fake("w", error="boom"),
    )
    radar, writer = await make_radar(engine, [good, bad, weird])
    outcomes = {o.source: o for o in await radar.run_once()}
    await writer.stop()
    assert outcomes["good"].ok and len(outcomes["good"].new_items) == 2
    assert not outcomes["bad"].ok and outcomes["bad"].error == "HTTP 500"
    assert not outcomes["w"].ok
    assert await count_raw_items(engine) == 2
    statuses = {s.source: s for s in await source_statuses(engine)}
    assert statuses["good"].last_ok and statuses["good"].last_item_count == 2
    assert not statuses["bad"].last_ok and statuses["bad"].last_error == "HTTP 500"


async def test_second_run_reports_no_new_items_and_callback_only_for_new(
    engine: AsyncEngine,
) -> None:
    seen: list[tuple[str, int]] = []
    fake = Fake("fake", [raw(1)])
    radar, writer = await make_radar(engine, [fake], on_new=lambda s, i: seen.append((s, len(i))))
    first = (await radar.run_once())[0]
    second = (await radar.run_once())[0]
    await writer.stop()
    assert len(first.new_items) == 1 and second.new_items == []
    assert seen == [("fake", 1)]


async def test_callback_error_does_not_break_the_run(engine: AsyncEngine) -> None:
    def explode(source: str, items: list[RawItem]) -> None:
        raise RuntimeError("UI chết")

    radar, writer = await make_radar(engine, [Fake("fake", [raw(1)])], on_new=explode)
    outcome = (await radar.run_once())[0]
    await writer.stop()
    assert outcome.ok


async def test_source_is_paused_after_three_consecutive_failures(engine: AsyncEngine) -> None:
    bad = Fake("bad", error="HTTP 500")
    radar, writer = await make_radar(engine, [bad])
    for _ in range(3):
        await radar.run_once()
    assert bad.calls == 3
    skipped = (await radar.run_once())[0]
    await writer.stop()
    assert skipped.skipped and bad.calls == 3


async def test_source_resumes_after_pause_expires(engine: AsyncEngine) -> None:
    bad = Fake("bad", error="HTTP 500")
    radar, writer = await make_radar(engine, [bad], Settings(failure_pause_minutes=0))
    for _ in range(3):
        await radar.run_once()
    bad.error = None
    bad.items = [raw(1, "bad")]
    outcome = (await radar.run_once())[0]
    await writer.stop()
    assert outcome.ok and not outcome.skipped and bad.calls == 4


async def test_success_resets_failure_counter(engine: AsyncEngine) -> None:
    flaky = Fake("flaky", error="HTTP 500")
    radar, writer = await make_radar(engine, [flaky])
    await radar.run_once()
    await radar.run_once()
    flaky.error = None
    await radar.run_once()
    flaky.error = "HTTP 500"
    await radar.run_once()
    await radar.run_once()
    outcome = (await radar.run_once())[0]
    await writer.stop()
    assert not outcome.skipped and flaky.calls == 6  # chỉ tạm ngưng sau 3 lỗi LIỀN


async def test_recovers_after_network_comes_back(engine: AsyncEngine) -> None:
    fake = Fake("fake", error="lỗi mạng")
    radar, writer = await make_radar(engine, [fake])
    assert not (await radar.run_once())[0].ok
    fake.error = None
    fake.items = [raw(1)]
    recovered = (await radar.run_once())[0]
    await writer.stop()
    assert recovered.ok and len(recovered.new_items) == 1


async def test_start_registers_one_job_per_adapter_and_stop_is_clean(engine: AsyncEngine) -> None:
    fakes = [Fake("a", [raw(1, "a")]), Fake("b", [raw(2, "b")])]
    radar, writer = await make_radar(engine, fakes)
    radar.start()
    assert radar._scheduler is not None
    assert {j.id for j in radar._scheduler.get_jobs()} == {"a", "b"}
    await radar.stop()
    await radar.stop()
    await writer.stop()


async def test_stop_waits_for_running_job_so_its_data_is_not_lost(engine: AsyncEngine) -> None:
    fake = Fake("slow", [raw(1, "slow")])
    fake.gate = asyncio.Event()
    radar, writer = await make_radar(engine, [fake])
    job = asyncio.create_task(radar._job(fake))
    await fake.started.wait()
    stopping = asyncio.create_task(radar.stop())
    await asyncio.sleep(0.05)
    assert not stopping.done(), "stop phải chờ job đang chạy"
    fake.gate.set()
    await stopping
    await job
    await writer.stop()
    assert await count_raw_items(engine) == 1
    assert (await source_statuses(engine))[0].last_ok


async def test_stop_cancels_job_after_timeout_without_counting_it_as_source_failure(
    engine: AsyncEngine,
) -> None:
    fake = Fake("stuck", [raw(1, "stuck")])
    fake.gate = asyncio.Event()
    radar, writer = await make_radar(engine, [fake])
    job = asyncio.create_task(radar._job(fake))
    await fake.started.wait()
    await radar.stop(grace_seconds=0.05)
    assert job.cancelled()
    await writer.stop()
    assert await source_statuses(engine) == []
    assert radar._states["stuck"].consecutive_failures == 0


async def test_partial_result_is_recorded_as_ok_with_a_note(engine: AsyncEngine) -> None:
    fake = Fake("partial", [raw(1, "partial")])
    fake.warnings = ["hết quota, bỏ 8 truy vấn: HTTP 429"]
    radar, writer = await make_radar(engine, [fake])
    outcome = (await radar.run_once())[0]
    await writer.stop()
    assert outcome.ok and outcome.warnings == fake.warnings
    (status,) = await source_statuses(engine)
    assert status.last_ok and status.last_error is not None
    assert status.last_error.startswith("một phần:") and "hết quota" in status.last_error
    assert radar._states["partial"].consecutive_failures == 0


def test_build_adapters_has_the_four_mvp_sources(app_home: Path) -> None:
    names = [a.name for a in build_adapters(Settings())]
    assert names == ["github", "hf_papers", "hf_models", "hackernews"]


def test_fake_matches_protocol() -> None:
    adapter: SourceAdapter = Fake("x")  # type: ignore[assignment]
    assert adapter.interval_minutes == 5


@pytest.mark.parametrize("name", ["github", "hackernews"])
def test_default_intervals_within_plan_range(name: str) -> None:
    by_name = {a.name: a for a in build_adapters(Settings())}
    assert 15 <= by_name[name].interval_minutes <= 30
