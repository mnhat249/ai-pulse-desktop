from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from app import startup
from app.startup import LaunchCommand


class Recorder:
    def __init__(self, returncode: int = 0, stdout: str = "", raises: Exception | None = None):
        self.calls: list[list[str]] = []
        self._result = subprocess.CompletedProcess([], returncode, stdout, "lỗi giả")
        self._raises = raises

    def __call__(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(command)
        if self._raises:
            raise self._raises
        return self._result


def script_of(recorder: Recorder) -> str:
    command = recorder.calls[0]
    assert command[0] == "powershell.exe" and "-NoProfile" in command
    return command[command.index("-Command") + 1]


def test_enable_builds_a_shortcut_in_the_startup_folder() -> None:
    recorder = Recorder()
    command = LaunchCommand(r"C:\Apps\NeuralRadar\NeuralRadar.exe", "", r"C:\Apps\NeuralRadar")
    assert startup.enable(recorder, command) is True
    script = script_of(recorder)
    assert "Join-Path ([Environment]::GetFolderPath('Startup')) 'NeuralRadar.lnk'" in script
    assert r"TargetPath = 'C:\Apps\NeuralRadar\NeuralRadar.exe'" in script
    assert r"WorkingDirectory = 'C:\Apps\NeuralRadar'" in script
    assert "WindowStyle = 7" in script  # chạy thu nhỏ, không hiện cửa sổ


def test_paths_with_quotes_or_dollar_signs_cannot_inject_powershell() -> None:
    nasty = LaunchCommand(r"C:\It's $(calc)\app.exe", "-m app.main'; calc; '", r"C:\a`b")
    script = startup.create_script(nasty)
    assert r"'C:\It''s $(calc)\app.exe'" in script  # nháy đơn được nhân đôi, `$()` không nội suy
    assert "-m app.main''; calc; ''" in script  # không thoát được khỏi chuỗi
    assert script.count("calc") == 2  # chỉ nằm trong các chuỗi đã quote (đường dẫn, đối số)


def test_disable_and_status_scripts() -> None:
    off = Recorder()
    assert startup.disable(off) is True
    assert "Remove-Item" in script_of(off) and "NeuralRadar.lnk" in script_of(off)
    assert startup.is_enabled(Recorder(stdout="True\r\n")) is True
    assert startup.is_enabled(Recorder(stdout="False\r\n")) is False
    assert startup.is_enabled(Recorder(returncode=1, stdout="True")) is False


@pytest.mark.parametrize(
    "error", [OSError("không có powershell"), subprocess.TimeoutExpired("x", 1)]
)
def test_failures_are_reported_as_false_not_raised(error: Exception) -> None:
    assert startup.enable(Recorder(raises=error), LaunchCommand("a", "", "b")) is False
    assert startup.disable(Recorder(raises=error)) is False
    assert startup.is_enabled(Recorder(raises=error)) is False


def test_nonzero_exit_means_not_enabled() -> None:
    assert startup.enable(Recorder(returncode=1), LaunchCommand("a", "", "b")) is False


def test_apply_routes_to_enable_or_disable() -> None:
    on, off = Recorder(), Recorder()
    startup.apply(True, on)
    startup.apply(False, off)
    assert "CreateShortcut" in script_of(on) and "Remove-Item" in script_of(off)


def test_launch_command_for_source_run_uses_windowless_python(tmp_path: Path) -> None:
    command = startup.launch_command()
    assert command.arguments == "-m app.main" and Path(command.target).name.lower().startswith(
        "python"
    )
    assert Path(command.working_dir).is_dir()


def test_launch_command_for_frozen_app_is_the_exe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    exe = tmp_path / "NeuralRadar.exe"
    exe.write_bytes(b"")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    command = startup.launch_command()
    assert command == LaunchCommand(str(exe), "", str(tmp_path))
