#!/usr/bin/env python3
"""Đóng gói NeuralRadar thành thư mục `dist/NeuralRadar/` (có `NeuralRadar.exe`, không console)."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "packaging" / "neuralradar.spec"
ICON = ROOT / "packaging" / "neuralradar.ico"


def main() -> int:
    if not ICON.is_file():
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "make_icon.py")], cwd=ROOT, check=True
        )
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", str(SPEC)]
    return subprocess.run(command, cwd=ROOT, check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
