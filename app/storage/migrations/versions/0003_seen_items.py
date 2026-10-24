"""Dấu vết các bài đã bị dọn, để bài còn nằm trong feed không bị nạp lại thành tin mới.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

from app.storage.tables import UTCDateTime

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "seen_items",
        sa.Column("source", sa.String(40), primary_key=True),
        sa.Column("source_id", sa.String(200), primary_key=True),
        sa.Column("purged_at", UTCDateTime, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("seen_items")
