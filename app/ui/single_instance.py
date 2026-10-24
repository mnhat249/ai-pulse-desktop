from __future__ import annotations

import enum
import logging
import socket
import threading
from collections.abc import Callable

logger = logging.getLogger(__name__)

DEFAULT_PORT = 47653
SHOW_MESSAGE = b"show"
REPLY_MESSAGE = b"neuralradar"
CONNECT_TIMEOUT_SECONDS = 2.0


class Acquire(enum.Enum):
    ACQUIRED = "acquired"  # đây là bản đầu tiên
    ALREADY_RUNNING = "already_running"  # đã có bản NeuralRadar khác (và đã được yêu cầu hiện lên)
    PORT_BUSY = "port_busy"  # cổng bị chương trình khác chiếm; không biết có bản nào đang chạy


class SingleInstance:
    """Chỉ một bản chạy: bản đầu giữ cổng cục bộ; bản sau gửi "show" rồi thoát.

    Bản đang chạy trả lời `neuralradar` để phân biệt với chương trình khác chiếm cùng cổng.
    Cổng được hệ điều hành tự nhả khi tiến trình chết, nên không bị kẹt khóa sau khi crash.
    """

    def __init__(self, on_show: Callable[[], None], port: int = DEFAULT_PORT) -> None:
        self._on_show = on_show
        self._port = port
        self._server: socket.socket | None = None
        self._thread: threading.Thread | None = None

    def acquire(self) -> Acquire:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            server.bind(("127.0.0.1", self._port))
        except OSError:
            server.close()
            return self._ask_running_instance_to_show()
        server.listen(4)
        self._server = server
        self._thread = threading.Thread(target=self._serve, name="single-instance", daemon=True)
        self._thread.start()
        return Acquire.ACQUIRED

    def _ask_running_instance_to_show(self) -> Acquire:
        try:
            with socket.create_connection(
                ("127.0.0.1", self._port), timeout=CONNECT_TIMEOUT_SECONDS
            ) as conn:
                conn.sendall(SHOW_MESSAGE)
                reply = conn.recv(32)
        except OSError:
            reply = b""
        if reply == REPLY_MESSAGE:
            return Acquire.ALREADY_RUNNING
        logger.warning("Cổng %d đang bị chương trình khác chiếm", self._port)
        return Acquire.PORT_BUSY

    def _serve(self) -> None:
        server = self._server
        assert server is not None
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                return  # đã đóng
            with conn:
                conn.settimeout(CONNECT_TIMEOUT_SECONDS)
                try:
                    data = conn.recv(16)
                    if data == SHOW_MESSAGE:
                        conn.sendall(REPLY_MESSAGE)
                except OSError:
                    continue
            if data == SHOW_MESSAGE:
                try:
                    self._on_show()
                except Exception:
                    logger.exception("Callback hiện widget lỗi")

    def close(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=CONNECT_TIMEOUT_SECONDS)
            self._thread = None
