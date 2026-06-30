"""Data-quality metrics for normalized review rows."""

from __future__ import annotations

from typing import Any

import pandas as pd

from .models import NORMALIZED_FIELDS, NormalizedReview, ProbeResult


EXPECTED_FIELDS = {
    "steam": {
        "required_common": ["source", "item_id", "review_id", "review_text", "review_date"],
        "source_specific": ["recommendation", "author_id", "helpful_votes", "funny_votes", "playtime_forever", "playtime_at_review", "language"],
        "not_applicable": ["rating", "review_title", "verified_purchase"],
    },
    "amazon": {
        "required_common": ["source", "item_id", "review_id", "review_text", "review_date"],
        "source_specific": ["rating", "review_title", "author_name", "verified_purchase", "helpful_votes"],
        "not_applicable": ["recommendation", "funny_votes", "playtime_forever", "playtime_at_review"],
    },
}


def calculate_quality_metrics(result: ProbeResult) -> dict[str, Any]:
    """Calculate source-level data quality metrics."""
    rows = [review.to_dict() for review in result.reviews]
    frame = pd.DataFrame(rows, columns=NORMALIZED_FIELDS)
    total_rows = len(frame)
    duplicates_within_final_dataset = 0
    duplicate_percentage_within_final_dataset: float | None = None
    if total_rows and "review_id" in frame:
        duplicates_within_final_dataset = int(frame["review_id"].dropna().duplicated().sum())
        duplicate_percentage_within_final_dataset = duplicates_within_final_dataset / total_rows

    text_lengths = frame["review_text"].fillna("").astype(str).map(len) if total_rows else pd.Series(dtype=int)
    completeness = {
        field: (None if total_rows == 0 else float(frame[field].notna().mean()))
        for field in NORMALIZED_FIELDS
        if field in frame
    }
    request_count = len(result.requests)
    success_rate = result.request_success_rate()
    metrics: dict[str, Any] = {
        "source": result.source,
        "total_rows": total_rows,
        "unique_review_count": _unique_count(frame) if total_rows else 0,
        "duplicates_within_final_dataset": duplicates_within_final_dataset,
        "duplicate_percentage_within_final_dataset": duplicate_percentage_within_final_dataset,
        "overlap_across_repeat_runs": result.overlap_across_repeat_runs,
        "repeat_run_overlap_rate": result.repeat_run_overlap_rate,
        "empty_review_text_count": _empty_count(frame, "review_text") if total_rows else 0,
        "empty_review_text_percentage": (_empty_count(frame, "review_text") / total_rows) if total_rows else None,
        "missing_rating_count": _missing_count(frame, "rating") if total_rows and result.source != "steam" else None,
        "missing_date_count": _missing_count(frame, "review_date") if total_rows else 0,
        "missing_review_id_count": _missing_count(frame, "review_id") if total_rows else 0,
        "average_review_text_length": float(text_lengths.mean()) if total_rows else None,
        "minimum_review_text_length": int(text_lengths.min()) if total_rows else None,
        "maximum_review_text_length": int(text_lengths.max()) if total_rows else None,
        "metadata_fields_available_count": len(result.available_metadata_fields),
        "field_completeness": completeness,
        "pagination_requests": request_count,
        "pagination_success_rate": _pagination_success_rate(result),
        "http_request_success_rate": success_rate,
        "average_response_time": result.average_response_time(),
        "blocked_request_count": sum(1 for request in result.requests if request.blocked),
        "parser_error_count": len(result.parser_errors),
        "field_applicability": _field_applicability(result.source, frame),
    }
    return metrics


def metrics_to_frame(metrics: list[dict[str, Any]]) -> pd.DataFrame:
    """Flatten quality metrics for CSV output."""
    flattened: list[dict[str, Any]] = []
    for source_metrics in metrics:
        row = {key: value for key, value in source_metrics.items() if key not in {"field_completeness", "field_applicability"}}
        completeness = source_metrics.get("field_completeness") or {}
        for field, value in completeness.items():
            row[f"completeness_{field}"] = value
        applicability = source_metrics.get("field_applicability") or {}
        row["required_common_fields"] = ", ".join(applicability.get("required_common", []))
        row["source_specific_fields"] = ", ".join(applicability.get("source_specific", []))
        row["not_applicable_fields"] = ", ".join(applicability.get("not_applicable", []))
        row["missing_expected_fields"] = ", ".join(applicability.get("missing_expected_fields", []))
        flattened.append(row)
    return pd.DataFrame(flattened)


def _unique_count(frame: pd.DataFrame) -> int:
    if "review_id" not in frame or frame["review_id"].dropna().empty:
        return len(frame)
    return int(frame["review_id"].dropna().nunique())


def _missing_count(frame: pd.DataFrame, field: str) -> int:
    return int(frame[field].isna().sum()) if field in frame else len(frame)


def _empty_count(frame: pd.DataFrame, field: str) -> int:
    if field not in frame:
        return len(frame)
    values = frame[field].fillna("").astype(str).str.strip()
    return int((values == "").sum())


def _pagination_success_rate(result: ProbeResult) -> float | str | None:
    if result.offline_parsing_executed and result.pagination_success is not None:
        return 1.0 if result.pagination_success else 0.0
    if not result.requests:
        return None
    if result.pagination_success is None:
        return "not enough evidence"
    return 1.0 if result.pagination_success else 0.0


def _field_applicability(source: str, frame: pd.DataFrame) -> dict[str, Any]:
    spec = EXPECTED_FIELDS.get(source, {"required_common": [], "source_specific": [], "not_applicable": []})
    expected = spec["required_common"] + spec["source_specific"]
    missing_expected = []
    for field in expected:
        if frame.empty or field not in frame or _missing_count(frame, field) == len(frame):
            missing_expected.append(field)
    notes = {}
    if source == "steam":
        notes["rating"] = "not applicable; Steam provides a binary recommendation label"
    return {
        "required_common": spec["required_common"],
        "source_specific": spec["source_specific"],
        "not_applicable": spec["not_applicable"],
        "missing_expected_fields": missing_expected,
        "notes": notes,
    }
