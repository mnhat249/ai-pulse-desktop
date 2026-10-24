"""Thông tin trình bày và xếp hạng của từng nguồn, để thêm nguồn mới không phải sửa pipeline/ui.

Mỗi adapter tự `register(...)` khi được nạp; pipeline và giao diện chỉ hỏi `info(tên_nguồn)`.
Nguồn chưa đăng ký dùng giá trị mặc định (nhãn = tên nguồn, không có độ nóng).
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_COLOR = "#4F6B6B"
DEFAULT_RANK = 50


@dataclass(frozen=True)
class SourceInfo:
    name: str
    label: str  # chữ trên chip
    color: str = DEFAULT_COLOR
    rank: int = DEFAULT_RANK  # chọn link chính của cụm: số nhỏ hơn được ưu tiên
    heat_metric: str | None = None  # chỉ số đo "độ nóng" của bài (cột metric_snapshots.metric)


_REGISTRY: dict[str, SourceInfo] = {}
_PREFIXES: dict[str, SourceInfo] = {}
_loaded = False


def register(info: SourceInfo, *, prefix: bool = False) -> None:
    """Đăng ký theo tên chính xác, hoặc (prefix=True) cho mọi nguồn có tên bắt đầu bằng nó."""
    (_PREFIXES if prefix else _REGISTRY)[info.name] = info


def _ensure_loaded() -> None:
    """Nạp các adapter có sẵn để chúng tự đăng ký (tránh import vòng nên làm trễ)."""
    global _loaded
    if not _loaded:
        _loaded = True
        import app.adapters  # noqa: F401


def info(source: str) -> SourceInfo:
    _ensure_loaded()
    if source in _REGISTRY:
        return _REGISTRY[source]
    matches = [p for p in _PREFIXES if source.startswith(p)]
    if matches:
        return _PREFIXES[max(matches, key=len)]
    return SourceInfo(name=source, label=source)
