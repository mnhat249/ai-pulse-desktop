from __future__ import annotations

from app.config import RankingSettings

HF_PAPERS_UPVOTES_SCALE = 50.0
SPREAD_FULL_AT_SOURCES = 3


def item_heat(source: str, metrics: dict[str, float], settings: RankingSettings) -> float:
    """Độ "nóng" của một bài, từ 0 đến 1, theo chỉ số riêng của từng nguồn."""
    if source == "github":
        raw = metrics.get("stars_per_24h", 0.0) / settings.github_velocity_scale
    elif source == "hf_models":
        raw = metrics.get("trendingScore", 0.0) / settings.hf_trending_scale
    elif source == "hf_papers":
        raw = metrics.get("upvotes", 0.0) / HF_PAPERS_UPVOTES_SCALE
    elif source == "hackernews":
        raw = metrics.get("points", 0.0) / settings.hn_points_scale
    else:
        raw = 0.0
    return max(0.0, min(1.0, raw))


def importance_score(
    heats: list[float],
    source_count: int,
    llm_importance: int | None,
    settings: RankingSettings,
) -> float:
    """Điểm quan trọng 0–100 = nóng (tốc độ sao/trending) + số nguồn + điểm LLM (1–5).

    Thành phần nào chưa có (ví dụ LLM chưa tóm tắt) thì bỏ ra và chia lại trọng số.
    """
    parts: list[tuple[float, float]] = [
        (settings.heat_weight, max(heats, default=0.0)),
        (
            settings.spread_weight,
            min(1.0, (source_count - 1) / (SPREAD_FULL_AT_SOURCES - 1)),
        ),
    ]
    if llm_importance is not None:
        parts.append((settings.llm_weight, (llm_importance - 1) / 4))
    total_weight = sum(weight for weight, _ in parts)
    if total_weight == 0:
        return 0.0
    return round(100 * sum(weight * value for weight, value in parts) / total_weight, 2)
