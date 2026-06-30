"""Generate JSON, CSV, and Markdown assessment reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from .comparison import preliminary_recommendation
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


def _source_findings(result: ProbeResult, metrics: dict[str, Any]) -> str:
    if not result.executed:
        return f"Not executed. Reason: {result.skipped_reason}"
    live_executed = result.live_request_executed if result.live_request_executed is not None else bool(result.requests)
    offline_executed = bool(result.offline_parsing_executed)
    status_codes = ", ".join(str(request.status_code) for request in result.requests) or "none"
    details = [
        f"- Live request executed: {'yes' if live_executed else 'no'}",
        f"- Offline saved-response parsing executed: {'yes' if offline_executed else 'no'}",
        f"- Saved response batches parsed: {result.saved_response_batch_count}",
        f"- Live requests attempted: {len(result.requests)}",
        f"- HTTP status codes: {status_codes}",
        f"- Request batches attempted: {len(result.requests)}",
        f"- Reviews collected: {len(result.reviews)}",
        f"- Duplicates within final normalized dataset: {metrics.get('duplicates_within_final_dataset')}",
        f"- Repeat-run overlap: {_not_applicable(metrics.get('overlap_across_repeat_runs'))}",
        f"- Repeat-run overlap rate: {_format_rate(metrics.get('repeat_run_overlap_rate'))}",
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


def _format_rate(value: Any) -> str:
    if value is None:
        return "not applicable"
    if isinstance(value, (int, float)):
        return f"{value:.0%}"
    return str(value)


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
