"""Bảng ban đầu: 7 bảng của giai đoạn 0.

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op

from app.storage.tables import UTCDateTime

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "raw_items",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("source_id", sa.String(200), nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("url_norm", sa.Text),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("author", sa.String(200)),
        sa.Column("published_at", UTCDateTime, nullable=False),
        sa.Column("fetched_at", UTCDateTime, nullable=False),
        sa.Column("links", sa.JSON, nullable=False),
        sa.UniqueConstraint("source", "source_id", name="uq_raw_items_source_sid"),
    )
    op.create_table(
        "metric_snapshots",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "item_id",
            sa.Integer,
            sa.ForeignKey("raw_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("metric", sa.String(60), nullable=False),
        sa.Column("value", sa.Float, nullable=False),
        sa.Column("captured_at", UTCDateTime, nullable=False),
    )
    op.create_index(
        "ix_metric_snapshots_item_metric_time",
        "metric_snapshots",
        ["item_id", "metric", "captured_at"],
    )
    op.create_table(
        "clusters",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("first_seen", UTCDateTime, nullable=False),
        sa.Column("last_seen", UTCDateTime, nullable=False),
        sa.Column("importance", sa.Float, nullable=False),
        sa.Column("is_noise", sa.Boolean, nullable=False),
        sa.Column("digest", sa.JSON),
        sa.Column("primary_url", sa.Text),
    )
    op.create_table(
        "cluster_items",
        sa.Column(
            "cluster_id",
            sa.Integer,
            sa.ForeignKey("clusters.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "item_id",
            sa.Integer,
            sa.ForeignKey("raw_items.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_table(
        "user_state",
        sa.Column("cluster_id", sa.Integer, primary_key=True),
        sa.Column("read_at", UTCDateTime),
        sa.Column("bookmarked", sa.Boolean, nullable=False),
    )
    op.create_table(
        "source_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("started_at", UTCDateTime, nullable=False),
        sa.Column("ok", sa.Boolean, nullable=False),
        sa.Column("item_count", sa.Integer, nullable=False),
        sa.Column("error", sa.Text),
    )
    op.create_index("ix_source_runs_source_started", "source_runs", ["source", "started_at"])
    op.create_table(
        "llm_usage",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("day", sa.String(10), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("calls", sa.Integer, nullable=False),
        sa.UniqueConstraint("day", "provider", name="uq_llm_usage_day_provider"),
    )


def downgrade() -> None:
    for table in (
        "llm_usage",
        "source_runs",
        "user_state",
        "cluster_items",
        "clusters",
        "metric_snapshots",
        "raw_items",
    ):
        op.drop_table(table)
