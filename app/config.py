from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import keyring
from pydantic import BaseModel, Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

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
    topics: list[str] = ["llm", "ai-agent", "computer-vision", "mcp", "rag"]
    interval_minutes: int = Field(30, ge=1)
    pushed_within_hours: int = 48
    created_within_days: int = 7
    per_page: int = 30


class HuggingFaceSettings(BaseModel):
    interval_minutes: int = Field(30, ge=1)
    models_limit: int = 50
    papers_limit: int = 50


class HackerNewsSettings(BaseModel):
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


class DedupSettings(BaseModel):
    threshold: float = Field(0.80, ge=0.0, le=1.0)  # tạm; chọn lại bằng scripts/eval_dedup.py
    window_hours: int = 72
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


class NoiseSettings(BaseModel):
    github_min_stars: int = 20
    hf_models_min_likes: int = 5
    hn_min_points: int = 50
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
    github_velocity_scale: float = 100.0  # sao/24h được tính là "nóng tối đa"
    hf_trending_scale: float = 1000.0
    hn_points_scale: float = 300.0


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
    dedup: DedupSettings = DedupSettings()
    noise: NoiseSettings = NoiseSettings()
    llm: LLMSettings = LLMSettings()
    ranking: RankingSettings = RankingSettings()
    ui: UISettings = UISettings()

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
    return Settings(**overrides)
