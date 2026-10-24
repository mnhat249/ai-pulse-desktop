from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import pytest

from app.config import NoiseSettings
from app.pipeline.pairs import CSV_COLUMNS, PairItem, candidate_pairs, export_pairs
from app.quality import dedup, noise
from app.storage.tables import item_embeddings
from tests.helpers import FakeEmbedder, gh, item, make


def test_f1_at_counts_correctly() -> None:
    scores = [0.9, 0.8, 0.6, 0.3]
    labels = [True, False, True, False]
    s = dedup.f1_at(scores, labels, 0.7)
    assert (s.precision, s.recall) == (0.5, 0.5) and s.f1 == pytest.approx(0.5)
    assert dedup.f1_at(scores, labels, 0.95).f1 == 0.0


def test_sweep_picks_threshold_with_best_f1_and_higher_on_ties() -> None:
    scores = [0.95, 0.9, 0.85, 0.2, 0.1, 0.05]
    labels = [True, True, True, False, False, False]
    result = dedup.sweep("x", scores, labels)
    assert result.best.f1 == 1.0 and result.best.threshold == 0.85
    assert len(result.table) == 46 and result.table[0].threshold == 0.50


def write_labeled_csv(path: Path, rows: list[tuple[str, str, str, str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["a_title", "a_text", "b_title", "b_text", "label"])
        writer.writerows(rows)


def labeled_rows() -> list[tuple[str, str, str, str, str]]:
    same = [
        (
            f"OpenAI releases model o{i}",
            "new reasoning model",
            f"OpenAI releases model o{i}",
            "reasoning model news",
            "1",
        )
        for i in range(12)
    ]
    different = [
        (
            f"Rust compiler {i} update",
            "async runtime",
            f"Photosynthesis study {i}",
            "plants light energy",
            "0",
        )
        for i in range(12)
    ]
    return same + different + [("x", "y", "z", "w", "")]


def test_read_pairs_skips_unlabeled(tmp_path: Path) -> None:
    path = tmp_path / "p.csv"
    write_labeled_csv(path, labeled_rows())
    pairs = dedup.read_pairs(path)
    assert len(pairs) == 24 and sum(p.same for p in pairs) == 12


async def test_run_writes_report_comparing_tfidf_and_embedding(tmp_path: Path) -> None:
    path, out = tmp_path / "p.csv", tmp_path / "docs" / "dedup-eval.md"
    write_labeled_csv(path, labeled_rows())
    messages: list[str] = []
    code = await dedup.run(path, out, FakeEmbedder(), messages.append)
    report = out.read_text(encoding="utf-8")
    assert code == 0 and "TF-IDF" in report and "Embedding" in report
    assert "24 cặp" in report and "F1 theo ngưỡng" in report and "fake-bow" in report
    assert "F1=" in messages[0]


async def test_run_refuses_too_few_or_one_sided_labels(tmp_path: Path) -> None:
    path = tmp_path / "p.csv"
    write_labeled_csv(path, labeled_rows()[:5])
    messages: list[str] = []
    assert await dedup.run(path, tmp_path / "o.md", FakeEmbedder(), messages.append) == 1
    assert not (tmp_path / "o.md").exists() and "ít nhất" in messages[0]


def test_candidate_pairs_skips_same_key_and_spreads_over_similarity() -> None:
    items = [PairItem(i, "s", f"t{i}", "", f"u{i}", f"k{i}") for i in range(30)]
    items[1] = PairItem(1, "s", "t1", "", "u1", "k0")  # trùng khóa chuẩn với item 0
    rng = np.random.default_rng(0)
    base = rng.normal(size=(30, 8)).astype(np.float32)
    base[1] = base[0]
    vectors = base / np.linalg.norm(base, axis=1, keepdims=True)
    pairs = candidate_pairs(items, vectors, count=10, low=-1.0)
    assert len(pairs) == 10 and (0, 1) not in {(i, j) for i, j, _ in pairs}
    sims = [p[2] for p in pairs]
    assert sims == sorted(sims, reverse=True) and sims[0] - sims[-1] > 0.5


def test_candidate_pairs_returns_all_when_fewer_than_count() -> None:
    items = [PairItem(i, "s", "t", "", f"u{i}", f"k{i}") for i in range(3)]
    vectors = np.array([[1.0, 0.0], [0.9, 0.1], [0.0, 1.0]], dtype=np.float32)
    assert len(candidate_pairs(items, vectors, count=50, low=0.0)) == 3
    assert candidate_pairs(items[:1], vectors[:1], 5) == []


async def test_export_pairs_writes_csv_from_stored_embeddings(
    engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import Settings

    items = [
        item(
            "hackernews", "1", "https://a.com/1", "OpenAI releases reasoning model o5", points=100.0
        ),
        item(
            "hackernews",
            "2",
            "https://b.com/2",
            "OpenAI releases reasoning model o5 today",
            points=100.0,
        ),
        gh("3", "acme/tool"),
    ]
    proc, writer = await make(engine, items, embedder=FakeEmbedder())
    await proc.run()
    await writer.stop()
    settings = Settings.model_validate({"dedup": {"embedding_model": "fake-bow"}})
    monkeypatch.setattr(Settings, "db_path", property(lambda _s: Path(engine.url.database)))
    out = tmp_path / "pairs.csv"
    assert await export_pairs(settings, out, 5) == 0
    with out.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert list(rows[0].keys()) == CSV_COLUMNS and rows[0]["label"] == ""
    assert all(float(r["cosine"]) >= 0.45 for r in rows) and len(rows) >= 1
    assert item_embeddings.name == "item_embeddings"


async def test_export_pairs_without_embeddings_explains(
    engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from app.config import Settings

    monkeypatch.setattr(Settings, "db_path", property(lambda _s: Path(engine.url.database)))
    assert await export_pairs(Settings(), tmp_path / "p.csv", 5) == 1
    assert "embedding" in capsys.readouterr().err


NOISE_ROWS = [
    # source, title, text, metrics, label
    *[
        ("hackernews", f"Free AI course giveaway {i}", "", {"points": 300}, "noise")
        for i in range(5)
    ],
    *[("github", f"nobody/tiny-{i}", "demo", {"stars": 2}, "noise") for i in range(5)],
    *[("hf_models", f"user/model-{i}", "x", {"likes": 50}, "keep") for i in range(6)],
    *[
        ("hackernews", f"Show HN: LLM agent runner {i}", "", {"points": 200}, "keep")
        for i in range(6)
    ],
]


def write_noise_csv(path: Path, rows: list[tuple[str, str, str, dict[str, int], str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["source", "title", "text", "metrics", "label"])
        for source, title, text, metrics, label in rows:
            writer.writerow([source, title, text, json.dumps(metrics), label])


def test_noise_measure_reports_leak_rate_and_goal(tmp_path: Path) -> None:
    path = tmp_path / "n.csv"
    write_noise_csv(path, NOISE_ROWS)
    report = noise.measure(noise.read_items(path), NoiseSettings())
    assert (report.total, report.noise_total, report.caught, report.leaked) == (22, 10, 10, 0)
    assert report.leak_rate == 0.0 and report.meets_goal and report.wrongly_blocked == 0


def test_noise_leak_rate_above_ten_percent_fails_goal(tmp_path: Path) -> None:
    leaked = [("hackernews", f"Sneaky promo {i}", "", {"points": 300}, "noise") for i in range(3)]
    path = tmp_path / "n.csv"
    write_noise_csv(path, NOISE_ROWS + leaked)
    report = noise.measure(noise.read_items(path), NoiseSettings())
    assert report.leaked == 3 and report.kept == 15
    assert report.leak_rate == pytest.approx(0.2) and not report.meets_goal
    assert "CHƯA ĐẠT" in noise.render(report)


def test_noise_main_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    good, short = tmp_path / "g.csv", tmp_path / "s.csv"
    write_noise_csv(good, NOISE_ROWS)
    write_noise_csv(short, NOISE_ROWS[:3])
    assert noise.main([str(good)]) == 0 and "ĐẠT" in capsys.readouterr().out
    assert noise.main([str(short)]) == 1
