from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from app.core.topics import DEFAULT_KEYS, DEFAULT_RULES, TopicRule
from app.storage import ui_queries
from app.storage.ui_queries import ClusterFilter, ClusterView, SourceStatusView

ALL_SOURCES = "Mọi nguồn"
MY_TOPICS = "★ Của tôi"
ALL_TOPICS = "Mọi chủ đề"
FILTER_LABELS: dict[str, ClusterFilter] = {
    "Tất cả": "all",
    "Chưa đọc": "unread",
    "Bookmark": "bookmarked",
}


@dataclass
class UIModel:
    """Trạng thái bộ lọc và dữ liệu của widget; không phụ thuộc Tk nên test được."""

    reader: sqlite3.Connection
    limit: int = 30  # tổng số tin tối đa (mọi trang cộng lại)
    page_size: int = 6
    page: int = 0  # bắt đầu từ 0
    view: ClusterFilter = "all"
    source: str | None = None
    expanded: set[int] = field(default_factory=set)
    rules: tuple[TopicRule, ...] = DEFAULT_RULES
    enabled_topics: tuple[str, ...] = DEFAULT_KEYS
    topic: str = MY_TOPICS  # nhãn đang chọn: MY_TOPICS, ALL_TOPICS hoặc nhãn một chủ đề
    _total: int | None = field(default=None, init=False, repr=False)

    def set_filter_label(self, label: str) -> None:
        self.view = FILTER_LABELS.get(label, "all")
        self.page, self._total = 0, None

    def set_source_label(self, label: str) -> None:
        self.source = None if label == ALL_SOURCES else label
        self.page, self._total = 0, None

    def topic_choices(self) -> list[str]:
        labels = [r.label for r in self.rules if r.key in self.enabled_topics]
        return [MY_TOPICS, ALL_TOPICS, *labels]

    def set_topic_label(self, label: str) -> None:
        """Nhãn lạ (ví dụ chủ đề đã bị tắt trong cài đặt) quay về "★ Của tôi"."""
        self.topic = label if label in self.topic_choices() else MY_TOPICS
        self.page, self._total = 0, None

    def topic_keys(self) -> tuple[str, ...] | None:
        """Khóa chủ đề dùng để lọc; None = không lọc."""
        if self.topic == ALL_TOPICS:
            return None
        if self.topic == MY_TOPICS:
            return self.enabled_topics or None
        return tuple(r.key for r in self.rules if r.label == self.topic) or None

    def total(self) -> int:
        """Đọc lại số tin khớp bộ lọc (tối đa `limit`) và nhớ cho `page_count`."""
        self._total = ui_queries.count_clusters(
            self.reader,
            view=self.view,
            source=self.source,
            topics=self.topic_keys(),
            topic_rules=self.rules,
            cap=self.limit,
        )
        return self._total

    def page_count(self) -> int:
        """Số trang theo lần đọc gần nhất (`clusters()` đọc lại), để thanh trang không quét DB."""
        total = self._total if self._total is not None else self.total()
        return max(1, -(-total // self.page_size))

    def next_page(self) -> bool:
        if self.page + 1 >= self.page_count():
            return False
        self.page += 1
        return True

    def prev_page(self) -> bool:
        if self.page == 0:
            return False
        self.page -= 1
        return True

    def clusters(self) -> list[ClusterView]:
        """Tin của trang hiện tại; trang vượt quá (vừa đọc hết trang cuối) lùi về trang cuối."""
        self.total()
        self.page = min(self.page, self.page_count() - 1)
        offset = self.page * self.page_size
        return ui_queries.list_clusters(
            self.reader,
            view=self.view,
            source=self.source,
            limit=max(0, min(self.page_size, self.limit - offset)),
            offset=offset,
            topics=self.topic_keys(),
            topic_rules=self.rules,
        )

    def cluster(self, cluster_id: int) -> ClusterView | None:
        return ui_queries.get_cluster(self.reader, cluster_id)

    def source_choices(self) -> list[str]:
        return [ALL_SOURCES, *ui_queries.list_sources(self.reader)]

    def unread_count(self) -> int:
        return ui_queries.count_unread(self.reader)

    def statuses(self) -> list[SourceStatusView]:
        return ui_queries.source_statuses(self.reader)

    def last_error(self, source: str) -> str | None:
        return ui_queries.last_error(self.reader, source)

    def toggle_expanded(self, cluster_id: int) -> bool:
        if cluster_id in self.expanded:
            self.expanded.discard(cluster_id)
            return False
        self.expanded.add(cluster_id)
        return True
