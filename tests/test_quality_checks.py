from __future__ import annotations

from src.models import NormalizedReview, ProbeResult
from src.quality_checks import calculate_quality_metrics


def test_duplicate_review_metrics_and_completeness() -> None:
    result = ProbeResult(
        source="steam",
        reviews=[
            NormalizedReview(source="steam", review_id="1", review_text="abc", rating=1),
            NormalizedReview(source="steam", review_id="1", review_text="", rating=None),
        ],
        duplicate_review_ids=["1"],
        overlap_across_repeat_runs=1,
        repeat_run_overlap_rate=0.5,
        available_metadata_fields=["source", "review_id", "review_text"],
    )

    metrics = calculate_quality_metrics(result)

    assert metrics["total_rows"] == 2
    assert metrics["duplicates_within_final_dataset"] == 1
    assert metrics["overlap_across_repeat_runs"] == 1
    assert metrics["empty_review_text_count"] == 1
    assert metrics["missing_rating_count"] is None
    assert metrics["field_completeness"]["review_id"] == 1.0


def test_repeat_overlap_without_final_dataset_duplicates() -> None:
    result = ProbeResult(
        source="steam",
        reviews=[
            NormalizedReview(source="steam", review_id="1", review_text="a", recommendation=True),
            NormalizedReview(source="steam", review_id="2", review_text="b", recommendation=False),
        ],
        overlap_across_repeat_runs=2,
        repeat_run_overlap_rate=1.0,
    )

    metrics = calculate_quality_metrics(result)

    assert metrics["duplicates_within_final_dataset"] == 0
    assert metrics["duplicate_percentage_within_final_dataset"] == 0
    assert metrics["overlap_across_repeat_runs"] == 2
    assert metrics["repeat_run_overlap_rate"] == 1.0


def test_steam_rating_is_not_applicable() -> None:
    result = ProbeResult(
        source="steam",
        reviews=[NormalizedReview(source="steam", review_id="1", review_text="a", recommendation=True)],
    )

    metrics = calculate_quality_metrics(result)

    assert metrics["missing_rating_count"] is None
    assert "rating" in metrics["field_applicability"]["not_applicable"]
    assert "binary recommendation" in metrics["field_applicability"]["notes"]["rating"]


def test_no_reviews_returns_insufficient_metrics() -> None:
    metrics = calculate_quality_metrics(ProbeResult(source="amazon"))

    assert metrics["total_rows"] == 0
    assert metrics["average_review_text_length"] is None
    assert metrics["pagination_success_rate"] is None
