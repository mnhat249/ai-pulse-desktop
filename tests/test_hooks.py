from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

HOOK = Path(__file__).parent.parent / ".claude" / "hooks" / "pre_commit_guard.py"
COMMIT = "git" + " commit -m x"  # tách chuỗi để chính file này không bị hook chặn khi đọc

# `.claude/` không nằm trong repo (xem .gitignore): máy nào không có hook thì bỏ qua các test này.
pytestmark = pytest.mark.skipif(not HOOK.is_file(), reason="không có .claude/hooks trên máy này")


def load_hook() -> ModuleType:
    spec = importlib.util.spec_from_file_location("pre_commit_guard", HOOK)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_hook(command: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    payload = json.dumps({"tool_input": {"command": command}, "cwd": str(cwd)})
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=payload,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def make_repo(path: Path, check_exit: int) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    (path / "scripts").mkdir()
    (path / "scripts" / "check.py").write_text(
        f"import sys\nprint('kiểm tra giả')\nsys.exit({check_exit})\n", encoding="utf-8"
    )
    return path


def test_non_commit_commands_are_never_blocked(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "r", check_exit=1)
    assert run_hook("git status", repo).returncode == 0
    assert run_hook("pytest -q", repo).returncode == 0


def test_commit_is_blocked_when_the_working_tree_check_fails(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "r", check_exit=1)
    result = run_hook(COMMIT, repo)
    assert result.returncode == 2
    assert "CHẶN COMMIT" in result.stderr and "kiểm tra giả" in result.stderr


def test_commit_passes_when_the_check_passes(tmp_path: Path) -> None:
    assert run_hook(COMMIT, make_repo(tmp_path / "r", check_exit=0)).returncode == 0


def test_check_of_the_cwd_tree_is_used_not_another_tree(tmp_path: Path) -> None:
    good = make_repo(tmp_path / "good", check_exit=0)
    bad = make_repo(tmp_path / "bad", check_exit=1)
    assert run_hook(COMMIT, good).returncode == 0
    assert run_hook(COMMIT, bad).returncode == 2


def test_subdirectory_resolves_to_the_repo_root(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "r", check_exit=1)
    sub = repo / "app" / "deep"
    sub.mkdir(parents=True)
    assert run_hook(COMMIT, sub).returncode == 2


def test_missing_check_script_does_not_block(tmp_path: Path) -> None:
    repo = tmp_path / "empty"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    assert run_hook(COMMIT, repo).returncode == 0


def test_garbage_input_does_not_block() -> None:
    result = subprocess.run(
        [sys.executable, str(HOOK)], input="không phải json", capture_output=True, text=True
    )
    assert result.returncode == 0


def test_venv_python_is_preferred_and_falls_back_to_current(tmp_path: Path) -> None:
    hook = load_hook()
    assert hook.venv_python(tmp_path) == sys.executable
    fake = tmp_path / ".venv" / "Scripts" / "python.exe"
    fake.parent.mkdir(parents=True)
    fake.write_text("", encoding="utf-8")
    assert hook.venv_python(tmp_path) == str(fake)


@pytest.mark.parametrize(
    "command",
    ["git commit -m x", "git -c user.name=a commit -m x", "cd x && git commit --amend"],
)
def test_commit_detection_pattern(command: str, tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "r", check_exit=1)
    assert run_hook(command, repo).returncode == 2
