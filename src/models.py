"""Shared dataclasses for normalized reviews and probe results."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


NORMALIZED_FIELDS = [
    "source",
    "item_id",
    "item_name",
    "review_id",
    "review_title",
    "review_text",
    "rating",
    "recommendation",
    "review_date",
    "author_id",
    "author_name",
    "verified_purchase",
    "helpful_votes",
    "funny_votes",
    "playtime_forever",
    "playtime_at_review",
    "language",
    "source_url",
    "collected_at",
    "raw_page_number",
    "raw_cursor",
]


def utc_now_iso() -> str:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class NormalizedReview:
    """Source-neutral review record."""

    source: str
    item_id: str | None = None
    item_name: str | None = None
    review_id: str | None = None
    review_title: str | None = None
    review_text: str | None = None
    rating: float | None = None
    recommendation: bool | None = None
    review_date: str | None = None
    author_id: str | None = None
    author_name: str | None = None
    verified_purchase: bool | None = None
    helpful_votes: int | None = None
    funny_votes: int | None = None
    playtime_forever: int | None = None
    playtime_at_review: int | None = None
    language: str | None = None
    source_url: str | None = None
    collected_at: str = field(default_factory=utc_now_iso)
    raw_page_number: int | None = None
    raw_cursor: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to a dict with stable field order."""
        data = asdict(self)
        return {field_name: data.get(field_name) for field_name in NORMALIZED_FIELDS}


@dataclass
class RequestRecord:
    """Technical facts about one HTTP request."""

    url: str
    status_code: int | None
    elapsed_seconds: float | None
    success: bool
    content_type: str | None = None
    response_size: int | None = None
    error: str | None = None
    blocked: bool = False


@dataclass
class ProbeResult:
    """Collected evidence for one source."""

    source: str
    executed: bool = False
    skipped_reason: str | None = None
    reviews: list[NormalizedReview] = field(default_factory=list)
    requests: list[RequestRecord] = field(default_factory=list)
    raw_reviews_returned: int = 0
    duplicate_review_ids: list[str] = field(default_factory=list)
    overlap_across_repeat_runs: int | None = 0
    repeat_run_overlap_rate: float | None = None
    available_metadata_fields: list[str] = field(default_factory=list)
    pagination_success: bool | None = None
    cursor_changed_correctly: bool | None = None
    pagination_batches: list[dict[str, Any]] = field(default_factory=list)
    blocked: bool | None = False
    parser_errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    mode: str | None = None
    live_request_executed: bool | None = None
    offline_parsing_executed: bool | None = None
    saved_response_batch_count: int = 0
    blocking_status: str | None = None
    captcha_status: str | None = None

    def request_success_rate(self) -> float | None:
        """Return successful HTTP request fraction, or None when no requests ran."""
        if not self.requests:
            return None
        return sum(1 for request in self.requests if request.success) / len(self.requests)

    def average_response_time(self) -> float | None:
        """Return average response time for requests with timings."""
        timings = [request.elapsed_seconds for request in self.requests if request.elapsed_seconds is not None]
        if not timings:
            return None
        return sum(timings) / len(timings)

    def summary(self) -> dict[str, Any]:
        """Return a JSON-friendly result summary."""
        return {
            "source": self.source,
            "executed": self.executed,
            "skipped_reason": self.skipped_reason,
            "mode": self.mode,
            "live_request_executed": self.live_request_executed if self.live_request_executed is not None else bool(self.requests),
            "offline_saved_response_parsing_executed": bool(self.offline_parsing_executed),
            "saved_response_batch_count": self.saved_response_batch_count,
            "review_count": len(self.reviews),
            "request_count": len(self.requests),
            "successful_request_count": sum(1 for request in self.requests if request.success),
            "status_codes": [request.status_code for request in self.requests],
            "request_details": [
                {
                    "url": _safe_url(request.url),
                    "status_code": request.status_code,
                    "elapsed_seconds": request.elapsed_seconds,
                    "success": request.success,
                    "content_type": request.content_type,
                    "response_size": request.response_size,
                    "error": request.error,
                    "blocked": request.blocked,
                }
                for request in self.requests
            ],
            "raw_reviews_returned": self.raw_reviews_returned,
            "unique_review_count": len({review.review_id for review in self.reviews if review.review_id}),
            "duplicate_review_ids": self.duplicate_review_ids,
            "overlap_across_repeat_runs": self.overlap_across_repeat_runs,
            "repeat_run_overlap_rate": self.repeat_run_overlap_rate,
            "available_metadata_fields": self.available_metadata_fields,
            "pagination_success": self.pagination_success,
            "cursor_changed_correctly": self.cursor_changed_correctly,
            "pagination_batches": self.pagination_batches,
            "blocked": self.blocked,
            "blocking_status": self.blocking_status,
            "captcha_status": self.captcha_status,
            "parser_error_count": len(self.parser_errors),
            "warnings": self.warnings,
            "errors": self.errors,
        }


def _safe_url(url: str) -> str:
    if "?" not in url:
        return url
    return url.split("?", 1)[0] + "?..."
