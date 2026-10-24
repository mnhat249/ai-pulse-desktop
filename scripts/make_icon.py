#!/usr/bin/env python3
"""Tạo `packaging/neuralradar.ico` từ icon khay (chạy một lần hoặc khi đổi thiết kế icon)."""

import sys
from pathlib import Path

from app.ui.tray import icon_image

SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
TARGET = Path(__file__).resolve().parent.parent / "packaging" / "neuralradar.ico"

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    TARGET.parent.mkdir(exist_ok=True)
    icon_image().resize((256, 256)).save(TARGET, format="ICO", sizes=SIZES)
    print(f"Đã ghi {TARGET}")
