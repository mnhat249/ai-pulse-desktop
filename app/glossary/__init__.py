"""Từ điển thuật ngữ viết tắt (tab "Thuật ngữ"): dữ liệu tĩnh trong `terms_vi.toml`.

Hàm thuần, không phụ thuộc DB hay Tk; file chỉ được đọc một lần lúc khởi động.
"""

from __future__ import annotations

import logging
import re
import tomllib
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

TERMS_FILE = Path(__file__).parent / "terms_vi.toml"
ALL_GROUPS = "Tất cả"
MAX_TERMS_PER_CARD = 4


@dataclass(frozen=True)
class Term:
    term: str
    full: str
    group: str
    vi: str
    example: str
    aliases: tuple[str, ...] = ()
    common: bool = False  # quá phổ biến (AI, API...): không gắn chip trên thẻ tin

    @property
    def taggable(self) -> bool:
        """Chỉ gắn chip cho từ viết tắt (từ hai chữ hoa trở lên) và không quá phổ biến."""
        return not self.common and sum(ch.isupper() for ch in self.term) >= 2


def load_terms(path: Path = TERMS_FILE) -> tuple[Term, ...]:
    """Đọc file thuật ngữ; file thiếu hoặc hỏng thì trả về rỗng (tab Thuật ngữ trống)."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        return tuple(
            Term(
                term=entry["term"],
                full=entry["full"],
                group=entry["group"],
                vi=entry["vi"],
                example=entry.get("example", ""),
                aliases=tuple(entry.get("aliases", ())),
                common=bool(entry.get("common", False)),
            )
            for entry in data.get("term", [])
        )
    except (OSError, tomllib.TOMLDecodeError, KeyError, TypeError):
        logger.exception("Không đọc được file thuật ngữ %s", path)
        return ()


def groups(terms: Iterable[Term]) -> list[str]:
    return [ALL_GROUPS, *dict.fromkeys(t.group for t in terms)]


def _fold(text: str) -> str:
    """Chữ thường, bỏ dấu tiếng Việt: tìm "huan luyen" vẫn ra "huấn luyện"."""
    text = unicodedata.normalize("NFD", text.lower()).replace("đ", "d")
    return "".join(ch for ch in text if unicodedata.category(ch) != "Mn")


def search(terms: Iterable[Term], query: str = "", group: str = ALL_GROUPS) -> list[Term]:
    """Lọc theo nhóm và chữ cần tìm; khớp đúng tên thuật ngữ được đưa lên đầu."""
    needle = _fold(query.strip())
    picked = [t for t in terms if group in (ALL_GROUPS, t.group)]
    if not needle:
        return picked
    exact, partial = [], []
    for t in picked:
        names = [_fold(n) for n in (t.term, *t.aliases)]
        if needle in names:
            exact.append(t)
        elif any(needle in _fold(field) for field in (*names, t.full, t.vi)):
            partial.append(t)
    return exact + partial


def _name_regex(name: str) -> str:
    parts = [re.escape(p) for p in re.split(r"[\s-]+", name.strip()) if p]
    body = r"[\s-]+".join(parts)
    # tên có chữ hoa phân biệt hoa thường ("ReAct" không khớp "React", "ANN" không khớp "Ann");
    # tên toàn chữ thường (alias như "speech-to-text") thì không phân biệt
    if name != name.lower():
        return rf"(?<![^\W_]){body}(?![^\W_])"
    return rf"(?<![^\W_])(?i:{body})(?![^\W_])"


@lru_cache(maxsize=256)
def _pattern(term: Term) -> re.Pattern[str]:
    return re.compile("|".join(_name_regex(n) for n in (term.term, *term.aliases) if n.strip()))


def find_terms(
    text: str, terms: Iterable[Term], limit: int = MAX_TERMS_PER_CARD
) -> tuple[Term, ...]:
    """Các thuật ngữ gắn chip được có mặt trong `text`, theo thứ tự xuất hiện trong bài."""
    hits: list[tuple[int, Term]] = []
    for term in terms:
        if term.taggable and (match := _pattern(term).search(text)):
            hits.append((match.start(), term))
    hits.sort(key=lambda hit: hit[0])
    return tuple(term for _, term in hits[:limit])
