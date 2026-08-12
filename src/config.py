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
class GooglePlayConfig:
    enabled: bool = True
    app_name: str = "YouTube"
    package_id: str = "com.google.android.youtube"
    country: str = "us"
    language: str = "en"
    reviews_per_batch: int = 50


@dataclass(frozen=True)
class AppleAppStoreTarget:
    app_name: str
    app_id: str
    country: str = "us"
    language: str = "en"
    category: str | None = None


@dataclass(frozen=True)
class AppleAppStoreConfig:
    enabled: bool = True
    app_name: str = "YouTube"
    app_id: str = "544007664"
    country: str = "us"
    language: str = "en"
    reviews_per_page: int = 50
    validation_targets: tuple[AppleAppStoreTarget, ...] = ()
    validation_reviews_per_target: int = 1000
    validation_total_reviews: int = 10000
    validation_max_pages_per_target: int = 20
    validation_low_signal_min_text_length: int = 15
    validation_output_dir: str = "apple_app_store_validation"


@dataclass(frozen=True)
class AppConfig:
    assessment: AssessmentConfig
    steam: SteamConfig
    amazon: AmazonConfig
    google_play: GooglePlayConfig
    apple_app_store: AppleAppStoreConfig
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
            "google_play": {
                "enabled": self.google_play.enabled,
                "app_name": self.google_play.app_name,
                "package_id": self.google_play.package_id,
                "country": self.google_play.country,
                "language": self.google_play.language,
                "reviews_per_batch": self.google_play.reviews_per_batch,
            },
            "apple_app_store": {
                "enabled": self.apple_app_store.enabled,
                "app_name": self.apple_app_store.app_name,
                "app_id": self.apple_app_store.app_id,
                "country": self.apple_app_store.country,
                "language": self.apple_app_store.language,
                "reviews_per_page": self.apple_app_store.reviews_per_page,
                "validation_targets": [
                    {
                        "app_name": target.app_name,
                        "app_id": target.app_id,
                        "country": target.country,
                        "language": target.language,
                        "category": target.category,
                    }
                    for target in self.apple_app_store.validation_targets
                ],
                "validation_reviews_per_target": self.apple_app_store.validation_reviews_per_target,
                "validation_total_reviews": self.apple_app_store.validation_total_reviews,
                "validation_max_pages_per_target": self.apple_app_store.validation_max_pages_per_target,
                "validation_low_signal_min_text_length": self.apple_app_store.validation_low_signal_min_text_length,
                "validation_output_dir": self.apple_app_store.validation_output_dir,
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
    google_play_raw = raw.get("google_play", {}) or {}
    apple_raw = raw.get("apple_app_store", {}) or {}

    assessment = AssessmentConfig(
        max_reviews_per_item=min(int(assessment_raw.get("max_reviews_per_item", 100)), 100),
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
    google_play = GooglePlayConfig(
        enabled=bool(google_play_raw.get("enabled", True)),
        app_name=str(google_play_raw.get("app_name", "YouTube")),
        package_id=str(google_play_raw.get("package_id", "com.google.android.youtube")),
        country=str(google_play_raw.get("country", "us")).lower(),
        language=str(google_play_raw.get("language", "en")).lower(),
        reviews_per_batch=min(max(1, int(google_play_raw.get("reviews_per_batch", 50))), 100),
    )
    apple_app_store = AppleAppStoreConfig(
        enabled=bool(apple_raw.get("enabled", True)),
        app_name=str(apple_raw.get("app_name", "YouTube")),
        app_id=str(apple_raw.get("app_id", "544007664")),
        country=str(apple_raw.get("country", "us")).lower(),
        language=str(apple_raw.get("language", "en")).lower(),
        reviews_per_page=min(max(1, int(apple_raw.get("reviews_per_page", 50))), 100),
        validation_targets=_load_apple_validation_targets(apple_raw),
        validation_reviews_per_target=min(max(1, int(apple_raw.get("validation_reviews_per_target", 1000))), 10000),
        validation_total_reviews=min(max(1, int(apple_raw.get("validation_total_reviews", 10000))), 50000),
        validation_max_pages_per_target=min(max(1, int(apple_raw.get("validation_max_pages_per_target", 20))), 100),
        validation_low_signal_min_text_length=max(
            1, int(apple_raw.get("validation_low_signal_min_text_length", 15))
        ),
        validation_output_dir=str(apple_raw.get("validation_output_dir", "apple_app_store_validation")),
    )
    return AppConfig(
        assessment=assessment,
        steam=steam,
        amazon=amazon,
        google_play=google_play,
        apple_app_store=apple_app_store,
        path=config_path,
    )


def _load_apple_validation_targets(raw: dict[str, Any]) -> tuple[AppleAppStoreTarget, ...]:
    """Load optional multi-app Apple validation targets."""
    targets_raw = raw.get("validation_targets") or raw.get("apps") or []
    if not targets_raw:
        app_id = str(raw.get("app_id", "544007664"))
        if app_id and not app_id.startswith("APPLE_APP_ID"):
            return (
                AppleAppStoreTarget(
                    app_name=str(raw.get("app_name", "YouTube")),
                    app_id=app_id,
                    country=str(raw.get("country", "us")).lower(),
                    language=str(raw.get("language", "en")).lower(),
                    category=str(raw["category"]) if raw.get("category") else None,
                ),
            )
        return ()
    if not isinstance(targets_raw, list):
        raise ValueError("apple_app_store.validation_targets must be a list.")

    targets: list[AppleAppStoreTarget] = []
    for index, item in enumerate(targets_raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"apple_app_store.validation_targets[{index}] must be a mapping.")
        app_id = str(item.get("app_id", "")).strip()
        if not app_id or app_id.startswith("APPLE_APP_ID"):
            continue
        targets.append(
            AppleAppStoreTarget(
                app_name=str(item.get("app_name", app_id)),
                app_id=app_id,
                country=str(item.get("country", raw.get("country", "us"))).lower(),
                language=str(item.get("language", raw.get("language", "en"))).lower(),
                category=str(item["category"]) if item.get("category") else None,
            )
        )
    return tuple(targets)
