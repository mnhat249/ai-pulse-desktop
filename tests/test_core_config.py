from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from app import setkey
from app.config import app_home, get_secret, load_settings, set_secret
from app.core.metrics import star_velocity
from app.core.models import Digest, RawItem
from app.logging_setup import setup_logging


def test_raw_item_defaults() -> None:
    item = RawItem(
        source="github",
        source_id="1",
        url="https://github.com/o/r",
        title="o/r",
        published_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert item.metrics == {} and item.links == [] and item.text == ""


def test_digest_has_no_link_field_and_validates_importance() -> None:
    assert not [f for f in Digest.model_fields if "url" in f or "link" in f]
    with pytest.raises(ValidationError):
        Digest(cluster_id=1, title_vi="t", innovation="a", impact="b", importance=9, is_noise=False)


def test_settings_defaults_and_toml_override(app_home: Path) -> None:
    assert load_settings().github.topics[0] == "llm"
    app_home.mkdir(parents=True)
    (app_home / "settings.toml").write_text(
        "request_timeout_seconds = 5\n[hackernews]\nmin_points = 80\n", encoding="utf-8"
    )
    s = load_settings()
    assert s.request_timeout_seconds == 5 and s.hackernews.min_points == 80
    assert s.hackernews.interval_minutes == 15
    assert s.db_path == app_home / "neuralradar.db"


def test_app_home_falls_back_to_appdata(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("NEURALRADAR_HOME")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert app_home() == tmp_path / "NeuralRadar"


def test_secrets_roundtrip() -> None:
    assert get_secret("gemini") is None
    set_secret("gemini", "abc")
    assert get_secret("gemini") == "abc"


def test_setkey_rejects_unknown_name(capsys: pytest.CaptureFixture[str]) -> None:
    assert setkey.main(["bogus"]) == 2
    assert setkey.main([]) == 2


def test_setkey_stores_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.setkey.getpass.getpass", lambda _prompt: "  secret-value ")
    assert setkey.main(["groq"]) == 0
    assert get_secret("groq") == "secret-value"


def test_setkey_rejects_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.setkey.getpass.getpass", lambda _prompt: "  ")
    assert setkey.main(["groq"]) == 1
    assert get_secret("groq") is None


def test_logging_rotates_5_files_of_2mb(tmp_path: Path) -> None:
    setup_logging(tmp_path / "logs", console=False)
    handler = logging.getLogger().handlers[0]
    assert handler.maxBytes == 2 * 1024 * 1024  # type: ignore[attr-defined]
    assert handler.backupCount + 1 == 5  # type: ignore[attr-defined]
    logging.getLogger("t").info("xin chào")
    handler.flush()
    assert "xin chào" in (tmp_path / "logs" / "neuralradar.log").read_text(encoding="utf-8")
    logging.getLogger().handlers.clear()


def test_star_velocity_uses_baseline() -> None:
    assert star_velocity(150, 500, (100, 12)) == pytest.approx(100)


def test_star_velocity_new_repo_uses_age() -> None:
    assert star_velocity(60, 12, None) == pytest.approx(120)
    assert star_velocity(10, 0.2, None) == pytest.approx(240)  # tuổi tối thiểu 1 giờ


def test_star_velocity_old_repo_without_history_is_unknown() -> None:
    assert star_velocity(500, 1000, None) is None
    assert star_velocity(500, 1000, (400, 0)) is None
