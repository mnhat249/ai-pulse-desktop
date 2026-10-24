from __future__ import annotations

from app.config import RankingSettings
from app.core import sources

SPREAD_FULL_AT_SOURCES = 3


def item_heat(source: str, metrics: dict[str, float], settings: RankingSettings) -> float:
    """Độ "nóng" của một bài, từ 0 đến 1, theo chỉ số riêng của nguồn (đăng ký ở SourceInfo)."""
    metric = sources.info(source).heat_metric
    scale = settings.heat_scales.get(source, 0.0)
    if metric is None or scale <= 0:
        return 0.0
    return max(0.0, min(1.0, metrics.get(metric, 0.0) / scale))


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
