"""Configuration loading and validation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class AssessmentConfig:
    max_reviews_per_item: int = 50
    max_pages_per_item: int = 5
    request_delay_seconds: float = 1.5
    request_timeout_seconds: float = 20
    repeat_runs: int = 2


@dataclass(frozen=True)
class SteamConfig:
    enabled: bool = True
    app_ids: tuple[str, ...] = ()
    language: str = "english"
    review_type: str = "all"
    purchase_type: str = "all"
    reviews_per_page: int = 20


@dataclass(frozen=True)
class AmazonConfig:
    enabled: bool = True
    review_urls: tuple[str, ...] = ()
    saved_response_files: tuple[str, ...] = ()


@dataclass(frozen=True)
class AppConfig:
    assessment: AssessmentConfig
    steam: SteamConfig
    amazon: AmazonConfig
    path: Path

    def sanitized(self) -> dict[str, Any]:
        """Return config values safe for reports."""
        return {
            "assessment": self.assessment.__dict__,
            "steam": {
                "enabled": self.steam.enabled,
                "app_ids": list(self.steam.app_ids),
                "language": self.steam.language,
                "review_type": self.steam.review_type,
                "purchase_type": self.steam.purchase_type,
                "reviews_per_page": self.steam.reviews_per_page,
            },
            "amazon": {
                "enabled": self.amazon.enabled,
                "review_urls_count": len(self.amazon.review_urls),
                "saved_response_files": list(self.amazon.saved_response_files),
            },
        }


def load_config(path: str | Path) -> AppConfig:
    """Load YAML config with conservative defaults."""
    config_path = Path(path)
    raw: dict[str, Any] = {}
    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or {}
            if not isinstance(loaded, dict):
                raise ValueError("Configuration root must be a mapping.")
            raw = loaded

    assessment_raw = raw.get("assessment", {}) or {}
    steam_raw = raw.get("steam", {}) or {}
    amazon_raw = raw.get("amazon", {}) or {}

    assessment = AssessmentConfig(
        max_reviews_per_item=min(int(assessment_raw.get("max_reviews_per_item", 50)), 50),
        max_pages_per_item=max(1, int(assessment_raw.get("max_pages_per_item", 5))),
        request_delay_seconds=max(1.0, float(assessment_raw.get("request_delay_seconds", 1.5))),
        request_timeout_seconds=float(assessment_raw.get("request_timeout_seconds", 20)),
        repeat_runs=max(1, int(assessment_raw.get("repeat_runs", 2))),
    )
    steam = SteamConfig(
        enabled=bool(steam_raw.get("enabled", True)),
        app_ids=tuple(str(value) for value in steam_raw.get("app_ids", []) if str(value).strip()),
        language=str(steam_raw.get("language", "english")),
        review_type=str(steam_raw.get("review_type", "all")),
        purchase_type=str(steam_raw.get("purchase_type", "all")),
        reviews_per_page=min(max(1, int(steam_raw.get("reviews_per_page", 20))), 50),
    )
    amazon = AmazonConfig(
        enabled=bool(amazon_raw.get("enabled", True)),
        review_urls=tuple(str(value) for value in amazon_raw.get("review_urls", []) if str(value).strip()),
        saved_response_files=tuple(
            str(value) for value in amazon_raw.get("saved_response_files", []) if str(value).strip()
        ),
    )
    return AppConfig(assessment=assessment, steam=steam, amazon=amazon, path=config_path)
