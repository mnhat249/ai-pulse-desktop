from __future__ import annotations

import argparse
import asyncio
import io
import logging
import signal
import sys
from collections.abc import Callable, Coroutine, Sequence
from pathlib import Path
from typing import Any

from app.config import Settings, load_settings
from app.core.models import RawItem
from app.logging_setup import setup_logging
from app.pipeline.pairs import export_pairs
from app.pipeline.process import ProcessResult
from app.runtime import close_runtime, open_runtime
from app.storage.db import make_engine, migrate
from app.storage.queries import count_raw_items, source_statuses

logger = logging.getLogger(__name__)


def print_new(source: str, items: list[RawItem]) -> None:
    for item in items:
        sys.stdout.write(f"[{source}] {item.title}\n    {item.url}\n")
    sys.stdout.flush()


def describe_status(ok: bool, error: str | None) -> str:
    if not ok:
        return f"LỖI: {error}"
    return f"ok ({error})" if error else "ok"


def describe_result(result: ProcessResult | None) -> str:
    if result is None:
        return "Xử lý tin: lỗi, xem log"
    return (
        f"Xử lý tin: {result.clustered} bài mới vào cụm, {len(result.touched)} cụm đổi, "
        f"{len(result.digested)} cụm được tóm tắt"
    )


async def run_once(settings: Settings) -> int:
    runtime = await open_runtime(settings, on_new=print_new)
    try:
        outcomes = await runtime.radar.run_once()
        result = await runtime.radar.process()
    finally:
        await close_runtime(runtime)
    for o in outcomes:
        if not o.ok:
            state = "tạm ngưng" if o.skipped else f"LỖI: {o.error}"
        else:
            state = f"ok (một phần: {'; '.join(o.warnings)})" if o.warnings else "ok"
        sys.stdout.write(f"{o.source}: {state}, {len(o.new_items)} bài mới\n")
    sys.stdout.write(describe_result(result) + "\n")
    return 0 if any(o.ok for o in outcomes) else 1


async def process(settings: Settings) -> int:
    runtime = await open_runtime(settings)
    try:
        result = await runtime.radar.process()
    finally:
        await close_runtime(runtime)
    sys.stdout.write(describe_result(result) + "\n")
    return 0 if result is not None else 1


async def serve(settings: Settings) -> int:
    runtime = await open_runtime(settings, on_new=print_new)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows không hỗ trợ add_signal_handler
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))
    runtime.radar.start()
    logger.info("NeuralRadar đang chạy ngầm; nhấn Ctrl+C để dừng")
    try:
        await stop.wait()
    finally:
        await close_runtime(runtime)
    return 0


async def status(settings: Settings) -> int:
    migrate(settings.db_path, settings.backup_dir)
    engine = make_engine(settings.db_path)
    try:
        sys.stdout.write(f"Số bài đã lưu: {await count_raw_items(engine)}\n")
        for s in await source_statuses(engine):
            state = describe_status(s.last_ok, s.last_error)
            sys.stdout.write(f"{s.source}: {state} lúc {s.last_run:%Y-%m-%d %H:%M} UTC\n")
    finally:
        await engine.dispose()
    return 0


def use_utf8_console() -> None:
    """Console Windows hay dùng cp1252 nên không in được tiếng Việt."""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv: Sequence[str] | None = None) -> int:
    use_utf8_console()
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    parser.add_argument(
        "command", choices=["run-once", "process", "serve", "status", "export-pairs"]
    )
    parser.add_argument(
        "--out", type=Path, default=Path("pairs.csv"), help="export-pairs: file CSV"
    )
    parser.add_argument("--count", type=int, default=200, help="export-pairs: số cặp")
    args = parser.parse_args(argv)
    settings = load_settings()
    setup_logging(settings.log_dir)
    handlers: dict[str, Callable[[Settings], Coroutine[Any, Any, int]]] = {
        "run-once": run_once,
        "process": process,
        "serve": serve,
        "status": status,
    }
    if args.command == "export-pairs":
        return asyncio.run(export_pairs(settings, args.out, args.count))
    return asyncio.run(handlers[args.command](settings))


if __name__ == "__main__":
    sys.exit(main())
