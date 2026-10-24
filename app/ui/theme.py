"""Màu, chữ và các hàm trình bày của widget: "hải đồ" sáng, dải tín hiệu theo điểm quan trọng."""

from __future__ import annotations

import tkinter.font as tkfont
from datetime import datetime

from app.core.models import utcnow

BG = "#E6ECE7"  # giấy hải đồ
CARD = "#F6F8F4"
INK = "#112A33"
MUTED = "#5C7479"
SELECTED = "#A9CFC8"  # mục đang chọn của bộ lọc
TRACK = "#CBD6D1"  # rãnh của dải tín hiệu
BORDER = "#BCCAC4"
ERROR = "#B3261E"

SIGNAL_LOW = (0x8F, 0xB5, 0xB0)  # xanh biển
SIGNAL_MID = (0xE0, 0xA1, 0x00)  # hổ phách
SIGNAL_HIGH = (0xC8, 0x34, 0x1D)  # phao đỏ

SOURCE_COLORS = {
    "github": "#3B5B7A",
    "hf_models": "#8A5F12",
    "hf_papers": "#8A5F12",
    "hackernews": "#B5481B",
}
DEFAULT_SOURCE_COLOR = "#4F6B6B"

DISPLAY_FONTS = ("Bahnschrift SemiBold", "Bahnschrift", "Segoe UI Semibold")
BODY_FONTS = ("Segoe UI", "Arial")


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return (
        round(a[0] + (b[0] - a[0]) * t),
        round(a[1] + (b[1] - a[1]) * t),
        round(a[2] + (b[2] - a[2]) * t),
    )


def signal_color(score: float) -> str:
    """Màu dải tín hiệu: điểm càng cao càng ấm (xanh biển -> hổ phách -> đỏ phao)."""
    t = max(0.0, min(100.0, score)) / 100
    r, g, b = (
        _mix(SIGNAL_LOW, SIGNAL_MID, t * 2)
        if t < 0.5
        else _mix(SIGNAL_MID, SIGNAL_HIGH, (t - 0.5) * 2)
    )
    return f"#{r:02X}{g:02X}{b:02X}"


def signal_fill(score: float) -> float:
    """Tỉ lệ chiều cao dải được lấp đầy; điểm thấp vẫn thấy một vạch nhỏ."""
    return max(0.08, min(1.0, score / 100))


def source_color(source: str) -> str:
    return SOURCE_COLORS.get(source, DEFAULT_SOURCE_COLOR)


def relative_time(moment: datetime, now: datetime | None = None) -> str:
    seconds = ((now or utcnow()) - moment).total_seconds()
    if seconds < 60:
        return "vừa xong"
    if seconds < 3600:
        return f"{int(seconds // 60)} phút trước"
    if seconds < 86400:
        return f"{int(seconds // 3600)} giờ trước"
    return f"{int(seconds // 86400)} ngày trước"


def pick_family(candidates: tuple[str, ...], fallback: str = "TkDefaultFont") -> str:
    """Họ chữ đầu tiên có trên máy này."""
    available = set(tkfont.families())
    for name in candidates:
        if name in available:
            return name
    return fallback
