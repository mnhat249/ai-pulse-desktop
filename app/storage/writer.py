from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

logger = logging.getLogger(__name__)

WriteOp = Callable[[AsyncConnection], Awaitable[Any]]


@dataclass
class _Pending:
    op: WriteOp
    future: asyncio.Future[Any]


class _Stop:
    pass


_STOP = _Stop()


class Writer:
    """Nơi duy nhất ghi DB: một task lấy lệnh từ hàng đợi và ghi theo lô trong một giao dịch."""

    def __init__(self, engine: AsyncEngine, batch_size: int = 100) -> None:
        self._engine = engine
        self._batch_size = batch_size
        self._queue: asyncio.Queue[_Pending | _Stop] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="db-writer")

    async def stop(self) -> None:
        """Chờ ghi xong mọi lệnh đã nhận rồi dừng."""
        if self._task is None:
            return
        await self._queue.put(_STOP)
        await self._task
        self._task = None

    async def submit(self, op: WriteOp) -> Any:
        if self._task is None or self._task.done():
            raise RuntimeError("Writer chưa chạy")
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        await self._queue.put(_Pending(op, future))
        return await future

    async def _run(self) -> None:
        stopping = False
        while not stopping:
            first = await self._queue.get()
            if isinstance(first, _Stop):
                return
            batch = [first]
            while len(batch) < self._batch_size:
                try:
                    nxt = self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if isinstance(nxt, _Stop):
                    stopping = True
                    break
                batch.append(nxt)
            await self._execute(batch)

    async def _execute(self, batch: list[_Pending]) -> None:
        try:
            results = await self._run_batch(batch)
        except Exception:
            logger.warning("Lô ghi lỗi, thử ghi từng lệnh riêng", exc_info=True)
            await self._execute_individually(batch)
            return
        for pending, result in zip(batch, results, strict=True):
            if not pending.future.done():
                pending.future.set_result(result)

    async def _run_batch(self, batch: list[_Pending]) -> list[Any]:
        async with self._engine.begin() as conn:
            return [await pending.op(conn) for pending in batch]

    async def _execute_individually(self, batch: list[_Pending]) -> None:
        for pending in batch:
            try:
                async with self._engine.begin() as conn:
                    result = await pending.op(conn)
            except Exception as exc:
                logger.exception("Lệnh ghi lỗi")
                if not pending.future.done():
                    pending.future.set_exception(exc)
            else:
                if not pending.future.done():
                    pending.future.set_result(result)
