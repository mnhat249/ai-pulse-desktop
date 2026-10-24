from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app import startup
from app.adapters.rss import build_entry, entry_time
from app.config import FeedSettings, Settings, feed_slug, load_settings
from app.core.models import utcnow
from app.pipeline.process import Processor
from app.startup import LaunchCommand
from tests.helpers import FakeEmbedder, all_clusters, gh, make
from tests.test_cluster import count_embeddings

# ---- feed trùng tên hoặc sai URL không làm app hỏng -------------------------------------------


def feeds(*pairs: tuple[str, str]) -> Settings:
    return Settings.model_validate({"rss": [{"name": n, "url": u} for n, u in pairs]})


def test_duplicate_feed_names_after_slugging_keep_only_the_first(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="app.config"):
        settings = feeds(("AI News", "https://a.test/f"), ("ai_news", "https://b.test/f"))
    assert [f.url for f in settings.rss] == ["https://a.test/f"]
    assert "trùng" in caplog.text and "rss_ai_news" in caplog.text


def test_feed_with_non_http_url_is_dropped() -> None:
    settings = feeds(
        ("ok", "https://ok.test/f"),
        ("file", "file:///c:/windows/win.ini"),
        ("js", "javascript:alert(1)"),
        ("ftp", "ftp://x.test/f"),
        ("trống", ""),
    )
    assert [f.name for f in settings.rss] == ["ok"]


def test_http_scheme_is_case_insensitive_and_defaults_are_untouched() -> None:
    assert len(feeds(("a", "HTTPS://A.TEST/f")).rss) == 1
    defaults = Settings().rss
    assert len({feed_slug(f.name) for f in defaults}) == len(defaults) >= 5


def test_adapter_ids_are_unique_for_any_accepted_feed_list() -> None:
    from app.scheduler import build_adapters

    settings = feeds(
        ("Blog A", "https://a.test/f"),
        ("blog-a", "https://b.test/f"),
        ("Blog B", "https://c.test/f"),
    )
    names = [a.name for a in build_adapters(settings)]
    assert len(names) == len(set(names))


# ---- settings.toml hỏng khi khởi động -----------------------------------------------------------


def test_corrupt_settings_file_is_moved_aside_and_defaults_are_used(
    app_home: Path, caplog: pytest.LogCaptureFixture
) -> None:
    app_home.mkdir(parents=True)
    (app_home / "settings.toml").write_text("[github\nenabled = ", encoding="utf-8")
    with caplog.at_level(logging.ERROR, logger="app.config"):
        settings = load_settings()
    assert settings.github.enabled is True and settings.hackernews.min_points == 50
    assert not (app_home / "settings.toml").exists()
    assert (app_home / "settings.toml.bad").read_text(encoding="utf-8").startswith("[github")
    assert "hỏng" in caplog.text


def test_valid_settings_file_is_left_alone(app_home: Path) -> None:
    app_home.mkdir(parents=True)
    (app_home / "settings.toml").write_text("request_timeout_seconds = 7\n", encoding="utf-8")
    assert load_settings().request_timeout_seconds == 7
    assert not (app_home / "settings.toml.bad").exists()


# ---- ghi embedding bù lỗi không làm hỏng cả vòng xử lý -----------------------------------------


async def test_failure_while_storing_backfilled_embeddings_does_not_break_the_run(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    proc, writer = await make(engine, [gh("1", "acme/tool")])
    await proc.run()
    with_model = Processor(Settings(), engine, writer, FakeEmbedder(), [])

    async def broken(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("ghi DB lỗi giả")

    monkeypatch.setattr(with_model, "_store_embeddings", broken)
    result = await with_model.run()  # không ném lỗi
    assert result.clustered == 0 and await count_embeddings(engine) == 0
    monkeypatch.undo()
    await with_model.run()  # lần sau ghi được bình thường
    await writer.stop()
    assert await count_embeddings(engine) == 1 and len(await all_clusters(engine)) == 1


# ---- PowerShell: mọi loại nháy đơn đều bị nhân đôi ---------------------------------------------


@pytest.mark.parametrize("quote", ["'", "\u2018", "\u2019", "\u201a", "\u201b"])
def test_every_powershell_single_quote_variant_is_doubled(quote: str) -> None:
    nasty = LaunchCommand(f"C:\\Users\\O{quote}Brien\\app.exe", f"x{quote}; calc; {quote}", "C:\\w")
    script = startup.create_script(nasty)
    assert f"O{quote}{quote}Brien" in script
    assert f"x{quote}{quote}; calc; {quote}{quote}" in script


def test_plain_paths_are_not_altered_by_quoting() -> None:
    assert startup._ps_quote(r"C:\Program Files\NeuralRadar\app.exe") == (
        r"'C:\Program Files\NeuralRadar\app.exe'"
    )


# ---- RSS: ngày tương lai không chiếm đầu danh sách -------------------------------------------


def parsed_time(moment: datetime) -> Any:
    return moment.utctimetuple()


def test_future_dated_entries_are_clamped_to_now() -> None:
    future = utcnow() + timedelta(days=30)
    clamped = entry_time({"published_parsed": parsed_time(future)})
    assert clamped <= utcnow()
    past = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    assert entry_time({"published_parsed": parsed_time(past)}) == past


def test_future_dated_item_does_not_outrank_a_real_recent_one() -> None:
    recent = utcnow() - timedelta(hours=2)
    future = utcnow() + timedelta(days=90)
    scheduled = {
        "title": "Bài đặt lịch",
        "link": "https://x.test/s",
        "published_parsed": parsed_time(future),
    }
    real = {
        "title": "Bài thật gần đây",
        "link": "https://x.test/r",
        "published_parsed": parsed_time(recent),
    }
    items = sorted(
        (build_entry("rss_x", e) for e in (scheduled, real)),
        key=lambda i: i.published_at,
        reverse=True,
    )
    assert all(i.published_at <= utcnow() for i in items)  # không bài nào có ngày ở tương lai
    assert items[0].title == "Bài đặt lịch"  # bị kẹp về "bây giờ" nên chỉ ngang bài mới nhất


def test_feed_settings_class_still_validates_bounds() -> None:
    with pytest.raises(ValueError):
        FeedSettings(name="x", url="https://x.test", max_entries=0)
