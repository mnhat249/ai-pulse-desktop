from __future__ import annotations

import re

from app.config import NoiseSettings


def spam_pattern(keywords: list[str]) -> re.Pattern[str]:
    alternatives = "|".join(re.escape(k) for k in keywords)
    return re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)", re.IGNORECASE)


def noise_reason(
    source: str,
    title: str,
    text: str,
    metrics: dict[str, float],
    settings: NoiseSettings,
) -> str | None:
    """Tầng luật: trả về lý do là rác, hoặc None nếu bài đáng giữ."""
    if len(title.strip()) < settings.min_title_chars:
        return "tiêu đề quá ngắn"
    if settings.spam_keywords and (match := spam_pattern(settings.spam_keywords).search(title)):
        return f"từ khóa quảng cáo: {match.group(0).lower()}"
    for metric, minimum in settings.thresholds.get(source, {}).items():
        if metrics.get(metric, 0) < minimum:
            return f"{metric} dưới {minimum:g}"
    return None
