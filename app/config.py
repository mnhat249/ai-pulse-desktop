from __future__ import annotations

import logging
import os
import re
import tomllib
import unicodedata
from pathlib import Path
from typing import Any

import keyring
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

logger = logging.getLogger(__name__)

KEYRING_SERVICE = "NeuralRadar"
SECRET_NAMES = ("gemini", "groq", "github")


def app_home() -> Path:
    """Thư mục dữ liệu: `%APPDATA%\\NeuralRadar` (đổi bằng NEURALRADAR_HOME khi test)."""
    override = os.environ.get("NEURALRADAR_HOME")
    if override:
        return Path(override)
    base = os.environ.get("APPDATA")
    return (Path(base) if base else Path.home() / ".config") / "NeuralRadar"


def get_secret(name: str) -> str | None:
    return keyring.get_password(KEYRING_SERVICE, name)


def set_secret(name: str, value: str) -> None:
    keyring.set_password(KEYRING_SERVICE, name, value)


class GitHubSettings(BaseModel):
    enabled: bool = True
    topics: list[str] = ["llm", "ai-agent", "computer-vision", "mcp", "rag"]
    interval_minutes: int = Field(30, ge=1)
    pushed_within_hours: int = 48
    created_within_days: int = 7
    per_page: int = 30


class HuggingFaceSettings(BaseModel):
    enabled: bool = True
    interval_minutes: int = Field(30, ge=1)
    models_limit: int = 50
    papers_limit: int = 50


class HackerNewsSettings(BaseModel):
    enabled: bool = True
    interval_minutes: int = Field(15, ge=1)
    min_points: int = 50
    lookback_hours: int = 48
    keywords: list[str] = [
        "llm",
        "ai",
        "gpt",
        "claude",
        "gemini",
        "openai",
        "anthropic",
        "diffusion",
        "transformer",
        "neural",
        "machine learning",
    ]


def feed_slug(name: str) -> str:
    """Tên nguồn ổn định, chỉ gồm a-z, 0-9 và `_` (bỏ dấu tiếng Việt)."""
    plain = unicodedata.normalize("NFKD", name.replace("đ", "d").replace("Đ", "D"))
    ascii_name = plain.encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", ascii_name.lower()).strip("_") or "feed"


class FeedSettings(BaseModel):
    """Một feed RSS: thêm nguồn mới chỉ cần thêm một mục `[[rss]]` trong settings.toml."""

    name: str
    url: str
    interval_minutes: int = Field(60, ge=1)
    max_entries: int = Field(30, ge=1, le=200)  # feed có thể có hàng nghìn bài cũ
    enabled: bool = True


DEFAULT_FEEDS = [
    FeedSettings(name="ainews", url="https://news.smol.ai/rss.xml", interval_minutes=120),
    FeedSettings(name="hf_blog", url="https://huggingface.co/blog/feed.xml"),
    FeedSettings(name="openai", url="https://openai.com/news/rss.xml"),
    FeedSettings(name="deepmind", url="https://deepmind.google/blog/rss.xml"),
    FeedSettings(name="google_ai", url="https://blog.google/technology/ai/rss/"),
]


class BlueskySettings(BaseModel):
    enabled: bool = True
    interval_minutes: int = Field(30, ge=1)
    handles: list[str] = [
        "simonwillison.net",
        "karpathy.bsky.social",
        "swyx.io",
        "hardmaru.bsky.social",
        "emollick.bsky.social",
    ]
    per_handle_limit: int = Field(30, ge=1, le=100)
    keywords: list[str] = HackerNewsSettings().keywords


class MaintenanceSettings(BaseModel):
    retention_days: int = Field(30, ge=1)  # xóa cụm cũ hơn mức này (trừ bookmark)
    backups_to_keep: int = Field(7, ge=1)
    backup_every_days: int = Field(7, ge=1)
    vacuum_every_days: int = Field(7, ge=1)
    tombstone_days: int = Field(180, ge=1)  # nhớ bài đã dọn bao lâu để không nạp lại thành tin mới


class DedupSettings(BaseModel):
    threshold: float = Field(0.80, ge=0.0, le=1.0)  # tạm; chọn lại bằng scripts/eval_dedup.py
    window_hours: int = 72
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


