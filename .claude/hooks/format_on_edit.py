#!/usr/bin/env python3
"""PostToolUse: tự format + lint file .py vừa sửa. Không bao giờ chặn."""
import importlib.util
import json
import subprocess
import sys


def main() -> int:
    try:
        data = json.load(sys.stdin)
        path = data.get("tool_input", {}).get("file_path", "")
    except (json.JSONDecodeError, AttributeError):
        return 0
    if not path.endswith(".py") or importlib.util.find_spec("ruff") is None:
        return 0
    subprocess.run([sys.executable, "-m", "ruff", "format", path], capture_output=True)
    subprocess.run([sys.executable, "-m", "ruff", "check", "--fix", "--quiet", path],
                   capture_output=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
