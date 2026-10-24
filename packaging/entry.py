"""Điểm vào của bản đóng gói (PyInstaller). Chạy từ mã nguồn thì dùng `python -m app.main`."""

import sys

from app.main import main

if __name__ == "__main__":
    sys.exit(main())
