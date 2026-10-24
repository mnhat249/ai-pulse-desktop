from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PARAMS = {"fbclid", "gclid", "ref", "ref_src", "source", "mc_cid", "mc_eid", "igshid"}
URL_PATTERN = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)
TRAILING_PUNCTUATION = ".,;:!?"

_GITHUB_REPO = re.compile(r"^/([^/\s]+)/([^/\s]+?)(?:\.git)?(?:/.*)?$")
_GITHUB_RESERVED = {
    "orgs", "topics", "search", "sponsors", "marketplace", "features", "about", "login",
    "settings", "notifications", "explore", "collections", "trending", "pricing", "enterprise",
}  # fmt: skip
_ARXIV = re.compile(r"^/(?:abs|pdf|html)/(\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?/?$")
_ARXIV_OLD = re.compile(r"^/(?:abs|pdf)/([a-z\-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?(?:\.pdf)?/?$")
_HF_PAPER = re.compile(r"^/papers/(\d{4}\.\d{4,5})(?:v\d+)?/?$")
_HF_NON_MODEL = {
    "papers", "datasets", "spaces", "blog", "docs", "models", "collections", "posts", "chat",
    "pricing", "organizations", "settings", "join", "login", "tasks", "learn",
}  # fmt: skip


def _host(netloc: str) -> str:
    host = netloc.lower().split("@")[-1].split(":")[0]
    return host.removeprefix("www.")


def strip_tracking(url: str) -> str:
    """Bỏ `utm_*`, tham số theo dõi và `#...`; chuẩn hóa host, bỏ dấu `/` cuối."""
    parts = urlsplit(url.strip())
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS
    ]
    path = parts.path.rstrip("/") or ""
    scheme = parts.scheme.lower() or "https"
    return urlunsplit((scheme, _host(parts.netloc), path, urlencode(query), ""))


def canonical_key(url: str) -> str:
    """Khóa chuẩn để biết hai URL cùng trỏ về một thứ.

    `github:owner/repo`, `arxiv:2401.01234`, `hf:owner/model`; còn lại là URL đã bỏ theo dõi.
    """
    parts = urlsplit(url.strip())
    host = _host(parts.netloc)
    path = parts.path
    if host == "github.com":
        match = _GITHUB_REPO.match(path)
        if match and match.group(1).lower() not in _GITHUB_RESERVED:
            return f"github:{match.group(1).lower()}/{match.group(2).lower()}"
    elif host in {"arxiv.org", "export.arxiv.org"}:
        for pattern in (_ARXIV, _ARXIV_OLD):
            if match := pattern.match(path):
                return f"arxiv:{match.group(1)}"
    elif host == "huggingface.co":
        if match := _HF_PAPER.match(path):
            return f"arxiv:{match.group(1)}"
        segments = [s for s in path.split("/") if s]
        if len(segments) >= 2 and segments[0].lower() not in _HF_NON_MODEL:
            return f"hf:{segments[0].lower()}/{segments[1].lower()}"
    return strip_tracking(url)


def extract_links(text: str) -> list[str]:
    """Mọi URL có trong nội dung bài, theo thứ tự xuất hiện, không lặp."""
    seen: dict[str, None] = {}
    for raw in URL_PATTERN.findall(text):
        seen.setdefault(raw.rstrip(TRAILING_PUNCTUATION), None)
    return list(seen)


def item_keys(url: str, links: list[str], text: str = "") -> list[str]:
    """Các khóa chuẩn của một bài: URL chính trước, rồi link đi kèm và link trích từ nội dung."""
    keys: dict[str, None] = {}
    for candidate in [url, *links, *extract_links(text)]:
        keys.setdefault(canonical_key(candidate), None)
    return list(keys)
