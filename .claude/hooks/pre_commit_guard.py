#!/usr/bin/env python3
"""PreToolUse(Bash): chặn `git commit` nếu scripts/check.py không đạt (exit 2 = chặn)."""
import json
import os
import re
import subprocess
import sys


def main() -> int:
    try:
        data = json.load(sys.stdin)
        command = data.get("tool_input", {}).get("command", "")
    except (json.JSONDecodeError, AttributeError):
        return 0
    if not re.search(r"\bgit\s+(-\S+\s+)*commit\b", command):
        return 0
    root = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    proc = subprocess.run(
        [sys.executable, os.path.join(root, "scripts", "check.py")],
        cwd=root, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        sys.stderr.write("CHẶN COMMIT: kiểm tra trước commit không đạt. Sửa rồi commit lại.\n")
        sys.stderr.write(proc.stdout + proc.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
