"""Cautious Amazon live probing and offline response parsing."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd
from bs4 import BeautifulSoup

from .config import AppConfig
from .http_utils import AMAZON_USER_AGENT, PoliteSession, load_optional_amazon_auth
from .models import NORMALIZED_FIELDS, NormalizedReview, ProbeResult, utc_now_iso

BLOCK_PATTERNS = [
    "captcha",
    "robot check",
    "enter the characters you see below",
    "access denied",
    "sorry, we just need to make sure you're not a robot",
    "/ap/signin",
    "validatecaptcha",
]


def detect_amazon_block(text: str, status_code: int | None = None) -> bool:
    """Detect obvious Amazon blocking, sign-in, or robot-check responses."""
    lowered = text.lower()
    if status_code in {401, 403, 429}:
        return True
    if not text.strip():
        return True
    return any(pattern in lowered for pattern in BLOCK_PATTERNS)


def parse_amazon_response(text: str, source_url: str | None = None, page_number: int | None = None) -> list[NormalizedReview]:
    """Parse Amazon HTML or JSON-wrapped HTML into normalized review rows."""
    html = _extract_html(text)
    soup = BeautifulSoup(html, "html.parser")
    reviews: list[NormalizedReview] = []
    asin = _extract_asin(source_url or "") or _extract_asin_from_html(html)
    containers = soup.select("[data-hook='review']")
    if not containers:
        containers = soup.select("div[id^='customer_review-']")
    for container in containers:
        review_id = container.get("id")
        if review_id and review_id.startswith("customer_review-"):
            review_id = review_id.replace("customer_review-", "", 1)
        title_node = container.select_one("[data-hook='review-title']")
        text_node = container.select_one("[data-hook='review-body']")
        rating_node = container.select_one("[data-hook='review-star-rating'], [data-hook='cmps-review-star-rating']")
        date_node = container.select_one("[data-hook='review-date']")
        author_node = container.select_one(".a-profile-name")
        verified_node = container.select_one("[data-hook='avp-badge']")
        helpful_node = container.select_one("[data-hook='helpful-vote-statement']")
        reviews.append(
            NormalizedReview(
                source="amazon",
                item_id=asin,
                review_id=review_id,
                review_title=_clean_text(title_node),
                review_text=_clean_text(text_node),
                rating=_parse_rating(_clean_text(rating_node)),
                review_date=_clean_text(date_node),
                author_name=_clean_text(author_node),
                verified_purchase=bool(verified_node and _clean_text(verified_node)),
                helpful_votes=_parse_helpful(_clean_text(helpful_node), default_zero=True),
                source_url=source_url,
                raw_page_number=page_number,
            )
        )
    return reviews


def run_amazon_probe(config: AppConfig, root: Path, skip_live: bool = False, offline_only: bool = False) -> ProbeResult:
    """Run cautious Amazon live checks and offline parsing where configured."""
    result = ProbeResult(source="amazon", executed=True, mode="live+offline")
    result.offline_parsing_executed = bool(config.amazon.saved_response_files)
    result.saved_response_batch_count = len(config.amazon.saved_response_files)
    if not config.amazon.enabled:
        result.executed = False
        result.skipped_reason = "Amazon source disabled in configuration."
        return result
    placeholder_urls = [url for url in config.amazon.review_urls if url and not url.startswith("AMAZON_REVIEW_URL")]
    if len(placeholder_urls) == 1 and not offline_only and not skip_live:
        result.warnings.append("Amazon live coverage is limited to one configured review URL.")

    raw_dir = root / "data" / "raw" / "amazon"
    raw_dir.mkdir(parents=True, exist_ok=True)
    seen_ids: set[str] = set()
    duplicates: set[str] = set()

    if config.amazon.saved_response_files:
        previous_ids: set[str] = set()
        source_url = placeholder_urls[0] if placeholder_urls else None
        for path_text in config.amazon.saved_response_files:
            path = Path(path_text)
            try:
                text = path.read_text(encoding="utf-8")
                reviews = parse_amazon_response(text, source_url=source_url)
                if not reviews:
                    result.parser_errors.append(f"No reviews parsed from saved file: {path}")
                batch_ids = {review.review_id for review in reviews if review.review_id}
                overlap = len(batch_ids & previous_ids)
                result.pagination_batches.append(
                    {
                        "filename": str(path),
                        "batch_sequence": len(result.pagination_batches) + 1,
                        "review_count": len(reviews),
                        "unique_review_count": len(batch_ids),
                        "overlap_with_previous_batch": overlap,
                        "distinct_from_previous_batch": None if not previous_ids else overlap == 0,
                        "detected_next_page_number": _detect_next_page_number(text),
                        "next_page_token_detected": _detect_next_page_token(text),
                    }
                )
                previous_ids = batch_ids
                _append_unique(result, reviews, seen_ids, duplicates)
            except OSError as exc:
                result.parser_errors.append(f"Could not read saved Amazon response {path}: {exc}")
    else:
        result.warnings.append("No manually saved Amazon response files configured for offline parsing.")

    if offline_only or skip_live:
        if not config.amazon.saved_response_files:
            result.warnings.append("Amazon live request test skipped by CLI flag.")
    elif not placeholder_urls:
        result.warnings.append("No concrete Amazon review URLs configured for live probing.")
    else:
        headers, cookies = load_optional_amazon_auth()
        session = PoliteSession(
            timeout_seconds=config.assessment.request_timeout_seconds,
            delay_seconds=config.assessment.request_delay_seconds,
            user_agent=AMAZON_USER_AGENT,
        )
        if headers:
            session.session.headers.update(headers)
        if cookies:
            session.session.cookies.update(cookies)
        for url in placeholder_urls:
            live_result = session.get(url)
            result.requests.append(live_result.record)
            result.live_request_executed = True
            response = live_result.response
            if response is None:
                result.errors.append(f"Amazon live request failed for {url}")
                continue
            if not live_result.record.success:
                result.warnings.append(
                    f"Amazon live request returned HTTP {response.status_code}; no raw file saved and no parsing attempted."
                )
                continue
            blocked = detect_amazon_block(response.text, response.status_code)
            live_result.record.blocked = blocked
            if blocked:
                live_result.record.success = False
                result.blocked = True
                result.warnings.append(f"Amazon blocking or incomplete response detected for {url}; stopped for this URL.")
                continue
            raw_path = raw_dir / f"amazon_live_{_stamp()}.html"
            raw_path.write_text(response.text, encoding="utf-8")
            reviews = parse_amazon_response(response.text, source_url=url, page_number=1)
            if not reviews:
                result.parser_errors.append(f"Amazon live response contained no recognizable review containers: {url}")
            _append_unique(result, reviews, seen_ids, duplicates)

    result.duplicate_review_ids = sorted(duplicates)
    result.raw_reviews_returned = len(result.reviews) + len(result.duplicate_review_ids)
    result.available_metadata_fields = _available_fields(result.reviews)
    if config.amazon.saved_response_files:
        result.pagination_success = _saved_batches_show_pagination(result.pagination_batches)
        result.overlap_across_repeat_runs = None
        result.repeat_run_overlap_rate = None
    else:
        result.pagination_success = None
    if offline_only and not result.requests:
        result.blocked = None
        result.blocking_status = "not assessed"
        result.captcha_status = "not assessed"
        result.live_request_executed = False
    _save_normalized(root, result.reviews)
    if not result.requests and not config.amazon.saved_response_files:
        result.executed = False
        result.skipped_reason = "No Amazon live URL or saved response file was available."
    return result


def _extract_html(text: str) -> str:
    stripped = text.strip()
    ajax_fragments = _extract_amazon_ajax_fragments(stripped)
    if ajax_fragments:
        return "\n".join(ajax_fragments)
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            return text
        fragments = list(_walk_for_html(data))
        if fragments:
            return "\n".join(fragments)
    return text


def _extract_amazon_ajax_fragments(text: str) -> list[str]:
    fragments: list[str] = []
    if "]&&&[" not in text:
        return fragments
    for chunk in text.split("&&&"):
        try:
            data = json.loads(chunk)
        except json.JSONDecodeError:
            continue
        fragments.extend(_walk_for_html(data))
    return fragments


def _walk_for_html(value: Any) -> list[str]:
    fragments: list[str] = []
    if isinstance(value, str) and ("data-hook" in value or "customer_review" in value):
        fragments.append(value)
    elif isinstance(value, list):
        for item in value:
            fragments.extend(_walk_for_html(item))
    elif isinstance(value, dict):
        for item in value.values():
            fragments.extend(_walk_for_html(item))
    return fragments


def _append_unique(result: ProbeResult, reviews: list[NormalizedReview], seen_ids: set[str], duplicates: set[str]) -> None:
    for review in reviews:
        if review.review_id and review.review_id in seen_ids:
            duplicates.add(review.review_id)
            continue
        if review.review_id:
            seen_ids.add(review.review_id)
        result.reviews.append(review)


def _clean_text(node: Any) -> str | None:
    if node is None:
        return None
    text = node.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text).strip() or None


def _parse_rating(text: str | None) -> float | None:
    if not text:
        return None
    match = re.search(r"([0-5](?:\.\d+)?)\s+out of\s+5", text)
    return float(match.group(1)) if match else None


def _parse_helpful(text: str | None, default_zero: bool = False) -> int | None:
    if not text:
        return 0 if default_zero else None
    if text.lower().startswith("one person"):
        return 1
    match = re.search(r"([\d,]+)", text)
    return int(match.group(1).replace(",", "")) if match else None


def _extract_asin(url: str) -> str | None:
    match = re.search(r"/(?:product-reviews|dp)/([A-Z0-9]{10})", url)
    return match.group(1) if match else None


def _extract_asin_from_html(html: str) -> str | None:
    match = re.search(r"/(?:product-reviews|customer-reviews|dp|portal/customer-reviews)/([A-Z0-9]{10})", html)
    return match.group(1) if match else None


def _detect_next_page_number(text: str) -> int | None:
    match = re.search(r"(?:pageNumber|page-number)(?:&quot;|\"|=|%22|:)+\s*(?:&quot;|\")?(\d+)", text)
    return int(match.group(1)) if match else None


def _detect_next_page_token(text: str) -> bool:
    return "nextPageToken" in text or "nextpagetoken" in text.lower()


def _saved_batches_show_pagination(batches: list[dict[str, Any]]) -> bool:
    if len(batches) < 2:
        return False
    later_batches = batches[1:]
    return all(batch.get("unique_review_count", 0) > 0 for batch in batches) and all(
        batch.get("distinct_from_previous_batch") is True for batch in later_batches
    )


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
    frame = pd.DataFrame(rows, columns=NORMALIZED_FIELDS)
    frame.to_csv(processed / "amazon_reviews.csv", index=False)
    with (processed / "amazon_reviews.jsonl").open("w", encoding="utf-8") as handle:
        if rows:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        else:
            handle.write(json.dumps({"status": "no Amazon reviews collected", "fields": NORMALIZED_FIELDS}) + "\n")


def _stamp() -> str:
    return utc_now_iso().replace(":", "").replace("+", "Z")
