"""Generate JSON, CSV, and Markdown assessment reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from .comparison import app_store_recommendation, preliminary_recommendation
from .config import AppConfig
from .models import ProbeResult, utc_now_iso
from .quality_checks import metrics_to_frame


def generate_reports(
    config: AppConfig,
    root: Path,
    results: dict[str, ProbeResult],
    quality_metrics: list[dict[str, Any]],
    comparison: pd.DataFrame,
    network_available: bool | None,
) -> None:
    """Write all requested report artifacts."""
    reports = root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    summary = {
        "execution_timestamp": utc_now_iso(),
        "configuration_used": config.sanitized(),
        "tests_executed": [name for name, result in results.items() if result.executed],
        "tests_skipped": {name: result.skipped_reason for name, result in results.items() if not result.executed},
        "network_availability": network_available,
        "per_source_statistics": {name: result.summary() for name, result in results.items()},
        "errors": {name: result.errors for name, result in results.items() if result.errors},
        "warnings": {name: result.warnings for name, result in results.items() if result.warnings},
        "limitations": [
            "Small feasibility probe only; not a production ingestion pipeline.",
            "Review caps prevent total platform volume measurement.",
            "Amazon live behavior may vary by session, geography, and time.",
        ],
    }
    (reports / "test_run_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    metrics_to_frame(quality_metrics).to_csv(reports / "data_quality_metrics.csv", index=False)
    comparison.to_csv(reports / "source_comparison.csv", index=False)
    (reports / "feasibility_report.md").write_text(
        _markdown_report(results, quality_metrics, comparison), encoding="utf-8"
    )


def generate_app_store_reports(
    config: AppConfig,
    root: Path,
    results: dict[str, ProbeResult],
    quality_metrics: list[dict[str, Any]],
    comparison: pd.DataFrame,
    network_available: bool | None,
) -> None:
    """Write Phase 2 app-store report artifacts without replacing Phase 1 reports."""
    reports = root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    summary = {
        "execution_timestamp": utc_now_iso(),
        "phase": "Phase 2 App Store Assessment",
        "test_app": {
            "app_name": config.google_play.app_name,
            "selection_reason": (
                "Widely available, high-volume consumer app present in both Google Play Store and "
                "Apple App Store; suitable for comparing broad app-product review ingestion."
            ),
            "google_play_package_id": config.google_play.package_id,
            "apple_app_store_app_id": config.apple_app_store.app_id,
            "country": config.google_play.country,
            "language": config.google_play.language,
        },
        "configuration_used": config.sanitized(),
        "tests_executed": [name for name, result in results.items() if result.executed],
        "tests_skipped": {name: result.skipped_reason for name, result in results.items() if not result.executed},
        "network_availability": network_available,
        "per_source_statistics": {name: result.summary() for name, result in results.items()},
        "errors": {name: result.errors for name, result in results.items() if result.errors},
        "warnings": {name: result.warnings for name, result in results.items() if result.warnings},
        "limitations": [
            "Small feasibility probe only; not a production ingestion pipeline.",
            "Review caps prevent total platform volume measurement.",
            "Google Play collection uses an unofficial third-party library if available.",
            "Apple App Store results depend on a publicly accessible but undocumented RSS feed; it is not an official supported Apple review API.",
            "Two immediate successful runs do not prove long-term repeatability.",
            "Observed 100% cross-run overlap may only reflect an unchanged recent-review window during closely timed runs.",
            "No authentication, CAPTCHA bypass, stealth, or access-control circumvention was attempted.",
        ],
    }
    (reports / "app_store_test_run_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    metrics_to_frame(quality_metrics).to_csv(reports / "app_store_data_quality_metrics.csv", index=False)
    comparison.to_csv(reports / "app_store_source_comparison.csv", index=False)
    _metadata_field_matrix(results).to_csv(reports / "app_store_metadata_field_matrix.csv", index=False)
    (reports / "app_store_feasibility_report.md").write_text(
        _app_store_markdown_report(config, results, quality_metrics, comparison), encoding="utf-8"
    )


def _markdown_report(
    results: dict[str, ProbeResult], quality_metrics: list[dict[str, Any]], comparison: pd.DataFrame
) -> str:
    amazon = results.get("amazon", ProbeResult(source="amazon"))
    steam = results.get("steam", ProbeResult(source="steam"))
    metrics_by_source = {item["source"]: item for item in quality_metrics}
    recommendation = preliminary_recommendation(amazon, steam)
    return "\n".join(
        [
            "# Data-Ingestion Feasibility Report",
            "",
            "## Executive Summary",
            recommendation,
            "",
            "## Project Objective",
            "Assess whether Amazon Product Reviews or Steam User Reviews is a better limited-test source for future review ingestion and sentiment-analysis work.",
            "",
            "## Scope and Test Method",
            "This is a small feasibility assessment. It does not build a production scraper, database, scheduler, or sentiment model.",
            "",
            "## Evaluation Criteria",
            "Accessibility, review volume, available metadata, data quality, commercial value, and long-term maintainability.",
            "",
            "## Steam Findings",
            _source_findings(steam, metrics_by_source.get("steam", {})),
            "",
            "## Amazon Findings",
            _source_findings(amazon, metrics_by_source.get("amazon", {})),
            "",
            "## Data-Quality Comparison",
            _quality_summary(metrics_by_source),
            "",
            "## Accessibility and Pagination Comparison",
            _comparison_rows(comparison, "Accessibility"),
            "",
            "## Commercial Relevance",
            "Amazon is closely aligned with broad product reviews and customer-product insight. Steam provides rich user feedback but is gaming-specific.",
            "",
            "## Maintainability Risks",
            "Steam uses a structured public JSON response. Amazon may depend on page HTML, browser-generated sessions, temporary tokens, or blocking behavior.",
            "",
            "## Limitations",
            "- Results reflect only configured live requests and saved files actually processed.",
            "- Collected review counts are capped and must not be read as total source volume.",
            "- Amazon findings in this run are based on three browser-captured AJAX response files parsed offline. They demonstrate parseability and sequential pagination, but do not establish unattended direct-request reliability.",
            "",
            "## Preliminary Recommendation",
            recommendation,
            "",
            "## Suggested Next Step",
            "1. Use Steam for the initial automated ingestion prototype.\n"
            "2. Preserve the validated Amazon offline parser as a proof of parseability.\n"
            "3. Conduct a separate controlled proof of concept for repeatable, approved Amazon access without manual Network copying.\n"
            "4. Reassess Amazon for production ingestion only after access stability, compliance, and maintenance requirements are confirmed.",
            "",
        ]
    )


def _app_store_markdown_report(
    config: AppConfig,
    results: dict[str, ProbeResult],
    quality_metrics: list[dict[str, Any]],
    comparison: pd.DataFrame,
) -> str:
    google = results.get("google_play", ProbeResult(source="google_play"))
    apple = results.get("apple_app_store", ProbeResult(source="apple_app_store"))
    metrics_by_source = {item["source"]: item for item in quality_metrics}
    recommendation = app_store_recommendation(results)
    return "\n".join(
        [
            "# Phase 2 App Store Feasibility Report",
            "",
            "## Executive Summary",
            recommendation,
            "",
            "## Scope and Methodology",
            (
                "This phase assesses Google Play Store and Apple App Store reviews as potential primary sources for "
                "future review ingestion and product-intelligence work. It uses modest request limits, conservative "
                "pacing, and no authentication or access-control bypass."
            ),
            "",
            "## Test App and Identifiers",
            f"- App name: {config.google_play.app_name}",
            f"- Google Play package ID: {config.google_play.package_id}",
            f"- Apple App Store app ID: {config.apple_app_store.app_id}",
            f"- Storefront/country: {config.google_play.country}",
            f"- Language: {config.google_play.language}",
            "- Selection reason: widely available, high-volume app present on both platforms.",
            "",
            "## Google Play Store Findings",
            _source_findings(google, metrics_by_source.get("google_play", {})),
            _app_store_extra_findings(google),
            "",
            "## Apple App Store Findings",
            _source_findings(apple, metrics_by_source.get("apple_app_store", {})),
            _app_store_extra_findings(apple),
            "",
            "## Accessibility and Access-Method Comparison",
            _app_store_comparison_rows(comparison, "Consistent accessibility"),
            "",
            "## Pagination/Batching Comparison",
            _app_store_comparison_rows(comparison, "Pagination or batching"),
            "",
            "## Metadata Field Comparison",
            _metadata_summary(results),
            "",
            "## Data-Quality and Repeatability Results",
            _app_store_quality_summary(metrics_by_source),
            "",
            "## Access Limitations and Compliance Considerations",
            (
                "No authentication bypass, CAPTCHA solving, stealth browser behavior, or rate-limit evasion was used. "
                "Google Play access is classified as third-party/unofficial when using google-play-scraper. Apple "
                "access is classified as a publicly accessible undocumented RSS JSON feed, not an official supported "
                "Apple review API. Production use requires monitoring, failure detection, schema-change alerts, "
                "platform-policy review, and stakeholder/legal approval."
            ),
            "",
            "## Long-Term Maintainability Risks",
            (
                "Apple's RSS JSON shape is simple, but long-term endpoint and schema stability are not guaranteed. "
                "Two immediate successful runs do not prove long-term repeatability, and the observed 100% cross-run "
                "overlap may only reflect an unchanged recent-review window during two closely timed runs. Incremental "
                "ingestion is conditionally feasible only while stable review IDs and stable ordering remain available. "
                "Google Play is riskier because the selected path depends on an unofficial package and undocumented "
                "store behavior."
            ),
            "",
            "## Commercial Value and Generalizability",
            (
                "Both app stores are better aligned than Steam with broad consumer-product feedback and app product "
                "intelligence. The earlier Steam recommendation is superseded by stakeholder concerns that Steam is "
                "too gaming-specific. Amazon remains commercially valuable but on hold until repeatable access is resolved."
            ),
            "",
            "## Limitations of This Assessment",
            "- Results reflect only the configured app, country, language, network environment, and execution time.",
            "- Apple is recommended only as the stronger source under the current tested constraints, not as a risk-free production API.",
            "- Empty or failed live results are not treated as successful access.",
            "- Offline fixtures validate parsers only; they are not evidence of live platform access.",
            "- Sample sizes are capped and cannot estimate total platform review volume.",
            "",
            "## Final Recommendation",
            recommendation,
            "",
        ]
    )


def _source_findings(result: ProbeResult, metrics: dict[str, Any]) -> str:
    if not result.executed:
        return f"Not executed. Reason: {result.skipped_reason}"
    live_executed = result.live_request_executed if result.live_request_executed is not None else bool(result.requests)
    offline_executed = bool(result.offline_parsing_executed)
    status_codes = ", ".join(str(request.status_code) for request in result.requests) or "none"
    request_count = _request_count_label(result)
    success_count = _successful_request_count_label(result)
    details = [
        f"- Live request executed: {'yes' if live_executed else 'no'}",
        f"- Live collection executed: {'yes' if live_executed else 'no'}",
        f"- Offline saved-response parsing executed: {'yes' if offline_executed else 'no'}",
        f"- Saved response batches parsed: {result.saved_response_batch_count}",
        f"- Live requests attempted: {request_count}",
        f"- Successful requests: {success_count}",
        f"- Request count status: {result.request_count_status}",
        f"- HTTP status codes: {status_codes}",
        f"- Reviews collected: {len(result.reviews)}",
        f"- Final dataset duplicate count: {metrics.get('final_dataset_duplicate_count', metrics.get('duplicates_within_final_dataset'))}",
        f"- Cross-run overlap count: {_not_applicable(metrics.get('cross_run_overlap_count', metrics.get('overlap_across_repeat_runs')))}",
        f"- Cross-run overlap rate: {_format_rate(metrics.get('cross_run_overlap_rate', metrics.get('repeat_run_overlap_rate')))}",
        f"- New records in second run: {_not_applicable(metrics.get('new_records_in_second_run'))}",
        f"- Blocking status: {result.blocking_status or _yes_no(result.blocked)}",
        f"- CAPTCHA status: {result.captcha_status or ('yes' if _captcha_observed(result) else 'no')}",
        f"- Pagination demonstrated: {_yes_no(result.pagination_success)}",
        f"- Parser errors: {len(result.parser_errors)}",
        f"- Warnings: {'; '.join(result.warnings) if result.warnings else 'none'}",
    ]
    if result.source == "steam":
        details.append("- Rating: not applicable; Steam provides a binary recommendation label.")
    if result.source == "amazon" and result.requests and result.request_success_rate() != 1.0:
        details.append("- Interpretation: this configured live request did not return usable review content; Amazon feasibility remains unresolved.")
    if result.source == "amazon" and offline_executed and not result.requests:
        details.append("- Direct live accessibility: not tested in this run.")
        details.append("- Browser-captured offline parseability: successfully demonstrated.")
        details.append("- Browser-captured pagination: successfully demonstrated.")
    return "\n".join(details)


def _app_store_extra_findings(result: ProbeResult) -> str:
    if not result.executed:
        return ""
    details = [
        f"- Access method: {result.access_method}",
        f"- Access method classification: {result.access_method_type}",
        f"- Country/storefront: {result.country}",
        f"- Language: {result.language}",
        f"- Run timestamps: {', '.join(result.run_timestamps) if result.run_timestamps else 'none'}",
        f"- Batches/pages attempted: {result.pages_attempted}",
        f"- Batches/pages completed: {result.pages_completed}",
        f"- Repeated collection demonstrated: {_yes_no(result.repeated_collection_demonstrated)}",
        f"- Incremental collection appears feasible: {_yes_no(result.incremental_collection_feasible)}",
        f"- Access limitations observed: {'; '.join(result.access_limitations) if result.access_limitations else 'none'}",
    ]
    return "\n".join(details)


def _quality_summary(metrics_by_source: dict[str, dict[str, Any]]) -> str:
    lines = []
    for source in ("steam", "amazon"):
        metrics = metrics_by_source.get(source, {})
        if not metrics:
            lines.append(f"- {source}: no metrics available")
            continue
        lines.append(
            f"- {source}: rows={metrics.get('total_rows')}, "
            f"duplicates within final dataset={metrics.get('duplicates_within_final_dataset')}, "
            f"repeat-run overlap={_not_applicable(metrics.get('overlap_across_repeat_runs'))}, "
            f"empty text={metrics.get('empty_review_text_count')}, parser errors={metrics.get('parser_error_count')}"
        )
        applicability = metrics.get("field_applicability") or {}
        if source == "steam":
            lines.append("- steam field note: Rating: not applicable; Steam provides a binary recommendation label.")
        if applicability.get("not_applicable"):
            lines.append(f"- {source} not-applicable fields: {', '.join(applicability['not_applicable'])}")
    return "\n".join(lines)


def _app_store_quality_summary(metrics_by_source: dict[str, dict[str, Any]]) -> str:
    lines = []
    for source in ("google_play", "apple_app_store"):
        metrics = metrics_by_source.get(source, {})
        if not metrics:
            lines.append(f"- {source}: no metrics available")
            continue
        lines.append(
            f"- {source}: rows={metrics.get('total_rows')}, unique={metrics.get('unique_review_count')}, "
            f"final dataset duplicate count={metrics.get('final_dataset_duplicate_count')}, "
            f"cross-run overlap count={_not_applicable(metrics.get('cross_run_overlap_count'))}, "
            f"cross-run overlap rate={_format_rate(metrics.get('cross_run_overlap_rate'))}, "
            f"new records in second run={_not_applicable(metrics.get('new_records_in_second_run'))}, "
            f"empty text={metrics.get('empty_review_text_count')}, parser errors={metrics.get('parser_error_count')}"
        )
    return "\n".join(lines)


def _comparison_rows(comparison: pd.DataFrame, criterion: str) -> str:
    rows = comparison[comparison["criterion"] == criterion].to_dict("records")
    if not rows:
        return "No comparison row available."
    row = rows[0]
    return (
        f"- Amazon evidence: {row.get('amazon_evidence')}\n"
        f"- Steam evidence: {row.get('steam_evidence')}\n"
        f"- Amazon assessment: {row.get('amazon_assessment')}\n"
        f"- Steam assessment: {row.get('steam_assessment')}\n"
        f"- Confidence: {row.get('confidence')}"
    )


def _app_store_comparison_rows(comparison: pd.DataFrame, criterion: str) -> str:
    rows = comparison[comparison["criterion"] == criterion].to_dict("records")
    if not rows:
        return "No comparison row available."
    row = rows[0]
    return (
        f"- Google Play evidence: {row.get('google_play_evidence')}\n"
        f"- Apple App Store evidence: {row.get('apple_app_store_evidence')}\n"
        f"- Google Play assessment: {row.get('google_play_assessment')}\n"
        f"- Apple App Store assessment: {row.get('apple_app_store_assessment')}\n"
        f"- Confidence: {row.get('confidence')}"
    )


def _metadata_field_matrix(results: dict[str, ProbeResult]) -> pd.DataFrame:
    fields = [
        "source",
        "app_name",
        "item_id",
        "package_id",
        "review_id",
        "review_title",
        "review_text",
        "rating",
        "review_date",
        "author_name",
        "author_id",
        "helpful_votes",
        "app_version",
        "language",
        "country",
        "developer_response",
        "developer_response_date",
        "source_url",
        "raw_page_number",
        "raw_cursor",
        "collected_at",
    ]
    rows = []
    for field in fields:
        row = {"field": field}
        for source in ("google_play", "apple_app_store"):
            result = results.get(source, ProbeResult(source=source))
            if field in result.available_metadata_fields:
                row[source] = "available"
            elif result.reviews:
                row[source] = "unavailable"
            else:
                row[source] = "not verified"
        rows.append(row)
    return pd.DataFrame(rows)


def _metadata_summary(results: dict[str, ProbeResult]) -> str:
    matrix = _metadata_field_matrix(results)
    lines = []
    for row in matrix.to_dict("records"):
        lines.append(f"- {row['field']}: Google Play={row['google_play']}; Apple App Store={row['apple_app_store']}")
    return "\n".join(lines)


def _format_rate(value: Any) -> str:
    if value is None:
        return "not applicable"
    if isinstance(value, (int, float)):
        return f"{value:.0%}"
    return str(value)


def _request_count_label(result: ProbeResult) -> str:
    if result.request_count_status != "available":
        return "unavailable via third-party wrapper"
    return str(len(result.requests))


def _successful_request_count_label(result: ProbeResult) -> str:
    if result.request_count_status != "available":
        return "unavailable via third-party wrapper"
    return str(sum(1 for request in result.requests if request.success))


def _captcha_observed(result: ProbeResult) -> bool:
    evidence = " ".join(result.warnings + result.errors).lower()
    return "captcha" in evidence


def _yes_no(value: Any) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return "not enough evidence"


def _not_applicable(value: Any) -> str:
    return "not applicable" if value is None else str(value)
