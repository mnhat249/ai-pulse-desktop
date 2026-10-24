"""Giai đoạn 2: khóa chuẩn, vector embedding, lý do rác của cụm.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("clusters", sa.Column("noise_reason", sa.Text))
    op.create_table(
        "item_keys",
        sa.Column(
            "item_id",
            sa.Integer,
            sa.ForeignKey("raw_items.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("key", sa.String(500), primary_key=True),
    )
    op.create_index("ix_item_keys_key", "item_keys", ["key"])
    op.create_table(
        "item_embeddings",
        sa.Column(
            "item_id",
            sa.Integer,
            sa.ForeignKey("raw_items.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("vector", sa.LargeBinary, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("item_embeddings")
    op.drop_index("ix_item_keys_key", table_name="item_keys")
    op.drop_table("item_keys")
    op.drop_column("clusters", "noise_reason")
