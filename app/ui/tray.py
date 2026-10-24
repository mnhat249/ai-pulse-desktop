from __future__ import annotations

import logging
import queue
from collections.abc import Callable

import pystray
from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)

TOGGLE = "toggle"
RUN_NOW = "run_now"
PAUSE = "pause"
RESUME = "resume"
QUIT = "quit"
SHOW = "show"


def icon_image() -> Image.Image:
    img = Image.new("RGB", (64, 64), "#0b1220")
    draw = ImageDraw.Draw(img)
    for radius in (28, 19, 10):
        draw.ellipse(
            (32 - radius, 32 - radius, 32 + radius, 32 + radius), outline="#38bdf8", width=2
        )
    draw.line((32, 32, 54, 14), fill="#38bdf8", width=3)
    return img


class Tray:
    """Icon khay. Callback chạy ở thread của pystray nên chỉ được đẩy lệnh vào hàng đợi.

    Mọi thao tác thật (hiện/ẩn, chạy ngay, thoát) do luồng giao diện xử lý khi đọc hàng đợi.
    """

    def __init__(
        self, commands: queue.SimpleQueue[str], is_paused: Callable[[], bool] = lambda: False
    ) -> None:
        self._commands = commands
        menu = pystray.Menu(
            pystray.MenuItem("Hiện/ẩn widget", lambda *_: commands.put(TOGGLE), default=True),
            pystray.MenuItem("Chạy ngay", lambda *_: commands.put(RUN_NOW)),
            pystray.MenuItem(
                "Tạm dừng",
                lambda *_: commands.put(RESUME if is_paused() else PAUSE),
                checked=lambda _item: is_paused(),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Thoát", lambda *_: commands.put(QUIT)),
        )
        self._icon = pystray.Icon("neuralradar", icon_image(), "NeuralRadar", menu)

    def start(self) -> None:
        self._icon.run_detached()

    def update(self) -> None:
        """Vẽ lại menu (dấu tích "Tạm dừng")."""
        try:
            self._icon.update_menu()
        except Exception:
            logger.debug("Không cập nhật được menu khay", exc_info=True)

    def stop(self) -> None:
        try:
            self._icon.stop()
        except Exception:
            logger.debug("Icon khay đã dừng", exc_info=True)
