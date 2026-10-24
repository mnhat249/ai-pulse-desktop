from __future__ import annotations

WINDOW_HOURS = 24.0


def star_velocity(
    stars: float,
    age_hours: float | None,
    baseline: tuple[float, float] | None,
) -> float | None:
    """Số sao tăng thêm trong 24 giờ.

    `baseline` là (số sao lúc trước, số giờ đã trôi qua kể từ đó). Chưa có mốc thì repo
    mới tạo (dưới 24 giờ) dùng sao chia tuổi; repo cũ chưa có lịch sử thì chưa tính được.
    """
    if baseline is not None:
        old_stars, elapsed_hours = baseline
        if elapsed_hours <= 0:
            return None
        return (stars - old_stars) / elapsed_hours * WINDOW_HOURS
    if age_hours is not None and age_hours < WINDOW_HOURS:
        return stars / max(age_hours, 1.0) * WINDOW_HOURS
    return None
