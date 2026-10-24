"""Đo chất lượng lọc trùng: so TF-IDF với embedding trên cặp bài đã gán nhãn, chọn ngưỡng theo F1.

Chạy: `python -m app.quality.dedup pairs.csv --out docs/dedup-eval.md`
Cột `label` trong CSV: 1 = cùng tin, 0 = khác tin (xuất CSV: `python -m app.cli export-pairs`).
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from app.config import app_home, load_settings
from app.pipeline.embeddings import Embedder, FastEmbedder, embedding_text

THRESHOLDS = [round(0.50 + 0.01 * i, 2) for i in range(46)]  # 0.50 ... 0.95
MIN_PAIRS = 20


@dataclass(frozen=True)
class LabeledPair:
    a_text: str
    b_text: str
    same: bool


@dataclass(frozen=True)
class ThresholdScore:
    threshold: float
    precision: float
    recall: float
    f1: float


@dataclass(frozen=True)
class MethodResult:
    name: str
    best: ThresholdScore
    table: list[ThresholdScore]


def read_pairs(path: Path) -> list[LabeledPair]:
    """Đọc CSV đã gán nhãn; bỏ dòng chưa điền `label`."""
    pairs = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            label = (row.get("label") or "").strip().lower()
            if label not in {"0", "1"}:
                continue
            pairs.append(
                LabeledPair(
                    embedding_text(row["a_title"], row["a_text"]),
                    embedding_text(row["b_title"], row["b_text"]),
                    label == "1",
                )
            )
    return pairs


def f1_at(scores: Sequence[float], labels: Sequence[bool], threshold: float) -> ThresholdScore:
    tp = sum(1 for s, y in zip(scores, labels, strict=True) if s >= threshold and y)
    fp = sum(1 for s, y in zip(scores, labels, strict=True) if s >= threshold and not y)
    fn = sum(1 for s, y in zip(scores, labels, strict=True) if s < threshold and y)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return ThresholdScore(threshold, precision, recall, f1)


def sweep(name: str, scores: Sequence[float], labels: Sequence[bool]) -> MethodResult:
    table = [f1_at(scores, labels, t) for t in THRESHOLDS]
    best = max(table, key=lambda s: (s.f1, s.threshold))  # F1 bằng nhau thì lấy ngưỡng cao hơn
    return MethodResult(name, best, table)


def tfidf_scores(pairs: Sequence[LabeledPair]) -> list[float]:
    texts = [t for p in pairs for t in (p.a_text, p.b_text)]
    matrix = TfidfVectorizer(sublinear_tf=True).fit_transform(texts)
    out = []
    for i in range(len(pairs)):
        a, b = matrix[2 * i], matrix[2 * i + 1]
        out.append(float(a.multiply(b).sum()))  # TF-IDF đã chuẩn hóa nên tích vô hướng = cosine
    return out


async def embedding_scores(pairs: Sequence[LabeledPair], embedder: Embedder) -> list[float]:
    texts = [t for p in pairs for t in (p.a_text, p.b_text)]
    vectors = np.stack(await embedder.embed(texts))
    return [float(vectors[2 * i] @ vectors[2 * i + 1]) for i in range(len(pairs))]


def render_report(
    tfidf: MethodResult, embedding: MethodResult, pairs: Sequence[LabeledPair], model: str
) -> str:
    positives = sum(p.same for p in pairs)
    verdict = "cao hơn" if embedding.best.f1 > tfidf.best.f1 else "KHÔNG cao hơn"

    def row(r: MethodResult) -> str:
        b = r.best
        return f"| {r.name} | {b.threshold:.2f} | {b.precision:.3f} | {b.recall:.3f} | {b.f1:.3f} |"

    lines = [
        "# Đánh giá lọc trùng",
        "",
        f"Chạy ngày {date.today():%d/%m/%Y} trên {len(pairs)} cặp đã gán nhãn "
        f"({positives} cùng tin, {len(pairs) - positives} khác tin). Model: `{model}`.",
        "",
        "| Phương pháp | Ngưỡng tốt nhất | Precision | Recall | F1 |",
        "| --- | --- | --- | --- | --- |",
        row(tfidf),
        row(embedding),
        "",
        f"Embedding {verdict} TF-IDF (mốc so sánh). "
        f"Đặt `[dedup] threshold = {embedding.best.threshold:.2f}` trong `settings.toml`.",
        "",
        "## F1 theo ngưỡng",
        "",
        "| Ngưỡng | TF-IDF | Embedding |",
        "| --- | --- | --- |",
    ]
    for t, e in zip(tfidf.table, embedding.table, strict=True):
        lines.append(f"| {t.threshold:.2f} | {t.f1:.3f} | {e.f1:.3f} |")
    return "\n".join(lines) + "\n"


def write_report(out: Path, text: str) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")


async def evaluate(
    pairs: Sequence[LabeledPair], embedder: Embedder
) -> tuple[MethodResult, MethodResult]:
    labels = [p.same for p in pairs]
    tfidf = sweep("TF-IDF", tfidf_scores(pairs), labels)
    embedding = sweep("Embedding", await embedding_scores(pairs, embedder), labels)
    return tfidf, embedding


async def run(
    csv_path: Path,
    out: Path,
    embedder: Embedder,
    write: Callable[[str], object] = sys.stdout.write,
) -> int:
    pairs = read_pairs(csv_path)
    if len(pairs) < MIN_PAIRS or len({p.same for p in pairs}) < 2:
        write(
            f"Cần ít nhất {MIN_PAIRS} cặp đã gán nhãn, có cả 0 và 1 "
            f"(hiện có {len(pairs)}). Điền cột label trong {csv_path} rồi chạy lại.\n"
        )
        return 1
    tfidf, embedding = await evaluate(pairs, embedder)
    write_report(out, render_report(tfidf, embedding, pairs, embedder.model_name))
    write(
        f"TF-IDF F1={tfidf.best.f1:.3f} (ngưỡng {tfidf.best.threshold:.2f}); "
        f"Embedding F1={embedding.best.f1:.3f} (ngưỡng {embedding.best.threshold:.2f}). "
        f"Báo cáo: {out}\n"
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.quality.dedup")
    parser.add_argument("csv", type=Path)
    parser.add_argument("--out", type=Path, default=Path("docs/dedup-eval.md"))
    args = parser.parse_args(argv)
    settings = load_settings()
    embedder = FastEmbedder(settings.dedup.embedding_model, app_home() / "models")
    return asyncio.run(run(args.csv, args.out, embedder))


if __name__ == "__main__":
    sys.exit(main())
