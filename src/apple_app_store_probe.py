"""Apple App Store review RSS feasibility probe."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from .config import AppConfig
from .http_utils import PoliteSession
from .models import NORMALIZED_FIELDS, NormalizedReview, ProbeResult, utc_now_iso

APPLE_USER_AGENT = "review-feasibility-assessment/0.2 app-store technical test"


def parse_apple_app_store_reviews(
    payload: dict[str, Any],
    app_id: str,
    app_name: str,
    country: str,
    language: str,
    source_url: str,
    page_number: int,
) -> list[NormalizedReview]:
    """Normalize Apple App Store RSS review records."""
    entries = payload.get("feed", {}).get("entry", []) or []
    if isinstance(entries, dict):
        entries = [entries]
    reviews: list[NormalizedReview] = []
    for entry in entries:
        if not isinstance(entry, dict) or "im:rating" not in entry:
            continue
        author = entry.get("author") or {}
        reviews.append(
            NormalizedReview(
                source="apple_app_store",
                app_name=app_name,
                item_id=app_id,
                review_id=_label(entry.get("id")),
                review_title=_label(entry.get("title")),
                review_text=_label(entry.get("content")),
                rating=_safe_float(_label(entry.get("im:rating"))),
                review_date=_label(entry.get("updated")),
                author_name=_label(author.get("name")) if isinstance(author, dict) else None,
                helpful_votes=_safe_int(_label(entry.get("im:voteSum"))),
                app_version=_label(entry.get("im:version")),
                language=language,
                country=country,
                source_url=source_url,
                raw_page_number=page_number,
            )
        )
    return reviews


def run_apple_app_store_probe(config: AppConfig, root: Path) -> ProbeResult:
    """Collect a small Apple App Store review sample through Apple's public RSS JSON feed."""
    apple = config.apple_app_store
    result = ProbeResult(
        source="apple_app_store",
        executed=True,
        mode="live",
        access_method="Apple customer reviews RSS JSON feed",
        access_method_type="publicly accessible undocumented feed",
        app_identifiers={"app_name": apple.app_name, "app_id": apple.app_id},
        country=apple.country,
        language=apple.language,
    )
    if not apple.enabled:
        result.executed = False
        result.skipped_reason = "Apple App Store source disabled in configuration."
        return result
    if not apple.app_id or apple.app_id.startswith("APPLE_APP_ID"):
        result.executed = False
        result.skipped_reason = "No concrete Apple App Store app ID configured."
        return result

    raw_dir = root / "data" / "raw" / "apple_app_store"
    raw_dir.mkdir(parents=True, exist_ok=True)
    session = PoliteSession(
        timeout_seconds=config.assessment.request_timeout_seconds,
        delay_seconds=config.assessment.request_delay_seconds,
        user_agent=APPLE_USER_AGENT,
    )
    seen_ids: set[str] = set()
    duplicates: set[str] = set()
    run_ids: list[set[str]] = []

    for run_index in range(config.assessment.repeat_runs):
        result.run_timestamps.append(utc_now_iso())
        run_review_ids: set[str] = set()
        previous_page_ids: set[str] = set()
        for page_number in range(1, config.assessment.max_pages_per_item + 1):
            if len(run_review_ids) >= config.assessment.max_reviews_per_item:
                break
            url = _build_apple_url(apple.country, apple.app_id, apple.language, page_number)
            result.pages_attempted += 1
            http_result = session.get(url)
            result.requests.append(http_result.record)
            if http_result.response is None or not http_result.record.success:
                result.errors.append(f"Apple App Store request failed for page {page_number}.")
                break
            result.pages_completed += 1
            try:
                payload = http_result.response.json()
            except ValueError as exc:
                result.parser_errors.append(f"Apple App Store JSON parse error for page {page_number}: {exc}")
                break
            raw_path = raw_dir / f"apple_app_store_{apple.app_id}_run{run_index + 1}_page{page_number}_{_stamp()}.json"
            raw_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            parsed = parse_apple_app_store_reviews(
                payload,
                app_id=apple.app_id,
                app_name=apple.app_name,
                country=apple.country,
                language=apple.language,
                source_url=url,
                page_number=page_number,
            )
            if not parsed:
                if page_number == 1:
                    result.parser_errors.append("Apple App Store response contained no review entries.")
                else:
                    result.access_limitations.append(
                        f"Apple App Store page {page_number} returned no review entries for this app/storefront."
                    )
                break
            result.raw_reviews_returned += len(parsed)
            page_ids = {review.review_id for review in parsed if review.review_id}
            result.pagination_batches.append(
                {
                    "run": run_index + 1,
                    "page": page_number,
                    "raw_review_count": len(parsed),
                    "distinct_review_count": len(page_ids),
                    "distinct_from_previous_page": bool(page_ids and page_ids.isdisjoint(previous_page_ids))
                    if previous_page_ids
                    else None,
                }
            )
            if page_number > 1 and page_ids and page_ids.isdisjoint(previous_page_ids):
                result.pagination_success = True
            _append_unique(result, parsed, seen_ids, duplicates, run_review_ids, config.assessment.max_reviews_per_item)
            previous_page_ids = page_ids
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
    if not result.pagination_success and result.pages_completed < 2:
        result.access_limitations.append("Pagination was not demonstrated in the completed requests.")
    _save_normalized(root, result.reviews)
    return result


def _build_apple_url(country: str, app_id: str, language: str, page_number: int) -> str:
    return (
        f"https://itunes.apple.com/{country}/rss/customerreviews/page={page_number}/id={app_id}/"
        f"sortby=mostrecent/json?l={language}"
    )


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


def _label(value: Any) -> str | None:
    if isinstance(value, dict):
        label = value.get("label")
        return str(label) if label not in (None, "") else None
    return str(value) if value not in (None, "") else None


def _safe_float(value: str | None) -> float | None:
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def _safe_int(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
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
    pd.DataFrame(rows, columns=NORMALIZED_FIELDS).to_csv(processed / "apple_app_store_reviews.csv", index=False)
    with (processed / "apple_app_store_reviews.jsonl").open("w", encoding="utf-8") as handle:
        if rows:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        else:
            handle.write(json.dumps({"status": "no Apple App Store reviews collected", "fields": NORMALIZED_FIELDS}) + "\n")


def _stamp() -> str:
    return utc_now_iso().replace(":", "").replace("+", "Z")
