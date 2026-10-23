#!/usr/bin/env python3
"""Chạy toàn bộ kiểm tra chất lượng. Exit 0 = đạt, khác 0 = không đạt."""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECRET_PATTERNS = [
    r"AIza[0-9A-Za-z_\-]{35}",
    r"ghp_[0-9A-Za-z]{36}",
    r"github_pat_[0-9A-Za-z_]{20,}",
    r"sk-[A-Za-z0-9]{32,}",
    r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----",
    r"""(?i)(api_key|secret|token|password)\s*=\s*['"][^'"\s]{16,}['"]""",
]
FORBIDDEN_NAMES = {".env"}
FORBIDDEN_SUFFIXES = (".db", ".sqlite3")


def run(name: str, module: str, args: list[str]) -> bool:
    if importlib.util.find_spec(module) is None:
        print(f"[FAIL] {name}: chưa cài '{module}'. Chạy: pip install -r requirements-dev.txt")
        return False
    proc = subprocess.run(
        [sys.executable, "-m", module, *args], cwd=ROOT, capture_output=True, text=True
    )
    if name == "pytest" and proc.returncode == 5:  # chưa có test nào
        print("[WARN] pytest: chưa có test nào")
        return True
    if proc.returncode != 0:
        print(f"[FAIL] {name}\n{proc.stdout}{proc.stderr}")
        return False
    print(f"[ OK ] {name}")
    return True


def staged_files() -> list[Path]:
    proc = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        cwd=ROOT, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return []
    return [ROOT / line for line in proc.stdout.splitlines() if line.strip()]


def scan_secrets() -> bool:
    ok = True
    for path in staged_files():
        if path.name in FORBIDDEN_NAMES or path.name.endswith(FORBIDDEN_SUFFIXES):
            print(f"[FAIL] secrets: không được commit file '{path.name}'")
            ok = False
            continue
        if path.name == ".env.example" or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for pattern in SECRET_PATTERNS:
            if re.search(pattern, text):
                print(f"[FAIL] secrets: nghi có khóa/bí mật trong {path.relative_to(ROOT)}")
                ok = False
                break
    if ok:
        print("[ OK ] secrets")
    return ok


def main() -> int:
    results = [
        run("ruff format", "ruff", ["format", "--check", "."]),
        run("ruff lint", "ruff", ["check", "."]),
    ]
    if (ROOT / "src").exists():
        results.append(run("mypy", "mypy", ["src"]))
    results.append(run("pytest", "pytest", ["-q"]))
    results.append(scan_secrets())
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
