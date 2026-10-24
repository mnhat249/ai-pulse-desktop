from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy import Column as C
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator[datetime]):
    """Lưu UTC không múi giờ trong SQLite, trả về datetime có múi giờ UTC."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("datetime phải có múi giờ")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: Any, dialect: Dialect) -> datetime | None:
        return None if value is None else value.replace(tzinfo=UTC)


metadata = MetaData()

raw_items = Table(
    "raw_items",
    metadata,
    C("id", Integer, primary_key=True),
    C("source", String(40), nullable=False),
    C("source_id", String(200), nullable=False),
    C("url", Text, nullable=False),
    C("url_norm", Text),
    C("title", Text, nullable=False),
    C("text", Text, nullable=False, default=""),
    C("author", String(200)),
    C("published_at", UTCDateTime, nullable=False),
    C("fetched_at", UTCDateTime, nullable=False),
    C("links", JSON, nullable=False),
    UniqueConstraint("source", "source_id", name="uq_raw_items_source_sid"),
)

metric_snapshots = Table(
    "metric_snapshots",
    metadata,
    C("id", Integer, primary_key=True),
    C("item_id", Integer, ForeignKey("raw_items.id", ondelete="CASCADE"), nullable=False),
    C("metric", String(60), nullable=False),
    C("value", Float, nullable=False),
    C("captured_at", UTCDateTime, nullable=False),
    Index("ix_metric_snapshots_item_metric_time", "item_id", "metric", "captured_at"),
)

clusters = Table(
    "clusters",
    metadata,
    C("id", Integer, primary_key=True),
    C("first_seen", UTCDateTime, nullable=False),
    C("last_seen", UTCDateTime, nullable=False),
    C("importance", Float, nullable=False, default=0.0),
    C("is_noise", Boolean, nullable=False, default=False),
    C("digest", JSON),
    C("primary_url", Text),
    C("noise_reason", Text),
)

cluster_items = Table(
    "cluster_items",
    metadata,
    C("cluster_id", Integer, ForeignKey("clusters.id", ondelete="CASCADE"), primary_key=True),
    C("item_id", Integer, ForeignKey("raw_items.id", ondelete="CASCADE"), primary_key=True),
)

user_state = Table(
    "user_state",
    metadata,
    C("cluster_id", Integer, primary_key=True),
    C("read_at", UTCDateTime),
    C("bookmarked", Boolean, nullable=False, default=False),
)

source_runs = Table(
    "source_runs",
    metadata,
    C("id", Integer, primary_key=True),
    C("source", String(40), nullable=False),
    C("started_at", UTCDateTime, nullable=False),
    C("ok", Boolean, nullable=False),
    C("item_count", Integer, nullable=False, default=0),
    C("error", Text),
    Index("ix_source_runs_source_started", "source", "started_at"),
)

llm_usage = Table(
    "llm_usage",
    metadata,
    C("id", Integer, primary_key=True),
    C("day", String(10), nullable=False),
    C("provider", String(40), nullable=False),
    C("calls", Integer, nullable=False, default=0),
    UniqueConstraint("day", "provider", name="uq_llm_usage_day_provider"),
)

item_keys = Table(
    "item_keys",
    metadata,
    C("item_id", Integer, ForeignKey("raw_items.id", ondelete="CASCADE"), primary_key=True),
    C("key", String(500), primary_key=True),
    Index("ix_item_keys_key", "key"),
)

item_embeddings = Table(
    "item_embeddings",
    metadata,
    C("item_id", Integer, ForeignKey("raw_items.id", ondelete="CASCADE"), primary_key=True),
    C("model", String(200), nullable=False),
    C("vector", LargeBinary, nullable=False),
)
