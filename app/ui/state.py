from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

MIN_WIDTH, MIN_HEIGHT = 320, 300
MAX_SIZE = 4000
MAX_OFFSET = 10000


@dataclass
class WindowState:
    """Vị trí, kích thước và tùy chọn "luôn trên cùng" của widget, nhớ giữa các lần mở."""

    x: int = 40
    y: int = 80
    width: int = 400
    height: int = 560
    always_on_top: bool = True
    topic: str = ""  # nhãn chủ đề đang chọn; trống = mặc định "Chủ đề của tôi"

    @property
    def geometry(self) -> str:
        return f"{self.width}x{self.height}+{self.x}+{self.y}"


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def load_state(path: Path, default_on_top: bool = True) -> WindowState:
    """Đọc trạng thái đã lưu; file thiếu hoặc hỏng thì dùng mặc định, giá trị lạ bị kẹp lại."""
    state = WindowState(always_on_top=default_on_top)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return WindowState(
            x=_clamp(int(raw.get("x", state.x)), -MAX_OFFSET, MAX_OFFSET),
            y=_clamp(int(raw.get("y", state.y)), -MAX_OFFSET, MAX_OFFSET),
            width=_clamp(int(raw.get("width", state.width)), MIN_WIDTH, MAX_SIZE),
            height=_clamp(int(raw.get("height", state.height)), MIN_HEIGHT, MAX_SIZE),
            always_on_top=bool(raw.get("always_on_top", default_on_top)),
            topic=str(raw.get("topic", "")),
        )
    except FileNotFoundError:
        return state
    except (OSError, ValueError, TypeError, AttributeError):
        logger.warning("File trạng thái cửa sổ hỏng, dùng mặc định: %s", path)
        return state


def save_state(path: Path, state: WindowState) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(state)), encoding="utf-8")
    except OSError:
        logger.exception("Không lưu được trạng thái cửa sổ")
