from __future__ import annotations

from dataclasses import dataclass

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings
from app.pipeline.process import Processor, build_processor
from app.scheduler import NewItemsCallback, ProcessedCallback, Radar, build_adapters
from app.storage.db import make_engine, migrate
from app.storage.writer import Writer


@dataclass
class Runtime:
    """Mọi thứ của luồng nền: DB, task ghi, HTTP client, scheduler và bộ xử lý tin."""

    settings: Settings
    engine: AsyncEngine
    writer: Writer
    client: httpx.AsyncClient
    radar: Radar
    processor: Processor


async def open_runtime(
    settings: Settings,
    on_new: NewItemsCallback | None = None,
    on_processed: ProcessedCallback | None = None,
) -> Runtime:
    migrate(settings.db_path, settings.backup_dir)
    engine = make_engine(settings.db_path)
    writer = Writer(engine)
    writer.start()
    client = httpx.AsyncClient(
        timeout=settings.request_timeout_seconds,
        follow_redirects=True,
        headers={"User-Agent": "NeuralRadar/0.1 (personal AI news reader)"},
    )
    processor = build_processor(settings, engine, writer)
    radar = Radar(
        settings,
        writer,
        client,
        build_adapters(settings),
        on_new,
        processor=processor,
        on_processed=on_processed,
    )
    return Runtime(settings, engine, writer, client, radar, processor)


async def close_runtime(runtime: Runtime) -> None:
    """Thoát sạch: dừng scheduler, chờ task ghi xong, đóng DB."""
    try:
        await runtime.radar.stop()
    finally:
        try:
            await runtime.client.aclose()
        finally:
            try:
                await runtime.writer.stop()
            finally:
                await runtime.engine.dispose()
