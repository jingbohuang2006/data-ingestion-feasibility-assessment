"""Google Play Store review feasibility probe."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .config import AppConfig
from .models import NORMALIZED_FIELDS, NormalizedReview, ProbeResult, utc_now_iso


def parse_google_play_reviews(
    records: list[dict[str, Any]],
    package_id: str,
    app_name: str,
    country: str,
    language: str,
    source_url: str,
    page_number: int,
    raw_cursor: str | None = None,
) -> list[NormalizedReview]:
    """Normalize google-play-scraper review records."""
    reviews: list[NormalizedReview] = []
    for item in records:
        reviews.append(
            NormalizedReview(
                source="google_play",
                app_name=app_name,
                item_id=package_id,
                package_id=package_id,
                review_id=_string_or_none(item.get("reviewId")),
                review_text=_string_or_none(item.get("content")),
                rating=_safe_float(item.get("score")),
                review_date=_iso_or_string(item.get("at")),
                author_name=_string_or_none(item.get("userName")),
                helpful_votes=_safe_int(item.get("thumbsUpCount")),
                app_version=_string_or_none(item.get("reviewCreatedVersion")),
                language=language,
                country=country,
                developer_response=_string_or_none(item.get("replyContent")),
                developer_response_date=_iso_or_string(item.get("repliedAt")),
                source_url=source_url,
                raw_page_number=page_number,
                raw_cursor=raw_cursor,
            )
        )
    return reviews


def run_google_play_probe(config: AppConfig, root: Path) -> ProbeResult:
    """Collect a small Google Play review sample through google-play-scraper when available."""
    play = config.google_play
    result = ProbeResult(
        source="google_play",
        executed=True,
        mode="third_party_live",
        access_method="google-play-scraper reviews API wrapper",
        access_method_type="third-party unofficial library",
        app_identifiers={"app_name": play.app_name, "package_id": play.package_id},
        country=play.country,
        language=play.language,
        request_count_status="unavailable_via_third_party_wrapper",
    )
    if not play.enabled:
        result.executed = False
        result.skipped_reason = "Google Play source disabled in configuration."
        return result
    if not play.package_id or play.package_id.startswith("GOOGLE_PLAY_PACKAGE_ID"):
        result.executed = False
        result.skipped_reason = "No concrete Google Play package ID configured."
        return result

    try:
        from google_play_scraper import Sort, reviews  # type: ignore
    except ImportError as exc:
        result.executed = False
        result.skipped_reason = "google-play-scraper is not installed."
        result.errors.append(str(exc))
        result.access_limitations.append(
            "Google Play review collection uses an unofficial third-party package that was unavailable."
        )
        _save_normalized(root, result.reviews)
        return result

    result.live_request_executed = True
    raw_dir = root / "data" / "raw" / "google_play"
    raw_dir.mkdir(parents=True, exist_ok=True)
    seen_ids: set[str] = set()
    duplicates: set[str] = set()
    run_ids: list[set[str]] = []
    source_url = f"https://play.google.com/store/apps/details?id={play.package_id}&hl={play.language}&gl={play.country}"

    for run_index in range(config.assessment.repeat_runs):
        result.run_timestamps.append(utc_now_iso())
        continuation_token = None
        previous_batch_ids: set[str] = set()
        run_review_ids: set[str] = set()
        for page_number in range(1, config.assessment.max_pages_per_item + 1):
            if len(run_review_ids) >= config.assessment.max_reviews_per_item:
                break
            result.pages_attempted += 1
            try:
                batch, continuation_token = reviews(
                    play.package_id,
                    lang=play.language,
                    country=play.country,
                    sort=Sort.NEWEST,
                    count=play.reviews_per_batch,
                    continuation_token=continuation_token,
                )
            except Exception as exc:  # noqa: BLE001 - third-party package raises broad errors.
                result.errors.append(f"Google Play review request failed for batch {page_number}: {exc}")
                result.access_limitations.append("Third-party Google Play access failed or was blocked.")
                break
            result.pages_completed += 1
            raw_path = raw_dir / f"google_play_{play.package_id}_run{run_index + 1}_batch{page_number}_{_stamp()}.json"
            raw_path.write_text(json.dumps(batch, ensure_ascii=False, default=str, indent=2), encoding="utf-8")
            parsed = parse_google_play_reviews(
                batch,
                package_id=play.package_id,
                app_name=play.app_name,
                country=play.country,
                language=play.language,
                source_url=source_url,
                page_number=page_number,
                raw_cursor=str(continuation_token) if continuation_token else None,
            )
            result.raw_reviews_returned += len(parsed)
            batch_ids = {review.review_id for review in parsed if review.review_id}
            result.pagination_batches.append(
                {
                    "run": run_index + 1,
                    "batch": page_number,
                    "raw_review_count": len(parsed),
                    "distinct_review_count": len(batch_ids),
                    "distinct_from_previous_batch": bool(batch_ids and batch_ids.isdisjoint(previous_batch_ids))
                    if previous_batch_ids
                    else None,
                    "continuation_token_present": continuation_token is not None,
                }
            )
            if page_number > 1 and batch_ids and batch_ids.isdisjoint(previous_batch_ids):
                result.pagination_success = True
            _append_unique(result, parsed, seen_ids, duplicates, run_review_ids, config.assessment.max_reviews_per_item)
            previous_batch_ids = batch_ids
            if not parsed or continuation_token is None:
                break
        run_ids.append(run_review_ids)

    result.duplicate_review_ids = []
    result.cross_run_overlap_review_ids = _repeat_overlap_ids(run_ids)
    result.overlap_across_repeat_runs = len(result.cross_run_overlap_review_ids)
    unique_ids = {review.review_id for review in result.reviews if review.review_id}
    result.repeat_run_overlap_rate = result.overlap_across_repeat_runs / len(unique_ids) if unique_ids else None
    result.new_records_in_second_run = _new_records_in_second_run(run_ids)
    result.repeated_collection_demonstrated = len(run_ids) >= 2 and all(run_ids)
    result.incremental_collection_feasible = bool(result.pagination_success and unique_ids)
    result.available_metadata_fields = _available_fields(result.reviews)
    if result.reviews:
        result.access_limitations.append("Access depends on an unofficial third-party library and undocumented Google Play behavior.")
    _save_normalized(root, result.reviews)
    return result


def _append_unique(
    result: ProbeResult,
    reviews: list[NormalizedReview],
    seen_ids: set[str],
    duplicates: set[str],
    run_review_ids: set[str],
    max_reviews: int,
) -> None:
    for review in reviews:
        if review.review_id:
            run_review_ids.add(review.review_id)
        if review.review_id and review.review_id in seen_ids:
            duplicates.add(review.review_id)
            continue
        if len(result.reviews) >= max_reviews:
            continue
        if review.review_id:
            seen_ids.add(review.review_id)
        result.reviews.append(review)


def _repeat_overlap_ids(run_ids: list[set[str]]) -> list[str]:
    if len(run_ids) < 2 or not all(run_ids):
        return []
    return sorted(set.intersection(*run_ids))


def _new_records_in_second_run(run_ids: list[set[str]]) -> int | None:
    if len(run_ids) < 2:
        return None
    return len(run_ids[1] - run_ids[0])


def _string_or_none(value: Any) -> str | None:
    return str(value) if value not in (None, "") else None


def _iso_or_string(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _safe_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _available_fields(reviews: list[NormalizedReview]) -> list[str]:
    fields: set[str] = set()
    for review in reviews:
        for key, value in review.to_dict().items():
            if value not in (None, ""):
                fields.add(key)
    return sorted(fields)


def _save_normalized(root: Path, reviews: list[NormalizedReview]) -> None:
    processed = root / "data" / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    rows = [review.to_dict() for review in reviews]
    pd.DataFrame(rows, columns=NORMALIZED_FIELDS).to_csv(processed / "google_play_reviews.csv", index=False)
    with (processed / "google_play_reviews.jsonl").open("w", encoding="utf-8") as handle:
        if rows:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        else:
            handle.write(json.dumps({"status": "no Google Play reviews collected", "fields": NORMALIZED_FIELDS}) + "\n")


def _stamp() -> str:
    return utc_now_iso().replace(":", "").replace("+", "Z")
