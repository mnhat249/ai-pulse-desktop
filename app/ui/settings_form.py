"""Dữ liệu và kiểm tra của màn hình cài đặt (không phụ thuộc Tk nên test được)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.config import Settings

MAX_INTERVAL_MINUTES = 24 * 60
INTERVAL_SOURCES = {
    "github": "GitHub",
    "huggingface": "HuggingFace",
    "hackernews": "Hacker News",
    "bluesky": "Bluesky",
}


@dataclass
class SettingsDraft:
    enabled: dict[str, bool] = field(default_factory=dict)  # github, huggingface, ..., rss:<tên>
    intervals: dict[str, str] = field(default_factory=dict)  # phút, giữ dạng chữ như ô nhập
    toast_min_importance: str = "70"
    toast_max_per_hour: str = "4"
    start_with_windows: bool = False

    @classmethod
    def from_settings(cls, settings: Settings) -> SettingsDraft:
        enabled = {name: bool(getattr(settings, name).enabled) for name in INTERVAL_SOURCES}
        enabled.update({f"rss:{feed.name}": feed.enabled for feed in settings.rss})
        return cls(
            enabled=enabled,
            intervals={
                name: str(getattr(settings, name).interval_minutes) for name in INTERVAL_SOURCES
            },
            toast_min_importance=f"{settings.ui.toast_min_importance:g}",
            toast_max_per_hour=str(settings.ui.toast_max_per_hour),
            start_with_windows=settings.start_with_windows,
        )

    def errors(self) -> list[str]:
        problems: list[str] = []
        for name, label in INTERVAL_SOURCES.items():
            raw = self.intervals.get(name, "").strip()
            if not raw.isdigit() or not 1 <= int(raw) <= MAX_INTERVAL_MINUTES:
                problems.append(
                    f"Chu kỳ quét {label}: nhập số phút từ 1 đến {MAX_INTERVAL_MINUTES}"
                )
        try:
            importance = float(self.toast_min_importance.replace(",", "."))
            if not 0 <= importance <= 100:
                raise ValueError
        except ValueError:
            problems.append("Ngưỡng điểm báo toast: nhập số từ 0 đến 100")
        raw_cap = self.toast_max_per_hour.strip()
        if not raw_cap.isdigit() or not 1 <= int(raw_cap) <= 60:
            problems.append("Số toast tối đa mỗi giờ: nhập số từ 1 đến 60")
        return problems

    def to_updates(self, settings: Settings) -> dict[str, Any]:
        """Phần cần ghi vào settings.toml. Danh sách feed RSS được ghi đủ, chỉ đổi cờ bật/tắt."""
        if self.errors():
            raise ValueError("; ".join(self.errors()))
        updates: dict[str, Any] = {
            name: {
                "enabled": self.enabled.get(name, True),
                "interval_minutes": int(self.intervals[name]),
            }
            for name in INTERVAL_SOURCES
        }
        updates["rss"] = [
            {
                **feed.model_dump(),
                "enabled": self.enabled.get(f"rss:{feed.name}", feed.enabled),
            }
            for feed in settings.rss
        ]
        updates["ui"] = {
            "toast_min_importance": float(self.toast_min_importance.replace(",", ".")),
            "toast_max_per_hour": int(self.toast_max_per_hour),
        }
        updates["start_with_windows"] = self.start_with_windows
        return updates
