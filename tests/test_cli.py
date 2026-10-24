from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from typing import Any

import pytest
import respx

from app import cli
from app.adapters import base

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(_seconds: float) -> None:
        return None

    monkeypatch.setattr(base, "_SLEEP", fake)


def mock_all(router: respx.MockRouter, *, hn_status: int = 200) -> None:
    router.get("https://api.github.com/search/repositories").respond(
        200, json=fixture("github_search.json")
    )
    router.get("https://huggingface.co/api/daily_papers").respond(
        200, json=fixture("hf_daily_papers.json")
    )
    router.get("https://huggingface.co/api/models").respond(200, json=fixture("hf_models.json"))
    router.get("https://hn.algolia.com/api/v1/search_by_date").respond(
        hn_status, json=fixture("hn_search.json")
    )


def test_run_once_prints_summary_and_stores_items(capsys: pytest.CaptureFixture[str]) -> None:
    with respx.mock() as router:
        mock_all(router)
        assert cli.main(["run-once"]) == 0
    out = capsys.readouterr().out
    assert "github: ok" in out and "hf_papers: ok" in out and "hackernews: ok" in out
    assert cli.main(["status"]) == 0
    status = capsys.readouterr().out
    assert "Số bài đã lưu:" in status and "github: ok" in status


def test_run_once_second_time_reports_zero_new(capsys: pytest.CaptureFixture[str]) -> None:
    with respx.mock() as router:
        mock_all(router)
        cli.main(["run-once"])
        capsys.readouterr()
        cli.main(["run-once"])
    assert "github: ok, 0 bài mới" in capsys.readouterr().out


def test_run_once_with_one_broken_source_still_succeeds(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with respx.mock() as router:
        mock_all(router, hn_status=500)
        assert cli.main(["run-once"]) == 0
    out = capsys.readouterr().out
    assert "hackernews: LỖI" in out and "github: ok" in out


def test_run_once_returns_1_when_every_source_fails() -> None:
    with respx.mock() as router:
        router.route().respond(500)
        assert cli.main(["run-once"]) == 1


def test_console_is_switched_to_utf8(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = io.BytesIO()
    fake = io.TextIOWrapper(raw, encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", fake)
    cli.use_utf8_console()
    fake.write("Số bài mới ớ")
    fake.flush()
    assert raw.getvalue().decode("utf-8") == "Số bài mới ớ"


def test_describe_status() -> None:
    assert cli.describe_status(True, None) == "ok"
    assert cli.describe_status(True, "một phần: hết quota") == "ok (một phần: hết quota)"
    assert cli.describe_status(False, "HTTP 500") == "LỖI: HTTP 500"
