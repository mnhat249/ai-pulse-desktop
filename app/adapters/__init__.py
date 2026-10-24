"""Mỗi adapter nằm trong một file và tự đăng ký thông tin trình bày ở `app.core.sources`.

Thêm nguồn mới: một file adapter, một dòng import ở đây, một mục trong cài đặt.
"""

from app.adapters import bluesky, github, hackernews, huggingface, rss

__all__ = ["bluesky", "github", "hackernews", "huggingface", "rss"]
