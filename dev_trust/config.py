"""Configuration management using Pydantic settings."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # GitHub API
    github_token: Optional[str] = None
    github_api_url: str = "https://api.github.com"

    # Cache
    cache_dir: Path = Path.home() / ".dev_trust_cache"
    cache_ttl_hours: int = 24

    # Analysis
    min_confidence_threshold: float = 0.5
    sample_size: Optional[int] = None  # type: ignore[assignment]
    analysis_window_days: int = 90

    # Output
    output_format: str = "text"  # text, json, markdown
    output_file: Optional[Path] = None
    verbose: bool = False
    no_cache: bool = False

    @field_validator("sample_size", mode="before")
    @classmethod
    def empty_str_to_none(cls, v: object) -> object:
        """Convert empty strings to None for sample_size."""
        if v == "" or v is None:
            return None
        return v

    @property
    def cache_enabled(self) -> bool:
        """Check if caching is enabled."""
        return not self.no_cache


def get_settings() -> Settings:
    """Get application settings singleton."""
    return Settings()


# Global settings instance
settings = get_settings()
