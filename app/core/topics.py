"""Chủ đề tin (Model AI, Claude, AI tạo ảnh/video): khớp từ khóa nguyên từ.

Hàm thuần, không phụ thuộc DB hay Tk. Từ khóa được so khớp theo ranh giới từ (`flux` không
khớp `fluxion`, `veo` không khớp `video`); dấu cách trong từ khóa khớp cả dấu gạch nối.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class TopicRule:
    key: str
    label: str
    keywords: tuple[str, ...]
    patterns: tuple[str, ...] = ()  # regex nguyên văn (không phân biệt hoa thường), cho dạng số
    sources: tuple[str, ...] = ()  # nguồn luôn thuộc chủ đề này


# 7B, 70B, 1.5B...; "$5B" (tiền) không tính. "agent-7b" khớp vì gạch nối không phải chữ
_PARAM_COUNT = r"(?<![\w.$€£])\d{1,3}(?:\.\d)?b(?![^\W_])"

DEFAULT_RULES: tuple[TopicRule, ...] = (
    TopicRule(
        key="models",
        label="Model AI",
        keywords=(
            "gpt",
            "gemini",
            "gemma",
            "llama",
            "qwen",
            "mistral",
            "mixtral",
            "deepseek",
            "kimi",
            "open weight",
            "open weights",
            "open-weight model",
            "checkpoint",
            "benchmark",
            "model release",
            "new model",
        ),
        patterns=(_PARAM_COUNT,),
        sources=("hf_models",),
    ),
    TopicRule(
        key="claude",
        label="Claude",
        keywords=("claude", "anthropic", "claude code", "sonnet", "mcp"),
        patterns=(r"(?<!\w)(?:opus|haiku)[\s-]*\d",),
    ),
    TopicRule(
        key="aigi",
        label="AI tạo ảnh/video",
        keywords=(
            "diffusion",
            "stable diffusion",
            "sdxl",
            "flux",
            "black forest labs",
            "midjourney",
            "dall-e",
            "dall·e",
            "dalle",
            "imagen",
            "sora",
            "veo",
            "runwayml",
            "runway gen",
            "kling",
            "comfyui",
            "text-to-image",
            "text-to-video",
            "image-to-video",
            "image generation",
            "video generation",
            "image generator",
            "video generator",
        ),
    ),
)

DEFAULT_KEYS: tuple[str, ...] = tuple(rule.key for rule in DEFAULT_RULES)


def _keyword_regex(keyword: str) -> str:
    parts = [re.escape(p) for p in re.split(r"[\s-]+", keyword.strip().lower()) if p]
    return r"[\s-]+".join(parts)


_BOUNDARY_BEFORE = r"(?<![^\W_])"  # không đứng sau chữ hoặc số
_BOUNDARY_AFTER = r"(?![^\W_])"


@lru_cache(maxsize=64)
def _compile(rule: TopicRule) -> re.Pattern[str] | None:
    alternatives = [
        _BOUNDARY_BEFORE + _keyword_regex(k) + _BOUNDARY_AFTER for k in rule.keywords if k.strip()
    ]
    alternatives += rule.patterns
    if not alternatives:
        return None
    return re.compile("|".join(alternatives), re.IGNORECASE)


def match_topics(
    text: str, rules: Iterable[TopicRule] = DEFAULT_RULES, sources: Iterable[str] = ()
) -> tuple[str, ...]:
    """Khóa các chủ đề khớp với `text` (theo thứ tự luật); `sources` là nguồn của bài/cụm."""
    source_set = set(sources)
    found: list[str] = []
    for rule in rules:
        pattern = _compile(rule)
        if source_set.intersection(rule.sources) or (pattern and pattern.search(text)):
            found.append(rule.key)
    return tuple(found)
