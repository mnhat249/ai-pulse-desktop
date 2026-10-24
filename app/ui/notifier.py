from __future__ import annotations

import logging
import re
import time
import unicodedata
from collections import deque
from collections.abc import Callable
from typing import Any

from app.config import UISettings
from app.storage.ui_queries import ClusterView

logger = logging.getLogger(__name__)

HOUR_SECONDS = 3600.0
TOAST_TITLE_CHARS = 64
TOAST_BODY_CHARS = 200


class ToastPolicy:
    """Khi nào được hiện toast: cụm điểm cao hoặc nhiều nguồn, mỗi cụm một lần, có trần mỗi giờ."""

    def __init__(self, settings: UISettings, clock: Callable[[], float] = time.monotonic) -> None:
        self._settings = settings
        self._clock = clock
        self._shown_at: deque[float] = deque()
        self._notified: set[int] = set()

    def worthy(self, cluster: ClusterView) -> bool:
        return (
            cluster.importance >= self._settings.toast_min_importance
            or len(cluster.labels) >= self._settings.toast_min_sources
        )

    def allow(self, cluster: ClusterView) -> bool:
        """Trả về True và ghi nhận nếu cụm này được phép hiện toast ngay bây giờ."""
        if cluster.id in self._notified or cluster.read or not self.worthy(cluster):
            return False
        now = self._clock()
        while self._shown_at and now - self._shown_at[0] >= HOUR_SECONDS:
            self._shown_at.popleft()
        if len(self._shown_at) >= self._settings.toast_max_per_hour:
            return False
        self._shown_at.append(now)
        self._notified.add(cluster.id)
        return True


_UNSAFE_CHARS = re.compile(r"[^\w .,:;!?()/%+#_\-–…’]", re.UNICODE)
_SAFE_URL = re.compile(r"^https?://[A-Za-z0-9._~:/?#@!*+,;=%()&\-]+$")


def sanitize_toast_text(text: str) -> str:
    """Giữ chữ, số và vài dấu câu; bỏ mọi ký tự còn lại.

    winotify đưa chữ vào một here-string PowerShell và vào XML, nên `$(...)`, dấu backtick,
    `"`, `<`, `]]>`, xuống dòng... đều có thể chèn mã hoặc XML. Tiêu đề bài do người lạ viết.
    """
    text = unicodedata.normalize("NFC", text).replace("'", "’")
    return " ".join(_UNSAFE_CHARS.sub(" ", text).split())


def safe_toast_url(url: str | None) -> str | None:
    """Chỉ nhận http(s) gồm ký tự an toàn (`&` được escape cho XML); còn lại: không có nút."""
    if not url or not _SAFE_URL.match(url):
        return None
    return url.replace("&", "&amp;")


def toast_text(cluster: ClusterView) -> tuple[str, str]:
    title = sanitize_toast_text(cluster.title)[:TOAST_TITLE_CHARS]
    parts = [p for p in (cluster.innovation, cluster.impact) if p]
    body = " ".join(parts) if parts else cluster.source_text
    body = sanitize_toast_text(f"{cluster.source_text}: {body}")[:TOAST_BODY_CHARS]
    return title, body


class Notifier:
    """Toast Windows bằng winotify; lỗi (không phải Windows, thiếu thư viện) chỉ được log."""

    def __init__(self, policy: ToastPolicy, app_id: str = "NeuralRadar") -> None:
        self._policy = policy
        self._app_id = app_id
        self._factory: Any = None

    def _load(self) -> Any:
        if self._factory is None:
            from winotify import Notification

            self._factory = Notification
        return self._factory

    def notify(self, cluster: ClusterView) -> bool:
        if not self._policy.allow(cluster):
            return False
        title, body = toast_text(cluster)
        try:
            toast = self._load()(app_id=self._app_id, title=title, msg=body)
            if url := safe_toast_url(cluster.primary_url):
                toast.add_actions(label="Mở link", launch=url)
            toast.show()
        except Exception:
            logger.exception("Không hiện được toast")
            return False
        return True
