from __future__ import annotations

from pathlib import Path

from src.comparison import build_comparison, preliminary_recommendation
from src.config import AppConfig, AmazonConfig, AssessmentConfig, SteamConfig
from src.models import NormalizedReview, ProbeResult, RequestRecord
from src.quality_checks import calculate_quality_metrics
from src.report_generator import generate_reports


def test_comparison_contains_required_criteria() -> None:
    steam = ProbeResult(source="steam", executed=True, reviews=[NormalizedReview(source="steam")])
    amazon = ProbeResult(source="amazon", executed=False, skipped_reason="not configured")
    quality = {
        "steam": calculate_quality_metrics(steam),
        "amazon": calculate_quality_metrics(amazon),
    }

    frame = build_comparison(amazon, steam, quality)

    assert set(frame["criterion"]) >= {"Accessibility", "Commercial value", "Long-term maintainability"}


def test_report_generation_with_no_reviews(tmp_path: Path) -> None:
    config = AppConfig(
        assessment=AssessmentConfig(),
        steam=SteamConfig(enabled=False),
        amazon=AmazonConfig(enabled=False),
        path=tmp_path / "config.yaml",
    )
    steam = ProbeResult(source="steam", executed=False, skipped_reason="disabled")
    amazon = ProbeResult(source="amazon", executed=False, skipped_reason="disabled")
    quality = [calculate_quality_metrics(steam), calculate_quality_metrics(amazon)]
    comparison = build_comparison(amazon, steam, {item["source"]: item for item in quality})

    generate_reports(config, tmp_path, {"steam": steam, "amazon": amazon}, quality, comparison, False)

    assert (tmp_path / "reports" / "test_run_summary.json").exists()
    assert (tmp_path / "reports" / "feasibility_report.md").exists()


def test_disabled_source_is_reported_as_skipped() -> None:
    result = ProbeResult(source="amazon", executed=False, skipped_reason="Amazon source disabled in configuration.")

    assert result.summary()["executed"] is False
    assert "disabled" in result.summary()["skipped_reason"]


def test_amazon_offline_mode_reporting_is_explicit() -> None:
    result = ProbeResult(
        source="amazon",
        executed=True,
        live_request_executed=True,
        offline_parsing_executed=False,
        requests=[RequestRecord(url="https://example.test", status_code=404, elapsed_seconds=0.1, success=False)],
    )

    summary = result.summary()

    assert summary["live_request_executed"] is True
    assert summary["offline_saved_response_parsing_executed"] is False


def test_amazon_saved_batch_summary_is_safe() -> None:
    result = ProbeResult(
        source="amazon",
        executed=True,
        live_request_executed=False,
        offline_parsing_executed=True,
        saved_response_batch_count=3,
        pagination_success=True,
        overlap_across_repeat_runs=None,
        repeat_run_overlap_rate=None,
        pagination_batches=[
            {
                "filename": "data/raw/amazon/manual/amazon_response_1.txt",
                "batch_sequence": 1,
                "review_count": 10,
                "unique_review_count": 10,
                "overlap_with_previous_batch": 0,
                "distinct_from_previous_batch": None,
                "detected_next_page_number": 2,
                "next_page_token_detected": True,
            }
        ],
    )

    summary = result.summary()

    assert summary["saved_response_batch_count"] == 3
    assert summary["pagination_batches"][0]["next_page_token_detected"] is True
    assert "nextPageToken" not in str(summary["pagination_batches"][0])


def test_secret_values_not_in_report(tmp_path: Path) -> None:
    config = AppConfig(
        assessment=AssessmentConfig(),
        steam=SteamConfig(enabled=True, app_ids=("440",)),
        amazon=AmazonConfig(enabled=True, review_urls=("https://example.test/product-reviews/B000000001/?token=SECRET",)),
        path=tmp_path / "config.yaml",
    )
    amazon = ProbeResult(
        source="amazon",
        executed=True,
        requests=[RequestRecord(url="https://example.test/?token=SECRET", status_code=403, elapsed_seconds=0.1, success=False, blocked=True)],
        blocked=True,
    )
    steam = ProbeResult(source="steam", executed=False, skipped_reason="not selected")
    quality = [calculate_quality_metrics(steam), calculate_quality_metrics(amazon)]
    comparison = build_comparison(amazon, steam, {item["source"]: item for item in quality})

    generate_reports(config, tmp_path, {"steam": steam, "amazon": amazon}, quality, comparison, False)

    text = (tmp_path / "reports" / "test_run_summary.json").read_text(encoding="utf-8")
    assert "SECRET" not in text


def test_preliminary_recommendation_avoids_forced_winner() -> None:
    recommendation = preliminary_recommendation(ProbeResult(source="amazon"), ProbeResult(source="steam"))

    assert "No final source winner" in recommendation


def test_report_next_steps_are_not_stale(tmp_path: Path) -> None:
    config = AppConfig(
        assessment=AssessmentConfig(),
        steam=SteamConfig(enabled=True, app_ids=("730",)),
        amazon=AmazonConfig(enabled=True),
        path=tmp_path / "config.yaml",
    )
    steam = ProbeResult(source="steam", executed=True, reviews=[NormalizedReview(source="steam", review_id="1")])
    amazon = ProbeResult(source="amazon", executed=True, requests=[RequestRecord("https://example.test", 404, 0.1, False)])
    quality = [calculate_quality_metrics(steam), calculate_quality_metrics(amazon)]
    comparison = build_comparison(amazon, steam, {item["source"]: item for item in quality})

    generate_reports(config, tmp_path, {"steam": steam, "amazon": amazon}, quality, comparison, True)
    report = (tmp_path / "reports" / "feasibility_report.md").read_text(encoding="utf-8")

    assert "Add concrete Steam app IDs" not in report
    assert "Demonstrate Steam cursor pagination" not in report
    assert "Use Steam for the initial automated ingestion prototype" in report
    assert "approved Amazon access without manual Network copying" in report
