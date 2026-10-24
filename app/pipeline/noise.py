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
    if source == "github" and metrics.get("stars", 0) < settings.github_min_stars:
        return f"repo dưới {settings.github_min_stars} sao"
    if source == "hf_models" and metrics.get("likes", 0) < settings.hf_models_min_likes:
        return f"model dưới {settings.hf_models_min_likes} lượt thích"
    if source == "hackernews" and metrics.get("points", 0) < settings.hn_min_points:
        return f"bài HN dưới {settings.hn_min_points} điểm"
    return None
