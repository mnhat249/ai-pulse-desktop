from __future__ import annotations

from datetime import timedelta

import pytest

from app.ui import theme
from tests.helpers import NOW


def rgb(hex_color: str) -> tuple[int, int, int]:
    return int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)


def test_signal_color_goes_from_cool_to_warm_and_clamps() -> None:
    low, mid, high = theme.signal_color(0), theme.signal_color(50), theme.signal_color(100)
    assert low == "#8FB5B0" and mid == "#E0A100" and high == "#C8341D"
    assert theme.signal_color(-30) == low and theme.signal_color(500) == high
    assert rgb(low)[2] > rgb(high)[2]  # thấp thì xanh (nhiều blue), cao thì đỏ (ít blue)
    assert rgb(low)[2] > rgb(mid)[2] > rgb(high)[2] - 100  # ấm dần: ít xanh dương hơn
    assert rgb(mid)[1] > rgb(high)[1]  # từ hổ phách sang đỏ: giảm xanh lá


def test_signal_fill_is_proportional_with_a_visible_minimum() -> None:
    assert theme.signal_fill(0) == 0.08
    assert theme.signal_fill(50) == 0.5
    assert theme.signal_fill(250) == 1.0


def test_source_colors_are_distinct_per_family_with_a_default() -> None:
    assert theme.source_color("github") != theme.source_color("hackernews")
    assert theme.source_color("hf_models") == theme.source_color("hf_papers")
    assert theme.source_color("nguon-la") == theme.DEFAULT_SOURCE_COLOR


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        (timedelta(seconds=5), "vừa xong"),
        (timedelta(minutes=12), "12 phút trước"),
        (timedelta(hours=5, minutes=30), "5 giờ trước"),
        (timedelta(days=3), "3 ngày trước"),
    ],
)
def test_relative_time_in_vietnamese(delta: timedelta, expected: str) -> None:
    assert theme.relative_time(NOW - delta, NOW) == expected


def test_text_and_background_contrast_is_readable() -> None:
    def luminance(color: str) -> float:
        channels = [c / 255 for c in rgb(color)]
        lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]

    def ratio(a: str, b: str) -> float:
        hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
        return (hi + 0.05) / (lo + 0.05)

    assert ratio(theme.INK, theme.CARD) >= 7
    assert ratio(theme.MUTED, theme.CARD) >= 4.5
    assert ratio(theme.MUTED, theme.BG) >= 4.0
    for source in ("github", "hf_models", "hackernews"):
        assert ratio("#FFFFFF", theme.source_color(source)) >= 4.5  # chữ trắng trên chip
    assert ratio("#FFFFFF", theme.MUTED) >= 4.5  # chip "Chờ tóm tắt"
    assert ratio(theme.INK, theme.SELECTED) >= 7  # mục đang chọn của bộ lọc
