from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any, Protocol, TypeVar

import httpx
from tenacity import (
    AsyncRetrying,
    RetryCallState,
    retry_if_exception_type,
    stop_after_attempt,
)

from app.core.models import RawItem, utcnow

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

RETRIES = 3  # thử lại tối đa 3 lần (tổng 4 lần gọi), giãn cách 1s, 4s, 16s
MAX_ATTEMPTS = RETRIES + 1
TIMEOUT_SECONDS = 20.0
MAX_RETRY_AFTER_SECONDS = 60.0  # chờ lâu hơn mức này thì bỏ lượt, đợi chu kỳ sau

Sleep = Callable[[float], Awaitable[None]]
_SLEEP: Sleep = asyncio.sleep


async def _sleep(seconds: float) -> None:
    await _SLEEP(seconds)


class SourceError(Exception):
    """Một nguồn lấy tin thất bại. Chỉ nguồn đó dừng, app vẫn chạy."""

    def __init__(self, source: str, reason: str) -> None:
        super().__init__(f"{source}: {reason}")
        self.source = source
        self.reason = reason


class RateLimited(SourceError):
    """Nguồn báo hết quota và bắt chờ quá lâu; không nên gọi tiếp trong lượt này."""

    def __init__(self, source: str, reason: str, retry_after: float) -> None:
        super().__init__(source, reason)
        self.retry_after = retry_after


class SourceAdapter(Protocol):
    name: str
    interval_minutes: int
    warnings: list[str]
    """Cảnh báo của lần `fetch` gần nhất khi chỉ lấy được một phần; rỗng nếu lấy đủ."""

    async def fetch(self, client: httpx.AsyncClient) -> list[RawItem]:
        """Lỗi thì ném SourceError, không bao giờ làm sập app."""
        ...


class _Retryable(Exception):
    def __init__(self, reason: str, retry_after: float | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retry_after = retry_after


def parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        return max(0.0, (parsedate_to_datetime(value) - utcnow()).total_seconds())
    except (TypeError, ValueError):
        return None


def _rate_limit_wait(response: httpx.Response) -> float | None:
    """GitHub báo hết quota bằng 403 + x-ratelimit-remaining: 0 và x-ratelimit-reset."""
    explicit = parse_retry_after(response.headers.get("retry-after"))
    if explicit is not None:
        return explicit
    reset = response.headers.get("x-ratelimit-reset")
    if response.headers.get("x-ratelimit-remaining") == "0" and reset and reset.isdigit():
        return max(0.0, int(reset) - utcnow().timestamp())
    return None


def _wait_seconds(state: RetryCallState) -> float:
    exc = state.outcome.exception() if state.outcome else None
    if isinstance(exc, _Retryable) and exc.retry_after is not None:
        return exc.retry_after
    return float(4 ** (state.attempt_number - 1))


async def request(
    client: httpx.AsyncClient,
    source: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """GET có timeout 20s và thử lại 3 lần (1s, 4s, 16s); 429 đợi đúng Retry-After.

    Phải chờ quá 60s (ví dụ GitHub hết quota theo giờ) thì ném `RateLimited` ngay, không ngủ.
    Trả về cả 304 để adapter dùng ETag. Lỗi 4xx khác không thử lại.
    """

    async def attempt() -> httpx.Response:
        try:
            response = await client.get(
                url, params=params, headers=headers, timeout=TIMEOUT_SECONDS
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise _Retryable(f"lỗi mạng: {exc!r}") from exc
        status = response.status_code
        wait = _rate_limit_wait(response)
        if status == 429 or (status == 403 and wait is not None):
            reason = f"HTTP {status} (giới hạn tốc độ)"
            if wait is not None and wait > MAX_RETRY_AFTER_SECONDS:
                raise RateLimited(source, reason, wait)
            raise _Retryable(reason, wait)
        if status >= 500:
            raise _Retryable(f"HTTP {status}")
        if status >= 400:
            raise SourceError(source, f"HTTP {status}")
        return response

    retrying = AsyncRetrying(
        stop=stop_after_attempt(MAX_ATTEMPTS),
        wait=_wait_seconds,
        retry=retry_if_exception_type(_Retryable),
        sleep=_sleep,
        reraise=True,
    )
    try:
        return await retrying(attempt)
    except _Retryable as exc:
        logger.warning("Nguồn %s lỗi sau %d lần thử: %s", source, MAX_ATTEMPTS, exc.reason)
        raise SourceError(source, exc.reason) from exc


async def collect(
    source: str,
    queries: Sequence[str],
    search: Callable[[str], Awaitable[list[_T]]],
    warnings: list[str],
) -> list[_T]:
    """Chạy lần lượt các truy vấn; truy vấn lỗi thành cảnh báo.

    Chỉ ném lỗi khi không truy vấn nào xong.

    Gặp `RateLimited` thì bỏ các truy vấn còn lại của lượt này.
    """
    results: list[_T] = []
    succeeded = 0
    first_error: SourceError | None = None
    for index, query in enumerate(queries):
        try:
            results.extend(await search(query))
            succeeded += 1
        except RateLimited as exc:
            first_error = first_error or exc
            skipped = len(queries) - index
            warnings.append(f"hết quota, bỏ {skipped} truy vấn: {exc.reason}")
            break
        except SourceError as exc:
            first_error = first_error or exc
            warnings.append(f"'{query}': {exc.reason}")
            logger.warning("Nguồn %s, truy vấn '%s' lỗi: %s", source, query, exc.reason)
    if succeeded == 0 and first_error is not None:
        raise first_error
    return results


def parse_items(source: str, raw: Any, build: Callable[[Any], RawItem]) -> list[RawItem]:
    """API đổi định dạng thì ném SourceError rõ tên nguồn, các nguồn khác chạy bình thường."""
    try:
        return [build(entry) for entry in raw]
    except (KeyError, TypeError, ValueError, AttributeError, IndexError) as exc:
        raise SourceError(source, f"định dạng dữ liệu đã đổi: {exc!r}") from exc


def parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def parse_json(source: str, response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise SourceError(source, "phản hồi không phải JSON") from exc
