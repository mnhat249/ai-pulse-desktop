"""Đo bộ lọc rác (tầng luật) trên tập tin đã gán nhãn tay.

Chạy: `python -m app.quality.noise noise_labels.csv`
CSV có cột: `source,title,text,metrics,label` — `metrics` là JSON (ví dụ {"stars": 12}),
`label` là `noise` hoặc `keep`.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from app.config import NoiseSettings, load_settings
from app.pipeline.noise import noise_reason

MIN_ITEMS = 20
MAX_LEAK_RATE = 0.10  # mục tiêu của kế hoạch: tối đa 10% rác lọt qua


@dataclass(frozen=True)
class LabeledItem:
    source: str
    title: str
    text: str
    metrics: dict[str, float]
    is_noise: bool


@dataclass(frozen=True)
class NoiseReport:
    total: int
    noise_total: int
    caught: int  # rác bị bộ lọc chặn
    leaked: int  # rác lọt qua
    wrongly_blocked: int  # tin tốt bị chặn nhầm
    kept: int  # số tin bộ lọc cho qua
    leak_rate: float  # rác lọt / tin cho qua
    recall: float
    precision: float

    @property
    def meets_goal(self) -> bool:
        return self.leak_rate <= MAX_LEAK_RATE


def read_items(path: Path) -> list[LabeledItem]:
    items = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            label = (row.get("label") or "").strip().lower()
            if label not in {"noise", "keep"}:
                continue
            raw = (row.get("metrics") or "").strip()
            metrics = {k: float(v) for k, v in json.loads(raw).items()} if raw else {}
            items.append(
                LabeledItem(
                    row["source"].strip(),
                    row["title"],
                    row.get("text") or "",
                    metrics,
                    label == "noise",
                )
            )
    return items


def measure(items: Sequence[LabeledItem], settings: NoiseSettings) -> NoiseReport:
    blocked = [
        noise_reason(i.source, i.title, i.text, i.metrics, settings) is not None for i in items
    ]
    caught = sum(1 for i, b in zip(items, blocked, strict=True) if i.is_noise and b)
    leaked = sum(1 for i, b in zip(items, blocked, strict=True) if i.is_noise and not b)
    wrong = sum(1 for i, b in zip(items, blocked, strict=True) if not i.is_noise and b)
    kept = leaked + sum(1 for i, b in zip(items, blocked, strict=True) if not i.is_noise and not b)
    noise_total = caught + leaked
    return NoiseReport(
        total=len(items),
        noise_total=noise_total,
        caught=caught,
        leaked=leaked,
        wrongly_blocked=wrong,
        kept=kept,
        leak_rate=leaked / kept if kept else 0.0,
        recall=caught / noise_total if noise_total else 0.0,
        precision=caught / (caught + wrong) if caught + wrong else 0.0,
    )


def render(report: NoiseReport) -> str:
    verdict = "ĐẠT" if report.meets_goal else "CHƯA ĐẠT"
    return (
        f"{report.total} tin ({report.noise_total} rác). Bộ lọc chặn {report.caught} rác, "
        f"bỏ lọt {report.leaked}, chặn nhầm {report.wrongly_blocked} tin tốt.\n"
        f"Rác lọt trong số tin cho qua: {report.leak_rate:.1%} (mục tiêu ≤ {MAX_LEAK_RATE:.0%}) "
        f"-> {verdict}. Recall rác {report.recall:.1%}, precision {report.precision:.1%}.\n"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.quality.noise")
    parser.add_argument("csv", type=Path)
    args = parser.parse_args(argv)
    items = read_items(args.csv)
    if len(items) < MIN_ITEMS:
        sys.stdout.write(f"Cần ít nhất {MIN_ITEMS} tin đã gán nhãn (hiện có {len(items)}).\n")
        return 1
    report = measure(items, load_settings().noise)
    sys.stdout.write(render(report))
    return 0 if report.meets_goal else 2


if __name__ == "__main__":
    sys.exit(main())
