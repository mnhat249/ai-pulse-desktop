"""Đọc và ghi `settings.toml`: chỉ ghi các mục người dùng đổi, giữ nguyên phần còn lại."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

import tomli_w


def read_settings_file(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except FileNotFoundError:
        return {}


def deep_merge(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    """Trộn `updates` vào `base`: bảng con trộn đệ quy, giá trị khác (kể cả danh sách) thay hẳn."""
    merged = dict(base)
    for key, value in updates.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = deep_merge(current, value)
        else:
            merged[key] = value
    return merged


def update_settings_file(path: Path, updates: dict[str, Any]) -> None:
    """Ghi nguyên tử (file tạm rồi đổi tên) để mất điện giữa chừng không làm hỏng cài đặt."""
    merged = deep_merge(read_settings_file(path), updates)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".toml.tmp")
    with temp.open("wb") as handle:
        tomli_w.dump(merged, handle)
    os.replace(temp, path)
