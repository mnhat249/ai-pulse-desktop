"""Tự khởi động cùng Windows bằng shortcut trong thư mục Startup (bật/tắt trong cài đặt)."""

from __future__ import annotations

import logging
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

SHORTCUT_NAME = "NeuralRadar.lnk"
POWERSHELL = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass"]
RUN_TIMEOUT_SECONDS = 30

Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class LaunchCommand:
    target: str
    arguments: str
    working_dir: str


def default_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - lệnh PowerShell dựng từ chuỗi cố định, đã quote
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=RUN_TIMEOUT_SECONDS,
        check=False,
    )


def launch_command() -> LaunchCommand:
    """Lệnh mở app: file .exe khi đã đóng gói, không thì `pythonw -m app.main` (không console)."""
    exe = Path(sys.executable)
    if getattr(sys, "frozen", False):
        return LaunchCommand(str(exe), "", str(exe.parent))
    windowless = exe.with_name("pythonw.exe")
    target = windowless if windowless.is_file() else exe
    return LaunchCommand(str(target), "-m app.main", str(Path.cwd()))


# PowerShell coi cả nháy đơn cong (U+2018, U+2019, U+201A, U+201B) là nháy đơn khi phân tích chuỗi
SINGLE_QUOTES = "'‘’‚‛"


def _ps_quote(value: str) -> str:
    """Chuỗi PowerShell trong nháy đơn: nhân đôi mọi loại nháy đơn, không có nội suy `$`."""
    escaped = "".join(ch * 2 if ch in SINGLE_QUOTES else ch for ch in value)
    return "'" + escaped + "'"


def _startup_dir_expr() -> str:
    return (
        "([Environment]::GetFolderPath('Startup'))"  # ngoặc: nếu không Join-Path tách làm 2 tham số
    )


def create_script(command: LaunchCommand) -> str:
    return "; ".join(
        [
            "$ErrorActionPreference = 'Stop'",
            f"$path = Join-Path {_startup_dir_expr()} {_ps_quote(SHORTCUT_NAME)}",
            "$shell = New-Object -ComObject WScript.Shell",
            "$link = $shell.CreateShortcut($path)",
            f"$link.TargetPath = {_ps_quote(command.target)}",
            f"$link.Arguments = {_ps_quote(command.arguments)}",
            f"$link.WorkingDirectory = {_ps_quote(command.working_dir)}",
            "$link.WindowStyle = 7",
            "$link.Description = 'NeuralRadar'",
            "$link.Save()",
            "Write-Output $path",
        ]
    )


def remove_script() -> str:
    return "; ".join(
        [
            f"$path = Join-Path {_startup_dir_expr()} {_ps_quote(SHORTCUT_NAME)}",
            "if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force }",
            "Write-Output $path",
        ]
    )


def status_script() -> str:
    return "; ".join(
        [
            f"$path = Join-Path {_startup_dir_expr()} {_ps_quote(SHORTCUT_NAME)}",
            "Write-Output (Test-Path -LiteralPath $path)",
        ]
    )


def _run(script: str, runner: Runner) -> subprocess.CompletedProcess[str]:
    return runner([*POWERSHELL, "-Command", script])


def enable(runner: Runner = default_runner, command: LaunchCommand | None = None) -> bool:
    """Tạo shortcut Startup. Trả về False (và log) nếu không tạo được."""
    try:
        result = _run(create_script(command or launch_command()), runner)
    except (OSError, subprocess.SubprocessError):
        logger.exception("Không chạy được PowerShell để tạo shortcut Startup")
        return False
    if result.returncode != 0:
        logger.error("Tạo shortcut Startup lỗi: %s", result.stderr.strip())
    return result.returncode == 0


def disable(runner: Runner = default_runner) -> bool:
    try:
        result = _run(remove_script(), runner)
    except (OSError, subprocess.SubprocessError):
        logger.exception("Không chạy được PowerShell để xóa shortcut Startup")
        return False
    return result.returncode == 0


def is_enabled(runner: Runner = default_runner) -> bool:
    try:
        result = _run(status_script(), runner)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and result.stdout.strip().lower() == "true"


def apply(enabled: bool, runner: Runner = default_runner) -> bool:
    return enable(runner) if enabled else disable(runner)
