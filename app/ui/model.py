from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from app.core.topics import DEFAULT_KEYS, DEFAULT_RULES, TopicRule
from app.storage import ui_queries
from app.storage.ui_queries import ClusterFilter, ClusterView, SourceStatusView

ALL_SOURCES = "Mọi nguồn"
MY_TOPICS = "Chủ đề của tôi"
ALL_TOPICS = "Tất cả chủ đề"
FILTER_LABELS: dict[str, ClusterFilter] = {
    "Tất cả": "all",
    "Chưa đọc": "unread",
    "Bookmark": "bookmarked",
}


@dataclass
class UIModel:
    """Trạng thái bộ lọc và dữ liệu của widget; không phụ thuộc Tk nên test được."""

    reader: sqlite3.Connection
    limit: int = 30
    view: ClusterFilter = "all"
    source: str | None = None
    expanded: set[int] = field(default_factory=set)
    rules: tuple[TopicRule, ...] = DEFAULT_RULES
    enabled_topics: tuple[str, ...] = DEFAULT_KEYS
    topic: str = MY_TOPICS  # nhãn đang chọn: MY_TOPICS, ALL_TOPICS hoặc nhãn một chủ đề

    def set_filter_label(self, label: str) -> None:
        self.view = FILTER_LABELS.get(label, "all")

    def set_source_label(self, label: str) -> None:
        self.source = None if label == ALL_SOURCES else label

    def topic_choices(self) -> list[str]:
        labels = [r.label for r in self.rules if r.key in self.enabled_topics]
        return [MY_TOPICS, ALL_TOPICS, *labels]

    def set_topic_label(self, label: str) -> None:
        """Nhãn lạ (ví dụ chủ đề đã bị tắt trong cài đặt) quay về "Chủ đề của tôi"."""
        self.topic = label if label in self.topic_choices() else MY_TOPICS

    def topic_keys(self) -> tuple[str, ...] | None:
        """Khóa chủ đề dùng để lọc; None = không lọc."""
        if self.topic == ALL_TOPICS:
            return None
        if self.topic == MY_TOPICS:
            return self.enabled_topics or None
        return tuple(r.key for r in self.rules if r.label == self.topic) or None

    def clusters(self) -> list[ClusterView]:
        return ui_queries.list_clusters(
            self.reader,
            view=self.view,
            source=self.source,
            limit=self.limit,
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
