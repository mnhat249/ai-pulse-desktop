from __future__ import annotations

import re
from datetime import UTC, datetime

from pydantic import BaseModel, Field, field_validator

LINK_PATTERN = re.compile(r"(https?://|www\.|\b[\w-]+\.(com|org|net|io|ai|dev|co)\b/)", re.I)


def utcnow() -> datetime:
    return datetime.now(UTC)


class RawItem(BaseModel):
    """Một bài thô từ một nguồn."""

    source: str
    source_id: str
    url: str
    title: str
    text: str = ""
    author: str | None = None
    published_at: datetime
    metrics: dict[str, float] = Field(default_factory=dict)
    links: list[str] = Field(default_factory=list)


class Digest(BaseModel):
    """Thứ LLM được phép trả về. Cố ý không có trường link."""

    cluster_id: int
    title_vi: str
    intro: str | None = None  # tóm tắt cũ (trước khi có trường này) không có
    innovation: str
    impact: str
    importance: int = Field(ge=1, le=5)
    is_noise: bool
    noise_reason: str | None = None

    @field_validator("title_vi", "intro", "innovation", "impact", "noise_reason")
    @classmethod
    def no_links(cls, value: str | None) -> str | None:
        """LLM không được viết link: link của tin luôn lấy từ bài gốc."""
        if value is not None and LINK_PATTERN.search(value):
            raise ValueError("văn bản tóm tắt không được chứa link")
        return value


class Cluster(BaseModel):
    """Một sự kiện, gồm một hoặc nhiều bài."""

    id: int | None = None
    first_seen: datetime
    last_seen: datetime
    importance: float = 0.0
    is_noise: bool = False
    digest: Digest | None = None
    primary_url: str | None = None
