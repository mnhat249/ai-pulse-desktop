from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from app.storage import ui_queries
from app.storage.ui_queries import ClusterFilter, ClusterView, SourceStatusView

ALL_SOURCES = "Mọi nguồn"
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

    def set_filter_label(self, label: str) -> None:
        self.view = FILTER_LABELS.get(label, "all")

    def set_source_label(self, label: str) -> None:
        self.source = None if label == ALL_SOURCES else label

    def clusters(self) -> list[ClusterView]:
        return ui_queries.list_clusters(
            self.reader, view=self.view, source=self.source, limit=self.limit
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
