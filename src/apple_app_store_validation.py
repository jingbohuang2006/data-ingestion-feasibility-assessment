"""Larger Apple App Store validation collection and EDA outputs."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import Any

import pandas as pd

from .apple_app_store_probe import APPLE_USER_AGENT, _build_apple_url, parse_apple_app_store_reviews
from .config import AppConfig, AppleAppStoreTarget
from .http_utils import PoliteSession
from .models import NORMALIZED_FIELDS, NormalizedReview, RequestRecord, utc_now_iso


@dataclass
class AppleValidationResult:
    """Artifacts and evidence from one isolated Apple validation run."""

    run_id: str
    output_dir: Path
    processed_dir: Path
    reports_dir: Path
    raw_dir: Path
    reviews: list[NormalizedReview] = field(default_factory=list)
    requests: list[RequestRecord] = field(default_factory=list)
    pagination_batches: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    parser_errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    targets: list[dict[str, Any]] = field(default_factory=list)
    target_review_count: int = 0
    target_reached: bool = False
    shortfall_reason: str | None = None


def run_apple_app_store_validation(
    config: AppConfig,
    root: Path,
    run_id: str | None = None,
    max_reviews: int | None = None,
) -> AppleValidationResult:
    """Run a multi-target Apple validation collection into isolated output folders."""
    apple = config.apple_app_store
    target_total = min(max_reviews or apple.validation_total_reviews, apple.validation_total_reviews)
    run_id = _safe_run_id(run_id or _stamp())
    processed_dir = _unique_dir(root / "data" / "processed" / apple.validation_output_dir / run_id)
    reports_dir = _unique_dir(root / "reports" / apple.validation_output_dir / processed_dir.name)
    raw_dir = root / "data" / "raw" / apple.validation_output_dir / processed_dir.name
    processed_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    result = AppleValidationResult(
        run_id=processed_dir.name,
        output_dir=processed_dir.parent,
        processed_dir=processed_dir,
        reports_dir=reports_dir,
        raw_dir=raw_dir,
        target_review_count=target_total,
    )
    targets = _validation_targets(config)
    result.targets = [_target_to_dict(target) for target in targets]
    if not apple.enabled:
        result.warnings.append("Apple App Store source disabled in configuration.")
        _write_outputs(config, result)
        return result
    if not targets:
        result.warnings.append("No concrete Apple App Store validation targets configured.")
        _write_outputs(config, result)
        return result

    session = PoliteSession(
        timeout_seconds=config.assessment.request_timeout_seconds,
        delay_seconds=config.assessment.request_delay_seconds,
        user_agent=APPLE_USER_AGENT,
    )
    seen_ids: set[str] = set()
    duplicate_ids: set[str] = set()

    for target in targets:
        if len(result.reviews) >= target_total:
            break
        target_limit = min(apple.validation_reviews_per_target, target_total - len(result.reviews))
        _collect_target(config, session, target, target_limit, result, seen_ids, duplicate_ids)

    result.pagination_batches.append(
        {
            "summary": "final_dataset",
            "duplicate_review_id_count": len(duplicate_ids),
            "duplicate_review_ids_sample": sorted(duplicate_ids)[:25],
        }
    )
    result.target_reached = len(result.reviews) >= target_total
    if not result.target_reached:
        result.shortfall_reason = _shortfall_reason(result, targets)
        result.warnings.append(result.shortfall_reason)
    _write_outputs(config, result)
    return result


def build_apple_validation_eda(
    reviews: list[NormalizedReview],
    pagination_batches: list[dict[str, Any]],
    errors: list[str] | None = None,
    low_signal_min_text_length: int = 15,
) -> dict[str, pd.DataFrame]:
    """Build EDA tables for Apple validation reviews."""
    frame = pd.DataFrame([review.to_dict() for review in reviews], columns=NORMALIZED_FIELDS)
    if frame.empty:
        return _empty_eda_frames(pagination_batches, errors or [])

    frame["text_length"] = frame["review_text"].fillna("").astype(str).str.strip().str.len()
    frame["is_low_signal"] = (frame["text_length"] < low_signal_min_text_length) | frame["review_text"].isna()
    group_cols = ["app_name", "item_id", "country", "language"]

    volume = (
        frame.groupby(group_cols, dropna=False)
        .agg(
            review_count=("review_id", "size"),
            unique_review_count=("review_id", "nunique"),
            duplicate_count=("review_id", lambda values: int(values.dropna().duplicated().sum())),
        )
        .reset_index()
    )
    rating_distribution = (
        frame.groupby(group_cols + ["rating"], dropna=False).size().reset_index(name="review_count")
    )
    text_length = (
        frame.groupby(group_cols, dropna=False)["text_length"]
        .agg(
            review_count="size",
            minimum_text_length="min",
            maximum_text_length="max",
            average_text_length="mean",
            median_text_length=lambda values: float(median(values)),
        )
        .reset_index()
    )
    low_signal = (
        frame.groupby(group_cols, dropna=False)
        .agg(
            low_signal_review_count=("is_low_signal", "sum"),
            empty_text_count=("review_text", lambda values: int(values.fillna("").astype(str).str.strip().eq("").sum())),
        )
        .reset_index()
    )
    text_length = text_length.merge(low_signal, on=group_cols, how="left")
    text_length["low_signal_rate"] = text_length["low_signal_review_count"] / text_length["review_count"]

    date_coverage = (
        frame.groupby(group_cols, dropna=False)
        .agg(
            dated_review_count=("review_date", lambda values: int(values.notna().sum())),
            undated_review_count=("review_date", lambda values: int(values.isna().sum())),
            earliest_review_date=("review_date", "min"),
            latest_review_date=("review_date", "max"),
        )
        .reset_index()
    )
    missing_fields = _missing_fields(frame, group_cols)
    duplicates = _duplicate_records(frame)
    language_region = _language_region_issues(frame, group_cols)
    low_signal_reviews = frame.loc[
        frame["is_low_signal"],
        ["app_name", "item_id", "country", "language", "review_id", "rating", "review_date", "text_length", "review_text"],
    ].copy()
    pagination = pd.DataFrame(pagination_batches)
    error_frame = pd.DataFrame({"error": errors or []})

    return {
        "review_volume_by_app": volume,
        "rating_distribution": rating_distribution,
        "review_text_length": text_length,
        "date_coverage": date_coverage,
        "missing_fields": missing_fields,
        "duplicate_records": duplicates,
        "language_region_issues": language_region,
        "low_signal_reviews": low_signal_reviews,
        "pagination_depth_and_failures": pagination,
        "errors": error_frame,
    }


def _collect_target(
    config: AppConfig,
    session: PoliteSession,
    target: AppleAppStoreTarget,
    target_limit: int,
    result: AppleValidationResult,
    seen_ids: set[str],
    duplicate_ids: set[str],
) -> None:
    target_seen = 0
    previous_page_ids: set[str] = set()
    for page_number in range(1, config.apple_app_store.validation_max_pages_per_target + 1):
        if target_seen >= target_limit:
            break
        url = _build_apple_url(target.country, target.app_id, target.language, page_number)
        http_result = session.get(url)
        result.requests.append(http_result.record)
        if http_result.response is None or not http_result.record.success:
            status = "request_failed"
            if page_number > 1 and http_result.record.status_code in {400, 404}:
                status = "pagination_limit_or_unavailable_page"
            else:
                result.errors.append(f"Apple validation request failed for {target.app_name} page {page_number}.")
            result.pagination_batches.append(_batch_record(target, page_number, 0, 0, set(), previous_page_ids, status))
            break
        try:
            payload = http_result.response.json()
        except ValueError as exc:
            result.parser_errors.append(f"Apple validation JSON parse error for {target.app_name} page {page_number}: {exc}")
            result.pagination_batches.append(_batch_record(target, page_number, 0, 0, set(), previous_page_ids, "json_parse_error"))
            break

        raw_path = result.raw_dir / f"apple_app_store_{target.app_id}_page{page_number}_{_stamp()}.json"
        raw_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        parsed = parse_apple_app_store_reviews(
            payload,
            app_id=target.app_id,
            app_name=target.app_name,
            country=target.country,
            language=target.language,
            source_url=url,
            page_number=page_number,
        )
        page_ids = {review.review_id for review in parsed if review.review_id}
        status = "ok" if parsed else "empty_page"
        result.pagination_batches.append(
            _batch_record(target, page_number, len(parsed), len(page_ids), page_ids, previous_page_ids, status)
        )
        if not parsed:
            break
        for review in parsed:
            if target_seen >= target_limit:
                break
            if review.review_id and review.review_id in seen_ids:
                duplicate_ids.add(review.review_id)
                continue
            if review.review_id:
                seen_ids.add(review.review_id)
            result.reviews.append(review)
            target_seen += 1
        previous_page_ids = page_ids
    if target_seen < target_limit:
        result.pagination_batches.append(
            {
                "app_name": target.app_name,
                "app_id": target.app_id,
                "category": target.category,
                "country": target.country,
                "language": target.language,
                "status": "target_limit_not_reached",
                "target_limit": target_limit,
                "reviews_collected_for_target": target_seen,
                "max_pages_per_target": config.apple_app_store.validation_max_pages_per_target,
            }
        )


def _write_outputs(config: AppConfig, result: AppleValidationResult) -> None:
    rows = [review.to_dict() for review in result.reviews]
    pd.DataFrame(rows, columns=NORMALIZED_FIELDS).to_csv(
        result.processed_dir / "apple_app_store_validation_reviews.csv", index=False
    )
    with (result.processed_dir / "apple_app_store_validation_reviews.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        if not rows:
            handle.write(json.dumps({"status": "no Apple App Store validation reviews collected"}) + "\n")

    eda = build_apple_validation_eda(
        result.reviews,
        result.pagination_batches,
        result.errors + result.parser_errors + result.warnings,
        config.apple_app_store.validation_low_signal_min_text_length,
    )
    for name, frame in eda.items():
        frame.to_csv(result.reports_dir / f"{name}.csv", index=False)

    summary = {
        "execution_timestamp": utc_now_iso(),
        "phase": "Apple App Store larger-scale validation",
        "run_id": result.run_id,
        "target_review_count": result.target_review_count,
        "reviews_collected": len(result.reviews),
        "target_reached": result.target_reached,
        "shortfall_reason": result.shortfall_reason,
        "targets": result.targets,
        "request_count": len(result.requests),
        "successful_request_count": sum(1 for request in result.requests if request.success),
        "errors": result.errors,
        "parser_errors": result.parser_errors,
        "warnings": result.warnings,
        "processed_output_dir": str(result.processed_dir),
        "reports_output_dir": str(result.reports_dir),
        "raw_output_dir": str(result.raw_dir),
        "limitations": [
            "Validation run only; this is not a production-ready ingestion pipeline.",
            "Apple customer review RSS is publicly accessible but undocumented and not an official supported review API.",
            "Review volume is capped by configuration and may be limited by app, storefront, endpoint behavior, or paging depth.",
            "Language is configured by storefront request; independent language detection is not performed.",
        ],
    }
    (result.reports_dir / "apple_app_store_validation_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (result.reports_dir / "apple_app_store_validation_eda.md").write_text(
        _markdown_summary(result, eda), encoding="utf-8"
    )


def _markdown_summary(result: AppleValidationResult, eda: dict[str, pd.DataFrame]) -> str:
    volume_rows = eda["review_volume_by_app"].to_dict("records")
    volume_lines = [
        f"- {row.get('app_name')} ({row.get('country')}/{row.get('language')}): "
        f"{row.get('review_count')} rows, {row.get('unique_review_count')} unique"
        for row in volume_rows
    ] or ["- No reviews collected."]
    return "\n".join(
        [
            "# Apple App Store Validation EDA",
            "",
            "## Scope",
            "This is a larger validation path for Apple App Store review collection and EDA. It is not production-ready.",
            "",
            "## Output Isolation",
            f"- Processed output directory: {result.processed_dir}",
            f"- Report output directory: {result.reports_dir}",
            f"- Raw output directory: {result.raw_dir}",
            "",
            "## Target Status",
            f"- Target review count: {result.target_review_count}",
            f"- Reviews collected: {len(result.reviews)}",
            f"- Target reached: {'yes' if result.target_reached else 'no'}",
            f"- Shortfall reason: {result.shortfall_reason or 'not applicable'}",
            "",
            "## Review Volume By App",
            *volume_lines,
            "",
            "## Limitations",
            "- Apple review RSS access remains publicly accessible but undocumented.",
            "- This validation does not bypass authentication, CAPTCHA, rate limits, or access controls.",
            "- A successful validation run does not prove long-term endpoint stability or production readiness.",
            "- Google Play remains a secondary benchmark and is not expanded in this validation path.",
            "",
        ]
    )


def _shortfall_reason(result: AppleValidationResult, targets: tuple[AppleAppStoreTarget, ...]) -> str:
    statuses = [str(batch.get("status")) for batch in result.pagination_batches if batch.get("status")]
    if "pagination_limit_or_unavailable_page" in statuses:
        return (
            f"Target not reached: collected {len(result.reviews)} of {result.target_review_count} reviews because Apple "
            "RSS page depth was limited for several configured targets, with later pages returning unavailable-page "
            "responses after the available review window."
        )
    if "request_failed" in statuses or result.errors:
        return (
            f"Target not reached: collected {len(result.reviews)} of {result.target_review_count} reviews because one "
            "or more Apple RSS requests failed before the configured target was met."
        )
    if "json_parse_error" in statuses or result.parser_errors:
        return (
            f"Target not reached: collected {len(result.reviews)} of {result.target_review_count} reviews because one "
            "or more Apple RSS responses could not be parsed."
        )
    if "empty_page" in statuses:
        return (
            f"Target not reached: collected {len(result.reviews)} of {result.target_review_count} reviews because Apple "
            "RSS returned empty review pages for at least one configured target/storefront."
        )
    if all(status in {"ok", "target_limit_not_reached", "final_dataset"} for status in statuses):
        return (
            f"Target not reached: collected {len(result.reviews)} of {result.target_review_count} reviews after exhausting "
            f"{len(targets)} configured target/storefront combinations and the configured page depth."
        )
    return (
        f"Target not reached: collected {len(result.reviews)} of {result.target_review_count} reviews under the configured "
        "target, page-depth, app, and storefront limits."
    )


def _validation_targets(config: AppConfig) -> tuple[AppleAppStoreTarget, ...]:
    apple = config.apple_app_store
    if apple.validation_targets:
        return apple.validation_targets
    if apple.app_id and not apple.app_id.startswith("APPLE_APP_ID"):
        return (
            AppleAppStoreTarget(
                app_name=apple.app_name,
                app_id=apple.app_id,
                country=apple.country,
                language=apple.language,
            ),
        )
    return ()


def _target_to_dict(target: AppleAppStoreTarget) -> dict[str, Any]:
    return {
        "app_name": target.app_name,
        "app_id": target.app_id,
        "country": target.country,
        "language": target.language,
        "category": target.category,
    }


def _batch_record(
    target: AppleAppStoreTarget,
    page_number: int,
    raw_count: int,
    distinct_count: int,
    page_ids: set[str],
    previous_page_ids: set[str],
    status: str,
) -> dict[str, Any]:
    return {
        "app_name": target.app_name,
        "app_id": target.app_id,
        "category": target.category,
        "country": target.country,
        "language": target.language,
        "page": page_number,
        "raw_review_count": raw_count,
        "distinct_review_count": distinct_count,
        "distinct_from_previous_page": None if not previous_page_ids else bool(page_ids and page_ids.isdisjoint(previous_page_ids)),
        "status": status,
    }


def _missing_fields(frame: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for keys, group in frame.groupby(group_cols, dropna=False):
        key_values = dict(zip(group_cols, keys if isinstance(keys, tuple) else (keys,)))
        for field in NORMALIZED_FIELDS:
            missing = int(group[field].isna().sum()) if field in group else len(group)
            rows.append(
                {
                    **key_values,
                    "field": field,
                    "missing_count": missing,
                    "missing_rate": missing / len(group) if len(group) else None,
                }
            )
    return pd.DataFrame(rows)


def _duplicate_records(frame: pd.DataFrame) -> pd.DataFrame:
    ids = [value for value in frame["review_id"].dropna().astype(str)]
    counts = Counter(ids)
    duplicate_ids = {review_id for review_id, count in counts.items() if count > 1}
    if not duplicate_ids:
        return pd.DataFrame(columns=["review_id", "duplicate_count"])
    rows = []
    for review_id in sorted(duplicate_ids):
        apps = sorted(set(frame.loc[frame["review_id"] == review_id, "app_name"].dropna().astype(str)))
        rows.append({"review_id": review_id, "duplicate_count": counts[review_id], "apps": ", ".join(apps)})
    return pd.DataFrame(rows)


def _language_region_issues(frame: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    rows = []
    for keys, group in frame.groupby(group_cols, dropna=False):
        key_values = dict(zip(group_cols, keys if isinstance(keys, tuple) else (keys,)))
        rows.append(
            {
                **key_values,
                "review_count": len(group),
                "language_detection_available": False,
                "region_storefront": key_values.get("country"),
                "issue_note": "Language is request-configured; independent language detection is not performed.",
            }
        )
    return pd.DataFrame(rows)


def _empty_eda_frames(pagination_batches: list[dict[str, Any]], errors: list[str]) -> dict[str, pd.DataFrame]:
    return {
        "review_volume_by_app": pd.DataFrame(
            columns=["app_name", "item_id", "country", "language", "review_count", "unique_review_count", "duplicate_count"]
        ),
        "rating_distribution": pd.DataFrame(columns=["app_name", "item_id", "country", "language", "rating", "review_count"]),
        "review_text_length": pd.DataFrame(
            columns=[
                "app_name",
                "item_id",
                "country",
                "language",
                "review_count",
                "minimum_text_length",
                "maximum_text_length",
                "average_text_length",
                "median_text_length",
                "low_signal_review_count",
                "empty_text_count",
                "low_signal_rate",
            ]
        ),
        "date_coverage": pd.DataFrame(
            columns=["app_name", "item_id", "country", "language", "dated_review_count", "undated_review_count"]
        ),
        "missing_fields": pd.DataFrame(columns=["app_name", "item_id", "country", "language", "field", "missing_count", "missing_rate"]),
        "duplicate_records": pd.DataFrame(columns=["review_id", "duplicate_count"]),
        "language_region_issues": pd.DataFrame(
            columns=["app_name", "item_id", "country", "language", "review_count", "language_detection_available", "issue_note"]
        ),
        "low_signal_reviews": pd.DataFrame(
            columns=["app_name", "item_id", "country", "language", "review_id", "rating", "review_date", "text_length", "review_text"]
        ),
        "pagination_depth_and_failures": pd.DataFrame(pagination_batches),
        "errors": pd.DataFrame({"error": errors}),
    }


def _unique_dir(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(2, 1000):
        candidate = path.with_name(f"{path.name}_{index}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"Could not allocate unique output directory for {path}")


def _safe_run_id(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value.strip())
    return safe or _stamp()


def _stamp() -> str:
    return utc_now_iso().replace(":", "").replace("+", "Z")
