from __future__ import annotations

import logging
import queue
import sys

from app.cli import use_utf8_console
from app.config import app_home, load_settings
from app.logging_setup import setup_logging
from app.storage.db import migrate
from app.storage.ui_queries import open_reader
from app.ui import tray as tray_commands
from app.ui.backend import Backend, UIEvent
from app.ui.model import UIModel
from app.ui.notifier import Notifier, ToastPolicy
from app.ui.single_instance import DEFAULT_PORT, Acquire, SingleInstance
from app.ui.tray import Tray
from app.ui.widget import FloatingWidget

logger = logging.getLogger(__name__)


def main() -> int:
    """Luồng chính chạy giao diện; luồng nền chạy asyncio + scheduler + task ghi DB."""
    use_utf8_console()
    settings = load_settings()
    setup_logging(settings.log_dir, console=sys.stderr is not None)
    commands: queue.SimpleQueue[str] = queue.SimpleQueue()

    instance = SingleInstance(on_show=lambda: commands.put(tray_commands.SHOW))
    outcome = instance.acquire()
    if outcome is Acquire.ALREADY_RUNNING:
        logger.info("NeuralRadar đã chạy; đã yêu cầu bản đang chạy hiện widget")
        return 0
    if outcome is Acquire.PORT_BUSY:
        logger.error(
            "Cổng %d bị chương trình khác chiếm nên không kiểm tra được bản đang chạy; "
            "vẫn khởi động (có thể chạy trùng bản)",
            DEFAULT_PORT,
        )

    migrate(settings.db_path, settings.backup_dir)  # đảm bảo DB có sẵn trước khi giao diện đọc
    events: queue.Queue[UIEvent] = queue.Queue()
    backend = Backend(settings, events)
    reader = open_reader(settings.db_path)
    notifier = Notifier(ToastPolicy(settings.ui))
    widget_box: list[FloatingWidget] = []
    tray = Tray(commands, is_paused=lambda: bool(widget_box and widget_box[0].paused))
    widget = FloatingWidget(
        settings,
        UIModel(
            reader,
            settings.ui.max_clusters_shown,
            rules=settings.topics.resolved_rules(),
            enabled_topics=settings.topics.enabled_keys(),
        ),
        backend,
        events,
        commands,
        notifier,
        app_home() / "ui_state.json",
        tray,
    )
    widget_box.append(widget)
    backend.start()
    try:
        tray.start()
        widget.mark_tray_ready()
    except Exception:
        logger.exception("Không khởi động được icon khay; đóng cửa sổ sẽ thoát app")
    try:
        widget.run()
    finally:
        tray.stop()
        backend.stop()
        reader.close()
        instance.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
