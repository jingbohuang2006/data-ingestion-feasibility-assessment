from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

import src.apple_app_store_validation as validation
from src.apple_app_store_validation import build_apple_validation_eda, run_apple_app_store_validation
from src.config import AppConfig, AppleAppStoreConfig, AssessmentConfig, load_config
from src.config import AmazonConfig, GooglePlayConfig, SteamConfig
from src.http_utils import HttpResult
from src.models import NormalizedReview, RequestRecord


def test_multi_app_apple_config_loads_validation_targets(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
apple_app_store:
  validation_total_reviews: 10000
  validation_reviews_per_target: 1000
  validation_targets:
    - app_name: Spotify
      app_id: "324684580"
      country: us
      language: en
      category: music
    - app_name: Duolingo
      app_id: "570060128"
      country: gb
      language: en
      category: education
""",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert len(config.apple_app_store.validation_targets) == 2
    assert config.apple_app_store.validation_targets[0].app_name == "Spotify"
    assert config.apple_app_store.validation_targets[1].country == "gb"
    assert config.apple_app_store.validation_total_reviews == 10000


def test_validation_outputs_are_isolated_and_do_not_overwrite_phase2(monkeypatch, tmp_path: Path) -> None:
    _patch_fake_apple_session(monkeypatch, [_payload("a-1"), _payload("a-1")])
    phase2_path = tmp_path / "data" / "processed" / "apple_app_store_reviews.csv"
    phase2_path.parent.mkdir(parents=True)
    phase2_path.write_text("sentinel\n", encoding="utf-8")
    config = _validation_config()

    first = run_apple_app_store_validation(config, tmp_path, run_id="small-test", max_reviews=1)
    second = run_apple_app_store_validation(config, tmp_path, run_id="small-test", max_reviews=1)

    assert phase2_path.read_text(encoding="utf-8") == "sentinel\n"
    assert first.run_id == "small-test"
    assert second.run_id == "small-test_2"
    assert (first.processed_dir / "apple_app_store_validation_reviews.csv").exists()
    assert (second.reports_dir / "apple_app_store_validation_eda.md").exists()


def test_eda_metric_calculations_cover_required_tables() -> None:
    reviews = [
        NormalizedReview(
            source="apple_app_store",
            app_name="App A",
            item_id="1",
            review_id="r1",
            review_text="Great app",
            rating=5,
            review_date="2026-01-01T00:00:00Z",
            country="us",
            language="en",
        ),
        NormalizedReview(
            source="apple_app_store",
            app_name="App A",
            item_id="1",
            review_id="r2",
            review_text="ok",
            rating=3,
            review_date=None,
            country="us",
            language="en",
        ),
    ]

    eda = build_apple_validation_eda(reviews, [], low_signal_min_text_length=5)

    volume = eda["review_volume_by_app"].iloc[0]
    text = eda["review_text_length"].iloc[0]
    dates = eda["date_coverage"].iloc[0]
    missing_rating = eda["missing_fields"].query("field == 'review_date'").iloc[0]

    assert volume["review_count"] == 2
    assert volume["unique_review_count"] == 2
    assert text["low_signal_review_count"] == 1
    assert dates["undated_review_count"] == 1
    assert missing_rating["missing_count"] == 1
    assert set(eda) >= {
        "rating_distribution",
        "duplicate_records",
        "language_region_issues",
        "pagination_depth_and_failures",
        "low_signal_reviews",
    }


def test_validation_records_pagination_and_empty_page(monkeypatch, tmp_path: Path) -> None:
    _patch_fake_apple_session(monkeypatch, [_payload("p1"), _empty_payload()])
    config = _validation_config(max_pages=3)

    result = run_apple_app_store_validation(config, tmp_path, run_id="empty-page", max_reviews=10)

    assert len(result.reviews) == 1
    statuses = [batch.get("status") for batch in result.pagination_batches]
    assert statuses[:2] == ["ok", "empty_page"]
    pagination = pd.read_csv(result.reports_dir / "pagination_depth_and_failures.csv")
    assert "empty_page" in set(pagination["status"].dropna())


def test_duplicate_report_uses_source_app_storefront_context() -> None:
    frame = pd.DataFrame([
        {"source": "apple_app_store", "item_id": "app-a", "country": "us", "language": "en", "review_id": "same"},
        {"source": "apple_app_store", "item_id": "app-b", "country": "us", "language": "en", "review_id": "same"},
        {"source": "apple_app_store", "item_id": "app-a", "country": "gb", "language": "en", "review_id": "same"},
    ])
    assert validation._duplicate_records(frame).empty

    duplicated = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    result = validation._duplicate_records(duplicated)
    assert len(result) == 1
    assert result.iloc[0]["item_id"] == "app-a"
    assert result.iloc[0]["country"] == "us"


def test_validation_report_language_avoids_production_readiness_claim(monkeypatch, tmp_path: Path) -> None:
    _patch_fake_apple_session(monkeypatch, [_payload("r1")])
    config = _validation_config()

    result = run_apple_app_store_validation(config, tmp_path, run_id="language", max_reviews=1)

    report = (result.reports_dir / "apple_app_store_validation_eda.md").read_text(encoding="utf-8")
    summary = json.loads((result.reports_dir / "apple_app_store_validation_summary.json").read_text(encoding="utf-8"))
    assert "not production-ready" in report
    assert any("not a production-ready ingestion pipeline" in item for item in summary["limitations"])


def _validation_config(max_pages: int = 2) -> AppConfig:
    return AppConfig(
        assessment=AssessmentConfig(max_reviews_per_item=100, max_pages_per_item=max_pages, repeat_runs=1),
        steam=SteamConfig(enabled=False),
        amazon=AmazonConfig(enabled=False),
        google_play=GooglePlayConfig(enabled=False),
        apple_app_store=AppleAppStoreConfig(
            enabled=True,
            validation_total_reviews=10,
            validation_reviews_per_target=10,
        ),
        path=Path("config.yaml"),
    )


def _patch_fake_apple_session(monkeypatch, payloads: list[dict]) -> None:
    class FakeResponse:
        status_code = 200
        headers = {"content-type": "application/json"}
        content = b"{}"

        def __init__(self, payload: dict) -> None:
            self._payload = payload

        def json(self) -> dict:
            return self._payload

    class FakeSession:
        def __init__(self, *args, **kwargs) -> None:
            self.index = 0

        def get(self, url: str) -> HttpResult:
            payload = payloads[min(self.index, len(payloads) - 1)]
            self.index += 1
            return HttpResult(FakeResponse(payload), RequestRecord(url, 200, 0.01, True, "application/json", 2))

    monkeypatch.setattr(validation, "PoliteSession", FakeSession)


def _payload(review_id: str) -> dict:
    return {
        "feed": {
            "entry": [
                {"id": {"label": "app-metadata"}},
                {
                    "id": {"label": review_id},
                    "title": {"label": "Useful app"},
                    "content": {"label": "Works well for daily listening."},
                    "im:rating": {"label": "5"},
                    "updated": {"label": "2026-01-01T00:00:00-07:00"},
                    "author": {"name": {"label": "Reviewer One"}},
                    "im:voteSum": {"label": "3"},
                    "im:version": {"label": "9.0.0"},
                },
            ]
        }
    }


def _empty_payload() -> dict:
    return {"feed": {"entry": [{"id": {"label": "app-metadata"}}]}}
