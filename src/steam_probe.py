"""Steam Store review endpoint feasibility probe."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote

import pandas as pd

from .config import AppConfig
from .http_utils import PoliteSession, STEAM_USER_AGENT
from .models import NORMALIZED_FIELDS, NormalizedReview, ProbeResult, utc_now_iso

STEAM_ENDPOINT = "https://store.steampowered.com/appreviews/{app_id}"


def parse_steam_reviews(payload: dict, app_id: str, source_url: str, page_number: int, cursor: str) -> list[NormalizedReview]:
    """Normalize Steam review JSON records."""
    reviews: list[NormalizedReview] = []
    for item in payload.get("reviews", []) or []:
        author = item.get("author") or {}
        timestamp = item.get("timestamp_created")
        reviews.append(
            NormalizedReview(
                source="steam",
                item_id=app_id,
                review_id=str(item.get("recommendationid")) if item.get("recommendationid") is not None else None,
                review_text=item.get("review"),
                recommendation=item.get("voted_up"),
                review_date=str(timestamp) if timestamp is not None else None,
                author_id=str(author.get("steamid")) if author.get("steamid") is not None else None,
                helpful_votes=_safe_int(item.get("votes_up")),
                funny_votes=_safe_int(item.get("votes_funny")),
                playtime_forever=_safe_int(author.get("playtime_forever")),
                playtime_at_review=_safe_int(author.get("playtime_at_review")),
                language=item.get("language"),
                source_url=source_url,
                raw_page_number=page_number,
                raw_cursor=cursor,
            )
        )
    return reviews


def run_steam_probe(config: AppConfig, root: Path) -> ProbeResult:
    """Run limited Steam collection for configured app IDs."""
    result = ProbeResult(source="steam", executed=True, mode="live")
    if not config.steam.enabled:
        result.executed = False
        result.skipped_reason = "Steam source disabled in configuration."
        return result
    valid_app_ids = [app_id for app_id in config.steam.app_ids if not app_id.startswith("STEAM_APP_ID")]
    if not valid_app_ids:
        result.executed = False
        result.skipped_reason = "No concrete Steam app IDs configured."
        return result

    raw_dir = root / "data" / "raw" / "steam"
    raw_dir.mkdir(parents=True, exist_ok=True)
    session = PoliteSession(
        timeout_seconds=config.assessment.request_timeout_seconds,
        delay_seconds=config.assessment.request_delay_seconds,
        user_agent=STEAM_USER_AGENT,
    )
    seen_ids: set[str] = set()
    duplicate_ids: set[str] = set()
    normalized_ids_by_app: dict[str, set[str]] = {}
    run_ids_by_app: dict[str, list[set[str]]] = {}

    for app_id in valid_app_ids:
        run_ids_by_app[app_id] = []
        normalized_ids_by_app[app_id] = set()
        for run_index in range(config.assessment.repeat_runs):
            cursor = "*"
            run_collected_ids: set[str] = set()
            previous_page_ids: set[str] = set()
            previous_response_cursor: str | None = None
            for page_number in range(1, config.assessment.max_pages_per_item + 1):
                url = _build_steam_url(config, app_id, cursor)
                http_result = session.get(url)
                result.requests.append(http_result.record)
                if http_result.response is None or not http_result.record.success:
                    result.errors.append(f"Steam request failed for app {app_id} page {page_number}.")
                    break
                try:
                    payload = http_result.response.json()
                except ValueError as exc:
                    result.parser_errors.append(f"Steam JSON parse error for app {app_id}: {exc}")
                    break
                raw_path = raw_dir / f"steam_{app_id}_run{run_index + 1}_page{page_number}_{_stamp()}.json"
                raw_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                raw_reviews = payload.get("reviews", []) or []
                result.raw_reviews_returned += len(raw_reviews)
                normalized = parse_steam_reviews(payload, app_id, url, page_number, cursor)
                page_ids = {review.review_id for review in normalized if review.review_id}
                next_cursor = str(payload.get("cursor") or "")
                result.pagination_batches.append(
                    {
                        "app_id": app_id,
                        "run": run_index + 1,
                        "page": page_number,
                        "request_cursor": cursor,
                        "response_cursor": next_cursor or None,
                        "raw_review_count": len(raw_reviews),
                        "distinct_review_count": len(page_ids),
                        "distinct_from_previous_page": bool(page_ids and page_ids.isdisjoint(previous_page_ids))
                        if previous_page_ids
                        else None,
                    }
                )
                new_count = 0
                for review in normalized:
                    if len(run_collected_ids) >= config.assessment.max_reviews_per_item:
                        break
                    if review.review_id:
                        run_collected_ids.add(review.review_id)
                    if review.review_id and review.review_id in seen_ids:
                        duplicate_ids.add(review.review_id)
                        continue
                    if len(normalized_ids_by_app[app_id]) >= config.assessment.max_reviews_per_item:
                        continue
                    if review.review_id:
                        seen_ids.add(review.review_id)
                        normalized_ids_by_app[app_id].add(review.review_id)
                    result.reviews.append(review)
                    new_count += 1
                    if len(run_collected_ids) >= config.assessment.max_reviews_per_item:
                        break
                if next_cursor and previous_response_cursor is not None and next_cursor != previous_response_cursor:
                    result.cursor_changed_correctly = True
                if page_number > 1 and page_ids and page_ids.isdisjoint(previous_page_ids):
                    result.pagination_success = True
                if not raw_reviews or not next_cursor or next_cursor == cursor or next_cursor == previous_response_cursor:
                    if page_number > 1 and next_cursor == previous_response_cursor:
                        result.warnings.append(f"Steam cursor stopped changing for app {app_id}.")
                    break
                if len(run_collected_ids) >= config.assessment.max_reviews_per_item:
                    break
                previous_response_cursor = next_cursor
                previous_page_ids = page_ids
                cursor = next_cursor
            run_ids_by_app[app_id].append(run_collected_ids)

    result.duplicate_review_ids = sorted(duplicate_ids)
    result.overlap_across_repeat_runs = _repeat_overlap_count(run_ids_by_app)
    unique_review_ids = {review.review_id for review in result.reviews if review.review_id}
    result.repeat_run_overlap_rate = (
        result.overlap_across_repeat_runs / len(unique_review_ids) if unique_review_ids else None
    )
    result.available_metadata_fields = _available_fields(result.reviews)
    _save_normalized(root, result.reviews)
    return result


def _build_steam_url(config: AppConfig, app_id: str, cursor: str) -> str:
    params = (
        f"?json=1&filter=recent&language={quote(config.steam.language)}"
        f"&review_type={quote(config.steam.review_type)}&purchase_type={quote(config.steam.purchase_type)}"
        f"&num_per_page={config.steam.reviews_per_page}&cursor={quote(cursor, safe='')}"
    )
    return STEAM_ENDPOINT.format(app_id=quote(app_id, safe="")) + params


def _save_normalized(root: Path, reviews: list[NormalizedReview]) -> None:
    processed = root / "data" / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    rows = [review.to_dict() for review in reviews]
    frame = pd.DataFrame(rows, columns=NORMALIZED_FIELDS)
    frame.to_csv(processed / "steam_reviews.csv", index=False)
    with (processed / "steam_reviews.jsonl").open("w", encoding="utf-8") as handle:
        if rows:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        else:
            handle.write(json.dumps({"status": "no Steam reviews collected", "fields": NORMALIZED_FIELDS}) + "\n")


def _available_fields(reviews: list[NormalizedReview]) -> list[str]:
    fields: set[str] = set()
    for review in reviews:
        for key, value in review.to_dict().items():
            if value not in (None, ""):
                fields.add(key)
    return sorted(fields)


def _safe_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _repeat_overlap_count(run_ids_by_app: dict[str, list[set[str]]]) -> int:
    overlap = 0
    for run_sets in run_ids_by_app.values():
        if len(run_sets) < 2:
            continue
        common_ids = set.intersection(*run_sets) if all(run_sets) else set()
        overlap += len(common_ids)
    return overlap


def _stamp() -> str:
    return utc_now_iso().replace(":", "").replace("+", "Z")