class NoiseSettings(BaseModel):
    # ngưỡng tối thiểu theo nguồn: {nguồn: {chỉ số: giá trị}}; nguồn không có mục thì không lọc
    thresholds: dict[str, dict[str, float]] = {
        "github": {"stars": 20},
        "hf_models": {"likes": 5},
        "hackernews": {"points": 50},
        "bluesky": {"likes": 20},
    }
    min_title_chars: int = 8
    spam_keywords: list[str] = [
        "giveaway",
        "airdrop",
        "online course",
        "free course",
        "bootcamp",
        "discount code",
        "coupon",
        "promo code",
        "free trial",
        "sign up now",
        "buy now",
        "limited offer",
        "khóa học",
        "khuyến mãi",
    ]


class LLMSettings(BaseModel):
    gemini_model: str = "gemini-2.0-flash"
    groq_model: str = "llama-3.3-70b-versatile"
    batch_size: int = Field(8, ge=1, le=10)
    gemini_daily_cap: int = 100  # thấp hơn mức free tier
    groq_daily_cap: int = 100
    max_text_chars: int = 1200


class RankingSettings(BaseModel):
    heat_weight: float = 0.4
    spread_weight: float = 0.3
    llm_weight: float = 0.3
    # giá trị của chỉ số "độ nóng" (xem SourceInfo.heat_metric) được tính là nóng tối đa
    heat_scales: dict[str, float] = {
        "github": 100.0,  # sao tăng trong 24 giờ
        "hf_models": 1000.0,  # trendingScore
        "hf_papers": 50.0,  # upvotes
        "hackernews": 300.0,  # điểm
        "bluesky": 200.0,  # lượt thích
    }


class UISettings(BaseModel):
    toast_min_importance: float = 70.0
    toast_min_sources: int = 3
    toast_max_per_hour: int = 4
    always_on_top: bool = True
    max_clusters_shown: int = 30
    process_interval_minutes: int = Field(5, ge=1)


class Settings(BaseSettings):
    """Đọc từ `settings.toml` trong thư mục dữ liệu; khóa API đọc riêng từ keyring."""

    model_config = SettingsConfigDict(extra="ignore")

    request_timeout_seconds: float = 20.0
    failure_pause_threshold: int = 3
    failure_pause_minutes: int = 120
    github: GitHubSettings = GitHubSettings()
    huggingface: HuggingFaceSettings = HuggingFaceSettings()
    hackernews: HackerNewsSettings = HackerNewsSettings()
    rss: list[FeedSettings] = DEFAULT_FEEDS
    bluesky: BlueskySettings = BlueskySettings()
    maintenance: MaintenanceSettings = MaintenanceSettings()
    start_with_windows: bool = False
    dedup: DedupSettings = DedupSettings()
    noise: NoiseSettings = NoiseSettings()
    llm: LLMSettings = LLMSettings()
    ranking: RankingSettings = RankingSettings()
    ui: UISettings = UISettings()

    @field_validator("rss")
    @classmethod
    def drop_invalid_feeds(cls, feeds: list[FeedSettings]) -> list[FeedSettings]:
        """Bỏ feed sai (không phải http/https, trùng tên nguồn) và log, không làm app hỏng."""
        seen: set[str] = set()
        kept: list[FeedSettings] = []
        for feed in feeds:
            slug = feed_slug(feed.name)
            if not feed.url.lower().startswith(("http://", "https://")):
                logger.warning(
                    "Bỏ feed '%s': URL phải bắt đầu bằng http:// hoặc https://", feed.name
                )
            elif slug in seen:
                logger.warning(
                    "Bỏ feed '%s': trùng tên nguồn rss_%s với feed trước đó", feed.name, slug
                )
            else:
                seen.add(slug)
                kept.append(feed)
        return kept

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        toml = TomlConfigSettingsSource(settings_cls, toml_file=app_home() / "settings.toml")
        return (init_settings, toml)

    @property
    def db_path(self) -> Path:
        return app_home() / "neuralradar.db"

    @property
    def log_dir(self) -> Path:
        return app_home() / "logs"

    @property
    def backup_dir(self) -> Path:
        return app_home() / "backups"


def load_settings(**overrides: Any) -> Settings:
    """Đọc cài đặt; `settings.toml` hỏng thì đổi tên thành `.bad` và dùng giá trị mặc định."""
    try:
        return Settings(**overrides)
    except tomllib.TOMLDecodeError:
        path = app_home() / "settings.toml"
        bad = path.with_suffix(".toml.bad")
        logger.error("settings.toml hỏng, đã đổi tên thành %s và dùng cài đặt mặc định", bad.name)
        try:
            os.replace(path, bad)
        except OSError:
            logger.exception("Không đổi tên được settings.toml hỏng")
        return Settings(**overrides)
